# Skill: Writing tests with ctrlrunner

Use this whenever asked to write, edit, or review a Playwright test in
this repository. **This project does not use pytest.** Do not import
`pytest`, use `pytest.fixture`, `pytest.mark`, `pytest.raises`,
`conftest.py` pytest-plugin hooks, or any pytest CLI flags. There is no
`pytest_collection_modifyitems`, no `pytest.ini`, no `pyproject.toml`
`[tool.pytest.ini_options]` section — none of that applies here.

## Imports

```python
from ctrlrunner import test, fixture, parametrize
```

## Golden rule: decorator order

`@test` is always the outermost decorator; `@parametrize` sits directly
above the function. This is backwards from what pytest muscle memory
suggests — write it wrong and ctrlrunner raises a clear error at import
time, but don't rely on that; get it right the first time:

```python
# CORRECT
@test(case_id="TC-100-{locale}")
@parametrize("locale", ["en-US", "uk-UA"])
def test_locale_switch(locale, page):
    ...

# WRONG -- do not do this
@parametrize("locale", ["en-US", "uk-UA"])
@test(case_id="TC-100-{locale}")
def test_locale_switch(locale, page):
    ...
```

Also don't nest a class inside a `@test_class` body -- `@test_class`
raises a clear `TypeError` at import time if it finds one. Give any
class-like grouping its own top-level `@test_class` instead:

```python
# WRONG -- raises TypeError at import time
@test_class()
class LoginTests:
    @test(case_id="TC-1")
    def test_valid_login(self, page):
        ...

    class HelperGroup:  # nested class -- not supported
        ...
```

## Every test needs a `case_id`

Every `@test` in this repo must set `case_id` unless explicitly told
otherwise. Ask for the case ID if it isn't given; do not invent one.
Format: whatever the existing test file / TestRail-Jira convention in
that directory uses (check nearby tests before guessing).

```python
@test(timeout=30, case_id="TC-1234", tags={"smoke"})
def test_login_with_valid_credentials(page):
    ...
```

For parametrized tests, use a `"{param_name}"` placeholder in `case_id`
matching an actual `@parametrize` argument name or a fixture that has
`params=[...]` (see below):

```python
@test(case_id="TC-1234-{browser_type}")
@parametrize("browser_type", ["chromium", "firefox"])
def test_x(browser_type, page):
    ...
```

## Fixtures

For Playwright tests, prefer the built-in fixtures over writing your
own -- no fixture code needed, and trace/screenshot capture is
controlled entirely by `--trace`/`--screenshot` CLI flags or
`ctrlrunner.toml`:

```python
from ctrlrunner import test
from ctrlrunner.playwright_fixtures import page

@test(timeout=15, case_id="TC-1")
def test_login(page):
    page.goto("https://example.com/login")
```

Only write a custom `browser`/`context`/`page` fixture if the test
needs something the built-ins don't support (custom launch args,
multiple contexts per test, non-standard capture logic). If you do:

Never write setup/teardown as bare module-level code or `with` blocks
duplicated across tests — use `@fixture`:

```python
@fixture(scope="function")
def page(context):
    p = context.new_page()
    yield p
    # no explicit close needed here if context-level teardown already closes it
```

Scope rules of thumb:
- `"function"` (default) — anything that must be fresh per test (a `page`).
- `"module"` — expensive-ish shared state reused across tests in one
  file, not safe/needed to share across files (a seeded per-suite test
  user, a shared mock server on one port).
- `"session"` — one per worker process for the whole run: `browser`
  launch, a Playwright driver instance.

Never put `scope="session"` on anything that holds per-test mutable
state (a `page`, a `context`) — it will leak between tests.

## Screenshots/traces on failure

With the built-in `ctrlrunner.playwright_fixtures.page`, this is just
`--trace`/`--screenshot` CLI flags (see Fixtures section above) — don't
write capture code at all unless using a custom fixture.

For a custom fixture, attach `on_failure` to the fixture that owns the
Playwright object, not inside the test body:

```python
def _capture_screenshot(page, prefix):
    path = f"{prefix}.png"
    page.screenshot(path=path)
    return path

@fixture(scope="function", on_failure=_capture_screenshot)
def page(context):
    p = context.new_page()
    yield p
```

Which fixture matters: `on_failure` gets called with *that fixture's own*
yielded value, not a fresh `page`. `page` has `.screenshot()`; `browser`
and `context` don't — put screenshot capture on `page`, trace capture on
`context` (it has `.tracing`), same as the built-ins. A callback that
raises (e.g. wrong object type) never fails the test, but does emit a
`RuntimeWarning` naming the fixture — check the run's warnings if an
artifact silently doesn't show up.

