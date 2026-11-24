import abc
import difflib
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager
from typing import Any, ClassVar, Generic, TypedDict, TypeVar, cast, overload

from morphtest.component import (
    Component,
    ComponentDependencySet,
    ComponentMeta,
    Condition,
    ConditionLike,
    ConditionsBuilder,
)
from morphtest.solver import ComponentSetSolver, PerEntry, SatSolver

C = TypeVar("C")


class NoSolutionError(Exception):
    """
    Raised when a condition set of a test suite has no solution.

    not_implemented: components of the conditions without any implementation
    conflicting_conditions: conditions which make the condition set solvable when removed
    """

    def __init__(
        self,
        conditions: Iterable[Condition],
        *,
        not_implemented: Iterable[ComponentMeta],
        conflicting_conditions: Iterable[Condition],
    ) -> None:
        self.conditions = frozenset(conditions)
        self.not_implemented = frozenset(not_implemented)
        self.conflicting_conditions = frozenset(conflicting_conditions)

        lines = [
            f"no solution found for the given conditions: {', '.join(sorted(map(str, self.conditions)))}"
        ]
        if self.not_implemented:
            lines.append("no implementations found for these components:")
            lines.extend(f"* {c}" for c in sorted(map(str, self.not_implemented)))
        if self.conflicting_conditions:
            lines.append("remove any of these conditions to get a solution:")
            lines.extend(
                f"* {c}" for c in sorted(map(str, self.conflicting_conditions))
            )
        else:
            lines.append("could not find individual conflicting conditions")
        super().__init__("\n".join(lines))


def group_depsets_by(
    depsets: Iterable[tuple[ComponentDependencySet[C], int]],
    group_by: Sequence[ComponentMeta] | PerEntry,
) -> Iterator[tuple[ComponentDependencySet[C], int]]:
    """
    Sorts depsets by their implementations of group_by (in order of priority),
    so consecutive depsets share as many of these implementations as possible.

    group_by is either a fixed list or a function getting the entry implementation
    of a depset.
    """

    def _component_key(
        component: ComponentMeta, group_by: Sequence[ComponentMeta]
    ) -> tuple[int, str]:
        component_ancestors = list(component.ancestors())
        for idx, preferred in enumerate(group_by):
            if preferred in component_ancestors:
                return idx, str(component)
        return len(group_by), str(component)

    def _depset_key(
        depset: tuple[ComponentDependencySet[C], int],
    ) -> tuple[tuple[int, str], ...]:
        depset_group_by = (
            group_by(depset[0].entry_implementation())
            if callable(group_by)
            else group_by
        )
        return tuple(
            sorted(
                _component_key(component, depset_group_by)
                for component in depset[0].implementations()
            )
        )

    yield from sorted(depsets, key=_depset_key)


class ConditionsMetadata(TypedDict, total=False):
    repeat: int


class BaseTestSuite(Generic[C]):
    """
    Tree of condition sets, which resolves to the depsets of the entry component.

    The first condition is also the entry: the component that depset.build()
    instantiates. A bare component means .all_of (fan-out over its implementations),
    .one_of selects only the best fitting implementation.

        ts = BaseTestSuite(Test, Device)     # entry Test; conditions of all leafs
        ts(Test_A)                           # leaf: Test, Device, Test_A
        with ts(Test_B):                     # node without own depsets
            ts(Protocol_X)                   # leaf: Test, Device, Test_B, Protocol_X
            ts(Protocol_Y, repeat=3)         # leaf: Test, Device, Test_B, Protocol_Y

    Iterating yields the best fitting depset per AllOf group of every leaf,
    sorted by group_by and repeated `repeat` times.
    recommended_components and group_by are fixed lists or functions getting the
    entry implementation (see ComponentSetSolver and group_depsets_by).
    """

    __test__ = False  # not a pytest test class

    @overload
    def __init__(
        self: "BaseTestSuite[C]",
        entry: type[C],
        *conditions: ConditionLike,
        repeat: int = 1,
        recommended_components: Sequence[ComponentMeta] | PerEntry = (),
        group_by: Sequence[ComponentMeta] | PerEntry = (),
        sat_solver: SatSolver = "minisat22",
    ) -> None: ...
    @overload
    def __init__(
        self: "BaseTestSuite[Any]",
        entry: Condition,
        *conditions: ConditionLike,
        repeat: int = 1,
        recommended_components: Sequence[ComponentMeta] | PerEntry = (),
        group_by: Sequence[ComponentMeta] | PerEntry = (),
        sat_solver: SatSolver = "minisat22",
    ) -> None: ...
    def __init__(
        self,
        entry: type[C] | Condition,
        *conditions: ConditionLike,
        repeat: int = 1,
        recommended_components: Sequence[ComponentMeta] | PerEntry = (),
        group_by: Sequence[ComponentMeta] | PerEntry = (),
        sat_solver: SatSolver = "minisat22",
    ) -> None:
        entry_condition = (
            entry
            if isinstance(entry, Condition)
            else cast("ComponentMeta", entry).all_of
        )
        self._setup(
            cast("type[C]", entry_condition.component),
            (entry_condition, *conditions),
            repeat=repeat,
            recommended_components=recommended_components,
            group_by=group_by,
            sat_solver=sat_solver,
        )

    def _setup(  # noqa: PLR0913
        self,
        entry_component: type[C],
        conditions: Sequence[ConditionLike],
        *,
        repeat: int,
        recommended_components: Sequence[ComponentMeta] | PerEntry,
        group_by: Sequence[ComponentMeta] | PerEntry,
        sat_solver: SatSolver,
    ) -> None:
        self.entry_component = entry_component
        self.conditions_builder = ConditionsBuilder[ConditionsMetadata](
            *conditions, metadata={"repeat": repeat}
        )
        self.recommended_components = recommended_components
        self.group_by = group_by
        self.sat_solver: SatSolver = sat_solver

    def conditions(self) -> Iterator[tuple[set[Condition], ConditionsMetadata]]:
        yield from self.conditions_builder

    def __call__(
        self, *conditions: ConditionLike, repeat: int = 1
    ) -> AbstractContextManager[None]:
        return self.conditions_builder(*conditions, metadata={"repeat": repeat})

    def solve(
        self, conditions: Iterable[Condition]
    ) -> Iterator[ComponentDependencySet[C]]:
        return ComponentSetSolver(
            self.entry_component,
            conditions=conditions,
            recommended_components=self.recommended_components,
            sat_solver=self.sat_solver,
        ).solve()

    def __iter__(self) -> Iterator[ComponentDependencySet[C]]:
        all_depsets: list[tuple[ComponentDependencySet[C], int]] = []
        for conditions, metadata in self.conditions_builder:
            depsets = list(self.solve(conditions))
            if not depsets:
                raise self._no_solution_error(conditions)
            all_depsets.extend(
                (depset, metadata.get("repeat", 1)) for depset in depsets
            )

        yield from (
            depset
            for depset, repeat in group_depsets_by(all_depsets, group_by=self.group_by)
            for _ in range(repeat)
        )

    def _no_solution_error(self, conditions: set[Condition]) -> NoSolutionError:
        return NoSolutionError(
            conditions,
            not_implemented=(
                condition.component
                for condition in conditions
                if not list(condition.component.implementations())
            ),
            conflicting_conditions=(
                condition
                for condition in conditions
                if next(self.solve(conditions - {condition}), None) is not None
            ),
        )


