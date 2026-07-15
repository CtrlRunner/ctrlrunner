# Reporters, history & flake management

[← Back to README](../README.md)

## Reporters

```
--reporter line,dots,json     # console reporters, comma-separated, default: line
                              # (a custom reporter loads via "module.path:ClassName")
--json-output results.json
--junit-xml report.xml        # always written; feeds the existing Teams pipeline
--junit-logs system-out|split # embed captured stdout/stderr in the JUnit XML
```

- `line` — single progress line, failures printed below as they happen.
- `dots` — classic `.`/`F` per test.
- `json` — `{stats, tests: [...]}` with case ID, tags, outcome, attempts,
  error, artifact paths, captured `warnings`, plus run-level
  `suiteProperties`.
- JUnit XML — `<properties>` per `<testcase>` carry `test_case_id`,
  `tags`, `attempts` (if retried), `artifacts` (if captured), plus any
  custom `properties` passed to `@test`.

Before scheduling starts, every run prints a one-line collection
summary regardless of `--reporter` (e.g. `Collected 42 tests across 5
modules (12 tagged smoke, 3 tagged regression)`) — the only output
`json`-only runs produce beyond the file itself. `line`/`dots` end-of-run
summaries additionally include a short per-module breakdown table
(total/passed/failed) whenever 2+ modules ran.

JUnit XML hardening & options:

- The file is written **atomically** (tmp + rename) and all text is
  **sanitized** — control chars (NUL, ANSI codes) in an assert message
  can no longer produce unparseable XML.
- `<testsuite>` carries `timestamp`, `hostname` and `errors`
  attributes; testcase rows are **sorted** (project, then id) so two
  identical runs produce diff-identical reports.
- `--junit-logs system-out|split` (or `junit_logs` in config) embeds
  captured stdout/stderr (requires `--logs` capture) in `<system-out>`
  / `<system-err>` — the `junit_logging` equivalent.
- `junit_infra_errors = true` renders runner-synthesized failures
  (timeout hard-kill, worker crash) as `<error>` instead of
  `<failure>` and counts them in the `errors` attribute — "the infra
  broke" vs "the test failed". Off by default (shape-compatible).
  Regardless of the flag, such results always carry `infraError: true`
  in the JSON report / `test_end` event payload.

Runtime metadata from inside a test or fixture:

```python
from pyrunner import record_property, record_suite_property

@test()
def test_checkout(page):
    record_property("testrail", "C123")        # per-test <property> / JSON properties
    record_suite_property("environment", "staging")  # <testsuite><properties> / JSON suiteProperties
```

Unlike pytest+xdist, suite properties stream to the orchestrator per
call, so a later worker kill can't lose them; across workers, last
write per key wins.

Python warnings raised during a test are captured per-test (capped at
100), reported in the JSON/event `warnings` field, and counted in the
console summary.

Fixture teardown failures are **never silent**: a passing test whose
fixture teardown raised is reported `failed` (message includes the
teardown traceback). Set `strict_teardown = false` to keep the old
outcome — the result then carries a `teardown_failed = "true"` property
instead. Module/session-scope teardown failures (they run between/after
tests) are logged and recorded as `teardown_error:<fixture>` suite
properties.

## Rerun workflows

```
pyrunner --last-failed                              # rerun what failed in the most recent report
pyrunner --failed-from old-results.json               # rerun what failed in a specific JSON report
pyrunner --changed-since origin/main                   # rerun tests in files changed since a git ref
```

All three are pure ways to pre-populate `--test-id` -- no new selection
logic, just different ways to arrive at a list of ids.

- **`--last-failed`** reads the previous run's `results.json` (written
  by every run); finds the most recently modified report directory (read-only
  -- unlike the normal report-writing path, this never creates a fresh
  timestamped directory, so it actually finds your last run instead of
  an empty new one) and reruns whatever has `outcome: "failed"` in it.
- **`--failed-from PATH`** does the same against an explicit JSON file
  (e.g. one downloaded from a CI artifact).
- **`--changed-since REF`** shells out to `git diff --name-only REF`
  and reruns every test whose source file appears in that diff.
  Deliberately file-level, not import-graph-aware -- it can over-select
  (rerun a file's tests even if your specific change didn't touch them)
  but never under-selects, the safe direction for "did I break
  anything."

If a stored test id from a previous report doesn't exist verbatim in
the current collection (e.g. `@parametrize` values changed since then),
it falls back to matching every current variant sharing the same base
id, rather than silently dropping it. Combined with `--project`, rerun
selection naturally intersects with the project's own test set (each
project only ever sees tests inside its own `tests_dir` regardless of
what's being reused for selection).

A rerun selection that touches a `@test_class(serial=True)` class
expands to the **whole class** — rerunning only the failed member of an
inter-dependent flow would exercise a partial group. Explicit
`--test-id` selections are never expanded.

## Historical timing store

Every run's per-test durations/outcomes are recorded to a local SQLite
file -- the foundation for future smart sharding and flaky-test
analytics, and already independently useful for your own queries:

```toml
[pyrunner.history]
enabled = true                    # default; set false to disable entirely
db_path = "reports/.history.db"   # default: <reports-dir>/.history.db
window_runs = 20
```

