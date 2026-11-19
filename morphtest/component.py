import abc
import dataclasses
import functools
import inspect
import textwrap
import typing
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import (
    Annotated,
    Any,
    ClassVar,
    Generic,
    NamedTuple,
    Optional,
    Self,
    TypeVar,
    cast,
)
from weakref import WeakKeyDictionary

from typing_extensions import dataclass_transform

_DEPENDENCY_MARKER = object()

D = TypeVar("D")
Dependency = Annotated[D, _DEPENDENCY_MARKER]


def if_not_overwritten(component: type[D]) -> D:
    return component  # type: ignore[return-value]


class DependencyAnnotation(NamedTuple):
    component: "ComponentMeta"
    if_not_overwritten: Optional["ComponentMeta"] = None

    @classmethod
    def from_annotation(cls, annotation: Any, *, value: Any = None) -> Self | None:
        if typing.get_origin(annotation) != Annotated:
            return None

        component, *markers = typing.get_args(annotation)
        if _DEPENDENCY_MARKER not in markers:
            return None

        return cls(
            component,
            if_not_overwritten=value if isinstance(value, ComponentMeta) else None,
        )


class ComponentError(Exception):
    pass


class ComponentConventionsError(ComponentError):
    pass


class ComponentNameWithoutRootPrefixError(ComponentConventionsError):
    def __init__(self, component: "ComponentMeta") -> None:
        super().__init__(
            f"{component} needs to be prefixed with root name ({', '.join(f'{root}_{component}' for root in component.roots())})"
        )
        self.component = component


class RootComponentWithPrefixError(ComponentConventionsError):
    def __init__(self, component: "ComponentMeta") -> None:
        super().__init__(
            f"root component {component} must not have a prefix (did you forget to inherit?)"
        )
        self.component = component


class ComponentSpecializationPrefixError(ComponentConventionsError):
    def __init__(self, component: "ComponentMeta") -> None:
        super().__init__(
            f"specialization component {component} needs to be prefixed with base component name ({', '.join(f'{base}_{component}' for base in component.bases())})"
        )
        self.component = component


class ComponentNameDuplicatedError(ComponentConventionsError):
    def __init__(self, component: "ComponentMeta", original: "ComponentMeta") -> None:
        super().__init__(
            f"component with same name as {component.__module__}.{component} already exists {original.__module__}.{original}"
        )
        self.component = component
        self.original = original


class MixinPrefixError(ComponentConventionsError):
    def __init__(self, component: "ComponentMeta") -> None:
        super().__init__(f"{component} must be prefixed with non-mixin component")
        self.component = component


class MixinConventionError(ComponentConventionsError):
    pass


class NonAbstractMixinError(MixinConventionError):
    def __init__(self, component: "ComponentMeta") -> None:
        super().__init__(f"mixin {component} must be abstract")
        self.component = component


class OverrideDependencyWithDifferentNameError(ComponentError):
    def __init__(
        self,
        dependency: DependencyAnnotation,
        component: "ComponentMeta",
        field: str,
        base_field: str,
    ) -> None:
        super().__init__(
            f"{dependency.component} already defined as {component}.{base_field}. Replace {component}.{field} with {component}.{base_field}"
        )
        self.dependency = dependency
        self.component = component
        self.field = field
        self.base_field = base_field


class DependencyAssignmentError(ComponentError):
    def __init__(self, component: "ComponentMeta", property_name: str) -> None:
        super().__init__(
            f"use type annotations for dependencies (replace '{property_name} = ...' with '{property_name}: ...')"
        )
        self.component = component
        self.property_name = property_name


@dataclasses.dataclass(frozen=True)
class Condition:
    component: "ComponentMeta"


@dataclasses.dataclass(frozen=True)
class OneOf(Condition):
    def __str__(self) -> str:
        return f"{self.component}.one_of"


@dataclasses.dataclass(frozen=True)
class AllOf(Condition):
    def __str__(self) -> str:
        return f"{self.component}.all_of"


