# Session & test hooks

[← Back to README](../README.md)

Twenty-seven conftest.py-discovered hooks mirroring pytest's — same naming
convention as [`ctrlrunner_addoption`](../README.md#custom-options-pytest_addoption-equivalent):
`pytest_X` → `ctrlrunner_X`, with **pytest-shaped signatures** (hooks
receive `item` / `report` / `session` / `config` shim objects carrying
the commonly-used pytest attribute surface), so a migrated pytest hook
body usually works after just the rename (which `ctrlrunner.migrate`
does automatically). Arguments bind **by parameter name**, exactly like
pytest/pluggy — `def ctrlrunner_collection_modifyitems(items)` legally
skips the leading `session`/`config` parameters.

Full lifecycle order:

```
ctrlrunner_addoption(parser, pluginmanager)     main process, declaration time
ctrlrunner_generate_tests(metafunc)             per test function, at conftest/module import
  (registration time, main process AND each worker -- see "Dynamic parametrization" below)
ctrlrunner_make_parametrize_id(config, val, argname)   consulted while generating test ids
ctrlrunner_configure(config)                    main process, once, before anything
ctrlrunner_sessionstart(session)                main process, before collection
ctrlrunner_report_header(config, start_path)    main process → printed header lines
ctrlrunner_ignore_collect(collection_path, config)   per test_*.py file, True = skip
ctrlrunner_itemcollected(item)                  per collected test
ctrlrunner_deselected(items)                    once, if filters removed tests
ctrlrunner_collection_modifyitems(session, config, items)   reorder/filter/mark
ctrlrunner_collection_finish(session)           collection final
  — per attempt, in each worker: —
  ctrlrunner_runtest_logstart(nodeid, location)
  ctrlrunner_runtest_setup(item)
    ctrlrunner_fixture_setup(fixturedef, request)      once per fixture resolved
  ctrlrunner_runtest_call(item)                 notification, before the test body
    ctrlrunner_assertrepr_compare(config, op, left, right)   only on a failing ==/!= assert
    ctrlrunner_warning_recorded(warning_message, when, nodeid, location)   once per captured warning
  ctrlrunner_runtest_makereport(item, call)     may replace the report; hookwrapper-capable
  ctrlrunner_exception_interact(node, call, report)   only on failure
  ctrlrunner_runtest_teardown(item, nextitem)
    ctrlrunner_fixture_post_finalizer(fixturedef, request)   once per fixture torn down
  ctrlrunner_runtest_logreport(report)
  ctrlrunner_runtest_logfinish(nodeid, location)
ctrlrunner_report_teststatus(report, config)    consulted by Dots/Line reporters per result
ctrlrunner_terminal_summary(terminalreporter, exitstatus, config)
ctrlrunner_sessionfinish(session, exitstatus)   main process, results final
ctrlrunner_unconfigure(config)                  main process, the very last hook
```

Collection-phase notes: `ctrlrunner_ignore_collect` uses pytest's
firstresult semantics (first non-None return decides; `True` excludes
the file before it is even imported). `ctrlrunner_collection_modifyitems`
mutates `items` in place — reordering changes execution order, removing
an entry deselects the test, and `item.add_marker("tag")` writes through
to the real test's tags. `ctrlrunner_report_header` returns a string or
list of strings printed in the run header; `ctrlrunner_terminal_summary`
gets a `terminalreporter` with `.section(title)` / `.write_line(s)` /
`.write_sep(sep, title)` / `.stats` (outcome → list of Results).
Collection/configure/sessionstart hook errors abort the run;
terminal_summary/sessionfinish/unconfigure errors degrade to warnings
(results are already final).

```python
# conftest.py -- the classic pytest pattern, ported:
from ctrlrunner import skip

def ctrlrunner_runtest_setup(item):
    if item.get_closest_marker("mac_only"):   # matched against @test(tags={...})
        skip(True, "This test can only run on macOS.")
```

No `@pytest.hookimpl` needed (or meaningful): ctrlrunner hooks are
matched by function name in conftest.py, never registered — there is no
plugin manager. `ctrlrunner.migrate` strips the decorator automatically.

These are for doing real work around a run — distinct from
[the event model](event-model.md), which is for *observing* a run
(`ConsoleReporter`/`EventSubscriber`).

## Two execution contexts

ctrlrunner runs tests in spawned worker processes while the CLI/orchestrator
itself lives in the main process — unlike pytest's single-process model, so
hooks split into two groups by where they run.

### Main-process hooks (once per CLI invocation)

```python
# conftest.py
def ctrlrunner_configure(config):
    """Runs once, main process, before any worker spawns."""
    ...

def ctrlrunner_sessionfinish(session, exitstatus):
    """Runs once, main process, after the whole run finishes.
    Declaring just (session) works too."""
    ...
```

- `config` is a read-only Mapping over the resolved `ctrlrunner.toml`
  dict, plus pytest-`Config`-style surface: `config.getoption(name,
  default)` (answered from the `ctrlrunner_addoption` options store,
  already seeded), `config.getini(name)` (from the toml dict),
  `config.option.<name>` (attribute-style access to the same),
  `config.rootpath`/`.inipath`/`.args`, `config.cache` (a **real**
  pytest-style JSON cache under `.ctrlrunner_cache/` — `get`/`set`/
  `mkdir`), `config.pluginmanager` (truthful answers for a runner
  with no plugin system: `hasplugin()` is `False`, `register()` accepts
  and ignores), `config.stash` (a real mutable dict), and
  `config.invocation_params` (`.args` — the raw CLI args — and `.dir`).
  `config.addinivalue_line("markers", "name: desc")` is real too: it
  registers the marker name into `registered_tags` before tag validation
  runs — for projects that use a tag registry; without one every tag is
  accepted anyway, so it's a no-op.
- `session` carries `.results` (the final `list[Result]`, single- or
  multi-project — hooks fire exactly once either way), `.duration`,
  `.exitstatus`, `.testscollected`, `.testsfailed`.
- `exitstatus` is a simple `0`/`1` (any failure) signal — not necessarily
  identical to the process's final exit code in every edge case (coverage
  `fail-under`, `--fail-on-flaky`, and zero-tests-selected can still
  change the real exit code afterward).
