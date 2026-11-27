# Publish morphtest to PyPI via Release Actions

## Context

morphtest shall be released with the baltech Release Actions pipeline
(`release-(major|minor|patch)` branch -> `[release]` PR -> tag -> deploy) and published to
PyPI. The publish part is centralized in ci-scripts (workspace `pypi-deploy`, plan
`+plans/PYPI-DEPLOY.01.central-pypi-publish-workflow.md` there):

- composite action `baltech-ag/ci-scripts/actions/pypi-version`: writes
  `<version>.dev<run_number>` into the version file (development) or leaves it (release),
  rejects non-normalized versions
- reusable workflow `release-actions-deploy-pypi.yml`: uploads a dist artifact to TestPyPI
  (development, skip-existing) or PyPI (release)

## Decisions

- YouTrack project `ROBO`, version template `morphtest-$version` (version
  `morphtest-0.1.0` exists). Repo vars `PROJECT`, `VERSION_TEMPLATE` and access to
  `YOUTRACK_URL`/`YOUTRACK_TOKEN` are set by the user.
- `VERSION` is the single version source, starts at `0.0.0`; the first `release-minor`
  makes it `0.1.0`. pyproject reads it via setuptools `dynamic`.
- Dev builds (every push) go to TestPyPI as `<version>.devN`, the tag to PyPI.
- Auth via org secrets `TEST_PYPI_TOKEN`/`PYPI_TOKEN`.
- Metadata: authors Baltech AG, GitHub URLs, classifiers, keywords.
- lint/test move into the reusable deploy workflow; the master ruleset's required checks
  are renamed by the user (`deploy-build / lint`, ...).
- During testing, ci-scripts is referenced with `@pypi-deploy`; switched to `@master`
  after the ci-scripts PR is merged.

## Changes

1. `VERSION` = `0.0.0`; `pyproject.toml`: `dynamic = ["version"]`,
   `[tool.setuptools.dynamic] version = {file = "VERSION"}`, metadata.
2. `tox.ini` (pattern of bec2format): tox 3.28, envdir `.tox-venv`, `uv run inv {posargs}`
   (create-pr runs `tox -- apply-version --version=X`).
3. `tasks.py`: `apply-version --version=X` checks that VERSION contains X (written by
   create-pr before) and that X is a normalized `X.Y.Z`; `build` = `uv build`.
4. `.github/workflows/org-release-actions.yml`: copy of the ci-scripts template.
5. `.github/workflows/repo-release-actions-deploy.yml`: `workflow_call` with the template
   inputs; jobs lint, test (as before), build (pypi-version action + `uv build` + upload
   artifact), publish (reusable workflow).
6. `.gitignore`: `.tox-venv/`.
7. README: installation via `uv add morphtest`; AGENTS.md: release section.
