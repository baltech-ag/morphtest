# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
uv run inv lint                # Format (ruff format) + lint (ruff check --fix) + mypy + uv lock --check
uv run inv lint --no-fix       # Check-only mode (no auto-fix)
uv run inv lint --file path    # Lint single file (skips mypy, won't remove unused imports)
uv run inv tests               # Run all unit tests (pytest tests/)
uv run inv tests --testname X  # Run tests matching pattern X (pytest -k=X)
```

## Layout

- `morphtest/component.py`: `ComponentMeta`, `Component`, `Dependency`, `if_not_overwritten`, `mixin`, conditions (`AllOf`, `OneOf`), `ComponentDependencySet`, `ConditionsBuilder`
- `morphtest/solver.py`: `ComponentSetSolver` (CNF generation + incremental solving per `AllOf` group), `PerEntry` (recommended components/group_by per entry implementation)
- `morphtest/suite.py`: `TestCase` (root with abstract `run()` and the class variables `recommended_components`, `group_by`), generic `BaseTestSuite` (entry = first condition), `TestSuite` (entry `TestCase`, settings from its class variables, `run()` builds each `TestCase` and calls its `run()`), `NoSolutionError`, `group_depsets_by`
- `morphtest/overview.py`: HTML component tree
- Public API is re-exported from `morphtest/__init__.py`. Keep `__all__` up to date

## Code Quality

- **mypy**: strict mode, `type-abstract` disabled (abstract components are passed as `type[...]` on purpose)
- **ruff**: `select = ["ALL"]` with specific exclusions (see `pyproject.toml`). `N801` is disabled because component names contain `_`
- Python 3.14 is not supported yet: `ComponentMeta` reads `namespace["__annotations__"]`, which PEP 649 removed from the class namespace
- Tests define local component trees per test (`class Base(metaclass=ComponentMeta)`) so component names don't clash between tests. Components inheriting from `morphtest.Component` need globally unique root names
- `TestCase` subclasses defined in tests stay alive (cached on the metaclass), so `TestSuite` tests restrict themselves with a condition on a local abstract group (`TestSuite(TestCase_MyGroup)`, or `.one_of` for a best fit within it)