- A `ctrlrunner_configure` exception **aborts the run** with a clear error
  message — no worker spawns, no test executes. A `ctrlrunner_sessionfinish`
  exception **cannot** change the run's outcome (results are already final)
  — it prints a warning to stderr and the run's exit code is unaffected.
- **Not invoked on `--list`** (a pure discovery-time view, nothing "runs").
  `--last-failed`/`--failed-from`/`--changed-since` DO invoke both — they
  select a subset of tests but still run them for real.
- Multiple conftest.py files may each define these; `ctrlrunner_configure`
  runs shallowest-conftest-first (same discovery order as
  `ctrlrunner_addoption`).
- `from ctrlrunner import ExitCode` — `OK=0`, `TESTS_FAILED=1`,
  `NO_TESTS_COLLECTED=4`. **Not** numerically identical to pytest's own
  `ExitCode` (which has 6 members and `NO_TESTS_COLLECTED=5`) — don't
  port code that branches on the raw int without checking against this
  enum instead.

### Per-test hooks (once per test attempt, inside each worker)

```python
# conftest.py
def ctrlrunner_runtest_logstart(nodeid, location):
    """Start of each attempt. location = (filename, lineno, testname)."""
    ...

def ctrlrunner_runtest_setup(item):
    """After logstart, before fixtures resolve. skip()/fixme()/fail()
    called here control the test's outcome exactly as from the body."""
    ...

def ctrlrunner_runtest_teardown(item, nextitem):
    """After the attempt finishes (every outcome, matching pytest —
    including skips), before fixture teardown, so live fixture state is
    still reachable. nextitem is the next test in THIS worker's batch
    (an Item shim), or None for the worker's last test — the same
    semantics pytest-xdist gives the hook; inside a serial class it's
    the next member. Declaring just (item) works too."""
    ...

def ctrlrunner_runtest_call(item):
    """Notification right before the test body runs. Unlike the other
    per-test hooks, an exception here IS NOT isolated — it fails the
    test exactly as an exception from the test body itself would,
    matching pytest_runtest_call."""
    ...

def ctrlrunner_runtest_makereport(item, call):
    """Fires once ctrlrunner's single consolidated report for this
    attempt is ready (not per-phase like pytest's three calls — see the
    documented delta below). Returning a truthy, non-None value REPLACES
    the report exception_interact/logreport receive; the classic
    `item.rep_call = report` pattern also works, since item is a plain
    mutable object a hook body can freely attach to."""
    ...

def ctrlrunner_exception_interact(node, call, report):
    """Fires only when the attempt failed — the screenshot/DOM-dump
    hook, with the live exception via call.excinfo."""
    ...

def ctrlrunner_runtest_teardown(item, nextitem):
    """After the attempt finishes (every outcome, matching pytest —
    including skips), before fixture teardown, so live fixture state is
    still reachable. nextitem is the next test in THIS worker's batch
    (an Item shim), or None for the worker's last test — the same
    semantics pytest-xdist gives the hook; inside a serial class it's
    the next member. Declaring just (item) works too."""
    ...

def ctrlrunner_runtest_logreport(report):
    """End of each attempt, once the outcome is known."""
    ...

def ctrlrunner_runtest_logfinish(nodeid, location):
    """Right after logreport."""
    ...
```

