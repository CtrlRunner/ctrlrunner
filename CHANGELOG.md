# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Per-test indirect fixture parametrization**: `@parametrize(...)`
  now accepts pytest's `indirect=` argument — `True` (all names) or a
  list of names. An indirect name's per-combination value is delivered
  to that *fixture* as `request.param` instead of being passed to the
  test as a kwarg, so each test can feed a shared, stateful fixture its
  own value (feature-flag mocks, guard fixtures, per-test route
  interception), exactly like pytest's indirect parametrize. The test's
  indirect values replace the fixture's own `params=[...]` (if any) for
  that test; transitive and autouse fixture targets are supported;
  module/session-scoped fixtures get a distinct cached instance per
  value. Invalid targets (unknown fixture, fixture without `request`,
  fixture the test never uses) raise at registration with the fix
  spelled out.
- The migration tool now converts `@pytest.mark.parametrize(...,
  indirect=...)` by passing it through nearly verbatim (values stay on
  the test; the target fixture gets a `request` parameter added if
  missing, cross-file included) instead of relocating values onto the
  fixture's `params=[...]`. Every previously-bailing indirect shape —
  conflicting value sets across tests, already-parametrized fixtures,
  `indirect=True` with several names, non-literal argvalues — now
  migrates cleanly with no TODO. (Output from earlier versions of the
  tool, with values injected into fixture `params=[...]`, remains valid
  ctrlrunner and needs no re-migration.)

### Fixed

- `@parametrize` with a **single** arg name no longer unpacks tuple
  values: `@parametrize("x", [(1, 2)])` now gives `x == (1, 2)`,
  matching pytest. Previously a 1-element tuple was silently unpacked
  and anything longer crashed at import time with an opaque
  `zip() argument 2 is longer than argument 1` — the shape every
  tuple-valued indirect parametrize hits.

- `conftest.py` discovery now walks upward to ancestor directories (to a
  `.git` boundary, or the filesystem root) in addition to the existing
  downward scan from the given root — a run scoped to a subdirectory
  (`ctrlrunner spec/web/some_suite/`) now also registers fixtures and
  runs the top-level setup from any `conftest.py` above that
  subdirectory, matching pytest's conftest discovery. Ancestor
  directories are added to `sys.path` in shallowest-first order, so a
  plain `from conftest import some_name` in a test file now reliably
  reaches the *project root's* `conftest.py` even when a differently-scoped
  `conftest.py` also exists closer to the test file.
- Fixed a related `sys.modules` collision uncovered while testing the
  above: `import_module_by_path` used to unconditionally alias every
  imported module under its computed dotted name, including a bare
  (dot-less) `"conftest"` for whichever `conftest.py` happens to sit
  directly in the scoped root's parent directory. That alias is set
  *before* any test file runs, so it silently pre-empted the `sys.path`
  order above — `from conftest import some_name` would find the wrong,
  nearer `conftest.py` in `sys.modules` before ever consulting
  `sys.path`. `conftest.py` files are no longer given a bare dotted-name
  alias, so resolution now genuinely follows `sys.path` order.
- Fixed a third layer of the same bug class: `discover_conftests`'s
  ancestor `sys.path` insertion only ran `sys.path.insert(0, ...)` when
  a directory was *entirely absent* from `sys.path`. A dev/editable
  install (`uv run`, `pip install -e .`) can already have the project
  root on `sys.path` via a `.pth` file or similar — just buried near
  the end, after `site-packages`/`.venv` entries — so that guard saw it
  "already present" and left it at that low-priority position instead
  of promoting it to the front, silently defeating the ordering fix
  above in exactly this kind of environment. Ancestor directories are
  now unconditionally removed from any existing `sys.path` position and
  re-inserted at the front, so the priority order always takes effect
  regardless of what an install mechanism already put on `sys.path`.

## [0.1.0] - 2026-07-15

Initial release.

### Added

- Real OS-process workers with hard-kill timeouts via Windows Job Objects (POSIX fallback for dev).
- Decorator-based test API: `@test`, `@fixture`, `@parametrize`, `@test_class`, dependency injection.
- Parallel scheduling with scoped worker budgets and serial-class support.
- Rerun workflows, flaky analytics, and quarantine management.
- Historical timing store and fixture/execution profiling.
- Console, JUnit XML, and self-contained HTML reporters.
- Code coverage integration.
- UI Mode: local web server with live test tree, report viewer, and trace/screenshot artifacts.
- `pytest` -> `ctrlrunner` source migration tool (`libcst`-based).
