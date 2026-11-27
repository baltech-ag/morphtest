import re
import sys
from pathlib import Path

from invoke import Context, task

ProjectRootPath = Path(__file__).parent
VersionFilePath = ProjectRootPath / "VERSION"


@task()
def lint(ctx: Context, *, fix: bool = True, file: str | None = None) -> None:
    """runs linting jobs"""
    check_flag = "" if fix else "--check"
    fix_flag = "--fix" if fix else ""

    # in file-mode (used by watcher) we do not want to delete unused imports / variables
    ruff_check_flags = "--unfixable F401 --unfixable F841" if file is not None else ""

    ok = ctx.run(
        f"uv run ruff format {check_flag} {file or ProjectRootPath}", warn=True
    ).ok
    ok &= ctx.run(
        f"uv run ruff check {fix_flag} {ruff_check_flags} {file or ProjectRootPath}",
        warn=True,
    ).ok

    if file is None:
        ok &= ctx.run(f"uv run ty check {ProjectRootPath}", warn=True).ok
        ok &= ctx.run("uv lock --check", warn=True).ok

    if not ok:
        sys.exit(1)


@task()
def tests(ctx: Context, testname: str | None = None) -> None:
    """runs unit tests and the examples of README.md"""
    ctx.run(f"pytest {ProjectRootPath}/tests -k={testname or ''}")
    # own process: components of the README must not mix with those of the unit tests
    ctx.run(f"pytest {ProjectRootPath}/README.md -k={testname or ''}")


@task()
def apply_version(_ctx: Context, version: str) -> None:
    """checks the version the release actions wrote into VERSION"""
    # pyproject.toml reads the version from VERSION, so there is nothing to apply
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        sys.exit(f"{version!r} is no normalized X.Y.Z version")
    file_version = VersionFilePath.read_text().strip()
    if file_version != version:
        sys.exit(f"VERSION contains {file_version!r} instead of {version!r}")


@task()
def build(ctx: Context) -> None:
    """builds sdist and wheel into dist/"""
    ctx.run(f"uv build --clear {ProjectRootPath}")


@task(pre=[lint, tests])
def all(_ctx: Context) -> None:  # noqa: A001 shadows python builtin
    pass