- `item` carries `.nodeid` (the ctrlrunner test id), `.name`,
  `.originalname`, `.attempt`, `.tags`, `.properties`/`.user_properties`,
  `.location`, `.path`/`.fspath`, `.module` (the real imported module
  object), `.cls` (the `@test_class` class, or `None`), `.keywords`,
  `.funcargs` (live resolved fixtures — populated by teardown time),
  `.config` and `.session` (real objects, threaded into the worker),
  `.stash` (a real per-item mutable dict — any hashable key, not just
  pytest's typed `StashKey`), `.callspec` (only present on a
  parametrized test — `.params`/`.id` — `hasattr(item, 'callspec')`
  first, exactly like pytest), `.add_report_section(when, key, content)`
  (appends to this attempt's eventual `report.sections`, titled
  `"Captured {key} {when}"` — pytest's own convention), plus the marker
  API: `.get_closest_marker(name, default=None)`, `.iter_markers(name=None)`,
  `.own_markers`, and `.add_marker(...)` — all answered from the test's
  tags, so `@test(tags={"mac_only"})` is what `@pytest.mark.mac_only`
  was. Markers have `.name`/`.args`/`.kwargs` (args/kwargs always empty
  — ctrlrunner tags are bare names).
- `call` (`ctrlrunner_runtest_makereport`/`ctrlrunner_exception_interact`)
  carries `.when` (always `"call"`), `.start`/`.stop`/`.duration`, and
  `.excinfo` — `None` when the phase passed, or a real `ExceptionInfo`
  (`.value` is the **live exception object**, plus `.type`/`.tb`/
  `.typename`/`.exconly()`) when it raised. Only populated for an actual
  `AssertionError`/`Exception` in the test body — `skip()`/`fixme()`
  aren't "failures" in the sense these two hooks exist for (screenshots/
  diagnostics on real failures).
- `report` carries `.nodeid`, `.attempt`, `.outcome` (pytest's
  three-value vocabulary: `"passed"`/`"failed"`/`"skipped"` — `fixme`
  and `expected_failure` map to `"skipped"`, with the raw value in
  `.ctrlrunner_outcome` and the xfail reason in `.wasxfail`),
  `.passed`/`.failed`/`.skipped` booleans, `.longrepr`/`.longreprtext`,
  `.duration`, `.location`, `.keywords`, `.user_properties`,
  `.sections` (pytest's `("Captured stdout call", text)` pairs, filled
  from the attempt's captured logs when `--logs` capture is on plus any
  `item.add_report_section(...)` calls, with `.capstdout`/`.capstderr`/
  `.caplog` derived), and `.when` (always `"call"` — one report per
  attempt, not per phase).
- These run **inside worker processes**. A retried test
  (`@test(retries=N)`) fires all eight once per attempt.
