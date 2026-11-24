"""example components and test suite for test_cli.py (loaded by the CLI, not collected by pytest)"""

import abc

from morphtest import Component, Dependency, TestCase, TestSuite


class CliDevice(Component, abc.ABC): ...


class CliDevice_Big(CliDevice): ...


class CliDevice_Small(CliDevice): ...


class TestCase_Cli(TestCase, abc.ABC):
    device: Dependency[CliDevice]

    def run(self) -> None:
        print(f"{type(self).__name__} on {type(self.device).__name__}")  # noqa: T201


class TestCase_Cli_A(TestCase_Cli): ...


class TestCase_Cli_B(TestCase_Cli): ...


class TestCase_CliFailing(TestCase):
    def run(self) -> None:
        raise AssertionError("failed on purpose")


ts = TestSuite(TestCase_Cli, CliDevice)
ts(TestCase_Cli_A)
ts(TestCase_Cli_B, repeat=2)