Deliberately **not** inside the (possibly timestamped, possibly pruned
by `--keep-reports`) per-run report directory -- history is meant to
accumulate across many runs over time, so it lives at `reports_dir`'s
stable root instead. A single consolidated file, not one-file-per-test
(thousands of small files is a known pain point for AV scanners and
filesystem overhead on Windows CI runners).

Written once per run (or once per project, in a multi-project run --
each gets its own row; SQLite `INSERT`s are naturally additive, so
unlike the JSON reporter there's no clobbering risk from writing
multiple times in one invocation), never mid-run, so a killed/crashed
run simply never gets recorded rather than leaving a partial entry.

```python
from pyrunner.reporting.history import HistoryStore

with HistoryStore("reports/.history.db") as store:
    durations = store.get_durations("mod::test_x", window=10)
    outcomes = store.get_outcomes("mod::test_x", window=20)
```

Once enabled, this also drives **smart scheduling**: batches are
assigned via longest-processing-time-first (LPT) bin-packing using each
test's historical median duration, instead of plain round-robin -- so
five slow tests don't pile onto one worker while forty fast ones sit on
another. A test with no history yet gets the overall median as a
neutral placeholder (never zero, which would cluster every new test
onto a single worker). With an empty/fresh history store, LPT
degenerates to exactly today's round-robin order -- so there's no
"cold start" behavior change, it only helps once real data exists.
Scoped by project, same as the duration lookups themselves.

## Fail policies

Stop a run early once things are clearly going wrong, instead of
burning through the whole suite:

```
--max-failures 5          # stop once 5 tests have failed (0/unset = unlimited)
--max-timeouts 3          # stop once 3 tests have been hard-killed by timeout
--stop-on-worker-crash    # stop if a worker process crashes on its own
--fail-fast                # sugar for --max-failures 1
```

```toml
[pyrunner.fail_policy]
max_failures = 0
max_timeouts = 0
stop_on_worker_crash = false
```

Reuses the exact same `cancel_event`/hard-kill mechanism as UI Mode's
Cancel button -- no separate kill path. Tests that don't get to run
because a threshold was crossed are reported as **`not_run`**,
deliberately distinct from `cancelled` (an explicit external stop, e.g.
UI Mode's Stop button) -- so a CI dashboard can tell "the run stopped
itself on purpose" apart from "someone hit Stop." Neither counts as a
failure, but the run's exit code still reflects the real failures that
did happen.

A retried test that eventually passes never counts toward
`--max-failures` (only *final* outcomes are counted). A worker crash
is always detected and reported, whether or not `--stop-on-worker-crash`
is set -- the flag only controls whether it also stops the run; its
remaining tests are marked failed (with a message pointing at a likely
import-time error) and are **not** requeued onto a fresh worker the way
a timeout's leftover batch is, since retrying a deterministic crash
risks an infinite loop.

In a multi-project run (`--project a,b`), all four policies count
**across the whole invocation**, not per project -- a threshold crossed
partway through project `a` stops project `b` from ever starting.

## Flaky analytics and quarantine

`pyrunner flaky-report` computes flake scores from the history store --
a *separate* command from a normal test run, so acting on this data
(quarantining something) is always an explicit, human-reviewed step:

```
pyrunner flaky-report
pyrunner flaky-report --window 20 --project smoke --format json --output flaky.json
```

A test's flake score is the fraction of its recent runs (where retries
were configured) that failed at least once but ultimately passed:

```
 100%  (n=4  )  tests.test_demo::test_sometimes_flaky
  n/a  (n=0  )  tests.test_demo::test_stable
```

`n/a` means "never had retries configured" -- not "definitely not
flaky." A test needs `@test(retries=...)` for its history to say
anything about flakiness at all.

Quarantine is a config-driven allowlist, populated by a human after
reviewing `flaky-report` output:

```toml
[pyrunner.quarantine]
test_ids = ["tests.test_demo::test_flaky_checkout"]
reason = "JIRA-4821, flaky since 2026-06, investigating"
```

A quarantined test **still runs** (quarantine is not `skip()`), but a
failure is reported as **`quarantined_failure`** -- distinct from
`failed`, excluded from `--max-failures`/`--max-timeouts`/the exit
code, shown with its own badge (and the reason on hover) in the HTML
report and UI Mode. A pass stays ordinary `passed`, still flagged as
quarantined so it stays visible either way. `flaky-report` also flags a
quarantined test whose score has since dropped near zero, suggesting
it might be worth un-quarantining -- an informational nudge only, never
automatic.

## Fixture and execution profiling

The step tree (`with step(...)`, HTML report / UI Mode timeline) now
accounts for the test's *entire* wall time, not just what a test author
happened to wrap in explicit steps:

```
fixture:resource:setup     <- each fixture's setup, timed
test body                   <- the test function itself
capture:resource             <- an on_failure artifact capture, if one ran
fixture:resource:teardown   <- each fixture's teardown, timed
```

A retried test's full history is visible in one tree, not just its
final attempt -- each attempt gets its own `attempt N` parent (only
when `retries` is actually configured; a plain test keeps today's exact
flat shape, no extra nesting):

```
attempt 1
  test body (failed)
attempt 2
  test body (failed)
attempt 3
  test body (passed)
```

A requeued test (its batch got hard-killed and reassigned to a fresh
worker after a timeout) carries a `worker_restart_overhead` field on
its `Result` -- the actual observed latency between the requeue
decision and that new worker's first `started` message, purely
informational.