- **skip/fixme/fail from `ctrlrunner_runtest_setup`**: `skip()` /
  `fixme()` / `fail()` (ctrlrunner's runtime annotations — `pytest.skip`
  etc. after migration) behave exactly as they do inside a test body:
  the test is skipped / marked fixme / marked expected-to-fail. This is
  the supported way to implement pytest's marker-driven-skip pattern
  shown at the top of this page. A test statically skipped via
  `param(skip=...)` never reaches the setup hook (already decided).
- Any exception from `logstart`/`setup`/`teardown`/`logreport`/`logfinish`
  never fails the test it's observing — caught and surfaced as a
  `RuntimeWarning` (in `Result.warnings` for `setup`/`teardown`, which run
  inside the attempt's warning-capture window; straight to the worker's
  stderr for the others). `runtest_call` is the one exception (see above)
  — it fails the test on purpose, matching pytest.

## Dynamic parametrization, fixture/warning/assert/report hooks, and ordering

### `ctrlrunner_generate_tests(metafunc)` — dynamic parametrization

```python
# conftest.py
def ctrlrunner_generate_tests(metafunc):
    if "browser" in metafunc.fixturenames:
        metafunc.parametrize("browser", ["chromium", "firefox"], ids=["cr", "ff"])
```

Fires once per `@test` function, at the point `registry.py`'s `test()`
decorator processes it (i.e. at conftest/module import time — both the main
process's discovery pass and, redundantly but harmlessly, each worker's own
re-import). `metafunc` carries `.function`, `.fixturenames` (list of the
test's parameter names), `.config`, `.cls`, `.module`, and
`.parametrize(argnames, argvalues, indirect=False, ids=None, scope=None)`,
which buffers the call and replays it through the real `@parametrize`
decorator — so ids/tags/cartesian-product behave exactly like a static
`@parametrize`. **Only consulted when the test has no static `@parametrize`
already** (mutually exclusive, not additive — unlike pytest, which allows
layering `generate_tests` on top of marker-based parametrize).

### `ctrlrunner_make_parametrize_id(config, val, argname)` — custom id text

```python
def ctrlrunner_make_parametrize_id(config, val, argname):
    if isinstance(val, MyEnum):
        return val.name
    return None   # fall through to the default id logic
```

Consulted first (firstresult — the first non-`None` return wins) whenever a
parametrize combination needs a test-id suffix. Registered per-conftest in
both the main process (`orchestrator.py`, which is what actually schedules
test ids) and each worker.

### `ctrlrunner_fixture_setup` / `ctrlrunner_fixture_post_finalizer`

```python
def ctrlrunner_fixture_setup(fixturedef, request):
    print(f"setting up {fixturedef.argname} ({fixturedef.scope})")

def ctrlrunner_fixture_post_finalizer(fixturedef, request):
    print(f"tore down {fixturedef.argname}, cached value was {fixturedef.cached_result}")
```

Pure notifications (not firstresult/override — the fixture's own body is
always the real setup code) fired immediately before a fixture function runs
and immediately after its teardown, for every fixture resolved by any test.
`fixturedef` carries `.argname`/`.scope`/`.cached_result` (the finalizer's
cached value for module/session-scoped fixtures, `None` for function-scoped).
`request` carries `.fixturename`/`.scope`/`.config`; `.node` isn't threaded
through the resolver and raises `CompatibilityError` if accessed. A broken
hook here never affects fixture resolution itself.

### `ctrlrunner_warning_recorded(warning_message, when, nodeid, location)`

Fires once per warning captured during a test attempt's `call` phase (`when`
is always `"runtest"` — config/collection-phase warnings aren't captured
today). `warning_message` is the raw `warnings.WarningMessage`.

### `ctrlrunner_assertrepr_compare(config, op, left, right)`

```python
def ctrlrunner_assertrepr_compare(config, op, left, right):
    if op == "==" and isinstance(left, MyDataclass):
        return [f"MyDataclass mismatch:", f"  left:  {left}", f"  right: {right}"]
```

Consulted for a failing `==`/`!=` assertion inside a test body. A non-empty
list of strings returned is appended to the assertion failure message — the
same custom-comparison-explanation pattern as pytest's own hook.

### `ctrlrunner_report_teststatus(report, config)`

```python
def ctrlrunner_report_teststatus(report, config):
    if report.outcome == "passed" and report.duration > 5:
        return ("slow", "S", "SLOW")
```

