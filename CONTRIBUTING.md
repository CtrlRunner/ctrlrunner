# Contributing

## Dev setup

Clone the repo and sync it with [uv](https://docs.astral.sh/uv/) — this installs ctrlrunner
itself in editable mode plus its dev tooling:

```
uv sync --group dev                          # ruff + ty + coverage, editable install
uv sync --group dev --extra playwright --extra migrate  # + playwright/libcst, for the
                                                          # playwright-fixture tests and
                                                          # migrate/ tests
uv run playwright install                    # browser binaries, if you don't have them
```

## Running the test suite

ctrlrunner is tested with the standard library `unittest`, not itself or pytest —
avoids both the irony and a dependency on either:

```
uv run python -m unittest discover -s tests
```

## Linting, formatting, type checking

```
uv run ruff check .       # lint
uv run ruff format .      # format
uv run ty check           # type check (src/ctrlrunner/ only; see [tool.ty.src])
```

Config for all three lives in `pyproject.toml` (`[tool.ruff]`, `[tool.ty]`).

Optionally, run `uv run pre-commit install` once to wire these three checks up as a git
pre-commit hook (`.pre-commit-config.yaml`) — same commands CI's `lint` job runs, so
failures surface locally in seconds instead of after a push.

## Before opening a PR

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and
  `uv run python -m unittest discover -s tests` all pass.
- Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat: ...`, `fix: ...`, `docs: ...`, `chore: ...`) where you reasonably can — `CHANGELOG.md`
  is generated from commit messages by [git-cliff](https://git-cliff.org) on every release, and
  `feat`/`fix`/`docs` commits are what show up as real changelog entries; everything else lands
  in an "Other" section rather than being dropped. This isn't enforced by CI, just followed
  best-effort.
- Keep the change focused — see the project's design philosophy in `README.md`
  ("Explicitly not included") before proposing new extension points.

## Releasing

Releases are fully automated by `publish.yml` -- there's no manual version bump or
tag to create. From the Actions tab, run the "Publish" workflow on `main` with the
desired `version_strategy` (`patch`/`minor`/`major`). It verifies `main` is releasable
(lint, format, type check, full test suite), computes the next version from the latest
`vX.Y.Z` tag, bumps `pyproject.toml` and `uv.lock`, prepends this release's entries to
`CHANGELOG.md` via [git-cliff](https://git-cliff.org), commits and tags that, then
builds, publishes to PyPI, and creates the matching GitHub Release with the freshly
generated notes.
