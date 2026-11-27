# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

morphtest is a test framework built on a generic component framework: dependency
injection via the `ComponentMeta` metaclass, resolved by a SAT solver into all
consistent component combinations (test matrices).

German commit messages and comments are used throughout the project.

The concepts (components, naming rules, defaults, specialization, solver, conditions,
TestCase, TestSuite) are documented in the README:

@README.md

## Commands

```bash
uv run inv --list              # List all available tasks
uv run inv all                 # Run lint + tests
uv run inv lint                # Format (ruff format) + lint (ruff check --fix) + ty check + uv lock --check
uv run inv lint --no-fix       # Check-only mode (no auto-fix)
uv run inv lint --file path    # Lint single file (skips ty, won't remove unused imports)
uv run inv tests               # Run all unit tests (pytest tests/), then the README examples (pytest README.md)
uv run inv tests --testname X  # Run tests matching pattern X (pytest -k=X)
```

## Layout

- `morphtest/component.py`: `ComponentMeta`, `Component`, `Dependency`, `if_not_overwritten`, `mixin`, conditions (`AllOf`, `OneOf`), `ComponentDependencySet`, `ConditionsBuilder`
- `morphtest/solver.py`: `ComponentSetSolver` (CNF generation + incremental solving per `AllOf` group, `components` = everything reachable from the entry), `PerEntry` (recommended components/group_by per entry implementation)
- `morphtest/suite.py`: `TestCase` (root with abstract `run()` and the class variables `recommended_components`, `group_by`), generic `BaseTestSuite` (entry = first condition), `TestSuite` (entry `TestCase`, settings from its class variables, `run()` builds each `TestCase` and calls its `run()`), `NoSolutionError`, `group_depsets_by`, `find_component`/`components_by_name` (lookup by name among the components reachable from `TestCase`, shared by CLI and pytest plugin)
- `morphtest/overview.py`: HTML component tree (`roots` allows several meta roots)
- `morphtest/cli.py`: typer CLI `morphtest run/describe/overview` (console script and `python -m morphtest`). Targets are modules or files (`load_target`); conditions are parsed by name among the components reachable from `TestCase`. Setup errors exit with 2, failing tests with 1
- `morphtest/pytest_plugin.py`: pytest plugin (`pytest11` entry point): a `TestSuite` named `ts` in a test module becomes one `DepsetItem` per depset (`ts[<depset>]`, repeats `#2`); `NoSolutionError` is a collection error; `--component NAME` (repeatable, all must match) deselects `ts` tests whose depset lacks that component or a subclass
- Public API is re-exported from `morphtest/__init__.py`. Keep `__all__` up to date

## Release

Released with the baltech Release Actions (`baltech-ag/ci-scripts`):
`git push origin master:release-(major|minor|patch)` lets CI bump `VERSION`, commit
`[release] morphtest X.Y.Z`, auto-merge the PR and push the tag `vX.Y.Z`.

- `VERSION` is the only version source (`pyproject.toml` reads it via setuptools
  `dynamic`, `uv.lock` holds no version). Never bump it by hand
- The YouTrack version `morphtest-X.Y.Z` must exist in project ROBO before the release
  (repo variables `PROJECT`, `VERSION_TEMPLATE`)
- `.github/workflows/org-release-actions.yml` is an unchanged copy of the ci-scripts
  template. `repo-release-actions-deploy.yml` runs lint/test, builds (version via the
  ci-scripts action `pypi-version`) and publishes via the ci-scripts workflow
  `release-actions-deploy-pypi.yml`: every push to TestPyPI as `X.Y.Z.dev<run_number>`,
  the tag to PyPI
- `tox.ini` only exists for the release actions (`tox -- apply-version --version=X`,
  which only checks `VERSION`). `uv run inv build` builds sdist and wheel into `dist/`

## Code Quality

- **ty** (Astral type checker): `incompatible-mutable-override` disabled, because subclasses narrow dependencies by redeclaring the field. ty does not require annotations, ruff's `ANN` rules do (only `ANN401` for `Any` is ignored). Suppress single ty errors with `# ty: ignore[rule]`, not mypy's `# type: ignore[code]`
- **ruff**: `select = ["ALL"]` with specific exclusions (see `pyproject.toml`). `N801` is disabled because component names contain `_`
- Tests define local component trees per test (`class Base(metaclass=ComponentMeta)`) so component names don't clash between tests. Components inheriting from `morphtest.Component` need globally unique root names
- `TestCase` subclasses defined in tests stay alive (cached on the metaclass), so `TestSuite` tests restrict themselves with a condition on a local abstract group (`TestSuite(TestCase_MyGroup)`, or `.one_of` for a best fit within it)
- `test_pytest_plugin.py` runs pytest via `pytester.runpytest_subprocess`, so the components of the test projects never leak into the test session
- The ```python blocks of README.md are tests (Sybil, hooked in the root `conftest.py`): plain blocks are executed, blocks starting with `>>>` are doctests, `<!-- skip: next "reason" -->` skips a block. All blocks share one namespace, so README components need unique root names. The README runs in its own pytest process (`pytest README.md`), separate from the unit tests
- Python 3.11+ is supported. Since 3.14 (PEP 649) the class namespace has no `__annotations__`, so `ComponentMeta` reads them via `inspect.get_annotations(cls)`. CI tests the oldest and newest version on Linux, Windows and macOS (lint runs once on Linux)
