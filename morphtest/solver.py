import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Generic, Literal, TypeVar

import pysat.solvers

from morphtest.component import AllOf, ComponentDependencySet, ComponentMeta, Condition

# python-sat backends that support incremental solving with assumptions
SatSolver = Literal["minisat22", "glucose4", "cadical153", "cadical195"]

C = TypeVar("C")

# components per entry implementation (e.g. a class variable of the entry)
PerEntry = Callable[[ComponentMeta], Sequence[ComponentMeta]]


def _in_subclass_relation(a: ComponentMeta, b: ComponentMeta) -> bool:
    return issubclass(a, b) or issubclass(b, a)


class ComponentSetSolver(Generic[C]):
    """
    recommended_components: preferred implementations, applied in list order when
        selecting the best fit of a group. Either a fixed list or a function getting
        the entry implementation of the group's first solution.
    """

    def __init__(
        self,
        entry_component: type[C],
        *,
        conditions: Iterable[Condition] = (),
        recommended_components: Sequence[ComponentMeta] | PerEntry = (),
        sat_solver: SatSolver = "minisat22",
    ) -> None:
        self._entry_component: ComponentMeta = entry_component  # type: ignore[assignment]
        self._conditions = frozenset(conditions)
        self._recommended_components = recommended_components
        self._sat_solver = sat_solver
        self._logger = logging.getLogger("morphtest.solver")

        self._tracked_components: set[ComponentMeta] = set()
        self._dependencies: dict[ComponentMeta, set[ComponentMeta]] = defaultdict(set)
        self._required_by: dict[ComponentMeta, set[ComponentMeta]] = defaultdict(set)
        self._defaults: dict[ComponentMeta, set[ComponentMeta]] = defaultdict(set)

        self._track_component_tree(self._entry_component)

    @property
    def components(self) -> frozenset[ComponentMeta]:
        """all components reachable from the entry (bases, subclasses, dependencies)"""
        return frozenset(self._tracked_components)

    def solve(self) -> Iterator[ComponentDependencySet[C]]:
        """
        Liefert pro Kombination der AllOf-Implementierungen (Gruppe) genau
        ein Depset, und zwar das am besten passende (siehe _select_best_fit).

        Statt alle Lösungen aufzuzählen und danach zu filtern, wird ein
        inkrementeller Solver verwendet: Pro Gruppe wird eine Lösung gesucht,
        innerhalb der Gruppe mit Assumptions die beste ausgewählt und danach
        die ganze Gruppe ausgeschlossen.
        """
        clauses, lookup = self._build_clauses()
        fvars = {component: vid for vid, component in lookup.items()}
        all_of_components = {
            condition.component
            for condition in self._conditions
            if isinstance(condition, AllOf)
        }
        group_vars = [
            vid
            for component, vid in fvars.items()
            if not component.is_abstract
            and any(issubclass(component, c) for c in all_of_components)
        ]

        # The clauses excluding already solved groups are only active with
        # groups_vid. Otherwise excluding the last group would make the formula
        # unsatisfiable at the top level, which some solvers (CaDiCaL) report on stdout.
        groups_vid = len(lookup) + 1
        next_vid = groups_vid + 1
        with pysat.solvers.Solver(
            name=self._sat_solver, bootstrap_with=clauses
        ) as solver:
            while solver.solve(assumptions=[groups_vid]):
                model = self._get_model(solver, lookup)
                group = [model[vid - 1] for vid in group_vars]
                yield self._select_best_fit(
                    solver, [groups_vid, *group], model, lookup, activation_vid=next_vid
                )
                next_vid += 1

                if not group:
                    break
                # exclude all solutions of this group
                solver.add_clause([-groups_vid, *(-lit for lit in group)])

    @staticmethod
    def _get_model(
        solver: pysat.solvers.Solver, lookup: dict[int, ComponentMeta]
    ) -> list[int]:
        # the model is ordered by variable (model[vid - 1] is vid or -vid) and also
        # contains the activation variables, which are not needed
        model: list[int] = solver.get_model()[: len(lookup)]
        return model

    def _recommended_for(
        self, model: list[int], lookup: dict[int, ComponentMeta]
    ) -> list[ComponentMeta]:
        if not callable(self._recommended_components):
            return list(self._recommended_components)
        entry_implementation = self._depset(
            {lookup[lit] for lit in model if lit > 0}, []
        ).entry_implementation()
        return list(self._recommended_components(entry_implementation))

    def _select_best_fit(
        self,
        solver: pysat.solvers.Solver,
        assumptions: list[int],
        model: list[int],
        lookup: dict[int, ComponentMeta],
        *,
        activation_vid: int,
    ) -> ComponentDependencySet[C]:
        recommended = self._recommended_for(model, lookup)
        fvars = {component: vid for vid, component in lookup.items()}
        recommended_vars = [
            vid
            for component in recommended
            if (vid := fvars.get(component)) is not None
        ]

        # narrow down to the solutions containing each recommended component where possible.
        # model always satisfies the current assumptions, so the solver is only needed
        # if the recommended component is not already part of it.
        for vid in recommended_vars:
            if model[vid - 1] > 0:
                assumptions = [*assumptions, vid]
            elif solver.solve(assumptions=[*assumptions, vid]):
                assumptions = [*assumptions, vid]
                model = self._get_model(solver, lookup)

        # enumerate the remaining candidates. The blocking clauses are only active
        # with activation_vid, which gets disabled afterwards.
        candidates: list[ComponentDependencySet[C]] = []
        while solver.solve(assumptions=[*assumptions, activation_vid]):
            model = self._get_model(solver, lookup)
            candidates.append(
                self._depset({lookup[lit] for lit in model if lit > 0}, recommended)
            )
            solver.add_clause([-activation_vid, *(-lit for lit in model)])
        solver.add_clause([-activation_vid])

        # ensure deterministic selection of depset when more then one remains
        # sort by depset with least amount of components and then str
        # amount of components might not be distinct, but str will be
        return min(candidates, key=lambda depset: (len(depset.components), str(depset)))

    def _depset(
        self, components: set[ComponentMeta], recommended: Sequence[ComponentMeta]
    ) -> ComponentDependencySet[C]:
        return ComponentDependencySet(
            self._entry_component,  # type: ignore[arg-type]
            (
                component
                for component in components
                if not component.is_abstract
                if not any(child in components for child in component.subclasses())
            ),
            conditions=self._conditions,
            recommended_components=recommended,
        )

    def _build_clauses(self) -> tuple[list[list[int]], dict[int, ComponentMeta]]:
        # Alle Constraints sind Implikationen und lassen sich direkt als CNF
        # schreiben. Ohne Hilfsvariablen (Tseitin) gibt es nur eine Variable pro
        # Komponente, wodurch die Blocking-Clauses von itersolve() kurz bleiben.
        fvars = {
            component: vid
            for vid, component in enumerate(
                sorted(self._tracked_components, key=str), start=1
            )
        }

        self._logger.debug(f"entry: {self._entry_component}")
        clauses = [[fvars[self._entry_component]]]

        for condition in sorted(self._conditions, key=str):
            clauses.extend(self._condition_clauses(condition, fvars))

        for component in sorted(self._tracked_components, key=str):
            clauses.extend(self._component_clauses(component, fvars))

        return clauses, {vid: component for component, vid in fvars.items()}

    def _is_entry(self, component: ComponentMeta) -> bool:
        """the entry component or one of its implementations (if it is abstract)"""
        return issubclass(component, self._entry_component)

    def _condition_clauses(
        self, condition: Condition, fvars: dict[ComponentMeta, int]
    ) -> Iterator[list[int]]:
        implementations = set(condition.component.implementations())

        self._logger.debug(
            f"any implementation of the explicit condition: {condition} is required: {' | '.join(map(str, sorted(implementations, key=str)))}"
        )
        yield [fvars[impl] for impl in implementations]

        for implementation in implementations:
            if self._is_entry(implementation):
                # the entry is always used, nothing has to depend on it
                continue
            required_by = self._required_by[implementation]
            self._logger.debug(
                f"implementation {implementation} for explicit condition: {condition} requires any of the components where it is a dependency: {' | '.join(map(str, sorted(required_by, key=str)))}"
            )
            yield [-fvars[implementation], *map(fvars.__getitem__, required_by)]

    def _component_clauses(
        self, component: ComponentMeta, fvars: dict[ComponentMeta, int]
    ) -> Iterator[list[int]]:
        var = fvars[component]
        subclasses = component.subclasses()
        if component.is_abstract:
            if subclasses:
                self._logger.debug(
                    f"{component} requires one of its subclasses: {' | '.join(map(str, sorted(subclasses, key=str)))}"
                )
            else:
                self._logger.debug(
                    f"exclude {component} because it is abstract and has no subclasses"
                )
            yield [-var, *map(fvars.__getitem__, subclasses)]
        else:
            for subclass in subclasses:
                dependencies = {
                    dep.component for dep in subclass.dependencies().values()
                }
                self._logger.debug(
                    f"{subclass} replaces {component} if: {' & '.join(map(str, sorted(dependencies, key=str)))}"
                )
                yield [
                    -var,
                    *(-fvars[dependency] for dependency in dependencies),
                    fvars[subclass],
                ]

            if (required_by := self._required_by[component]) and not self._is_entry(
                component
            ):
                self._logger.debug(
                    f"include {component} only if any of the following is included: {' | '.join(map(str, sorted(required_by, key=str)))}"
                )
                yield [-var, *map(fvars.__getitem__, required_by)]

            if defaults := self._defaults.get(component):
                self._logger.debug(
                    f"include defaults {' & '.join(map(str, sorted(defaults, key=str)))} "
                    f"for {component} when no specializations are included ({' | '.join(map(str, sorted(subclasses, key=str)))})"
                )
                for default in defaults:
                    yield [-var, *map(fvars.__getitem__, subclasses), fvars[default]]

        if component.is_root:
            yield from self._root_clauses(component, fvars)

        for dependency in sorted(self._dependencies[component], key=str):
            self._logger.debug(f"{component} depends on {dependency}")
            yield [-var, fvars[dependency]]

    def _root_clauses(
        self, root: ComponentMeta, fvars: dict[ComponentMeta, int]
    ) -> Iterator[list[int]]:
        implementations = set(root.implementations())
        for implementation in sorted(implementations, key=str):
            others = [
                other
                for other in implementations
                if not _in_subclass_relation(other, implementation)
            ]
            if others:
                self._logger.debug(
                    f"{implementation} excludes other implementations: {' | '.join(map(str, sorted(others, key=str)))}"
                )
                for other in others:
                    yield [-fvars[implementation], -fvars[other]]

    def _track_component_tree(self, component: ComponentMeta) -> None:
        if component in self._tracked_components:
            return
        self._tracked_components.add(component)

        for base in component.bases():
            self._track_component_tree(base)

        for subclass in component.subclasses():
            self._track_component_tree(subclass)
            self._dependencies[subclass].add(component)

        if not component.is_abstract:
            for dependency in component.dependencies().values():
                self._track_component_tree(dependency.component)
                self._dependencies[component].add(dependency.component)
                for implementation in dependency.component.implementations():
                    self._required_by[implementation].add(component)
                if default := dependency.if_not_overwritten:
                    self._defaults[component].add(default)
