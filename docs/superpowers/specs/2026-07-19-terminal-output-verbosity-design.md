# Terminal output verbosity, capture, and traceback control

Status: draft, approved by user in brainstorming, pending spec review sign-off.

## Problem

Test-produced output (`print()`, `logging`) currently always leaks live to the
terminal while ctrlrunner runs, regardless of the `--logs` setting
(`--logs` only controls whether captured output gets *persisted into report
files* — JSON/HTML/JUnit — not whether it's suppressed from the live
terminal). There is also no pytest-style way to control per-test verbosity
(`-v`/`-q`), which parts of the end-of-run summary print (`-r <chars>`), or
how much traceback detail a failure shows (`--tb=<style>`). This spec adds
all four, matching pytest's flags where a clean mapping exists, and calling
out where it deliberately doesn't.

## Current state (verified against source)

- `log_capture.py`: `capture_logs()` (`:109-145`) tees stdout/stderr via
  `_Tee` (`:59-80`), which **always forwards to the real stream** even while
  buffering, and adds a root-logger `_CaptureHandler` (`:83-106`). Bounded to
  5MB via `_BoundedBuffer` (`:23-56`, tail-keeping).
- `worker.py:457`: `capture_logs()` is only entered when `logs_mode != "off"`.
  Default `logs_mode` is `"off"` (`cli.py:546-551`), so by default there is
  **no interception at all** — output goes straight to the worker process's
  inherited stdout.
- `worker.py:717-722`: `keep_logs` decides whether captured content survives
  into the result payload for report files; this is orthogonal to live
  terminal forwarding, which `_Tee` does unconditionally whenever capture is
  active at all.
- `reporters.py`: `ConsoleReporter` base (`:56-67`), `DotsReporter`
  (`:138-150`), `LineReporter` (`:153-195`, the default —
  `cli.py:1177`). `LineReporter` overwrites a `\r` progress line, persists
  `✗ test_id` on failure only. `_summary_lines()` (`:70-123`) always prints
  full error text for every failure, no filtering.
- Outcome taxonomy actually used (`reporter.py`, `reporters.py`): `passed`,
  `failed`, `expected_failure`, and a "skipped" bucket covering `skipped`,
  `fixme`, `cancelled`, `not_run`, `quarantined_failure`. `flaky` is a
  boolean attribute on `Result`, not a separate outcome. `warnings` is a
  run-level count, not a per-test outcome.
- `tb_format.py`: binary only — `format_filtered_exc()` (`:44-58`) strips
  ctrlrunner-internal frames from the exception chain (`:30-41`) unless
  `set_full_trace(True)` (driven by `--full-trace`, `cli.py:500-505`).

## Design

### 1. Capture becomes default-on, non-forwarding

`capture_logs()` is entered for **every** test attempt unconditionally (no
longer gated on `--logs`). `_Tee` stops forwarding to the real stream by
default — output is buffered only, not printed live. `--logs` keeps its
current, unrelated meaning: whether buffered content gets embedded into
JSON/HTML/JUnit report files. These two now-independent axes both read from
the same buffer.

On a failed test, the buffer's content is sent back with the result
(regardless of `--logs`) and appended under that test's failure block in the
console summary, in the same place the traceback prints. On a passed test,
it's discarded unless `-rP` was passed (section 3).

New flag `-s` / `--capture=no` restores today's always-forward behavior, for
interactive debugging (e.g. a test with a `breakpoint()`).

Side effect (documented, not a goal): parallel workers no longer interleave
raw output on the terminal by default, since nothing writes to it live except
the reporter itself. `-s` can still interleave, same trade-off pytest-xdist
has with `-s`.

### 2. `-v` / `--verbose` and `-q` / `--quiet`

Single-level only (not pytest's stackable `-vv`/`-qq` — nothing here needs
finer granularity, and adding it would be speculative).

- Default: unchanged. `LineReporter`'s `\r`-overwritten progress line,
  `✗ test_id` persisted on failure, full summary at the end.