@dataclass_transform(kw_only_default=True)
class ComponentMeta(abc.ABCMeta):
    InstanceData: ClassVar[WeakKeyDictionary[object, dict[str, Any]]] = (
        WeakKeyDictionary()
    )

    def __init__(
        cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]
    ) -> None:
        cls.is_mixin: bool = False
        cls._base_dependencies: dict[str, DependencyAnnotation] = functools.reduce(
            lambda merged, base: merged | base.dependencies(), cls.bases(), {}
        )
        cls._own_dependencies = cls._init_own_dependencies(namespace)

        # non-component bases (plain Python classes) do not make a class a mixin
        component_bases = [base for base in bases if isinstance(base, ComponentMeta)]
        if component_bases and all(base.is_mixin for base in component_bases):
            mixin(cls)

        if not cls.is_meta_root:
            if any(cls is root for root in cls.roots()) and "_" in name:
                raise RootComponentWithPrefixError(cls)

            if not any(
                cls is root or name.startswith(f"{root.__name__}_")
                for root in cls.roots()
            ):
                raise ComponentNameWithoutRootPrefixError(cls)

            if not (
                cls.is_abstract
                or cls.is_root
                or any(
                    name.startswith(base_prefix)
                    for base in bases
                    if isinstance(base, ComponentMeta)
                    if not base.is_mixin
                    if (parts := base.__name__.split("_"))
                    if (base_prefix := parts[0])
                )
            ):
                raise MixinPrefixError(cls)

            non_abstract_bases = [base for base in cls.bases() if not base.is_abstract]
            if non_abstract_bases and not any(
                name.startswith(f"{base.__name__}_") for base in non_abstract_bases
            ):
                raise ComponentSpecializationPrefixError(cls)

            cls._raise_on_duplicate()
            cls._raise_on_dependency_override_with_different_name()

            for property_name, maybe_dependency in namespace.items():
                if DependencyAnnotation.from_annotation(maybe_dependency) is not None:
                    raise DependencyAssignmentError(cls, property_name)

        super().__init__(name, bases, namespace)

    def _init_own_dependencies(
        cls, namespace: dict[str, Any]
    ) -> dict[str, DependencyAnnotation]:
        # not namespace["__annotations__"]: since Python 3.14 (PEP 649) the namespace
        # only contains the lazy __annotate__ function
        dependencies = {
            name: dependency
            for name, annotation in inspect.get_annotations(cls).items()
            if (
                dependency := DependencyAnnotation.from_annotation(
                    annotation, value=namespace.get(name)
                )
            )
            is not None
        }
        for attr in dependencies:
            if hasattr(cls, attr):
                delattr(cls, attr)
        return dependencies

    def _raise_on_dependency_override_with_different_name(cls) -> None:
        for own_dep_name, own_dep in cls._own_dependencies.items():
            for base_dep_name, base_dep in cls._base_dependencies.items():
                if (
                    issubclass(own_dep.component, base_dep.component)
                    and own_dep_name != base_dep_name
                ):
                    raise OverrideDependencyWithDifferentNameError(
                        dependency=own_dep,
                        component=cls,
                        field=own_dep_name,
                        base_field=base_dep_name,
                    )

    def _raise_on_duplicate(cls) -> None:
        meta_root = cls.meta_root()
        maybe_duplicate = next(
            (
                subclass
                for subclass in meta_root.subclasses()
                if subclass is not cls
                if str(subclass) == str(cls)
            ),
            None,
        )
        if maybe_duplicate is not None:
            raise ComponentNameDuplicatedError(cls, maybe_duplicate)

    @functools.cache
    def bases(cls) -> frozenset["ComponentMeta"]:
        return frozenset(
            base
            for base in cls.__bases__
            if isinstance(base, ComponentMeta) and not base.is_meta_root
        )

    def roots(cls) -> Iterator["ComponentMeta"]:
        yield from cls._roots()

    @functools.cache
    def _roots(cls) -> tuple["ComponentMeta", ...]:
        return tuple(
            root
            for base in cls.__bases__
            if isinstance(base, ComponentMeta)
            for root in ((cls,) if base.is_meta_root else base.roots())
        )

    @functools.cache
    def ancestors(cls) -> frozenset["ComponentMeta"]:
        ancestors: set[ComponentMeta] = set()
        for base in cls.bases():
            ancestors.add(base)
            ancestors.update(base.ancestors())
        return frozenset(ancestors)

    @property
    def is_root(cls) -> bool:
        return cls in list(cls.roots())

    @property
    def is_abstract(cls) -> bool:
        return abc.ABC in cls.__bases__

    @property
    @functools.cache
    def is_meta_root(cls) -> bool:
        return not any(isinstance(base, ComponentMeta) for base in cls.__bases__)

    @property
    def one_of(cls) -> OneOf:
        return OneOf(cls)

    @property
    def all_of(cls) -> AllOf:
        return AllOf(cls)

    def meta_root(cls) -> "ComponentMeta":
        for base in cls.__bases__:
            if isinstance(base, ComponentMeta):
                if base.is_meta_root:
                    return base
                return base.meta_root()
        raise TypeError(f"{cls} must be a ComponentMeta subclass")

    def implementations(cls) -> Iterator["ComponentMeta"]:
        if not cls.is_abstract:
            yield cls

        for subcls in cls.subclasses():
            yield from subcls.implementations()

    def subclasses(cls) -> list["ComponentMeta"]:
        """direct subclasses (typed version of __subclasses__())"""
        # subclasses inherit the metaclass, so all of them are ComponentMeta instances
        return cast("list[ComponentMeta]", cls.__subclasses__())

    def dependencies(cls) -> dict[str, DependencyAnnotation]:
        return {**cls._base_dependencies, **cls._own_dependencies}

    def __repr__(cls) -> str:
        return cls.__qualname__

    @classmethod
    def __prepare__(
        cls, name: str, bases: tuple[type, ...], /, **kwargs: dict[str, object]
    ) -> dict[str, object]:
        namespace: dict[str, object] = {
            "__new__": cls._new,
            # lambdas are required: bound classmethods are no descriptors and would not get the instance
            "__getattr__": lambda o, a: cls._getattr(o, a),  # noqa: PLW0108
            "__repr__": lambda o: cls._repr(o),  # noqa: PLW0108
            "__str__": lambda o: str(type(o)),
        }
        return namespace

    @classmethod
    def _new(cls, klass: "ComponentMeta", **kwargs: dict[str, Any]) -> object:
        expected_args = set(klass.dependencies())
        if missing := (expected_args - set(kwargs)):
            raise TypeError(
                f"""{klass} missing {len(missing)} required keyword-only argument: {", ".join(f"'{a}'" for a in sorted(missing))}"""
            )
        if unexpected := (set(kwargs) - expected_args):
            raise TypeError(
                f"""{klass} got unexpected keyword arguments: {", ".join(f"'{a}'" for a in sorted(unexpected))}"""
            )

        obj: object = object.__new__(klass)  # type: ignore[arg-type]
        cls.InstanceData[obj] = kwargs
        return obj

    @classmethod
    def _getattr(cls, obj: object, attr: str) -> Any:
        try:
            return cls.InstanceData[obj][attr]
        except KeyError:
            return obj.__getattribute__(attr)

    @classmethod
    def _repr(cls, obj: object) -> str:
        indent = 4
        deps = ",\n".join(
            [f"{name}={value!r}" for name, value in cls.InstanceData[obj].items()]
        )
        deps = f"\n{textwrap.indent(deps, ' ' * indent)}\n" if deps else ""
        return f"{type(obj)}({deps})"


