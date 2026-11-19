import abc
from typing import Annotated

import pytest

from morphtest.component import (
    AllOf,
    ComponentDependencySet,
    ComponentMeta,
    ComponentNameDuplicatedError,
    ComponentNameWithoutRootPrefixError,
    ComponentSpecializationPrefixError,
    Condition,
    ConditionsBuilder,
    Dependency,
    DependencyAnnotation,
    DependencyAssignmentError,
    MixinPrefixError,
    NonAbstractMixinError,
    OneOf,
    OverrideDependencyWithDifferentNameError,
    RootComponentWithPrefixError,
    if_not_overwritten,
    mixin,
)


class TestComponentMeta:
    def test_roots_returns_base_class_directly_subclassing_component_meta(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        class Root_Middle(Root, abc.ABC): pass
        class Root_Leaf(Root_Middle): pass
        # fmt: on

        assert set(Root_Leaf.roots()) == {Root}

    def test_roots_works_with_multiple_inheritance(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class RootA(Component, abc.ABC): pass
        class RootB(Component, abc.ABC): pass
        class RootA_Leaf(RootA, RootB): pass
        # fmt: on

        assert set(RootA_Leaf.roots()) == {RootA, RootB}

    def test_iters_all_ancestors(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        class Root_A(Root, abc.ABC): pass
        class Root_B(Root_A, abc.ABC): pass
        class Root_C(Root_B, abc.ABC): pass
        class Root_D(Root_C): pass
        # fmt: on

        assert set(Root_D.ancestors()) == {Root, Root_A, Root_B, Root_C}

    def test_is_abstract_returns_true_when_inherits_from_abc(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Abstract(Component, abc.ABC): pass
        # fmt: on

        assert Abstract.is_abstract

    def test_is_abstract_return_false_by_default(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Abstract(Component, abc.ABC): pass
        class Abstract_Implementation(Abstract): pass
        # fmt: on

        assert not Abstract_Implementation.is_abstract

    def test_is_root(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        class Root_Implementation(Root): pass
        # fmt: on

        assert Root.is_root
        assert not Root_Implementation.is_root

    def test_dependencies_ignores_regular_annotations(self) -> None:
        class Component(metaclass=ComponentMeta):
            pass

        class AnnotatedComponent(Component):
            i: int
            a: Annotated[int, "annotation"]

        assert not AnnotatedComponent.dependencies()

    def test_dependencies_returns_dependency_annotations(self) -> None:
        class Component(metaclass=ComponentMeta):
            pass

        class WithDependency(Component):
            dep: Dependency[Component]

        assert WithDependency.dependencies() == {"dep": DependencyAnnotation(Component)}

    def test_dependencies_includes_base_classes(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class DRoot(Component): pass
        class DSub(Component): pass
        class Root(Component, abc.ABC): root: Dependency[DRoot]
        class Root_Sub(Root): sub: Dependency[DSub]
        # fmt: on

        assert Root_Sub.dependencies() == {
            "root": DependencyAnnotation(DRoot),
            "sub": DependencyAnnotation(DSub),
        }

    def test_dependencies_of_base_classes_are_overwritten(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class AnotherComponent(Component): pass
        class Root(Component, abc.ABC): dep: Dependency[Component]
        class Root_Sub(Root): dep: Dependency[AnotherComponent]
        # fmt: on

        assert Root_Sub.dependencies() == {
            "dep": DependencyAnnotation(AnotherComponent)
        }

    def test_do_not_allow_to_override_dependency_with_different_name(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class C(Component, abc.ABC): d: Dependency[D]
        # fmt: on

        with pytest.raises(OverrideDependencyWithDifferentNameError):

            class C_0(C):
                dd: Dependency[D_0]

    def test_do_not_allow_assignments_of_dependencies(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        # fmt: on

        with pytest.raises(DependencyAssignmentError):

            class C(Component):
                a = Dependency[Root]

    def test_init_raises_no_type_error_when_dependencies_are_given(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Implementation(Component): dep: Dependency[Component]
        # fmt: on

        Implementation(dep=Component())

    def test_init_raises_type_error_when_dependency_is_missing(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Implementation(Component): dep: Dependency[Component]
        # fmt: on

        with pytest.raises(TypeError):
            Implementation()  # type: ignore[call-arg]

    def test_init_raises_type_error_on_unknown_dependency(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Implementation(Component): pass
        # fmt: on

        with pytest.raises(TypeError):
            Implementation(dep=Component())  # type: ignore[call-arg]

    def test_init_calls_init_from_superclasses(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta):
            def __init__(self) -> None:
                self.initialized = True
        class Implementation(Component): pass
        # fmt: on

        assert Implementation().initialized

    def test_getattr_of_dependencies(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Implementation(Component): dep: Dependency[Component]
        # fmt: on

        dep = Component()
        assert Implementation(dep=dep).dep is dep

    def test_repr_shows_dependency_tree(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component): pass
        class B(Component): pass
        class X(Component):
            a: Dependency[A]
            b: Dependency[B]
        class T(Component): x: Dependency[X]
        # fmt: on

        assert (
            repr(T(x=X(a=A(), b=B())))
            == f"""{T}(
    x={X}(
        a={A}(),
        b={B}()
    )
)"""
        )

    def test_subclass_of_non_abstract_must_be_prefixed_with_base_name(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        # fmt: on

        with pytest.raises(ComponentSpecializationPrefixError):

            class A_Special(A_0):
                pass

    def test_component_names_must_be_prefixed_with_root_name(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        # fmt: on

        with pytest.raises(ComponentNameWithoutRootPrefixError):

            class Base(Root):
                pass

    def test_prefix_on_root_component_not_allowed(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        # fmt: on

        with pytest.raises(RootComponentWithPrefixError):

            class Prefix_Root(Component, abc.ABC):
                pass

    def test_component_names_must_be_unique(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class MustBeUnique(Component): pass
        # fmt: on

        with pytest.raises(ComponentNameDuplicatedError):

            class MustBeUnique(Component):  # type: ignore[no-redef]
                pass

    def test_component_names_can_be_duplicated_when_within_different_components(
        self,
    ) -> None:
        class Component(metaclass=ComponentMeta):
            pass

        class A(Component):
            class CanBeDuplicated(Component):
                pass

        class B(Component):
            class CanBeDuplicated(Component):
                pass

    def test_component_as_one_of_condition(self) -> None:
        class Component(metaclass=ComponentMeta):
            pass

        assert Component.one_of == OneOf(Component)

    def test_component_as_all_of_condition(self) -> None:
        class Component(metaclass=ComponentMeta):
            pass

        assert Component.all_of == AllOf(Component)

    def test_mark_as_mixin_with_decorator(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        @mixin
        class Mixin(Component, abc.ABC): pass
        # fmt: on

        assert Mixin.is_mixin

    def test_mark_as_mixin_when_only_mixin_bases(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        @mixin
        class MixinA(Component, abc.ABC): pass
        @mixin
        class MixinB(Component, abc.ABC): pass
        class MixinA_0(MixinA, MixinB, abc.ABC): pass
        # fmt: on

        assert MixinA_0.is_mixin

    def test_error_on_mixin_implementation(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        @mixin
        class Mixin(Component, abc.ABC): pass
        # fmt: on

        with pytest.raises(NonAbstractMixinError):

            class Mixin_0(Mixin):
                pass

    def test_error_when_mixin_decorator_used_with_implementation(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        # fmt: on

        with pytest.raises(NonAbstractMixinError):

            @mixin
            class Mixin(Component):
                pass

    def test_error_when_mixin_prefix(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class C(Component, abc.ABC): pass
        @mixin
        class M(Component, abc.ABC): pass
        # fmt: on

        with pytest.raises(MixinPrefixError):

            class M_0(C, M):
                pass

    def test_dependency_value_if_not_overwritten(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_None(D): pass
        class C(Component, abc.ABC): d: Dependency[D] = if_not_overwritten(D_None)
        class C_0(C): pass
        # fmt: on

        assert C_0.dependencies() == {
            "d": DependencyAnnotation(D, if_not_overwritten=D_None)
        }

    def test_dependency_no_value_if_overwritten(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_None(D): pass
        class D_0(D): pass
        class C(Component, abc.ABC): d: Dependency[D] = if_not_overwritten(D_None)
        class C_0(C): d: Dependency[D_0]
        # fmt: on

        assert C_0.dependencies() == {"d": DependencyAnnotation(D_0)}


class TestComponentDependencySet:
    def test_builds_base_component(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Implementation(Component): pass
        # fmt: on

        instance = ComponentDependencySet(Implementation, {Implementation}).build()
        assert isinstance(instance, Implementation)

    def test_initializes_dependencies_based_on_implementations(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class Implementation(Component): dep: Dependency[D]
        # fmt: on

        instance = ComponentDependencySet(Implementation, {Implementation, D_0}).build()
        assert isinstance(instance.dep, D_0)

    def test_single_instantiation_of_components(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component): pass
        class M0(Component): d: Dependency[D]
        class M1(Component): d: Dependency[D]
        class C(Component):
            m0: Dependency[M0]
            m1: Dependency[M1]
        # fmt: on

        c = ComponentDependencySet(C, {C, D, M0, M1}).build()
        assert c.m0.d is c.m1.d

    def test_iter_all_components(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_Implementation(D): pass
        class Implementation(Component):
            d: Dependency[D]
        # fmt: on

        assert set(
            ComponentDependencySet(
                Implementation, {Implementation, D_Implementation}
            ).components
        ) == {D, D_Implementation, Implementation}


def make_components(n: int) -> list[ComponentMeta]:
    class Component(metaclass=ComponentMeta):
        pass

    return [ComponentMeta(f"C{idx}", (Component,), {}) for idx in range(n)]


DefaultConditionsBuilder = ConditionsBuilder[dict[str, str]]


def only_conditions(cb: DefaultConditionsBuilder) -> list[set[Condition]]:
    return [conditions for conditions, _metadata in cb]


def only_metadata(cb: DefaultConditionsBuilder) -> list[dict[str, str]]:
    return [metadata for _conditions, metadata in cb]


class TestConditionBuilder:
    def test_build_conditions_with_init(self) -> None:
        a, b = make_components(2)
        assert only_conditions(DefaultConditionsBuilder(a, b)) == [{a.all_of, b.all_of}]

    def test_add_variations_with_calls(self) -> None:
        a, b = make_components(2)
        cb = DefaultConditionsBuilder()
        cb(a)
        cb(b)
        assert only_conditions(cb) == [{a.all_of}, {b.all_of}]

    def test_add_conditions_with_context(self) -> None:
        a, b, c = make_components(3)
        cb = DefaultConditionsBuilder()
        with cb(a):
            cb(c)
        with cb(b):
            cb(c)

        assert only_conditions(cb) == [{a.all_of, c.all_of}, {b.all_of, c.all_of}]

    def test_use_as_context(self) -> None:
        a, b = make_components(2)
        with DefaultConditionsBuilder(a) as cb:
            cb(b)
        assert only_conditions(cb) == [{a.all_of, b.all_of}]

    def test_empty_builder_return_no_conditions(self) -> None:
        cb = DefaultConditionsBuilder()
        assert only_conditions(cb) == [set()]

    def test_init_with_metadata(self) -> None:
        cb = DefaultConditionsBuilder(metadata={"key": "value"})
        assert only_metadata(cb) == [{"key": "value"}]

    def test_update_metadata(self) -> None:
        cb = DefaultConditionsBuilder(metadata={"key": "init"})
        cb(metadata={"key": "call"})
        assert only_metadata(cb) == [{"key": "call"}]

    def test_merge_metadata(self) -> None:
        cb = DefaultConditionsBuilder(metadata={"init": "init"})
        with cb(metadata={"context": "context"}):
            cb(metadata={"call": "call"})
        assert only_metadata(cb) == [
            {"init": "init", "context": "context", "call": "call"}
        ]
