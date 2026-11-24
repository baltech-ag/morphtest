"""Command line interface: `morphtest run`, `morphtest describe` and `morphtest overview`."""

import difflib
import importlib
import importlib.util
import inspect
import os
import sys
import tempfile
import webbrowser
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from types import ModuleType
from typing import Annotated, NoReturn

import typer

from morphtest.component import (
    AllOf,
    ComponentDependencySet,
    ComponentMeta,
    ConditionLike,
    OneOf,
)
from morphtest.overview import save_components_overview
from morphtest.solver import ComponentSetSolver
from morphtest.suite import BaseTestSuite, NoSolutionError, TestCase, TestSuite

EXIT_USAGE_ERROR = 2

app = typer.Typer(
    name="morphtest",
    help="Runs and inspects morphtest test suites.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


class CliError(Exception):
    """setup error (unknown target/component, missing ts, ...), reported without traceback"""


@contextmanager
def _report_errors() -> Iterator[None]:
    try:
        yield
    except (CliError, NoSolutionError) as e:
        _fail(str(e))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(EXIT_USAGE_ERROR)


# --- targets -----------------------------------------------------------------

_loaded_files: dict[Path, ModuleType] = {}


def load_target(target: str) -> ModuleType:
    """imports a module (`pkg.components`) or loads a file (`tests/devices.py`)"""
    path = Path(target)
    if target.endswith(".py") or path.is_file():
        return _load_file(path)

    # like `python -m`: modules of the working directory are importable
    if (cwd := str(Path.cwd())) not in sys.path:
        sys.path.insert(0, cwd)
    try:
        return importlib.import_module(target)
    except ModuleNotFoundError as e:
        raise CliError(f"cannot import {target}: {e}") from e


def _load_file(path: Path) -> ModuleType:
    path = path.resolve()
    if not path.is_file():
        raise CliError(f"file not found: {path}")
    if (module := _loaded_files.get(path)) is not None:
        # loading it again would define its components a second time
        return module

    # the file may import its siblings (like a script or a pytest test module)
    if (directory := str(path.parent)) not in sys.path:
        sys.path.insert(0, directory)

    name = path.stem
    if name in sys.modules:
        name = f"{name}_{len(_loaded_files)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CliError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _loaded_files[path] = module
    return module


# --- conditions --------------------------------------------------------------

_SUFFIXES: dict[str, Callable[[ComponentMeta], ConditionLike]] = {
    "": lambda component: component,
    "all_of": AllOf,
    "one_of": OneOf,
}


def _components_by_name() -> dict[str, list[ComponentMeta]]:
    """all components a TestSuite can use (reachable from TestCase), by name"""
    components: dict[str, list[ComponentMeta]] = {}
    for component in ComponentSetSolver(TestCase).components:
        components.setdefault(str(component), []).append(component)
    return components


def parse_condition(text: str) -> ConditionLike:
    """`Name`, `Name.all_of` or `Name.one_of`"""
    name, _, suffix = text.partition(".")
    if suffix not in _SUFFIXES:
        raise CliError(
            f"unknown suffix .{suffix} in {text} (allowed: .all_of, .one_of)"
        )

    components = _components_by_name()
    if name not in components:
        close = difflib.get_close_matches(name, components, n=5)
        hint = f" (did you mean: {', '.join(close)}?)" if close else ""
        raise CliError(f"unknown component {name}{hint}")
    if len(candidates := components[name]) > 1:
        modules = ", ".join(sorted(f"{c.__module__}.{c}" for c in candidates))
        raise CliError(f"ambiguous component {name}: {modules}")

    return _SUFFIXES[suffix](candidates[0])


def condition_completions(target: str, incomplete: str) -> list[str]:
    """conditions starting with incomplete, after importing target"""
    try:
        load_target(target)
    except Exception:  # noqa: BLE001 completion must never fail
        return []
    candidates = (
        f"{name}.{suffix}" if suffix else name
        for name in sorted(_components_by_name())
        for suffix in _SUFFIXES
    )
    return [candidate for candidate in candidates if candidate.startswith(incomplete)]


def _complete_conditions(ctx: typer.Context, incomplete: str) -> list[str]:
    target = ctx.params.get("target")
    return condition_completions(target, incomplete) if target else []


# --- commands ----------------------------------------------------------------

TargetArgument = Annotated[
    str,
    typer.Argument(
        help="module (pkg.components) or file (tests/devices.py) to import",
        show_default=False,
    ),
]


@app.command()
def run(
    target: TargetArgument,
    conditions: Annotated[
        list[str] | None,
        typer.Argument(
            help="components to fan out over: Name, Name.all_of or Name.one_of",
            autocompletion=_complete_conditions,
            show_default=False,
        ),
    ] = None,
) -> None:
    """Runs TestSuite(*CONDITIONS) over the components of TARGET."""
    with _report_errors():
        load_target(target)
        suite = TestSuite(*(parse_condition(c) for c in conditions or ()))
        depsets = list(suite)

    for idx, depset in enumerate(depsets, start=1):
        typer.echo(f"[{idx}/{len(depsets)}] {depset}")
        depset.build().run()
    typer.echo(f"{len(depsets)} test{'' if len(depsets) == 1 else 's'} passed")


@app.command()
def describe(target: TargetArgument) -> None:
    """Shows conditions, tests and components of the test suite `ts` of TARGET."""
    with _report_errors():
        suite = getattr(load_target(target), "ts", None)
        if not isinstance(suite, BaseTestSuite):
            raise CliError(f"{target} defines no test suite `ts`")
        depsets: Sequence[ComponentDependencySet[object]] = list(suite)

    typer.echo("# CONDITIONS")
    for conditions, metadata in suite.conditions():
        typer.echo(
            f"{', '.join(sorted(map(str, conditions)))} (repeat={metadata.get('repeat', 1)})"
        )

    typer.echo("\n# TESTS")
    for depset in depsets:
        typer.echo(str(depset))

    typer.echo("\n# COMPONENTS")
    counts = Counter(
        str(component) for depset in depsets for component in depset.components
    )
    for name, count in sorted(counts.items()):
        typer.echo(f"{name}: {count}")
    typer.echo("------")
    typer.echo(f"{len(depsets)} tests in this test suite")


def _source_url(template: str | None) -> Callable[[ComponentMeta], str | None]:
    def url(component: ComponentMeta) -> str | None:
        try:
            source_file = inspect.getsourcefile(component)
            _, line_idx = inspect.findsource(component)
        except (OSError, TypeError):
            return None
        if source_file is None:
            return None

        path = Path(source_file).resolve()
        line = line_idx + 1
        if template is None:
            return f"{path.as_uri()}#L{line}"
        with suppress(ValueError):  # outside of the working directory: absolute
            path = path.relative_to(Path.cwd())
        return template.format(path=path.as_posix(), line=line)

    return url


@app.command()
def overview(
    target: TargetArgument,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="write the HTML to this file instead of opening it in the browser",
        ),
    ] = None,
    source_url: Annotated[
        str | None,
        typer.Option(
            help="link to the source of a component, with {path} (relative to the "
            "working directory) and {line}, e.g. "
            "'https://github.com/org/repo/blob/main/{path}#L{line}'; "
            "default: local file links"
        ),
    ] = None,
) -> None:
    """Shows all components reachable from TestCase as HTML tree."""
    with _report_errors():
        load_target(target)

    roots = [c for c in ComponentSetSolver(TestCase).components if c.is_root]
    if output is None:
        fd, name = tempfile.mkstemp(prefix="morphtest-overview-", suffix=".html")
        os.close(fd)
        path = Path(name)
    else:
        path = output

    save_components_overview(
        path, roots=roots, entry_component=TestCase, source_url=_source_url(source_url)
    )
    if output is None:
        webbrowser.open(path.resolve().as_uri())
    else:
        typer.echo(f"overview written to {path}")