def mixin(cls: ComponentMeta) -> ComponentMeta:
    if not cls.is_abstract:
        raise NonAbstractMixinError(cls)

    cls.is_mixin = True
    return cls


class Component(metaclass=ComponentMeta):
    """
    Default meta root for components.

    Classes directly inheriting from Component are roots. Components get their
    dependencies as keyword-only arguments.
    """

    def __init__(self, **kwargs: object) -> None:
        # dependencies are stored by ComponentMeta._new(), object.__init__() would reject the kwargs
        pass


C = TypeVar("C")
Instance = TypeVar("Instance")


class ComponentDependencySet(Generic[C]):
    def __init__(
        self,
        entry_component: type[C],
        implementations: Iterable[ComponentMeta],
        *,
        conditions: Iterable[Condition] = (),
        recommended_components: Sequence[ComponentMeta] = (),
    ) -> None:
        # ComponentMeta[C] is not supported so the parameter must be type[C]
        # but we need it as ComponentMeta internally, so that all other type hints work.
        self._entry_component: ComponentMeta = entry_component  # type: ignore[assignment]
        self._implementations = {
            root: implementation
            for implementation in implementations
            for root in implementation.roots()
        }
        self.components = frozenset(self.implementations()) | {
            ancestor
            for implementation in self.implementations()
            for ancestor in implementation.ancestors()
        }
        self.conditions = frozenset(conditions)
        self.recommended_components = list(recommended_components)

    def entry_implementation(self) -> ComponentMeta:
        """the implementation of the entry component, which build() instantiates"""
        entry_implementation = self._get_implementation(self._entry_component)
        if entry_implementation is None:
            raise RuntimeError(f"no implementation found for {self._entry_component}")
        return entry_implementation

    def __repr__(self) -> str:
        entry_implementation = self.entry_implementation()

        implementations = [
            f"{root}={impl}"
            for root, impl in self._implementations.items()
            if impl is not entry_implementation
        ]
        return f"{entry_implementation}[{', '.join(sorted(implementations))}]"

    def __eq__(self, other: object) -> bool:
        return str(other) == str(self)

    def __hash__(self) -> int:
        return hash(str(self))

    def build(self, *, instances: dict[ComponentMeta, Instance] | None = None) -> C:
        return self._get_instance(
            self._entry_component, instances={} if instances is None else instances
        )  # type: ignore[return-value]

    def implementations(self) -> Iterator[ComponentMeta]:
        yield from self._implementations.values()

    def _get_implementation(self, component: ComponentMeta) -> ComponentMeta | None:
        implementations = {
            implementation
            for root in component.roots()
            if (implementation := self._implementations.get(root))
        }
        if len(implementations) == 0:
            raise RuntimeError(f"no implementation for {component} found")
        if len(implementations) > 1:
            raise RuntimeError(
                f"multiple implementations for {component} found "
                f"({[impl for impl in self._implementations.values() if issubclass(impl, component)]})"
            )
        (implementation,) = implementations
        return implementation

    def _get_instance(
        self, component: ComponentMeta, *, instances: dict[ComponentMeta, Any]
    ) -> Any | None:
        implementation = self._get_implementation(component)
        if implementation is None:
            return None

        if implementation not in instances:
            instances[implementation] = implementation(
                **{
                    dep_name: self._get_instance(
                        dep_info.component, instances=instances
                    )
                    for dep_name, dep_info in implementation.dependencies().items()
                }
            )
        return instances[implementation]