- `-v`: every completed test gets its own persisted line —
  `PASSED test_id`, `FAILED test_id`, `SKIPPED test_id` — instead of the
  overwritten progress line. Does not affect captured-output replay (that's
  `-r`'s job) or HTML/JUnit report content (console-only, see section 5).
- `-q`: no per-test output during the run (no dots, no progress line); only
  the final totals line and failure test ids, with no inline traceback text
  and no captured-output replay (section 1's failure-block content is
  suppressed too) unless `-r` explicitly asks for either.
- `-v` and `-q` together: usage error at argument-parsing time. Pytest's
  additive counting model isn't needed here.

### 3. `-r <chars>` — end-of-run summary control

Letters, mapped onto the outcome taxonomy above:

| Char | Outcome bucket |
|---|---|
| `f` | failed |
| `s` | skipped (skipped/fixme/cancelled/not_run/quarantined_failure) |
| `x` | expected_failure |
| `p` | passed |
| `P` | passed, with captured output replayed (ties into section 1) |
| `w` | warnings |
| `a` | all except passed (`f`+`s`+`x`+`w`) |
| `A` | all (`f`+`s`+`x`+`p`+`w`) |

Each requested letter adds a section to `_summary_lines()` listing that
outcome's test ids (+ reason where one exists, e.g. skip reason). Default
(flag omitted) behaves exactly as today: full error text for failures only,
nothing for other outcomes — purely additive, zero behavior change for
existing invocations that don't pass `-r`.

`flaky` has no dedicated letter (pytest has no analogous concept); the
existing unconditional flaky count line in the summary is unchanged.

`-rP`'s captured-output replay is sourced from the existing `--logs`-gated
`Result.logs` (not the new always-buffered failure path in section 1) —
buffering every passing test's output indefinitely just in case `-rP` is
later requested would reintroduce the memory cost section 1 exists to avoid.
`-rP` without `--logs on` shows the passed-test id with no output, same as
today when no logs were captured; this is a deliberate, documented scope
trim, not a gap.

### 4. `--tb=<style>` — traceback detail

Extends `tb_format.py`'s binary filtered/full into five named styles:

- `auto` (default): today's filtered behavior, unchanged.
- `long`: today's `--full-trace`, full unfiltered traceback. `--full-trace`
  keeps working as an alias; if both flags are given, `--tb` wins.
- `short`: filtered, trimmed to just the frame where the exception actually
  occurred plus the exception line (new formatting logic in `tb_format.py`).
- `line`: single line — `path/to/test.py:42: AssertionError: message`.
- `no`: suppress the traceback body entirely; only the failure's outcome
  line prints.
- `native`: accepted as an alias for `long`. Pytest's `native` reproduces
  Python's own unmodified traceback machinery as a distinct third style;
  ctrlrunner doesn't wrap a separate traceback system the way pytest does,
  so there's no distinct behavior to give it. This is a deliberate,
  documented parity gap, not an oversight.

### 5. Scope boundary

`-v`/`-q`/`-r` are **console-only** — they change what
`LineReporter`/`DotsReporter` print to the terminal. HTML, JSON, and JUnit
reports are unaffected and keep including full per-test data regardless,
consistent with how `--reporter` and `--logs` already each govern only their
own output channel today.

`--tb` is the one exception, and deliberately so: it extends `--full-trace`,
which today already formats `Result.error` globally, before any channel sees
it (`tb_format.format_filtered_exc()` is the single source of that string for
console, JUnit, HTML, and JSON alike — there's no per-channel traceback
formatting to hook into separately). Splitting that into a console-only copy
and an unfiltered channel copy would be a materially bigger change with no
clear demand for it, so `--tb` stays global, matching `--full-trace`'s
existing behavior exactly. `--tb=no` therefore also empties `<failure>` text
in JUnit and the HTML report, not just the console — documented here as an
intentional consequence, not an oversight.

## Testing

Following this project's TDD requirement — every behavior change below
gets a RED test before the implementation:

- Capture: a test that `print()`s and passes produces no terminal output by
  default; a test that `print()`s and fails shows that output in the failure
  block; `-s` restores live forwarding. Cover via the existing
  `tests/test_orchestrator_and_worker.py` end-to-end style (spawn a real
  worker against a scratch conftest/test file, assert on captured
  subprocess stdout).
- `-v`/`-q`: assert exact per-test line output for a small passing+failing+
  skipped suite under each mode; assert `-v -q` together raises a
  usage/argparse error.
- `-r`: for each letter and `a`/`A`, assert the right outcome buckets appear
  in `_summary_lines()` output; assert omitting `-r` reproduces today's
  exact output (regression guard).
- `--tb`: for each of the 6 accepted values (`auto/long/short/line/no/native`),
  assert the exact traceback shape ctrlrunner emits for a fixed sample
  exception; assert `--full-trace` and `--tb=long` produce identical output;
  assert `--tb=native` and `--tb=long` produce identical output.
- Regression: full existing `tests/test_reporters.py` (or equivalent) and
  `tests/test_orchestrator_and_worker.py` suites stay green with no flags
  passed — this feature must not change default output for callers who
  don't opt in, except for the capture-suppression fix in section 1, which
  *is* the intended default-behavior change and should have its own
  before/after test pair.

## Out of scope

- Multi-level `-vv`/`-qq`/`-q -q` counting.
- fd-level capture (subprocess/C-extension output) — sys-level capture via
  `_Tee` is what exists today and is sufficient for ctrlrunner's
  Python-only test model; noted in brainstorming as Option C and rejected
  as higher risk for marginal benefit.
- Coupling `-v` (or any of these flags) to HTML/JSON/JUnit report detail.
- A distinct behavior for `--tb=native`.
