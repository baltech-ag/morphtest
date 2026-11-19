import abc

import pytest

from morphtest.component import ComponentDependencySet, ComponentMeta, Dependency
from morphtest.suite import (
    BaseTestSuite,
    NoSolutionError,
    TestCase,
    TestSuite,
    group_depsets_by,
)


class TestDepsetsGrouping:
    def test_group_by_given_component_roots(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta): pass
        class A(Base, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class B(Base, abc.ABC): pass
        class B_0(B): pass
        class B_1(B): pass
        class C(Base, abc.ABC): pass
        class C_0(C): pass
        class C_1(C): pass
        # fmt: on

        depsets = [
            (ComponentDependencySet(A, {A_1, B_1, C_1}), 0),
            (ComponentDependencySet(A, {A_1, B_1, C_0}), 1),
            (ComponentDependencySet(A, {A_0, B_1, C_1}), 2),
            (ComponentDependencySet(A, {A_1, B_0, C_0}), 3),
        ]

        assert [
            (str(depset), repeat)
            for (depset, repeat) in group_depsets_by(depsets, group_by=[B, C])
        ] == [
            (f"{A_1}[{B}={B_0}, {C}={C_0}]", 3),
            (f"{A_1}[{B}={B_1}, {C}={C_0}]", 1),
            (f"{A_0}[{B}={B_1}, {C}={C_1}]", 2),
            (f"{A_1}[{B}={B_1}, {C}={C_1}]", 0),
        ]


class TestBaseTestSuite:
    def test_entry_is_first_condition(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta): pass
        class A(Base, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        # fmt: on

        assert list(map(str, BaseTestSuite(A))) == [f"{A_0}[]", f"{A_1}[]"]
        assert list(map(str, BaseTestSuite(A.all_of))) == [f"{A_0}[]", f"{A_1}[]"]
        assert list(map(str, BaseTestSuite(A.one_of))) == [f"{A_0}[]"]

    def test_yields_best_fit_per_all_of_group_of_every_leaf(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta): pass
        class A(Base, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class B(Base, abc.ABC): pass
        class B_0(B): pass
        class B_1(B): pass
        class C(Base, abc.ABC): pass
        class C_0(C):
            a: Dependency[A]
            b: Dependency[B]
        class C_1(C):
            a: Dependency[A]
            b: Dependency[B]
        class Entry(Base): c: Dependency[C]
        # fmt: on

        ts = BaseTestSuite(Entry, A, recommended_components=[B_1], group_by=[A])
        ts(C_0)
        with ts(C_1):
            ts(B_0, repeat=2)

        assert list(map(str, ts)) == [
            f"{Entry}[{A}={A_0}, {B}={B_0}, {C}={C_1}]",
            f"{Entry}[{A}={A_0}, {B}={B_0}, {C}={C_1}]",
            f"{Entry}[{A}={A_0}, {B}={B_1}, {C}={C_0}]",
            f"{Entry}[{A}={A_1}, {B}={B_0}, {C}={C_1}]",
            f"{Entry}[{A}={A_1}, {B}={B_0}, {C}={C_1}]",
            f"{Entry}[{A}={A_1}, {B}={B_1}, {C}={C_0}]",
        ]

    def test_raises_no_solution_error_with_diagnosis(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta): pass
        class A(Base, abc.ABC): pass
        class A_0(A): pass
        class A_1(A): pass
        class Missing(Base, abc.ABC): pass
        class Entry(Base): a: Dependency[A]
        # fmt: on

        with pytest.raises(NoSolutionError) as exc_info:
            list(BaseTestSuite(Entry, A_0, A_1))
        assert exc_info.value.not_implemented == frozenset()
        assert exc_info.value.conflicting_conditions == {A_0.all_of, A_1.all_of}

        with pytest.raises(NoSolutionError) as exc_info:
            list(BaseTestSuite(Entry, Missing))
        assert exc_info.value.not_implemented == {Missing}
        assert exc_info.value.conflicting_conditions == {Missing.all_of}


class TestTestSuite:
    def test_fans_out_over_test_cases_sorted_by_group_by(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta):
            def __init__(self, **kwargs: object) -> None: pass
        class Device(Base, abc.ABC): pass
        class Device_0(Device): pass
        class Device_1(Device): pass
        class TestCase_SuiteFanout(TestCase, abc.ABC):
            device: Dependency[Device]
            group_by = (TestCase,)
            def run(self) -> None: pass
        class TestCase_SuiteFanout_0(TestCase_SuiteFanout): pass
        class TestCase_SuiteFanout_1(TestCase_SuiteFanout): pass
        # fmt: on

        # the group restricts the suite to the test cases of this test
        assert list(map(str, TestSuite(TestCase_SuiteFanout, Device))) == [
            f"{TestCase_SuiteFanout_0}[{Device}={Device_0}]",
            f"{TestCase_SuiteFanout_0}[{Device}={Device_1}]",
            f"{TestCase_SuiteFanout_1}[{Device}={Device_0}]",
            f"{TestCase_SuiteFanout_1}[{Device}={Device_1}]",
        ]

    def test_recommended_components_of_test_case(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta):
            def __init__(self, **kwargs: object) -> None: pass
        class Device(Base, abc.ABC): pass
        class Device_0(Device): pass
        class Device_1(Device): pass
        class TestCase_SuiteRecommended(TestCase, abc.ABC):
            device: Dependency[Device]
            def run(self) -> None: pass
        class TestCase_SuiteRecommended_A(TestCase_SuiteRecommended):
            recommended_components = (Device_1,)
        class TestCase_SuiteRecommended_B(TestCase_SuiteRecommended): pass
        # fmt: on

        depsets = list(TestSuite(TestCase_SuiteRecommended))
        assert list(map(str, depsets)) == [
            f"{TestCase_SuiteRecommended_B}[{Device}={Device_0}]",
            f"{TestCase_SuiteRecommended_A}[{Device}={Device_1}]",
        ]
        assert depsets[0].recommended_components == []
        assert depsets[1].recommended_components == [Device_1]

    def test_test_case_is_best_fit_unless_condition(self) -> None:
        # fmt: off
        class Base(metaclass=ComponentMeta):
            def __init__(self, **kwargs: object) -> None: pass
        class Device(Base, abc.ABC): pass
        class Device_0(Device): pass
        class Device_1(Device): pass
        class TestCase_SuiteBestFit(TestCase, abc.ABC):
            device: Dependency[Device]
            def run(self) -> None: pass
        class TestCase_SuiteBestFit_A(TestCase_SuiteBestFit): pass
        class TestCase_SuiteBestFit_B(TestCase_SuiteBestFit): pass
        # fmt: on

        # without fan-out over the test cases: one best fitting test case per device
        assert list(map(str, TestSuite(TestCase_SuiteBestFit.one_of, Device))) == [
            f"{TestCase_SuiteBestFit_A}[{Device}={Device_0}]",
            f"{TestCase_SuiteBestFit_A}[{Device}={Device_1}]",
        ]
        assert len(list(TestSuite(TestCase_SuiteBestFit, Device))) == 4

    def test_run_calls_run_of_test_cases(self) -> None:
        events: list[str] = []

        # fmt: off
        class TestCase_SuiteRun(TestCase, abc.ABC):
            def run(self) -> None: events.append(type(self).__name__)
        class TestCase_SuiteRun_A(TestCase_SuiteRun): pass
        class TestCase_SuiteRun_B(TestCase_SuiteRun): pass
        # fmt: on

        TestSuite(TestCase_SuiteRun).run()
        assert events == ["TestCase_SuiteRun_A", "TestCase_SuiteRun_B"]

    def test_run_builds_dependencies_of_test_cases(self) -> None:
        events: list[str] = []

        # fmt: off
        class Base(metaclass=ComponentMeta):
            def __init__(self, **kwargs: object) -> None: pass
        class Device(Base, abc.ABC): pass
        class Device_Big(Device): pass
        class TestCase_SuiteDeps(TestCase):
            device: Dependency[Device]
            def run(self) -> None: events.append(type(self.device).__name__)
        # fmt: on

        TestSuite(TestCase_SuiteDeps).run()
        assert events == ["Device_Big"]

    def test_run_raises_exception_of_failing_test_case(self) -> None:
        # fmt: off
        class TestCase_SuiteFailing(TestCase):
            def run(self) -> None: raise AssertionError("failed")
        # fmt: on

        with pytest.raises(AssertionError, match="failed"):
            TestSuite(TestCase_SuiteFailing).run()