class TestCase(Component, abc.ABC):
    """
    Root of all test cases, the entry of every TestSuite.

    Implementations declare their dependencies like any other component and
    implement run(); an exception (e.g. AssertionError) fails the test case.

    recommended_components: preferred implementations of the components that are
        not fanned out, applied in list order (see ComponentSetSolver)
    group_by: depsets are sorted by their implementations of these components
        (in priority order), so consecutive test cases share them. Usually set once
        on a common base, so all test cases are sorted the same way.
    """

    __test__ = False  # not a pytest test class (also for all subclasses)

    recommended_components: ClassVar[Sequence[ComponentMeta]] = ()
    group_by: ClassVar[Sequence[ComponentMeta]] = ()

    @abc.abstractmethod
    def run(self) -> None: ...


class UnknownComponentError(LookupError):
    """no (or more than one) component of this name, with a hint in the message"""


def components_by_name() -> dict[str, list[ComponentMeta]]:
    """all components a TestSuite can use (reachable from TestCase), by name"""
    components: dict[str, list[ComponentMeta]] = {}
    for component in ComponentSetSolver(TestCase).components:
        components.setdefault(str(component), []).append(component)
    return components


def find_component(name: str) -> ComponentMeta:
    """the component reachable from TestCase with this name"""
    components = components_by_name()
    if name not in components:
        close = difflib.get_close_matches(name, components, n=5)
        hint = f" (did you mean: {', '.join(close)}?)" if close else ""
        raise UnknownComponentError(f"unknown component {name}{hint}")
    if len(candidates := components[name]) > 1:
        modules = ", ".join(sorted(f"{c.__module__}.{c}" for c in candidates))
        raise UnknownComponentError(f"ambiguous component {name}: {modules}")
    return candidates[0]


def _recommended_components(test_case: ComponentMeta) -> Sequence[ComponentMeta]:
    return cast("type[TestCase]", test_case).recommended_components


def _group_by(test_case: ComponentMeta) -> Sequence[ComponentMeta]:
    return cast("type[TestCase]", test_case).group_by


class TestSuite(BaseTestSuite[TestCase]):
    """
    BaseTestSuite with TestCase as entry. Unlike BaseTestSuite, the entry is no
    condition: like every other component, TestCase resolves to the best fit
    unless it (or a subclass) is a condition.

        ts = TestSuite(TestCase, Device)     # every TestCase on every Device
        ts(TestCase_A, Protocol)             # leaf: TestCase_A on every Device x Protocol
        TestSuite(Device)                    # one best fitting TestCase per Device

    recommended_components and group_by come from the class variables of the
    TestCase implementation of each depset.
    """

    def __init__(
        self,
        *conditions: ConditionLike,
        repeat: int = 1,
        sat_solver: SatSolver = "minisat22",
    ) -> None:
        self._setup(
            TestCase,
            conditions,
            repeat=repeat,
            recommended_components=_recommended_components,
            group_by=_group_by,
            sat_solver=sat_solver,
        )

    def run(self) -> None:
        """builds the TestCase of every depset and calls its run()"""
        for depset in self:
            depset.build().run()
