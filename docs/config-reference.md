# Config file, tags & test metadata reference

[← Back to README](../README.md)

## Config file (`pyrunner.toml`)

```toml
[pyrunner]
root = "tests"
num_workers = "auto"   # default: CPUs - 1. Or an int, or "50%" of CPUs
timeout = 30.0
reporter = ["line"]
# fully_parallel = false  # default: a file's tests share one worker, in order

reports_dir = "reports"
report_name = "html-report"
report_timestamp = false
keep_reports = 10
artifact_mode = "files"

# junit_xml = "report.xml"      # uncomment to override the managed path
# json_output = "results.json"  # uncomment to override the managed path

# junit_logs = "off"            # "system-out"/"split": captured stdout/stderr into JUnit XML
# junit_infra_errors = false    # true: timeout-kill/crash render as <error>, not <failure>
# strict_teardown = true        # false: a broken teardown no longer fails a passing test
# full_trace = false            # true: keep pyrunner-internal frames in failure tracebacks

# [pyrunner.workers]            # scoped worker budgets -- see "Parallelism & scheduling"
# "tests/test_checkout.py" = 1
```

Precedence: **CLI flag > `pyrunner.toml` > built-in default**. Running
`python -m pyrunner` with no arguments at all uses the config file's
`root`, or falls back to `"tests"`.

Unknown `[pyrunner]` keys and mis-nested tables (a bare `[workers]`
instead of `[pyrunner.workers]`) print a **warning** to stderr instead
of being silently ignored — typos no longer quietly run the suite with
defaults.

See [Parallelism, scheduling & test selection](parallelism-and-scheduling.md)
for worker budgets, and [Reporters, history & flake management](reporters-and-history.md)
for the history/coverage/fail-policy tables.

## Registered tag registry

Catches typos in `@test(tags=...)` before they cause a test to
silently not match a `--tag` filter. Fully opt-in -- absent from
config, zero validation, zero behavior change:

```toml
registered_tags = ["smoke", "regression", "team:*"]  # trailing * = prefix match
strict_tags = false  # default; true = unregistered tag -> 0 tests run, non-zero exit
```

```
--strict-tags   # override strict_tags for a single run
```

- **Warning mode** (default once `registered_tags` exists): unregistered
  tags print one summary line to stderr; the run proceeds normally.
- **Strict mode**: any unregistered tag anywhere in the suite is a
  collection-time error -- **zero tests run**, non-zero exit. Validation
  happens once, right after discovery, against every collected test
  (not just whatever `--tag`/`--case-id` happens to select this run),
  so a typo on a test nobody's currently filtering for still gets
  caught.
- `--tag some-typo` (the CLI value itself) gets its own **always-warning**
  check regardless of strict mode -- a one-off ad hoc filter shouldn't
  require a config change, but a likely typo is still worth flagging.
- UI Mode always treats this as warning-only, even if `strict_tags = true`
  in config -- blocking the whole live UI over a config strictness
  setting would be a bad local-dev experience; strict mode's "gate CI"
  purpose is a concern the CLI run path already covers.

## Class-level test metadata (`@test_class`)

Group related tests and give them shared defaults, without any shared
instance state between them:

```python
from pyrunner import test, test_class

@test_class(tags={"smoke"}, properties={"owner": "team_checkout"}, timeout=30, retries=1)
class LoginTests:
    @test(case_id="TC-1")
    def test_valid_login(self, page): ...

    @test(case_id="TC-2", tags={"regression"}, timeout=60)
    def test_invalid_login(self, page): ...
```

- **`tags`**: union of class tags and method tags.
- **`properties`**: dict merge; method-level key wins on conflict.
- **`timeout` / `retries`**: method-level wins if explicitly set, else
  the class's value, else the run's global default.
- **`workers` / `workers_mode` / `serial` / `fully_parallel`**:
  class-level scheduling controls -- see
  [Parallelism, scheduling & test selection](parallelism-and-scheduling.md).
  `@test` deliberately has no equivalents (scheduling below
  class/file granularity has no meaning).
- Test id becomes `module::LoginTests.test_valid_login`, and JUnit's
  `classname` reflects it correctly.

`self` is always bound to `None`, never a real instance -- classes here
are pure metadata containers, not shared state. This is enforced, not
just documented: `self.whatever = ...` fails loudly with
`AttributeError` rather than silently "working" on some per-test
instance. Methods that don't need `self` can omit it entirely.

`@test_class` must be the outermost decorator on the class, applied
once (not stacked, not inherited); it requires at least one
`@test`-decorated method inside.

## Runtime annotations: `skip`, `fail`, `fixme`, `slow`

Analogous to Playwright TS's `test.skip()` / `test.fail()` /
`test.fixme()` / `test.slow()`. Called from inside a test body (not the
`@test` decorator), since fixture values -- including parametrized ones
like `browser_type` -- are only known once the test is running, which is
also when a runtime condition like `browser_type == "firefox"` becomes
available:

```python
from pyrunner import skip, fail, fixme, slow

def test_x(browser_type, page):
    skip(browser_type == "firefox", "not implemented for Firefox")
    ...

def test_known_bug(page):
    fail(True, "JIRA-1000: known broken until fix ships", strict=True)
    ...  # expected to raise

def test_slow_operation(page):
    slow(True, factor=5.0)  # extends this test's timeout 5x for this run
    ...
```

- `skip(condition=True, description=None)` — stops the test immediately,
  reported as `skipped`, never counted as a failure, never retried.
- `fixme(condition=True, description=None)` — identical runtime
  behavior to `skip`, but reported as `fixme` (known-broken, needs
  attention) instead of `skipped` (intentionally not applicable) — a
  different triage bucket, not a different mechanism.
- `fail(condition=True, description=None, strict=True)` — marks the
  rest of the test as expected to fail (pytest's `xfail`, named after
  Playwright TS's `test.fail()`). Must be called *before* the failure
  happens:
  - Test raises afterward → reported as `expected_failure`, does not
    break the build.
  - Test unexpectedly passes:
    - `strict=True` (default) → reported as `failed` — an unexpected
      pass on a tracked bug is itself worth flagging.
    - `strict=False` → reported as `passed`, with an `unexpected_pass`
      property for visibility without breaking CI (useful right after a
      fix ships, before removing the `fail()` call).
- `slow(condition=True, factor=3.0)` — extends this test's timeout by
  `factor` for this run; the orchestrator's watchdog picks up the new
  deadline on its next check.

From the same family of runtime calls: `record_property(key, value)` and
`record_suite_property(key, value)` attach metadata to the current
test's result / to the whole run — see
[Reporters, history & flake management](reporters-and-history.md#reporters)
for where they land in JUnit/JSON.

`dots` prints distinct symbols: `.` pass, `F` fail, `s` skip, `f` fixme,
`x` expected failure. JUnit uses `<skipped>` for `skip`/`fixme` (not
`<failure>`) and a `expected_failure`/`unexpected_pass` property for
`fail()` outcomes — none of these break the exit code except a real
`failed`.
