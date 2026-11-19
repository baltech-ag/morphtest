import abc
import typing

import pytest

from morphtest.component import ComponentMeta, Dependency, if_not_overwritten
from morphtest.solver import ComponentSetSolver, SatSolver


def assert_solutions(solver: ComponentSetSolver[object], expected: list[str]) -> None:
    assert sorted(map(str, solver.solve())) == sorted(expected)


class TestComponentSetSolver:
    def test_includes_dependencies(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component): pass
        class B(Component): a: Dependency[A]
        # fmt: on

        assert_solutions(ComponentSetSolver(B), [f"{B}[{A}={A}]"])

    def test_includes_base_classes(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        class B(Component): a: Dependency[A_0]
        # fmt: on

        assert_solutions(ComponentSetSolver(B), [f"{B}[{A}={A}_0]"])

    def test_includes_subclasses(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Root(Component, abc.ABC): pass
        class Root_Middle(Root, abc.ABC): pass
        class Root_Leaf(Root_Middle): pass
        # fmt: onf

        assert_solutions(ComponentSetSolver(Root), [f"{Root}_Leaf[]"])

    def test_diamond_with_dependencies(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Shared(Component): pass

        class MiddleA(Component): dep: Dependency[Shared]
        class MiddleB(Component): dep: Dependency[Shared]

        class Leaf(Component):
            a: Dependency[MiddleA]
            b: Dependency[MiddleB]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(Leaf),
            [f"{Leaf}[{MiddleA}={MiddleA}, {MiddleB}={MiddleB}, {Shared}={Shared}]"],
        )

    def test_diamond_with_classes(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class Diamond(Component, abc.ABC): pass
        class Diamond_A(Diamond, abc.ABC): pass
        class Diamond_B(Diamond, abc.ABC): pass
        class Diamond_Combined(Diamond_A, Diamond_B): pass
        # fmt: on

        assert_solutions(ComponentSetSolver(Diamond), [f"{Diamond_Combined}[]"])

    def test_include_component_when_no_dependent_is_included_but_has_subclasses(
        self,
    ) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class C(Component, abc.ABC): pass
        class C_Middle(C, abc.ABC): pass
        class C_Leaf(C_Middle): pass

        class D(Component): c: Dependency[C_Middle]
        class C_D(C_Middle): d: Dependency[D]
        # fmt: on

        assert_solutions(ComponentSetSolver(C_Leaf), [f"{C_Leaf}[]"])

    def test_include_component_without_dependency_but_when_inherited_from(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class B(Component): a: Dependency[A]
        class C(Component, abc.ABC): pass
        class C_A(C, A): pass
        class C_B(C): support: Dependency[B]
        class E(Component): c: Dependency[C]
        # fmt: on

        assert_solutions(ComponentSetSolver(E), [f"{E}[{A}={C_A}, {C}={C_A}]"])

    def test_include_component_only_if_implementation_exists(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class C(Component): b: Dependency[A]
        # fmt: on

        assert_solutions(ComponentSetSolver(C), [])

    def test_all_of_condition(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class B(Component): a: Dependency[A]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(B, conditions=[A_0.all_of]), [f"{B}[{A}={A_0}]"]
        )

    def test_all_of_condition_on_abstract_entry(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class B(Component, abc.ABC): pass
        class B_0(B): pass
        class B_1(B): pass
        class A_0(A): b: Dependency[B]
        class A_1(A): b: Dependency[B_0]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(A, conditions=[A.all_of, B.all_of]),
            [f"{A_0}[{B}={B_0}]", f"{A_0}[{B}={B_1}]", f"{A_1}[{B}={B_0}]"],
        )

    def test_single_one_of_condition(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class One(Component, abc.ABC): pass
        class One_0(One): pass
        class One_1(One): pass
        class Entry(Component): single: Dependency[One]
        # fmt: on

        assert (
            len(list(ComponentSetSolver(Entry, conditions=[One.one_of]).solve())) == 1
        )

    def test_single_all_of_condition(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class One(Component, abc.ABC): pass
        class One_0(One): pass
        class One_1(One): pass
        class Entry(Component): single: Dependency[One]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(Entry, conditions=[One.all_of]),
            [f"{Entry}[{One}={One_0}]", f"{Entry}[{One}={One_1}]"],
        )

    def test_combination_one_and_all_of_conditions(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class One(Component, abc.ABC): pass
        class One_0(One): pass
        class One_1(One): pass
        class All(Component, abc.ABC): pass
        class All_0(All): pass
        class All_1(All): pass
        class Entry(Component):
            one: Dependency[One]
            all_: Dependency[All]
        # fmt: on

        assert (
            len(
                list(
                    ComponentSetSolver(
                        Entry, conditions=[One.one_of, All.all_of]
                    ).solve()
                )
            )
            == 2
        )

    def test_resolve_only_when_conditions_appear_in_dependency_tree(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class D_1(D): a: Dependency[A]
        class Entry(Component): d: Dependency[D]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(Entry, conditions=[D.all_of, A_0.one_of]),
            [f"{Entry}[{A}={A_0}, {D}={D_1}]"],
        )

    def test_select_best_fit_base_on_recommended_components(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class B(Component, abc.ABC): pass
        class B_0(B): pass
        class B_1(B): pass
        class C(Component, abc.ABC): pass
        class C_0(C): pass
        class C_1(C): pass
        class D(Component): pass
        class Entry(Component):
            a: Dependency[A]
            b: Dependency[B]
            c: Dependency[C]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(Entry, recommended_components=[C_1, D, B_0, A_1]),
            [f"{Entry}[{A}={A_1}, {B}={B_0}, {C}={C_1}]"],
        )

    @pytest.mark.parametrize("sat_solver", typing.get_args(SatSolver))
    def test_sat_solvers_yield_same_solutions(self, sat_solver: SatSolver) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class A(Component, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class B(Component, abc.ABC): pass
        class B_0(B): pass
        class B_1(B): a: Dependency[A_1]
        class Entry(Component):
            a: Dependency[A]
            b: Dependency[B]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(
                Entry,
                conditions=[A.all_of],
                recommended_components=[B_1],
                sat_solver=sat_solver,
            ),
            [f"{Entry}[{A}={A_0}, {B}={B_0}]", f"{Entry}[{A}={A_1}, {B}={B_1}]"],
        )

    def test_select_only_specialization(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class D_1(D): pass
        class A(Component): d: Dependency[D]
        class A_D1(A): d: Dependency[D_1]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(A, conditions=[D.all_of]),
            [f"{A}[{D}={D_0}]", f"{A_D1}[{D}={D_1}]"],
        )

    def test_select_default_if_not_overwritten(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class D_1(D): pass
        class C(Component, abc.ABC): d: Dependency[D] = if_not_overwritten(D_1)
        class C_0(C): pass
        # fmt: on

        assert_solutions(
            ComponentSetSolver(C, conditions=[D.all_of]), [f"{C_0}[{D}={D_1}]"]
        )

    def test_select_all_if_overwritten(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class D_1(D): pass
        class C(Component, abc.ABC): d: Dependency[D] = if_not_overwritten(D_1)
        class C_0(C): d: Dependency[D]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(C, conditions=[D.all_of]),
            [f"{C_0}[{D}={D_0}]", f"{C_0}[{D}={D_1}]"],
        )

    def test_select_all_if_overwritten_in_specialization(self) -> None:
        # fmt: off
        class Component(metaclass=ComponentMeta): pass
        class D(Component, abc.ABC): pass
        class D_0(D): pass
        class D_1(D): pass
        class C(Component): d: Dependency[D] = if_not_overwritten(D_0)
        class C_D1(C): d: Dependency[D_1]
        # fmt: on

        assert_solutions(
            ComponentSetSolver(C, conditions=[D.all_of]),
            [f"{C}[{D}={D_0}]", f"{C_D1}[{D}={D_1}]"],
        )
