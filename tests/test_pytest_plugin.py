import pytest

# components module like in the README; the test files only build the suites
COMPONENTS = """
import abc

from morphtest import Component, Dependency, TestCase, if_not_overwritten


class Chip(Component, abc.ABC): ...
class Chip_None(Chip): ...
class Chip_A(Chip): ...


class Device(Component, abc.ABC):
    chip: Dependency[Chip] = if_not_overwritten(Chip_None)
class Device_Small(Device): ...
class Device_Big(Device):
    chip: Dependency[Chip_A]


class TestCase_OnDevice(TestCase, abc.ABC):
    device: Dependency[Device]

    def run(self) -> None:
        assert type(self.device).__name__ != "Device_Small" or self.fails_on_small is False

    fails_on_small = False


class TestCase_Any(TestCase_OnDevice): ...


class TestCase_NeedsChip(TestCase_OnDevice):
    chip: Dependency[Chip_A]


class TestCase_FailsOnSmall(TestCase_OnDevice):
    fails_on_small = True
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makepyfile(components=COMPONENTS)
    return pytester


def test_creates_test_per_depset(project: pytest.Pytester) -> None:
    project.makepyfile(
        test_devices="""
        from components import Device, TestCase_Any, TestCase_NeedsChip
        from morphtest import TestSuite

        ts = TestSuite(Device)
        ts(TestCase_Any)
        ts(TestCase_NeedsChip, repeat=2)
        """
    )
    result = project.runpytest_subprocess("-v")

    result.assert_outcomes(passed=4)
    output = result.stdout.str()
    for node_id in (
        "test_devices.py::ts[TestCase_Any[Chip=Chip_A, Device=Device_Big]]",
        "test_devices.py::ts[TestCase_Any[Chip=Chip_None, Device=Device_Small]]",
        "test_devices.py::ts[TestCase_NeedsChip[Chip=Chip_A, Device=Device_Big]]",
        "test_devices.py::ts[TestCase_NeedsChip[Chip=Chip_A, Device=Device_Big]#2]",
    ):
        assert f"{node_id} PASSED" in output


def test_failing_test_case_fails_its_test(project: pytest.Pytester) -> None:
    project.makepyfile(
        test_failing="""
        from components import Device, TestCase_FailsOnSmall
        from morphtest import TestSuite

        ts = TestSuite(TestCase_FailsOnSmall, Device)
        """
    )
    result = project.runpytest_subprocess()

    result.assert_outcomes(passed=1, failed=1)
    output = result.stdout.str()
    assert (
        "FAILED test_failing.py::ts[TestCase_FailsOnSmall[Chip=Chip_None, Device=Device_Small]]"
        in output
    )
    # the traceback starts in the test case, not in pytest or the plugin
    assert "components.py:22: AssertionError" in output
    assert "_pytest" not in output


def test_no_solution_is_collection_error_without_traceback(
    project: pytest.Pytester,
) -> None:
    project.makepyfile(
        test_conflict="""
        from components import Device_Big, Device_Small
        from morphtest import TestSuite

        ts = TestSuite(Device_Big, Device_Small)
        """
    )
    result = project.runpytest_subprocess()

    result.assert_outcomes(errors=1)
    output = result.stdout.str()
    assert "no solution found for the given conditions" in output
    assert "Traceback" not in output


def test_only_test_suites_named_ts_are_collected(project: pytest.Pytester) -> None:
    project.makepyfile(
        test_names="""
        from components import TestCase_Any
        from morphtest import TestSuite

        other = TestSuite(TestCase_Any)
        ts = "not a test suite"


        def test_plain() -> None:
            pass
        """
    )
    result = project.runpytest_subprocess("-v")

    result.assert_outcomes(passed=1)
    assert "test_names.py::test_plain PASSED" in result.stdout.str()


def test_select_tests_by_keyword(project: pytest.Pytester) -> None:
    project.makepyfile(
        test_devices="""
        from components import Device, TestCase_Any
        from morphtest import TestSuite

        ts = TestSuite(TestCase_Any, Device)
        """
    )
    result = project.runpytest_subprocess("-v", "-k", "Device_Small")

    result.assert_outcomes(passed=1, deselected=1)


class TestComponentFilter:
    SUITE = """
    from components import Device, TestCase_Any, TestCase_NeedsChip
    from morphtest import TestSuite

    ts = TestSuite(Device)
    ts(TestCase_Any)
    ts(TestCase_NeedsChip)


    def test_plain() -> None:
        pass
    """

    def test_selects_tests_with_component(self, project: pytest.Pytester) -> None:
        project.makepyfile(test_devices=self.SUITE)
        result = project.runpytest_subprocess("-v", "--component", "Device_Small")

        # test_plain is no test suite test and therefore kept
        result.assert_outcomes(passed=2, deselected=2)
        output = result.stdout.str()
        assert "ts[TestCase_Any[Chip=Chip_None, Device=Device_Small]] PASSED" in output
        assert "test_plain PASSED" in output

    def test_matches_subclasses(self, project: pytest.Pytester) -> None:
        project.makepyfile(test_devices=self.SUITE)
        result = project.runpytest_subprocess("--component", "TestCase_OnDevice")

        result.assert_outcomes(passed=4)

    def test_all_components_must_match(self, project: pytest.Pytester) -> None:
        project.makepyfile(test_devices=self.SUITE)
        result = project.runpytest_subprocess(
            "-v", "--component", "Chip_A", "--component", "TestCase_Any"
        )

        result.assert_outcomes(passed=2, deselected=2)
        assert "ts[TestCase_Any[Chip=Chip_A, Device=Device_Big]] PASSED" in (
            result.stdout.str()
        )

    def test_unknown_component_is_usage_error(self, project: pytest.Pytester) -> None:
        project.makepyfile(test_devices=self.SUITE)
        result = project.runpytest_subprocess("--component", "Device_Smal")

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert (
            "--component: unknown component Device_Smal (did you mean: Device_Small"
            in result.stderr.str()
        )
