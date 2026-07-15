# CtrlRunner

A from-scratch Python test runner for Playwright, built to replace
`pytest` + `pytest-timeout` + `pytest-xdist` on Windows CI, where those
three combined to produce silent worker hangs, orphaned Chromium/Node
processes, and no-teardown thread-mode kills.

## Table of contents

- [Why this exists](#why-this-exists)
- [Install](#install)
- [Quick start](#quick-start)
- [Core concepts](#core-concepts)
- [Timeout & hard-kill model](#timeout--hard-kill-model)
- [Documentation](#documentation)

## Why this exists

- `pytest-timeout` (thread mode) interrupts a test but doesn't guarantee
  teardown, and doesn't touch child processes.
- `pytest-xdist` workers could hang on Windows with orphaned
  Chromium/Node processes holding stdout/stderr handles, once causing an
  8.5-hour CI hang.

ctrlrunner's answer to both: every worker is a real OS process wrapped in
a **Windows Job Object**, so a timeout is a guaranteed hard-kill of the
whole process tree (worker + browser + any Node helpers) — never a
best-effort thread interrupt.

## Install

```
pip install ctrlrunner                 # core install, zero third-party deps
pip install ctrlrunner[playwright]     # + playwright (for the built-in fixtures/actions)
pip install ctrlrunner[migrate]        # + libcst (pytest -> ctrlrunner migration script)
playwright install                   # browser binaries, if you don't have them
```

Windows also needs `pywin32` for Job Objects: `pip install ctrlrunner[windows]`.

With [uv](https://docs.astral.sh/uv/), the equivalent is `uv add ctrlrunner --extra playwright`.

No `pytest` dependency, anywhere.

Contributing to ctrlrunner itself (not just using it)? See
[CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup instead.

## Quick start

```python
# tests/test_example.py
from playwright.sync_api import sync_playwright
from ctrlrunner import fixture, test


@fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@fixture(scope="session")
def browser(playwright_instance):
    b = playwright_instance.chromium.launch(headless=True)
    yield b
    b.close()


@fixture(scope="function")
def page(browser):
    context = browser.new_context()
    p = context.new_page()
    yield p
    context.close()


@test(timeout=15, case_id="TC-EX-001", tags={"smoke"})
def test_example_dot_com(page):
    page.goto("https://example.com")
    assert page.title() == "Example Domain"
```

```
python -m ctrlrunner tests -n 4 --timeout 30 --junit-xml report.xml
```

## Core concepts

### `@test`

```python
@test(timeout=30.0, tags={"smoke"}, case_id="TC-1", properties={"owner": "sdet"}, retries=0)
def test_something(page):
    ...
```

- `timeout` — hard-kill deadline in seconds, enforced by the orchestrator
  (see [Timeout & hard-kill model](#timeout--hard-kill-model)), not a
  thread interrupt.
- `case_id` — a stable ID for the test case, written into JUnit
  `<properties>` for the Teams pipeline / TestRail-Jira sync. Can be a
  `"{param}"` template when the test is parametrized.
- `retries` — additional attempts after a failure (assertion/exception).
  Does **not** apply to hangs; a timed-out test is hard-killed and its
  batch requeued, a separate failure mode.

### `@fixture`

```python
@fixture(scope="function", on_failure=None, params=None, autouse=False)
def my_fixture(...):
    ...
```

- `scope`:
  - `"function"` — fresh per test call.
  - `"module"` — cached per test module, per worker; torn down when the
    worker moves to a different module.
  - `"session"` — cached for the whole worker process (i.e. the whole
    batch of tests that worker runs).
- `on_failure(value, path_prefix) -> Optional[str]` — capture an artifact
  (screenshot, trace) when a test using this fixture fails. Must never
  raise. Called for every fixture resolved for that test, including
  transitive dependencies.
- `params=[...]` — parametrizes the **fixture** itself (pytest's
  "indirect parametrization"). The fixture must accept `request` and
  read `request.param`. Any test that (transitively) depends on it is
  automatically multiplied, one variant per value, combined via
  cartesian product with any `@parametrize` on the test.
- `autouse=True` — resolved (setup/teardown) for every test in the run,
  even if no test names it as a parameter.

### `@parametrize`

```python
@test(case_id="TC-100-{locale}")
@parametrize("locale", ["en-US", "uk-UA", "de-DE"])
def test_locale_switch(locale, page):
    ...
```

**Decorator order matters**: `@test` must be on top (outermost),
`@parametrize` directly above the function — decorators apply bottom-up,
and `@test` needs the parametrization already attached when it runs.
Getting this backwards raises a `TypeError`/`ValueError` with the fix
spelled out, rather than silently registering one un-parametrized test.

`arg_names` is a comma-separated string (`"a, b"`) or, pytest-style, a
tuple/list of names (`("a", "b")`).

### `param()` — per-combination metadata

`param(...)` is ctrlrunner's equivalent of `pytest.param(..., id=...,
marks=[...])`, expressed as flat keyword arguments instead of marker
objects. Plain tuples/scalars mix freely with `param(...)` entries:

```python
@test()
@parametrize("entity_id, label", [
    param("E-1", "US", id="us_entity", case_id="7184475",
          xfail="[Bug 7438797] audit widget absent", xfail_strict=True),
    param("E-2", "Non-US", id="non_us_entity", case_id="7184476"),
    ("E-3", "plain-still-works"),
])
def test_audit_widget(entity_id, label):
    ...
```

- `id=` — custom test-id suffix for this combination.
- `case_id=` — per-combination case id; overrides `@test`'s `case_id`
  (template or plain) for that entry, and is selectable via `--case-id`.
- `tags=` — extra tags for this combination, unioned with `@test`'s.
- `xfail=` — `True` or a reason string; the combination is expected to
  fail (rides the same runtime `fail()` pipeline). `xfail_strict`
  defaults to `True`, matching `fail()`, not pytest.
- `skip=` — `True` or a reason string; the combination is skipped
  without resolving any fixtures.

### Shared fixtures (`conftest.py`)

Any `conftest.py` under the test root is discovered and imported
automatically, shallowest directory first — no explicit import needed in
test files, same convenience as pytest's `conftest.py`, but it's a plain
import list, not a plugin hook.

## Timeout & hard-kill model

```
watchdog_deadline = per_test_timeout + WORKER_RESTART_BUFFER (5s)
```

Each worker process is assigned to a Windows Job Object before it can
launch a browser. If a test exceeds its deadline, the orchestrator calls
`TerminateJobObject`, killing the worker **and every child process it
spawned** (browser, Node helpers) in one shot — no orphans, no reliance
on graceful teardown. The rest of that worker's batch is requeued onto a
fresh worker so one stuck test doesn't take the whole run down with it.

Retries (`@test(retries=N)`) are separate: they only apply to in-process
failures (assertions/exceptions), each attempt getting a fresh deadline.

The suite-**import** phase has its own separate watchdog budget (default
60s, never charged against the first test's timeout). Suites with heavy
imports (cold-AV-scanned CI) can raise it: `--import-timeout 180` or
`import_timeout = 180.0` in `ctrlrunner.toml`.

## Documentation

Everything past the core API lives in `docs/`:

- [Parallelism, scheduling & test selection](docs/parallelism-and-scheduling.md) — worker budgets, serial classes, worker isolation, `--test-id`/`--tag`/`--grep` filters, `--list`.
- [Reporters, history & flake management](docs/reporters-and-history.md) — console/JUnit/JSON reporters, rerun workflows, the historical timing store, fail policies, flaky analytics and quarantine, execution profiling.
- [Named projects, HTML report, coverage & UI Mode](docs/html-report-and-ui.md) — `--project`, grouping, the self-contained HTML report, code coverage, and the live UI Mode app.
- [Config file, tags & test metadata reference](docs/config-reference.md) — full `ctrlrunner.toml` reference, the registered tag registry, `@test_class`, and runtime `skip`/`fail`/`fixme`/`slow` annotations.
- [Tracing, artifacts & assertion details](docs/tracing-and-artifacts.md) — artifacts on failure, `step()`, built-in Playwright fixtures, `auto_step`, rich assertion failures, log capture.
- [Event model](docs/event-model.md) — the stable interface for reporter/hook/plugin authors.
- [Migrating from pytest](docs/migrating-from-pytest.md) — the `ctrlrunner.migrate` conversion tool.
- [Developing ctrlrunner](docs/development.md) — running the test suite, dev tooling, project layout.
- [Security model](docs/SECURITY.md) and [pytest migration checklist](docs/MIGRATION.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and PR expectations,
and [CHANGELOG.md](CHANGELOG.md) for release history.
