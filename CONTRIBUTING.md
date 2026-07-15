# Contributing

## Dev setup

Clone the repo and sync it with [uv](https://docs.astral.sh/uv/) — this installs pyrunner
itself in editable mode plus its dev tooling:

```
uv sync --group dev                          # ruff + ty + coverage, editable install
uv sync --group dev --extra playwright --extra migrate  # + playwright/libcst, for the
                                                          # playwright-fixture tests and
                                                          # migrate/ tests
uv run playwright install                    # browser binaries, if you don't have them
```

## Running the test suite

pyrunner is tested with the standard library `unittest`, not itself or pytest —
avoids both the irony and a dependency on either:

```
uv run python -m unittest discover -s tests
```

## Linting, formatting, type checking

```
uv run ruff check .       # lint
uv run ruff format .      # format
uv run ty check           # type check (pyrunner/ only; see [tool.ty.src])
```

Config for all three lives in `pyproject.toml` (`[tool.ruff]`, `[tool.ty]`).

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

1. Bump `version` in `pyproject.toml`.
2. Push to `main`, then create a GitHub Release for tag `vX.Y.Z` (`gh release create vX.Y.Z`
   or via the GitHub UI). Publishing the release triggers two workflows: `publish.yml` builds
   and publishes to PyPI, and `changelog.yml` regenerates `CHANGELOG.md` from commits since the
   previous tag and commits it back to `main`.