Do not wrap test bodies in `try/except` to take screenshots manually —
this bypasses the runner's artifact bookkeeping (JUnit properties, JSON
reporter) and duplicates logic that already exists per-fixture.

## Session & test hooks (`pytest_configure`/`pytest_runtest_*` equivalents)

For real setup/teardown work around a run (starting shared infra) or
per-test instrumentation — not for taking screenshots, that's fixtures
above — a `conftest.py` may define any of (pytest-shaped signatures;
`item`/`report`/`session`/`config` are shim objects carrying the common
pytest attribute surface):

```python
def ctrlrunner_configure(config): ...            # once, main process, before the run
def ctrlrunner_sessionfinish(session, exitstatus): ...  # once, after
def ctrlrunner_runtest_logstart(nodeid, location): ...  # per attempt, in-worker
def ctrlrunner_runtest_setup(item): ...          # item.get_closest_marker(tag) works;
                                                 # skip()/fixme()/fail() here control
                                                 # the test's outcome
def ctrlrunner_runtest_teardown(item, nextitem): ...
def ctrlrunner_runtest_logreport(report): ...    # report.outcome/.failed/.longrepr
```

Full contract (object attributes, exception handling, `--list`
behavior, ordering) in [docs/hooks.md](docs/hooks.md). Don't reach for
autouse fixtures to fake `ctrlrunner_runtest_setup`/`teardown` or a
custom `--reporter` class to fake `ctrlrunner_sessionfinish` — use the
matching hook directly.

## Steps

Use `with step("...")` (from `ctrlrunner`) to break a test into named,
reportable phases -- this is the equivalent of Playwright TS's `await
test.step(...)`, but as a context manager since there's no `await` here:

```python
from ctrlrunner import step

def test_checkout(page):
    with step("Add item to cart"):
        ...
    with step("Complete checkout"):
        with step("Fill payment details"):
            ...
        with step("Confirm order"):
            ...
```

Steps can nest. Only add them where they genuinely mark a meaningful
phase a reviewer would want to see in a report -- don't wrap every
single line in its own step.

## Skip / fail / fixme / slow

Call these from inside the test body, not as decorator arguments -- they
need runtime fixture values (like a parametrized `browser_type`) to
decide their condition, the same way Playwright TS's `test.skip()` is
called inline, not at declaration time:

```python
from ctrlrunner import skip, fail, fixme, slow

def test_x(browser_type, page):
    skip(browser_type == "firefox", "not implemented for Firefox")
```

- `skip(condition, description)` — not applicable in this environment/config.
- `fixme(condition, description)` — known broken, needs a fix (same
  mechanism as skip, different triage label -- always include a ticket
  reference in `description`).
- `fail(condition, description, strict=True)` — known bug, test is
  expected to fail; only set `strict=False` if explicitly told the fix
  might already have landed and an unexpected pass should not fail CI.
  Never default to `strict=False` on your own judgment.
- `slow(condition, factor)` — extends the timeout for a specific slow
  operation; do not use this to paper over a flaky/slow test that should
  actually be fixed or given a longer `@test(timeout=...)` from the start.

Do not use bare `if browser_type == "firefox": return` to skip a test --
that reports as a false "passed". Always use `skip()`.

## Retries

Only add `retries=N` to a test if explicitly told it's flaky and a
retry count is specified. Do not add retries speculatively to make a
new test "pass reliably" — that hides a real bug or a bad wait
condition. Prefer fixing the wait/assertion first.

## Tags

Use `tags={...}` for anything that needs to be selectable via
`--tag` later (`smoke`, `regression`, `cross-browser`, etc.). Don't
invent new tag names without checking what's already used elsewhere in
the suite (`grep -rn "tags=" tests/`).

## What NOT to generate

- No `conftest.py` **pytest** plugin code (`pytest_addoption`,
  `pytest_collection_modifyitems`, `pytest_runtest_makereport`, etc.).
  A `conftest.py` in this repo is just a plain module with `@fixture`
  definitions, auto-imported by the orchestrator — nothing else.
- No `pytest.mark.parametrize` — use `@parametrize` from `ctrlrunner`.
- No `pytest.fixture` — use `@fixture` from `ctrlrunner`.
- No `pytest.raises` — use plain `try/except` + `assert`, or
  `unittest.TestCase.assertRaises`-style patterns if writing ctrlrunner's
  *own* internals (not test suites) in `tests/`.
- No `-k` / `-m` pytest CLI flags in docs, CI YAML, or comments — the
  equivalents here are `--test-id` / `--case-id` / `--case-id-prefix` /
  `--tag`.
