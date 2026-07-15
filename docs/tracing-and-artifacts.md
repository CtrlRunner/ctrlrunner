# Tracing, artifacts & assertion details

[← Back to README](../README.md)

## Artifacts on failure

```python
def _capture_screenshot(page, prefix):
    path = f"{prefix}.png"
    page.screenshot(path=path)
    return path

@fixture(scope="function", on_failure=_capture_screenshot)
def page(context):
    ...
```

On failure, artifacts land in `pyrunner-artifacts/<test>/attempt-N/` and
their paths are written into the JUnit `<properties>` and JSON reporter
output.

### Steps (`test.step()` equivalent)

Playwright TS's `test.step()` is an `await`-wrapped block; pyrunner's
equivalent is a context manager, since steps are inline blocks inside a
test body, not separate functions:

```python
from pyrunner import step

def test_login(page):
    with step("Navigate to login page"):
        page.goto("https://example.com/login")
    with step("Log in"):
        with step("Fill credentials"):
            page.fill("#user", "alice")
            page.fill("#pass", "secret")
        with step("Submit"):
            page.click("#submit")
```

Each `step()` records name, duration, pass/fail, and nesting -- the same
shape Playwright's trace viewer/HTML report show. A failing step
re-raises after recording (the test still fails normally); the tree
shows up in JUnit `<system-out>` (plain-text rendering) and in the full
nested form in the `json` reporter's output, ready to feed the HTML
report.

This does **not** auto-wrap every Playwright API call/assertion into its
own step the way Playwright TS's internal instrumentation does -- that
needs patching Playwright's API surface itself. Explicit `with
step(...)` blocks only, same as writing `await test.step(...)`
explicitly in TS.

### Built-in Playwright fixtures with native trace/screenshot capture

The fastest way to get Playwright tests running — no fixture code at
all, capture controlled entirely by CLI flags or `pyrunner.toml`, same
idea as Playwright TS's CLI (https://playwright.dev/docs/test-cli):

```python
from pyrunner import test
from pyrunner.playwright.playwright_fixtures import page

@test(timeout=15, case_id="TC-1")
def test_login(page):
    page.goto("https://example.com/login")   # auto-recorded as a step
    ...
```

```
--trace off|on|retain-on-failure|on-first-retry   (default: off)
--screenshot off|on|only-on-failure                (default: off)
--browser chromium|firefox|webkit                  (default: chromium)
--headed                                            (default: headless)
```

- `off` — nothing captured.
- `on` — always captured, pass or fail.
- `retain-on-failure` — always recorded during the test, but only saved
  (kept) if the test fails; discarded on a pass. This is Playwright TS's
  own recommended default for CI.
- `on-first-retry` (trace only) — no capture on the first attempt;
  starts recording from the first retry onward and keeps that trace
  regardless of whether the retry itself passes or fails, since the
  point is diagnosing the original flake.

`page` here is already wrapped in `auto_step` (see below), so the
action list works out of the box too — genuinely "just import it and it
works," no per-project fixture code needed.

Config file equivalent:
```toml
[pyrunner]
trace = "retain-on-failure"
screenshot = "only-on-failure"
browser = "chromium"
headed = false
```

### Writing your own fixtures instead

The built-ins cover the common case; write your own `browser`/`context`/
`page` fixtures (as shown in the [README](../README.md#quick-start)) if you
need custom launch args, multiple browser contexts per test, or capture
logic the built-ins don't support. `on_failure` callbacks can optionally
accept a third `outcome` argument (`"passed"`/`"failed"`/...) if they
need outcome-aware behavior like the built-ins do; existing two-argument
callbacks keep working unchanged.

### Auto-recorded actions (`auto_step`)

Already applied automatically by `pyrunner.playwright.playwright_fixtures.page`
above. Writing your own `page` fixture instead? Wrap it the same way:

```python
from pyrunner import auto_step

@fixture(scope="function")
def page(context):
    p = context.new_page()
    yield auto_step(p)  # every action below becomes a step automatically

def test_login(page):
    page.goto("https://example.com/login")
    page.fill("#user", "alice")
    page.click("#submit")
```

`page.locator(...)` return values are wrapped too, so chained calls
(`page.locator("#btn").click()`) are captured the same way. Only
actions (`click`, `fill`, `goto`, `press`, ...) become steps —
non-action calls (`page.title()`, `page.url`) pass through untouched.

### Trace/screenshot for every test, not just failures (`always_capture`)

Already handled by `--trace`/`--screenshot` above for the built-in
fixtures. For a custom fixture:

```python
@fixture(scope="function", on_failure=_capture_trace, always_capture=True)
def context(browser):
    ...
```

`always_capture=True` calls the fixture's `on_failure` callback after
**every** test, pass or fail — matching Playwright TS's `trace: "on"`
mode, so a trace is viewable in UI Mode or the HTML report regardless
of outcome, not only for failures. **Must fire before the resource is
torn down** — if `on_failure` needs the object still "open" (e.g.
`context.tracing.stop()`), do the capture inside `on_failure` itself,
not in code that runs after `yield` unconditionally in a separate
teardown step, since pyrunner calls `on_failure` before generator
teardown for exactly this reason.

### Rich assertion failures

A failed plain `assert` gets a structured breakdown of the failing
expression — no import hook, no pytest dependency, always on (zero
cost when nothing fails):

```python
def test_totals():
    left = compute_total(cart)
    right = 42
    assert left == right
```

On failure, the JSON/HTML report gets an `assertDetails` block: the
raw expression text, the resolved operand values (with a diff for
strings/sets/dicts), and any plain local variable names referenced in
the expression. Resolution is safe and side-effect-free by
construction — no arbitrary `eval`, no calling into user code, no
invoking a user-defined dunder method (`__eq__`, `__hash__`, `__neg__`,
...) a second time beyond whatever the `assert` itself already
triggered. Anything the introspector can't safely resolve (a function
call, a comprehension, a property/lazy-attribute access) is left out,
falling back to the plain traceback for that part.

This is not a full pytest-style assertion rewrite — no AST rewriting
at import time, no nested sub-expression trees — a deliberate scope
limit in exchange for staying import-hook-free.

Failure tracebacks are **display-filtered**: frames from inside the
pyrunner package (worker dispatch, fixture resolution) are hidden so
the traceback starts at your code — the `__tracebackhide__`
equivalent. An exception raised entirely inside pyrunner keeps its
full stack, and `--full-trace` (or `full_trace = true` in config)
disables filtering altogether.

### Log/stdout capture

Capture a test's stdout, stderr, and Python `logging` output during
its worker process:

```
--logs off|on|only-on-failure   (default: off)
```

Config file equivalent:
```toml
[pyrunner]
logs = "only-on-failure"
```

- `off` — nothing captured (default).
- `on` — captured for every test, pass or fail.
- `only-on-failure` — captured every attempt, but only kept for
  attempts that failed; a flaky test's failed retry keeps its logs
  even if a later retry passes.

Shows up per test in the JSON/HTML report and the live UI, collapsed
by default (native `<details>`/`<summary>`, no extra JS to expand it).
Capture never touches the test's own logging configuration — one
temporary root-logger handler is added for the duration of the attempt
and removed afterward; `logging.basicConfig()` and user-defined
handlers/formatters/levels are never touched. Each stream is capped at
5MB (tail-kept, with a `truncated` flag) so a chatty test can't OOM the
worker.