Consulted by the built-in Dots/Line reporters for a custom `(category,
shortletter, verbose_word)` status; only `shortletter` is used today (both
reporters are single-character). Returning `None` (or nothing) falls through
to the default symbol.

### Hook ordering: `@ctrlrunner.hookimpl(tryfirst=True/trylast=True)`

```python
from ctrlrunner import hookimpl

@hookimpl(tryfirst=True)
def ctrlrunner_runtest_setup(item):
    ...
```

When multiple conftests (or one conftest with hooks registered from several
places) define the same hook, `tryfirst=True` hooks run before the default
order and `trylast=True` hooks run after; hooks with neither flag keep the
existing shallowest-conftest-first discovery order among themselves.
Conftest discovery order itself was **not** changed to match pytest's
LIFO/deepest-first (see [the parity plan](pytest-hooks-parity-plan.md)) —
`tryfirst`/`trylast` is the escape hatch for a hook that specifically needs
to win.

### `hookwrapper=True` — only for `ctrlrunner_runtest_makereport`

```python
from ctrlrunner import hookimpl

@hookimpl(hookwrapper=True)
def ctrlrunner_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        outcome.force_result(report)   # or mutate/replace as needed
```

A hookwrapper is a generator that yields exactly once; the value sent back
via `yield` is an `outcome` object with `.get_result()` (the report so far,
or re-raises if an earlier impl raised) and `.force_result(value)` (replaces
it for every hook still to run). Supported only for
`ctrlrunner_runtest_makereport` — the one hook where wrapper usage dominates
real-world pytest plugins; `hookwrapper=True` on any other hook is ignored.

## Compatibility limits — fail loudly, with guidance

Everything with a real ctrlrunner meaning is implemented for real —
including `item.session`, `item.cls`, `item.module`, `item.funcargs`,
`report.sections`, `config.cache`, and `config.pluginmanager`. For the
remainder (pytest's collection tree — `item.parent`,
`session.perform_collect`, hook-ordering machinery, ...) the compat layer
**fails loudly and helpfully**:

- **Unmodeled attributes raise `CompatibilityError`** (an `AttributeError`
  subclass, so `hasattr()`/`getattr(x, name, default)` probes keep their
  pytest behavior) whose message carries a concrete recommendation — e.g.
  `item.parent` → *"ctrlrunner has no collection tree; use item.module,
  item.cls, or item.nodeid"*. Inside a per-test hook this **fails that
  test** with the recommendation in the failure text, so an unported hook
  is impossible to miss.
- **Unsupported hook names abort at startup**: a conftest defining any
  `pytest_*` function, or a `ctrlrunner_*` name outside the supported set
  (typo protection), stops the run before anything executes, with per-hook
  guidance — "rename to ctrlrunner_X (the migrate tool does this)" for any of
  the 20 hooks with a compatible rename (see
  [the parity plan](pytest-hooks-parity-plan.md) for the full list), or the
  architectural alternative for hooks with no possible equivalent (no more
  "planned (Phase N)" hooks remain — every hook on the parity roadmap is
  implemented). Set `allow_unknown_hooks = true` in `ctrlrunner.toml` to
  downgrade this to a warning while a conftest still serves both runners
  mid-migration.

Hooks may declare fewer parameters than the full signature (e.g.
`def ctrlrunner_runtest_teardown(item)`) and receive just the prefix they
asked for.

## Full example

```python
# conftest.py
import subprocess
import sys

from ctrlrunner import skip

_mock_server = None

def ctrlrunner_configure(config):
    global _mock_server
    _mock_server = subprocess.Popen(["./scripts/mock_server.py"])

def ctrlrunner_sessionfinish(session, exitstatus):
    _mock_server.terminate()
    _mock_server.wait()

def ctrlrunner_runtest_setup(item):
    if item.get_closest_marker("mac_only") and sys.platform != "darwin":
        skip(True, "This test can only run on macOS.")

def ctrlrunner_runtest_logreport(report):
    if report.failed:
        print(f"[ctrlrunner] {report.nodeid} attempt {report.attempt}: {report.longrepr}")
```