M = TypeVar("M", bound=Mapping[str, object])


class _BuilderContext(Generic[M]):
    def __init__(self, conditions: Iterable[Condition], metadata: M) -> None:
        self.conditions = set(conditions)
        self.metadata = metadata
        self.children: list[_BuilderContext[M]] = []

    def __iter__(self) -> Iterator[tuple[set[Condition], M]]:
        if not self.children:
            yield self.conditions, self.metadata
        else:
            for child in self.children:
                for conditions, metadata in child:
                    yield (
                        self.conditions | conditions,
                        cast("M", {**self.metadata, **metadata}),
                    )


ConditionLike = Condition | ComponentMeta


def _make_condition(condition_like: ConditionLike) -> Condition:
    return (
        condition_like.all_of
        if isinstance(condition_like, ComponentMeta)
        else condition_like
    )


class ConditionsBuilder(Generic[M]):
    def __init__(self, *conditions: ConditionLike, metadata: M | None = None) -> None:
        self._active_context = _BuilderContext[M](
            map(_make_condition, conditions), metadata or cast("M", {})
        )

    def __call__(
        self, *conditions: ConditionLike, metadata: M | None = None
    ) -> AbstractContextManager[None]:
        ctx = _BuilderContext[M](
            map(_make_condition, conditions), metadata or cast("M", {})
        )
        self._active_context.children.append(ctx)
        return self._context(ctx)

    @contextmanager
    def _context(self, ctx: _BuilderContext[M]) -> Iterator[None]:
        prev_context = self._active_context
        self._active_context = ctx

        try:
            yield
        finally:
            self._active_context = prev_context

    def __iter__(self) -> Iterator[tuple[set[Condition], M]]:
        yield from self._active_context

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None
