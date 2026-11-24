"""
pytest plugin (registered via the pytest11 entry point): every test module defining a
TestSuite `ts` gets one pytest test per depset, e.g.
`test_devices.py::ts[TestCase_Any[Chip=Chip_A, Device=Device_Big]]`.
"""

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from _pytest._code import Code, Traceback

from morphtest.component import ComponentDependencySet
from morphtest.suite import NoSolutionError, TestCase, TestSuite

SUITE_NAME = "ts"


class DepsetItem(pytest.Item):
    """builds the TestCase of a depset and calls its run()"""

    def __init__(
        self, *, depset: ComponentDependencySet[TestCase], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.depset = depset

    def runtest(self) -> None:
        __tracebackhide__ = True
        self.depset.build().run()

    def _traceback_filter(
        self, excinfo: pytest.ExceptionInfo[BaseException]
    ) -> Traceback:
        # like pytest.Function: start the traceback at the test, not in pytest itself
        if self.config.getoption("fulltrace", default=False):
            return excinfo.traceback
        code = Code.from_function(DepsetItem.runtest)
        return excinfo.traceback.cut(
            path=code.path, firstlineno=code.firstlineno
        ).filter(excinfo)

    def reportinfo(self) -> tuple[Path, int | None, str]:
        return self.path, None, self.name


@pytest.hookimpl
def pytest_pycollect_makeitem(
    collector: pytest.Module | pytest.Class, name: str, obj: object
) -> list[pytest.Item] | None:
    if name != SUITE_NAME or not isinstance(obj, TestSuite):
        return None
    if not isinstance(collector, pytest.Module):
        return None

    try:
        depsets = list(obj)
    except NoSolutionError as e:
        # reported as collection error of the module, without traceback
        raise collector.CollectError(str(e)) from e

    items: list[pytest.Item] = []
    repetitions: Counter[str] = Counter()
    for depset in depsets:
        depset_name = str(depset)
        repetitions[depset_name] += 1
        if (repetition := repetitions[depset_name]) > 1:
            depset_name = f"{depset_name}#{repetition}"
        items.append(
            DepsetItem.from_parent(
                collector, name=f"{SUITE_NAME}[{depset_name}]", depset=depset
            )
        )
    return items
