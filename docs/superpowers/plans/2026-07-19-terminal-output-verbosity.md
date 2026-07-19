# Terminal Output Verbosity, Capture, and Traceback Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pytest-parity `-v`/`-q`/`-r <chars>`/`--tb=<style>` flags to ctrlrunner, and fix the underlying bug where captured test stdout/logging always leaks live to the terminal regardless of `--logs`.

**Architecture:** `log_capture.py`'s tee stops forwarding to the real stream by default (buffer-only), with a new `-s`/`--no-capture` escape hatch. A failed test's buffered output threads through the existing `worker.py` → `orchestrator.py` → `Result` → `reporters.py` pipeline as a new `console_captured` field, parallel to (not merged with) the pre-existing `--logs`-gated `Result.logs` used by JUnit/HTML/JSON. `-v`/`-q` become a `verbosity` attribute on `LineReporter`/`DotsReporter`; `-r <chars>` extends `_summary_lines()` with opt-in outcome-bucket sections. `--tb` extends `tb_format.py`'s existing binary filtered/full split into five named styles, threaded through the worker the same way `--full-trace` already is.

**Tech Stack:** Python 3, `argparse`, `unittest` (TDD, per this repo's `superpowers:test-driven-development` convention), `multiprocessing` (spawn context) for the worker process boundary.

## Global Constraints

- Every default-no-flags invocation must produce byte-identical console output to today, **except** the capture-suppression fix in Task 3 (test stdout/logging no longer leaks live) — that is this plan's one intentional default-behavior change; everything else is strictly additive/opt-in.
- Every new file/function change is TDD: write the failing test, watch it fail for the right reason, write minimal code, watch it pass.
- `docs/superpowers/specs/2026-07-19-terminal-output-verbosity-design.md` is the approved design spec — consult it for the "why" behind any decision here; this plan is the "how".
- Run `graphify update .` after implementation, before the final commit, per this repo's CLAUDE.md convention.
- No comments explaining WHAT code does — only WHY, and only where non-obvious (this repo's existing style, visible throughout every file touched here).

---

### Task 1: `log_capture.py` — `forward_live` parameter

**Files:**
- Modify: `src/ctrlrunner/core/log_capture.py:59-145`
- Test: `tests/test_log_capture.py`

**Interfaces:**
- Produces: `capture_logs(max_stream_bytes: int = _MAX_STREAM_BYTES, forward_live: bool = False)` — new default is buffer-only (no live echo to the real stream). `_Tee.__init__(self, original, buffer, forward_live: bool)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_log_capture.py`, inside `CaptureLogsTests`, replacing the existing `test_tees_to_the_original_stdout` (its name now describes non-default behavior — rename and add a sibling for the new default):

```python
    def test_does_not_forward_to_original_stdout_by_default(self):
        fake_stdout = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = fake_stdout
        try:
            with log_capture.capture_logs() as result:
                print("captured only")
        finally:
            sys.stdout = old_stdout
        self.assertNotIn("captured only", fake_stdout.getvalue())
        self.assertIn("captured only", result["stdout"])

    def test_forwards_to_original_stdout_when_forward_live_true(self):
        fake_stdout = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = fake_stdout
        try:
            with log_capture.capture_logs(forward_live=True) as result:
                print("visible on both")
        finally:
            sys.stdout = old_stdout
        self.assertIn("visible on both", fake_stdout.getvalue())
        self.assertIn("visible on both", result["stdout"])
```

Delete the old `test_tees_to_the_original_stdout` (lines 38-48 today) — it's superseded by the two tests above (one for each `forward_live` value).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_log_capture.CaptureLogsTests.test_does_not_forward_to_original_stdout_by_default -v`
Expected: FAIL — `AssertionError: 'captured only' unexpectedly found in ''` is wrong; actually today's code forwards unconditionally, so the failure is `"captured only" found in fake_stdout.getvalue()` when the test asserts `assertNotIn`. Confirm the failure message shows the tee is currently always forwarding.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/core/log_capture.py`, replace `_Tee` (lines 59-80) and `capture_logs` (lines 109-145):

```python
class _Tee:
    """Writes to the bounded buffer, and to the original stream too when
    forward_live is True -- worker output printed directly to
    stdout/stderr during a captured test only reaches the real
    console/log when the caller explicitly asked for it (-s /
    --capture=no); the default is buffer-only. Implements write/flush
    explicitly and delegates everything else (isatty, encoding, buffer,
    ...) to the original stream via __getattr__, so code that probes
    those attributes doesn't break."""

    def __init__(self, original, buffer: _BoundedBuffer, forward_live: bool):
        self._original = original
        self._buffer = buffer
        self._forward_live = forward_live

    def write(self, text):
        self._buffer.write(text)
        if self._forward_live:
            return self._original.write(text)
        return len(text)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)
```

```python
@contextmanager
def capture_logs(max_stream_bytes: int = _MAX_STREAM_BYTES, forward_live: bool = False):
    """Captures stdout, stderr, and Python logging records for the
    duration of the `with` block. Yields a dict that is filled in as
    output arrives and is fully populated only once the block exits:
    {"stdout": str, "stderr": str, "records": [...], "truncated": bool}.
    forward_live=False (default) means captured output does NOT reach
    the real stream live -- only the buffer sees it.
    """
    stdout_buffer = _BoundedBuffer(max_stream_bytes)
    stderr_buffer = _BoundedBuffer(max_stream_bytes)
    records: list = []
    handler = _CaptureHandler(records)

    result: dict = {"stdout": "", "stderr": "", "records": records, "truncated": False}

    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root_logger.removeHandler(existing)

    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(original_stdout, stdout_buffer, forward_live)
    sys.stderr = _Tee(original_stderr, stderr_buffer, forward_live)
    root_logger.addHandler(handler)
    try:
        yield result
    finally:
        root_logger.removeHandler(handler)
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        result["stdout"] = stdout_buffer.getvalue()
        result["stderr"] = stderr_buffer.getvalue()
        result["truncated"] = stdout_buffer.truncated or stderr_buffer.truncated
```

Also update the module docstring (lines 1-15) — replace `"""... used by worker.py when logs != "off"."""` wording with `"""... used by worker.py for every test attempt; forward_live controls whether output also reaches the real stream live."""` (keep the rest of the docstring's content about the two-phase capture shape and restore-in-finally guarantee unchanged).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_log_capture -v`
Expected: all tests PASS, including the two new ones and every pre-existing test in the file (none of them pass `forward_live`, so they all exercise the new default and must still pass since none of them assert on live-forwarding except the two just added/removed).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/core/log_capture.py tests/test_log_capture.py
git commit -m "feat: log_capture buffers by default, forwards live only when asked"
```

---

### Task 2: `Result.console_captured` field

**Files:**
- Modify: `src/ctrlrunner/reporting/reporter.py:47-87` (`Result` dataclass), `:128-182` (`JUnitReporter.add_result`)
- Test: `tests/test_reporter.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Result.console_captured: str | None = None`. `JUnitReporter.add_result(..., console_captured: str | None = None)` threads it into the constructed `Result`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reporter.py` (check the file's existing top-of-file imports/class layout first; add a new test class following its existing style):

```python
class ConsoleCapturedFieldTests(unittest.TestCase):
    def test_defaults_to_none(self):
        reporter = JUnitReporter()
        result = reporter.add_result("t::test_a", "failed", "boom", 0.1)
        self.assertIsNone(result.console_captured)

    def test_add_result_threads_console_captured_onto_the_result(self):
        reporter = JUnitReporter()
        result = reporter.add_result(
            "t::test_a", "failed", "boom", 0.1, console_captured="stdout: hi"
        )
        self.assertEqual(result.console_captured, "stdout: hi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_reporter.ConsoleCapturedFieldTests -v`
Expected: FAIL with `TypeError: add_result() got an unexpected keyword argument 'console_captured'`.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/reporting/reporter.py`, add the field to `Result` right after `started_at` (line 86):

```python
    started_at: float | None = None
    # Captured stdout/stderr for a FAILED test's last attempt, always
    # populated regardless of --logs (unlike `logs` above, which is
    # --logs-gated and feeds JUnit/HTML/JSON) -- console-only, read by
    # reporters.py's _summary_lines(), never serialized to JUnit/HTML/JSON.
    console_captured: str | None = None
```

In `JUnitReporter.add_result` (lines 128-182), add the parameter at the end of the signature and thread it into the `Result(...)` call:

```python
    def add_result(
        self,
        test_id,
        outcome,
        error,
        duration,
        case_id=None,
        tags=(),
        properties=None,
        attempts=None,
        artifacts=(),
        steps=None,
        groups=None,
        project=None,
        retries_configured=None,
        worker_restart_overhead=None,
        quarantined=False,
        quarantine_reason=None,
        worker_id=None,
        near_timeout=False,
        assert_details=None,
        logs=None,
        infra_error=False,
        warnings=None,
        flaky: bool = False,
        started_at: float | None = None,
        console_captured: str | None = None,
    ):
        result = Result(
            test_id=test_id,
            outcome=outcome,
            error=error,
            duration=duration,
            case_id=case_id,
            tags=tuple(tags),
            properties=properties or {},
            attempts=attempts,
            artifacts=tuple(artifacts),
            steps=steps or [],
            groups=groups or {},
            project=project,
            retries_configured=retries_configured,
            worker_restart_overhead=worker_restart_overhead,
            quarantined=quarantined,
            quarantine_reason=quarantine_reason,
            worker_id=worker_id,
            near_timeout=near_timeout,
            assert_details=assert_details,
            logs=logs,
            infra_error=infra_error,
            warnings=warnings,
            flaky=flaky,
            started_at=started_at,
            console_captured=console_captured,
        )
        self.results.append(result)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_reporter -v`
Expected: all PASS, including the full pre-existing suite in that file (no other test constructs `Result`/`add_result` positionally past `started_at`, so this is additive-only).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/reporting/reporter.py tests/test_reporter.py
git commit -m "feat: add Result.console_captured field for console-only failure replay"
```

---

### Task 3: `worker.py` — always-on capture, `console_captured` computation, `no_capture` threading

**Files:**
- Modify: `src/ctrlrunner/execution/worker.py:338-350` (`_execute_test` signature), `:397-399` (init locals), `:456-457` (capture entry), `:582-604` (post-attempt block), `:749-765` (return tuple), `:768-781` (`_run_serial_group` signature), `:849-862`, `:1010-1023`, `:1031-1044` (call sites), `:880-893` (`run_worker` signature), `:909` (tb_format call site, unchanged this task)
- Test: `tests/test_orchestrator_and_worker.py`

**Interfaces:**
- Consumes: `log_capture.capture_logs(forward_live=...)` from Task 1.
- Produces: `_execute_test(..., no_capture: bool = False)` returns a 16-element `"finished"` tuple (15 existing fields + `console_captured: str | None` appended last). `run_worker(..., no_capture: bool = False)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator_and_worker.py` (find the class that already spawns a real `Orchestrator` end-to-end against a scratch directory — e.g. the `Phase3HookTests` style used for `test_warning_message_is_the_real_warningmessage_object_with_category` — and add a sibling class following the same pattern):

```python
class CaptureSuppressionTests(unittest.TestCase):
    def test_passed_test_output_does_not_leak_and_failed_test_output_is_attached(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_quiet_pass():\n"
                "    print('should not leak')\n\n"
                "@test()\ndef test_noisy_fail():\n"
                "    print('should be attached to failure')\n"
                "    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertIsNone(by_id["test_quiet_pass"].console_captured)
        self.assertIn("should be attached to failure", by_id["test_noisy_fail"].console_captured)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_orchestrator_and_worker.CaptureSuppressionTests -v`
Expected: FAIL with `AttributeError: 'Result' object has no attribute 'console_captured'` is already fixed by Task 2 (field exists, defaults `None`), so the actual failure here is the second assertion: `self.assertIn(..., None)` raises `TypeError: argument of type 'NoneType' is not iterable` — confirms `console_captured` is never populated yet.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/execution/worker.py`:

**3a.** `_execute_test` signature (lines 338-350) — add `no_capture` parameter:

```python
def _execute_test(
    item,
    test_id: str,
    fixtures,
    resolver,
    result_queue,
    worker_id: int,
    logs_mode: str,
    cov,
    coverage_config,
    strict_teardown: bool = True,
    next_item=None,
    no_capture: bool = False,
):
```

**3b.** Init locals (lines 397-399) — add `console_captured = None` before the `while True:` loop:

```python
    captured_logs: list = []
    all_warnings: list = []
    teardown_failed = False
    console_captured = None
```

**3c.** Capture entry (line 457) — always enter capture, decoupled from `logs_mode`:

```python
        log_cm = log_capture.capture_logs(forward_live=no_capture)
```

(Remove the `if logs_mode != "off" else nullcontext(None)` branch entirely — `captured` is now always a populated dict, never `None`.)

**3d.** Post-attempt block (right after the existing `td_errors` handling, before `report_sections = []` at line 595) — compute `console_captured` fresh each iteration so it holds the FINAL attempt's content when the loop breaks:

```python
        if outcome == "failed":
            parts = []
            if captured.get("stdout"):
                parts.append(f"----- Captured stdout -----\n{captured['stdout']}")
            if captured.get("stderr"):
                parts.append(f"----- Captured stderr -----\n{captured['stderr']}")
            console_captured = "\n".join(parts) or None
        else:
            console_captured = None

        report_sections = []
        if captured:
```

(The `report_sections = []` line and everything after it through line 604 stays exactly as-is — this new block is inserted immediately before it. Note `if captured:` on the next line was previously guarding against `captured is None`; it's now always a dict, so this condition is always `True`, which is harmless — leave it unchanged rather than removing the now-redundant guard, to keep this diff minimal.)

**3e.** Return tuple (lines 749-765) — append `console_captured` as the 16th element:

```python
    return (
        "finished",
        worker_id,
        test_id,
        outcome,
        error,
        duration,
        attempt,
        artifacts,
        _trim_aria_snapshot_from_steps([s.to_dict() for s in attempt_steps]),
        extra_properties,
        max_attempt_duration,
        assert_details,
        final_logs,
        all_warnings or None,
        first_attempt_start,
        console_captured,
    )
```

**3f.** `_run_serial_group` signature (lines 768-781) — add `no_capture` parameter:

```python
def _run_serial_group(
    member_ids: list,
    tests_by_id: dict,
    attempts_used: int,
    fixtures,
    resolver,
    result_queue,
    worker_id: int,
    logs_mode: str,
    cov,
    coverage_config,
    strict_teardown: bool = True,
    next_item_after_group=None,
    no_capture: bool = False,
):
```

**3g.** Call site inside `_run_serial_group` (lines 849-862) — pass it through:

```python
            msg = _execute_test(
                tests_by_id[tid],
                tid,
                fixtures,
                resolver,
                result_queue,
                worker_id,
                logs_mode,
                cov,
                coverage_config,
                strict_teardown,
                next_item=member_next,
                no_capture=no_capture,
            )
```

(`next_item=member_next` already exists on its own line right after `strict_teardown,` per the current source — add `no_capture=no_capture,` as a new line right after it.)

**3h.** `run_worker` signature (lines 880-893) — add `no_capture` parameter at the end:

```python
def run_worker(
    test_ids: list,
    modules: list,
    result_queue,
    worker_id: int,
    playwright_config: dict | None = None,
    logs_mode: str = "off",
    coverage_config=None,
    serial_attempts_used: dict | None = None,
    strict_teardown: bool = True,
    full_trace: bool = False,
    options: dict | None = None,
    raw_config: dict | None = None,
    no_capture: bool = False,
):
```

**3i.** Call site at lines 1010-1023 (single-test path) — add `no_capture=no_capture`:

```python
            result_queue.put(
                _execute_test(
                    item,
                    test_id,
                    fixtures,
                    resolver,
                    result_queue,
                    worker_id,
                    logs_mode,
                    cov,
                    coverage_config,
                    strict_teardown,
                    next_item=tests_by_id.get(next_id) if next_id else None,
                    no_capture=no_capture,
                )
            )
```

**3j.** Call site at lines 1031-1044 (serial-group path) — add `no_capture=no_capture`:

```python
        _run_serial_group(
            test_ids[index:end],
            tests_by_id,
            serial_attempts_used.get(item.serial_group, 0),
            fixtures,
            resolver,
            result_queue,
            worker_id,
            logs_mode,
            cov,
            coverage_config,
            strict_teardown,
            next_item_after_group=tests_by_id.get(test_ids[end]) if end < len(test_ids) else None,
            no_capture=no_capture,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_orchestrator_and_worker.CaptureSuppressionTests -v`
Expected: still FAIL at this point — `Orchestrator` doesn't yet unpack the 16th tuple element or pass `no_capture` down to `run_worker` (that's Task 4). Confirm the failure has moved: now it's `ValueError: not enough values to unpack` (or similar) in `orchestrator.py`'s `elif kind == "finished":` unpack, NOT the `TypeError` from Step 2 — that shift confirms Task 3's worker-side change is live and the remaining gap is orchestrator-side (Task 4).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/execution/worker.py tests/test_orchestrator_and_worker.py
git commit -m "feat: worker captures every test attempt unconditionally, tracks console_captured for failures"
```

---

### Task 4: `orchestrator.py` — unpack `console_captured`, thread `no_capture`

**Files:**
- Modify: `src/ctrlrunner/execution/orchestrator.py:396-436` (`__init__` signature), `:455-497` (`__init__` body), `:1127-1151` (`_spawn_slot`), `:1238-1309` (`"finished"` unpack + `add_result` call)

**Interfaces:**
- Consumes: `run_worker(..., no_capture=...)` from Task 3, `Result(..., console_captured=...)` via `JUnitReporter.add_result` from Task 2.
- Produces: `Orchestrator(..., no_capture: bool = False)`.

- [ ] **Step 1: Write the failing test**

This task completes the wiring the Task 3 test (`CaptureSuppressionTests`) already exercises — no new test file needed. Confirm the CURRENT failure mode first:

Run: `python -m unittest tests.test_orchestrator_and_worker.CaptureSuppressionTests -v`
Expected (still failing, from Task 3 Step 4): the `"finished"` tuple unpack in `orchestrator.py` raises because the worker now sends 16 elements but the unpack still expects 15.

- [ ] **Step 2: (same test, no new one to add — proceed to implementation)**

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/execution/orchestrator.py`:

**4a.** `__init__` signature (lines 396-436) — add `no_capture` after `full_trace: bool = False,`:

```python
        full_trace: bool = False,
        no_capture: bool = False,
        import_timeout: float = IMPORT_PHASE_TIMEOUT,
```

**4b.** `__init__` body (after `self.full_trace = full_trace` at line 458):

```python
        self.full_trace = full_trace
        # True disables output buffering entirely (-s / --capture=no):
        # test stdout/stderr/logging is tee'd live to the real stream
        # again, same as before this feature existed.
        self.no_capture = no_capture
```

**4c.** `_spawn_slot`'s spawn-args tuple (lines 1135-1151) — append `self.no_capture` at the end, matching `run_worker`'s new trailing parameter from Task 3:

```python
        proc = ctx.Process(
            target=run_worker,
            args=(
                test_ids,
                modules,
                q,
                worker_id,
                self.playwright_config,
                self.logs_mode,
                self.coverage_config,
                serial_attempts_used,
                self.strict_teardown,
                self.full_trace,
                self.options,
                self.raw_config,
                self.no_capture,
            ),
        )
```

**4d.** `"finished"` unpack (lines 1238-1255) — add `console_captured` as the 16th unpacked name:

```python
        elif kind == "finished":
            (
                _,
                _wid,
                test_id,
                outcome,
                error,
                duration,
                attempts,
                artifacts,
                test_steps,
                extra_props,
                max_attempt_duration,
                assert_details,
                logs,
                captured_warnings,
                started_at,
                console_captured,
            ) = msg
```

**4e.** `add_result` call (lines 1279-1309) — pass it through, right after `started_at=started_at,`:

```python
                warnings=captured_warnings,
                flaky=flaky,
                started_at=started_at,
                console_captured=console_captured,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_orchestrator_and_worker.CaptureSuppressionTests -v`
Expected: PASS.

Then run the full file to check nothing else broke (this file is large/slow — capture to a file, don't tail-truncate, per this repo's convention):

Run: `python -m unittest tests.test_orchestrator_and_worker > /tmp/task4_full.log 2>&1; tail -20 /tmp/task4_full.log`
Expected: `OK` at the end, same test count as before this plan started plus the one new test.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/execution/orchestrator.py
git commit -m "feat: orchestrator threads no_capture to workers and carries console_captured onto Result"
```

---

### Task 5: `projects.py` + `cli.py` — `-s`/`--no-capture` flag, end-to-end threading

**Files:**
- Modify: `src/ctrlrunner/config/projects.py:96-137` (`run_projects` signature), `:255-285` (per-project `Orchestrator(...)` call)
- Modify: `src/ctrlrunner/cli.py:500-505` (near `--full-trace`, add new arg), `:1164` (near `full_trace` resolution, add `no_capture` resolution), `:1330-1340` (`run_projects(...)` call), `:1366-1399` (`Orchestrator(...)` call)

**Interfaces:**
- Consumes: `Orchestrator(..., no_capture=...)` from Task 4.
- Produces: `ctrlrunner -s` / `ctrlrunner --no-capture` on the CLI.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (find the existing test class that builds the run parser via `_build_run_parser()` or parses a full args list end-to-end and inspects resolved config — follow that file's existing style for a flag-resolution test):

```python
class NoCaptureFlagTests(unittest.TestCase):
    def test_no_capture_flag_parses(self):
        parser = _build_run_parser()
        args = parser.parse_args(["-s"])
        self.assertTrue(args.no_capture)

    def test_no_capture_defaults_false(self):
        parser = _build_run_parser()
        args = parser.parse_args([])
        self.assertFalse(args.no_capture)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli.NoCaptureFlagTests -v`
Expected: FAIL with `error: unrecognized arguments: -s` (argparse exits via `SystemExit`) — confirm the test harness surfaces this as a failure, not a hang.

- [ ] **Step 3: Write minimal implementation**

**5a.** In `src/ctrlrunner/cli.py`, add the argument right after the `--full-trace` block (after line 505):

```python
    parser.add_argument(
        "-s",
        "--no-capture",
        action="store_true",
        help="Disable output capturing: test stdout/stderr/logging is echoed "
        "live to the terminal again (pytest's -s). Default: captured output "
        "only appears in a failed test's summary block.",
    )
```

**5b.** Resolve it near `full_trace` (line 1164), right after that line:

```python
    full_trace = bool(args.full_trace) or bool(config.get("full_trace", False))
    no_capture = bool(args.no_capture) or bool(config.get("no_capture", False))
```

**5c.** Thread into the `run_projects(...)` call (lines 1330-1340), right after `full_trace=full_trace,`:

```python
                full_trace=full_trace,
                no_capture=no_capture,
```

**5d.** Thread into the `Orchestrator(...)` call (lines 1366-1399), right after `full_trace=full_trace,`:

```python
            full_trace=full_trace,
            no_capture=no_capture,
```

**5e.** In `src/ctrlrunner/config/projects.py`, add `no_capture` to `run_projects`'s signature (line 130), right after `full_trace=False,`:

```python
    full_trace=False,
    no_capture=False,
```

And thread it into the per-project `Orchestrator(...)` call (lines 255-285), right after `full_trace=full_trace,`:

```python
            full_trace=full_trace,
            no_capture=no_capture,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cli.NoCaptureFlagTests -v`
Expected: PASS.

Run the full CLI test file too: `python -m unittest tests.test_cli > /tmp/task5_cli.log 2>&1; tail -20 /tmp/task5_cli.log`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/cli.py src/ctrlrunner/config/projects.py tests/test_cli.py
git commit -m "feat: add -s/--no-capture CLI flag, threaded through run_projects and Orchestrator"
```

---

### Task 6: Console failure block shows captured output — `reporters.py`

**Files:**
- Modify: `src/ctrlrunner/reporting/reporters.py:95-101`
- Test: `tests/test_reporters.py`

**Interfaces:**
- Consumes: `Result.console_captured` (Task 2), now populated end-to-end (Tasks 3-5).
- Produces: `_summary_lines()` prints `r.console_captured` under a failed test's error text.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reporters.py`, near the existing `SummaryLinesFlakyTests`/`SummaryLinesFileBreakdownTests` classes (match their exact style — check how they build `Result` objects and call `_summary_lines(results, 1.0)`):

```python
class SummaryLinesConsoleCapturedTests(unittest.TestCase):
    def test_console_captured_appears_indented_under_the_failure(self):
        results = [
            Result(
                "t::test_a",
                "failed",
                "AssertionError: boom",
                0.1,
                console_captured="----- Captured stdout -----\nhello",
            )
        ]
        lines = _summary_lines(results, 1.0)
        self.assertIn("      ----- Captured stdout -----", lines)
        self.assertIn("      hello", lines)

    def test_no_console_captured_section_when_none(self):
        results = [Result("t::test_a", "failed", "boom", 0.1)]
        lines = _summary_lines(results, 1.0)
        joined = "\n".join(lines)
        self.assertNotIn("Captured stdout", joined)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_reporters.SummaryLinesConsoleCapturedTests -v`
Expected: FAIL — the first test's `assertIn` fails because `_summary_lines()` doesn't print `console_captured` yet.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/reporting/reporters.py`, extend the failure block in `_summary_lines()` (lines 95-101):

```python
    for r in results:
        if r.outcome == "failed":
            suffix = f"  [{r.case_id}]" if r.case_id else ""
            lines.append(f"  ✗ {r.test_id}{suffix}")
            if r.error:
                lines.extend(f"      {line}" for line in r.error.splitlines())
            if r.console_captured:
                lines.extend(f"      {line}" for line in r.console_captured.splitlines())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_reporters -v`
Expected: all PASS, including the full pre-existing suite (purely additive — `console_captured` defaults to `None`, so every existing `Result(...)` construction in that file is unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/reporting/reporters.py tests/test_reporters.py
git commit -m "feat: console failure summary shows captured stdout/stderr"
```

---

### Task 7: `-v`/`-q` verbosity — `reporters.py`

**Files:**
- Modify: `src/ctrlrunner/reporting/reporters.py:56-67` (`ConsoleReporter`), `:70-123` (`_summary_lines`), `:138-195` (`DotsReporter`, `LineReporter`), `:309-325` (`build_reporters`)
- Test: `tests/test_reporters.py`

**Interfaces:**
- Produces: `ConsoleReporter(verbosity: str = "normal")`; `LineReporter`/`DotsReporter` honor `"normal"`/`"verbose"`/`"quiet"`; `_summary_lines(results, duration, verbosity="normal")`; `build_reporters(names, json_output="results.json", verbosity="normal")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reporters.py`:

```python
class VerbosityTests(unittest.TestCase):
    def test_line_reporter_verbose_prints_a_line_per_test_including_passes(self):
        reporter = LineReporter(verbosity="verbose")
        reporter.on_run_start(2)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            reporter.on_test_start("t::test_a")
            reporter.on_test_end(Result("t::test_a", "passed", None, 0.1))
            reporter.on_test_start("t::test_b")
            reporter.on_test_end(Result("t::test_b", "failed", "boom", 0.1))
        finally:
            sys.stdout = old_stdout
        out = buf.getvalue()
        self.assertIn("PASSED t::test_a", out)
        self.assertIn("FAILED t::test_b", out)

    def test_line_reporter_quiet_prints_nothing_per_test(self):
        reporter = LineReporter(verbosity="quiet")
        reporter.on_run_start(1)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            reporter.on_test_start("t::test_a")
            reporter.on_test_end(Result("t::test_a", "failed", "boom", 0.1))
        finally:
            sys.stdout = old_stdout
        self.assertEqual(buf.getvalue(), "")

    def test_quiet_summary_omits_error_text_and_by_file_table(self):
        results = [
            Result("a.py::test_x", "failed", "boom", 0.1, groups={"file": "a.py"}),
            Result("b.py::test_y", "passed", None, 0.1, groups={"file": "b.py"}),
        ]
        lines = _summary_lines(results, 1.0, verbosity="quiet")
        joined = "\n".join(lines)
        self.assertIn("test_x", joined)
        self.assertNotIn("boom", joined)
        self.assertNotIn("By file", joined)

    def test_invalid_verbosity_raises(self):
        with self.assertRaises(ValueError):
            LineReporter(verbosity="loud")

    def test_build_reporters_threads_verbosity(self):
        reporters = build_reporters(["line"], verbosity="verbose")
        self.assertEqual(reporters[0].verbosity, "verbose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_reporters.VerbosityTests -v`
Expected: FAIL — `TypeError: LineReporter() takes no arguments` (or similar) for most of these, confirming `verbosity` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/reporting/reporters.py`:

**7a.** `ConsoleReporter` base (lines 56-67):

```python
class ConsoleReporter:
    def __init__(self, verbosity: str = "normal"):
        if verbosity not in ("normal", "verbose", "quiet"):
            raise ValueError(
                f"verbosity must be 'normal', 'verbose', or 'quiet', got {verbosity!r}"
            )
        self.verbosity = verbosity

    def on_run_start(self, total: int):
        pass

    def on_test_start(self, test_id: str):
        pass

    def on_test_end(self, result: Result):
        pass

    def on_run_end(self, results: list[Result], duration: float):
        pass
```

**7b.** Add an outcome-word table right above `_SYMBOLS` (before line 126):

```python
_OUTCOME_WORDS = {
    "passed": "PASSED",
    "failed": "FAILED",
    "skipped": "SKIPPED",
    "fixme": "FIXME",
    "expected_failure": "XFAIL",
    "cancelled": "CANCELLED",
    "not_run": "NOT_RUN",
    "quarantined_failure": "QUARANTINED",
}
```

**7c.** `DotsReporter` (lines 138-150):

```python
class DotsReporter(ConsoleReporter):
    """One character per test: '.' pass, 'F' fail, 's' skip, 'f' fixme,
    'x' expected failure (matches the common xfail convention). verbose
    prints a full outcome line per test instead; quiet prints nothing
    per test."""

    def on_test_end(self, result: Result):
        if self.verbosity == "quiet":
            return
        if self.verbosity == "verbose":
            word = _OUTCOME_WORDS.get(result.outcome, result.outcome.upper())
            print(f"{word} {result.test_id}")
            return
        symbol = _custom_status_symbol(result) or _SYMBOLS.get(result.outcome, "?")
        sys.stdout.write(symbol)
        sys.stdout.flush()

    def on_run_end(self, results, duration):
        if self.verbosity != "quiet":
            sys.stdout.write("\n")
        for line in _summary_lines(results, duration, verbosity=self.verbosity):
            print(line)
```

**7d.** `LineReporter` (lines 153-195):

```python
class LineReporter(ConsoleReporter):
    """Overwrites a single progress line as tests run, printing failures
    as they happen below it -- same idea as Playwright TS's 'line'.
    verbose prints a full persisted outcome line per test instead of the
    overwritten progress line; quiet prints nothing per test."""

    def __init__(self, verbosity: str = "normal"):
        super().__init__(verbosity)
        self._total = 0
        self._seen = set()

    def reset(self):
        """Clears per-run progress state. The reporter instance is
        reused across projects in a multi-project run (see cli.py's
        multi-project loop), so without this, `_seen` keeps accumulating
        test_ids from earlier projects and the "[n/total]" progress
        counter overshoots the next project's total (e.g. "[26/25]").
        TODO(cli.py owner): call reporter.reset() at the top of each
        per-project run in the multi-project loop (cli.py:613-616) --
        this file cannot call it itself since it has no visibility into
        the per-project loop boundary.
        """
        self._total = 0
        self._seen = set()

    def on_run_start(self, total: int):
        self._total = total

    def on_test_start(self, test_id: str):
        if self.verbosity in ("quiet", "verbose"):
            return
        self._seen.add(test_id)
        text = f"[{len(self._seen)}/{self._total}] {test_id}"
        sys.stdout.write("\r" + text + " " * max(0, 80 - len(text)))
        sys.stdout.flush()

    def on_test_end(self, result: Result):
        if self.verbosity == "quiet":
            return
        if self.verbosity == "verbose":
            word = _OUTCOME_WORDS.get(result.outcome, result.outcome.upper())
            print(f"{word} {result.test_id}")
            return
        if result.outcome == "failed":
            sys.stdout.write("\n")
            print(f"  ✗ {result.test_id}")

    def on_run_end(self, results, duration):
        if self.verbosity != "quiet":
            sys.stdout.write("\n")
        for line in _summary_lines(results, duration, verbosity=self.verbosity):
            print(line)
```

**7e.** `_summary_lines` (lines 70-123) — add `verbosity` parameter, trim detail when quiet:

```python
def _summary_lines(results, duration, verbosity="normal"):
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(
        1
        for r in results
        if r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")
    )
    expected = sum(1 for r in results if r.outcome == "expected_failure")

    parts = [f"{len(results)} tests", f"{passed} passed", f"{failed} failed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if expected:
        parts.append(f"{expected} expected failures")
    flaky_count = sum(1 for r in results if getattr(r, "flaky", False))
    if flaky_count:
        parts.append(f"{flaky_count} flaky")
    warning_count = sum(len(r.warnings or []) for r in results)
    if warning_count:
        parts.append(f"{warning_count} warning(s) captured")
    lines = [", ".join(parts) + f" ({duration:.2f}s)"]

    for r in results:
        if r.outcome == "failed":
            suffix = f"  [{r.case_id}]" if r.case_id else ""
            lines.append(f"  ✗ {r.test_id}{suffix}")
            if verbosity != "quiet":
                if r.error:
                    lines.extend(f"      {line}" for line in r.error.splitlines())
                if r.console_captured:
                    lines.extend(f"      {line}" for line in r.console_captured.splitlines())

    if verbosity == "quiet":
        return lines

    by_file: dict[str, list] = {}
    for r in results:
        file_key = r.groups.get("file") if r.groups else None
        if file_key is None:
            continue
        by_file.setdefault(file_key, []).append(r)

    if len(by_file) >= 2:
        lines.append("")
        lines.append("By file:")
        name_width = max(len(f) for f in by_file) if by_file else 0
        for file_key in sorted(by_file):
            file_results = by_file[file_key]
            m_total = len(file_results)
            m_passed = sum(1 for r in file_results if r.outcome == "passed")
            m_failed = sum(1 for r in file_results if r.outcome == "failed")
            lines.append(
                f"  {file_key.ljust(name_width)}  {m_total:>3} total  "
                f"{m_passed:>3} passed  {m_failed:>3} failed"
            )

    return lines
```

**7f.** `build_reporters` (lines 309-325) — thread `verbosity` through to `LineReporter`/`DotsReporter`:

```python
def build_reporters(
    names: list[str], json_output: str = "results.json", verbosity: str = "normal"
) -> list[ConsoleReporter]:
    reporters = []
    for name in names:
        if ":" in name:
            reporters.append(_load_custom_reporter(name))
            continue
        cls = REPORTER_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown reporter '{name}'. Available: {', '.join(REPORTER_REGISTRY)}, "
                f"or a custom 'module.path:ClassName' spec"
            )
        if name == "json":
            reporters.append(JsonReporter(json_output))
        else:
            reporters.append(cls(verbosity=verbosity))
    return reporters
```

Add `import io` and `import sys` to `tests/test_reporters.py`'s imports if not already present (check the top of the file first — `sys` is almost certainly already imported given `DotsReporter`/`LineReporter` write to `sys.stdout`; `io` may need adding for `io.StringIO()`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_reporters -v`
Expected: all PASS, full file including every pre-existing test (all existing `_summary_lines(results, 1.0)` two-arg calls keep working since `verbosity` defaults to `"normal"`; all existing `DotsReporter()`/`LineReporter()` no-arg constructions keep working since `verbosity` defaults too).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/reporting/reporters.py tests/test_reporters.py
git commit -m "feat: add -v/-q verbosity support to console reporters"
```

---

### Task 8: `-v`/`-q` CLI flags

**Files:**
- Modify: `src/ctrlrunner/cli.py:130-136` (`_build_reporters_or_exit`), near `--full-trace` block for new args, `:1177` (`reporter_names` resolution area, add verbosity resolution), `:1229-1232` and `:1281` (both `_build_reporters_or_exit` call sites)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_reporters(..., verbosity=...)` from Task 7.
- Produces: `ctrlrunner -v`/`--verbose`, `ctrlrunner -q`/`--quiet`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

Before writing the test, check `tests/test_cli.py` for its established pattern for exercising a `sys.exit(1)` error path end-to-end (e.g. its existing `junit_logs` validation test, or the `report_dir` OSError test) — it patches `sys.argv`, calls `cli.main()`, and asserts `SystemExit`. Follow that pattern exactly:

```python
class VerbosityFlagTests(unittest.TestCase):
    def test_verbose_and_quiet_flags_parse(self):
        parser = _build_run_parser()
        self.assertTrue(parser.parse_args(["-v"]).verbose)
        self.assertTrue(parser.parse_args(["-q"]).quiet)

    def test_verbose_and_quiet_together_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            old_argv = sys.argv
            sys.argv = ["ctrlrunner", str(root), "-v", "-q"]
            try:
                with self.assertRaises(SystemExit) as ctx:
                    cli.main()
                self.assertEqual(ctx.exception.code, 1)
            finally:
                sys.argv = old_argv
```

(Import `cli` and `sys` at the top of the test module if not already present — check first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli.VerbosityFlagTests -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'verbose'`.

- [ ] **Step 3: Write minimal implementation**

**8a.** In `src/ctrlrunner/cli.py`, add the two flags right after the `-s`/`--no-capture` block added in Task 5:

```python
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print a persisted PASSED/FAILED/SKIPPED line for every test "
        "instead of the overwritten progress line.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress per-test output; print only the final totals line and "
        "failure test ids (no error text) unless -r asks for more.",
    )
```

**8b.** Resolve verbosity right after the `no_capture` resolution added in Task 5 (near line 1164-1165):

```python
    if args.verbose and args.quiet:
        print("Error: -v/--verbose and -q/--quiet are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    verbosity = "verbose" if args.verbose else "quiet" if args.quiet else "normal"
```

**8c.** `_build_reporters_or_exit` (lines 130-136) — add `verbosity` parameter:

```python
def _build_reporters_or_exit(names, json_output, verbosity="normal"):
    try:
        return build_reporters(names, json_output=json_output, verbosity=verbosity)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
```

**8d.** Both call sites — single-project (lines 1229-1232):

```python
    console_reporters = _build_reporters_or_exit(
        [n for n in reporter_names if n != "json"] if json_deferred else reporter_names,
        json_output,
        verbosity=verbosity,
    )
```

...and multi-project (line 1281):

```python
        per_project_console_reporters = _build_reporters_or_exit(
            per_project_names, json_output, verbosity=verbosity
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cli -v`
Expected: all PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/cli.py tests/test_cli.py
git commit -m "feat: add -v/--verbose and -q/--quiet CLI flags"
```

---

### Task 9: `-r <chars>` summary control — `reporters.py`

**Files:**
- Modify: `src/ctrlrunner/reporting/reporters.py` (`_summary_lines`, `ConsoleReporter`, `DotsReporter`, `LineReporter`, `build_reporters`)
- Test: `tests/test_reporters.py`

**Interfaces:**
- Produces: `_summary_lines(results, duration, verbosity="normal", report_chars=None)`; `ConsoleReporter(verbosity="normal", report_chars=None)`; `build_reporters(names, json_output=..., verbosity="normal", report_chars=None)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reporters.py`:

```python
class ReportCharsTests(unittest.TestCase):
    def test_default_omitted_matches_todays_output(self):
        results = [Result("t::test_a", "failed", "boom", 0.1)]
        default = _summary_lines(results, 1.0)
        explicit_f = _summary_lines(results, 1.0, report_chars="f")
        self.assertEqual(default, explicit_f)

    def test_f_char_required_for_error_text_under_quiet(self):
        results = [Result("t::test_a", "failed", "boom", 0.1)]
        quiet_no_r = _summary_lines(results, 1.0, verbosity="quiet")
        quiet_with_f = _summary_lines(results, 1.0, verbosity="quiet", report_chars="f")
        self.assertNotIn("boom", "\n".join(quiet_no_r))
        self.assertIn("boom", "\n".join(quiet_with_f))

    def test_s_char_lists_skipped_tests(self):
        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="s")
        joined = "\n".join(lines)
        self.assertIn("test_a", joined)
        self.assertIn("not ready", joined)

    def test_no_s_section_without_the_char(self):
        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="f")
        self.assertNotIn("not ready", "\n".join(lines))

    def test_x_char_lists_expected_failures(self):
        results = [Result("t::test_a", "expected_failure", "known issue", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="x")
        self.assertIn("known issue", "\n".join(lines))

    def test_p_char_lists_passed_test_ids(self):
        results = [Result("t::test_a", "passed", None, 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="p")
        self.assertIn("test_a", "\n".join(lines))

    def test_w_char_lists_warnings(self):
        results = [
            Result(
                "t::test_a",
                "passed",
                None,
                0.1,
                warnings=[{"category": "UserWarning", "message": "be careful"}],
            )
        ]
        lines = _summary_lines(results, 1.0, report_chars="w")
        joined = "\n".join(lines)
        self.assertIn("UserWarning", joined)
        self.assertIn("be careful", joined)

    def test_a_expands_to_all_except_passed(self):
        results = [
            Result("t::test_f", "failed", "boom", 0.1),
            Result("t::test_s", "skipped", "why", 0.1),
        ]
        lines = _summary_lines(results, 1.0, report_chars="a")
        joined = "\n".join(lines)
        self.assertIn("boom", joined)
        self.assertIn("why", joined)

    def test_capital_a_includes_passed(self):
        results = [Result("t::test_p", "passed", None, 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="A")
        self.assertIn("test_p", "\n".join(lines))

    def test_build_reporters_threads_report_chars(self):
        reporters = build_reporters(["line"], report_chars="fs")
        self.assertEqual(reporters[0].report_chars, "fs")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_reporters.ReportCharsTests -v`
Expected: FAIL — `TypeError: _summary_lines() got an unexpected keyword argument 'report_chars'`.

- [ ] **Step 3: Write minimal implementation**

In `src/ctrlrunner/reporting/reporters.py`:

**9a.** `ConsoleReporter.__init__` — add `report_chars`:

```python
class ConsoleReporter:
    def __init__(self, verbosity: str = "normal", report_chars: str | None = None):
        if verbosity not in ("normal", "verbose", "quiet"):
            raise ValueError(
                f"verbosity must be 'normal', 'verbose', or 'quiet', got {verbosity!r}"
            )
        self.verbosity = verbosity
        self.report_chars = report_chars
```

**9b.** `LineReporter.__init__` — thread it through:

```python
    def __init__(self, verbosity: str = "normal", report_chars: str | None = None):
        super().__init__(verbosity, report_chars)
        self._total = 0
        self._seen = set()
```

**9c.** Both reporters' `on_run_end` — pass `report_chars` to `_summary_lines`:

In `DotsReporter.on_run_end`:
```python
        for line in _summary_lines(results, duration, verbosity=self.verbosity, report_chars=self.report_chars):
```

In `LineReporter.on_run_end`:
```python
        for line in _summary_lines(results, duration, verbosity=self.verbosity, report_chars=self.report_chars):
```

**9d.** `_summary_lines` — add the `report_chars` parameter and the new sections. Replace the function body (from Task 7's version) with:

```python
_RCHAR_SECTIONS = (
    ("s", "skipped", ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")),
    ("x", "expected failures", ("expected_failure",)),
)


def _resolve_report_chars(report_chars, verbosity):
    if report_chars is None:
        return "" if verbosity == "quiet" else "f"
    chars = report_chars
    if "A" in chars:
        chars += "fspxw"
    elif "a" in chars:
        chars += "fsxw"
    return chars


def _summary_lines(results, duration, verbosity="normal", report_chars=None):
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(
        1
        for r in results
        if r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")
    )
    expected = sum(1 for r in results if r.outcome == "expected_failure")

    parts = [f"{len(results)} tests", f"{passed} passed", f"{failed} failed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if expected:
        parts.append(f"{expected} expected failures")
    flaky_count = sum(1 for r in results if getattr(r, "flaky", False))
    if flaky_count:
        parts.append(f"{flaky_count} flaky")
    warning_count = sum(len(r.warnings or []) for r in results)
    if warning_count:
        parts.append(f"{warning_count} warning(s) captured")
    lines = [", ".join(parts) + f" ({duration:.2f}s)"]

    chars = _resolve_report_chars(report_chars, verbosity)
    show_failure_detail = "f" in chars

    for r in results:
        if r.outcome == "failed":
            suffix = f"  [{r.case_id}]" if r.case_id else ""
            lines.append(f"  ✗ {r.test_id}{suffix}")
            if show_failure_detail:
                if r.error:
                    lines.extend(f"      {line}" for line in r.error.splitlines())
                if r.console_captured:
                    lines.extend(f"      {line}" for line in r.console_captured.splitlines())

    for char, label, outcomes in _RCHAR_SECTIONS:
        if char in chars:
            matching = [r for r in results if r.outcome in outcomes]
            if matching:
                lines.append("")
                lines.append(f"Short summary ({label}):")
                for r in matching:
                    reason = f": {r.error}" if r.error else ""
                    lines.append(f"  {r.test_id}{reason}")

    if "p" in chars or "P" in chars:
        matching = [r for r in results if r.outcome == "passed"]
        if matching:
            lines.append("")
            lines.append("Short summary (passed):")
            for r in matching:
                lines.append(f"  {r.test_id}")
                if "P" in chars and r.logs:
                    for entry in r.logs:
                        if entry.get("stdout"):
                            lines.extend(
                                f"      {line}" for line in entry["stdout"].splitlines()
                            )

    if "w" in chars:
        warned = [r for r in results if r.warnings]
        if warned:
            lines.append("")
            lines.append("Short summary (warnings):")
            for r in warned:
                for w in r.warnings:
                    lines.append(f"  {r.test_id}: {w.get('category')}: {w.get('message')}")

    if verbosity == "quiet":
        return lines

    by_file: dict[str, list] = {}
    for r in results:
        file_key = r.groups.get("file") if r.groups else None
        if file_key is None:
            continue
        by_file.setdefault(file_key, []).append(r)

    if len(by_file) >= 2:
        lines.append("")
        lines.append("By file:")
        name_width = max(len(f) for f in by_file) if by_file else 0
        for file_key in sorted(by_file):
            file_results = by_file[file_key]
            m_total = len(file_results)
            m_passed = sum(1 for r in file_results if r.outcome == "passed")
            m_failed = sum(1 for r in file_results if r.outcome == "failed")
            lines.append(
                f"  {file_key.ljust(name_width)}  {m_total:>3} total  "
                f"{m_passed:>3} passed  {m_failed:>3} failed"
            )

    return lines
```

`"P"` (passed, with captured output) is handled together with `"p"` below.
Per the design spec, `-rP`'s output comes from `Result.logs` — which is
`--logs`-gated — not from `Result.console_captured`, since passing tests
never populate the latter (that field only exists for failures, to avoid
buffering every passing test's output indefinitely). Without `--logs on`,
`-rP` still lists the passed test id, just with no output beneath it,
identical to plain `-rp`.

```python
    if "p" in chars or "P" in chars:
        matching = [r for r in results if r.outcome == "passed"]
        if matching:
            lines.append("")
            lines.append("Short summary (passed):")
            for r in matching:
                lines.append(f"  {r.test_id}")
                if "P" in chars and r.logs:
                    for entry in r.logs:
                        if entry.get("stdout"):
                            lines.extend(
                                f"      {line}" for line in entry["stdout"].splitlines()
                            )
```

**9e.** `build_reporters` — add `report_chars`:

```python
def build_reporters(
    names: list[str],
    json_output: str = "results.json",
    verbosity: str = "normal",
    report_chars: str | None = None,
) -> list[ConsoleReporter]:
    reporters = []
    for name in names:
        if ":" in name:
            reporters.append(_load_custom_reporter(name))
            continue
        cls = REPORTER_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown reporter '{name}'. Available: {', '.join(REPORTER_REGISTRY)}, "
                f"or a custom 'module.path:ClassName' spec"
            )
        if name == "json":
            reporters.append(JsonReporter(json_output))
        else:
            reporters.append(cls(verbosity=verbosity, report_chars=report_chars))
    return reporters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_reporters -v`
Expected: all PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/reporting/reporters.py tests/test_reporters.py
git commit -m "feat: add -r <chars> summary sections (f/s/x/p/P/w/a/A)"
```

---

### Task 10: `-r <chars>` CLI flag

**Files:**
- Modify: `src/ctrlrunner/cli.py` (near the `-v`/`-q` block from Task 8, `_build_reporters_or_exit`, both call sites)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_reporters(..., report_chars=...)` from Task 9.
- Produces: `ctrlrunner -r fsxpPwaA`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class ReportCharsFlagTests(unittest.TestCase):
    def test_r_flag_parses(self):
        parser = _build_run_parser()
        self.assertEqual(parser.parse_args(["-r", "fs"]).report_chars, "fs")

    def test_unknown_r_char_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            old_argv = sys.argv
            sys.argv = ["ctrlrunner", str(root), "-r", "z"]
            try:
                with self.assertRaises(SystemExit) as ctx:
                    cli.main()
                self.assertEqual(ctx.exception.code, 1)
            finally:
                sys.argv = old_argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli.ReportCharsFlagTests -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'report_chars'`.

- [ ] **Step 3: Write minimal implementation**

**10a.** In `src/ctrlrunner/cli.py`, add the flag right after the `-v`/`-q` block from Task 8:

```python
    parser.add_argument(
        "-r",
        dest="report_chars",
        default=None,
        help="Show extra summary sections: f=failed, s=skipped, x=expected "
        "failures, p=passed, P=passed with captured output, w=warnings, "
        "a=all except passed, A=all. E.g. -rfs. Default: f (matches today's "
        "output).",
    )
```

**10b.** Validate and resolve, right after the verbosity mutual-exclusion check from Task 8:

```python
    _VALID_RCHARS = set("fsxpPwaA")
    report_chars = args.report_chars
    if report_chars is not None and not set(report_chars) <= _VALID_RCHARS:
        bad = "".join(sorted(set(report_chars) - _VALID_RCHARS))
        print(
            f"Error: -r contains unknown character(s) {bad!r}. Valid: f,s,x,p,P,w,a,A",
            file=sys.stderr,
        )
        sys.exit(1)
```

**10c.** `_build_reporters_or_exit` — add `report_chars`:

```python
def _build_reporters_or_exit(names, json_output, verbosity="normal", report_chars=None):
    try:
        return build_reporters(
            names, json_output=json_output, verbosity=verbosity, report_chars=report_chars
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
```

**10d.** Both call sites (from Task 8) — add `report_chars=report_chars`:

```python
    console_reporters = _build_reporters_or_exit(
        [n for n in reporter_names if n != "json"] if json_deferred else reporter_names,
        json_output,
        verbosity=verbosity,
        report_chars=report_chars,
    )
```

```python
        per_project_console_reporters = _build_reporters_or_exit(
            per_project_names, json_output, verbosity=verbosity, report_chars=report_chars
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cli -v`
Expected: all PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/cli.py tests/test_cli.py
git commit -m "feat: add -r <chars> CLI flag with validation"
```

---

### Task 11: `--tb=<style>` — `tb_format.py`

**Files:**
- Modify: `src/ctrlrunner/core/tb_format.py`
- Test: `tests/test_tb_format.py`

**Interfaces:**
- Produces: `set_tb_style(style: str) -> None`; `format_filtered_exc()` honors `auto`/`long`/`native`/`short`/`line`/`no`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tb_format.py`, inside `TbFilterTests` (reuse its existing `_formatted_through_di` helper and `_user_code_that_raises`):

```python
    def test_tb_style_auto_matches_todays_default(self):
        tb_format.set_tb_style("auto")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("user-level boom", text)
        self.assertNotIn("ctrlrunner/core/di.py", text)

    def test_tb_style_long_shows_full_unfiltered_trace(self):
        tb_format.set_tb_style("long")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", text)

    def test_tb_style_native_matches_long(self):
        tb_format.set_tb_style("native")
        self.addCleanup(tb_format.set_tb_style, "auto")
        native_text = self._formatted_through_di(_user_code_that_raises)
        tb_format.set_tb_style("long")
        long_text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", native_text)
        self.assertEqual(native_text.count("di.py"), long_text.count("di.py"))

    def test_tb_style_short_keeps_only_the_last_frame(self):
        tb_format.set_tb_style("short")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("user-level boom", text)
        self.assertNotIn("boom_fixture", text)

    def test_tb_style_line_is_a_single_line_with_file_and_message(self):
        tb_format.set_tb_style("line")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("ValueError: user-level boom", text)

    def test_tb_style_no_returns_empty(self):
        tb_format.set_tb_style("no")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertEqual(text, "")

    def test_full_trace_flag_still_works_when_tb_style_is_auto(self):
        # backward compatibility: --full-trace alone (no --tb) still means
        # "full unfiltered" via the pre-existing set_full_trace() path.
        tb_format.set_full_trace(True)
        tb_format.set_tb_style("auto")
        self.addCleanup(tb_format.set_full_trace, False)
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_tb_format -v`
Expected: FAIL — `AttributeError: module 'ctrlrunner.core.tb_format' has no attribute 'set_tb_style'`.

- [ ] **Step 3: Write minimal implementation**

Replace `src/ctrlrunner/core/tb_format.py` in full:

```python
"""
Failure tracebacks shown to test authors should start at THEIR code,
not at the runner's dispatch machinery -- ctrlrunner's equivalent of
pytest's __tracebackhide__. Filtering is display-only: the
exception object itself is untouched, and --full-trace (or
full_trace=true in ctrlrunner.toml) turns filtering off entirely.
--tb=<style> layers five named styles (auto/long/short/line/no, plus
native as an alias for long) on top of that same filtering -- auto is
exactly today's pre-existing behavior, so a caller that never calls
set_tb_style() sees zero change.

State is module-level per worker process, same reasoning as
annotations.py/context_info.py: a worker runs exactly one test at a
time, and set_full_trace()/set_tb_style() are each called once at
worker startup.
"""

import sys
import traceback
from pathlib import Path

# The ctrlrunner package directory -- any frame whose file lives under it
# is runner machinery (worker dispatch, DI resolution, step contexts),
# not something a test author can act on.
_PKG_DIR = str(Path(__file__).resolve().parent.parent)

_full_trace = False
_tb_style = "auto"


def set_full_trace(enabled: bool) -> None:
    global _full_trace
    _full_trace = bool(enabled)


def set_tb_style(style: str) -> None:
    global _tb_style
    _tb_style = style


def _filter_chain(te) -> None:
    """Drops ctrlrunner-internal frames from every link of the exception
    chain (__cause__/__context__), keeping a link's full stack whenever
    filtering would leave it empty -- an all-internal traceback (a
    runner bug) must stay fully visible, never become a bare message."""
    seen = set()
    while te is not None and id(te) not in seen:
        seen.add(id(te))
        kept = [f for f in te.stack if not f.filename.startswith(_PKG_DIR)]
        if kept:
            te.stack = traceback.StackSummary.from_list(kept)
        te = te.__cause__ or te.__context__


def _trim_to_last_frame(te) -> None:
    """--tb=short: keeps only the single frame closest to where the
    exception was actually raised in each link of the chain -- the rest
    of the call stack is noise once you just want 'which line broke'."""
    seen = set()
    while te is not None and id(te) not in seen:
        seen.add(id(te))
        if te.stack:
            te.stack = traceback.StackSummary.from_list([te.stack[-1]])
        te = te.__cause__ or te.__context__


def _format_line(te) -> str:
    """--tb=line: pytest's single-line style, 'file:lineno: ExcType: msg'."""
    exc_only = "".join(te.format_exception_only()).strip()
    if not te.stack:
        return exc_only
    frame = te.stack[-1]
    return f"{frame.filename}:{frame.lineno}: {exc_only}"


def format_filtered_exc() -> str:
    """traceback.format_exc() with ctrlrunner-internal frames removed
    (or reshaped further, depending on the active --tb style). Call
    from an except block, exactly like format_exc()."""
    exc = sys.exc_info()[1]
    if exc is None:
        return ""

    style = _tb_style
    if style == "auto":
        style = "long" if _full_trace else "filtered"
    elif style == "native":
        style = "long"

    if style == "no":
        return ""

    try:
        te = traceback.TracebackException.from_exception(exc)
        if style == "long":
            return "".join(te.format())
        _filter_chain(te)
        if style == "short":
            _trim_to_last_frame(te)
            return "".join(te.format())
        if style == "line":
            return _format_line(te)
        return "".join(te.format())  # style == "filtered" (today's default)
    except Exception:
        # Formatting must never mask the original failure.
        return traceback.format_exc()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_tb_format -v`
Expected: all PASS, full file (every pre-existing test in `TbFilterTests` never calls `set_tb_style`, so `_tb_style` stays at its default `"auto"`, which resolves to `"filtered"` unless `set_full_trace(True)` was called — identical to today's behavior).

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/core/tb_format.py tests/test_tb_format.py
git commit -m "feat: add --tb style support (auto/long/short/line/no/native) to tb_format"
```

---

### Task 12: `--tb` CLI flag + threading through worker startup

**Files:**
- Modify: `src/ctrlrunner/cli.py` (near `--full-trace`, near `full_trace`/`no_capture` resolution, both `run_projects`/`Orchestrator` call sites)
- Modify: `src/ctrlrunner/execution/orchestrator.py:396-436`, `:455-497`, `:1127-1151`
- Modify: `src/ctrlrunner/execution/worker.py:880-893` (`run_worker` signature), `:909` (call `set_tb_style`)
- Modify: `src/ctrlrunner/config/projects.py:96-137`, `:255-285`
- Test: `tests/test_cli.py`, `tests/test_orchestrator_and_worker.py`

**Interfaces:**
- Consumes: `tb_format.set_tb_style()` from Task 11.
- Produces: `ctrlrunner --tb short` end-to-end.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TbStyleFlagTests(unittest.TestCase):
    def test_tb_flag_parses(self):
        parser = _build_run_parser()
        self.assertEqual(parser.parse_args(["--tb", "short"]).tb, "short")

    def test_tb_defaults_to_none(self):
        parser = _build_run_parser()
        self.assertIsNone(parser.parse_args([]).tb)
```

Add to `tests/test_orchestrator_and_worker.py`, a sibling of `CaptureSuppressionTests`:

```python
class TbStyleThreadingTests(unittest.TestCase):
    def test_tb_style_short_reaches_the_worker_and_trims_the_traceback(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_fails():\n"
                "    assert 1 == 2\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, tb_style="short")
            reporter = orch.run()

        result = reporter.results[0]
        self.assertEqual(result.error.strip().count("\n"), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli.TbStyleFlagTests tests.test_orchestrator_and_worker.TbStyleThreadingTests -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'tb'` for the CLI tests, and `TypeError: Orchestrator.__init__() got an unexpected keyword argument 'tb_style'` for the orchestrator test.

- [ ] **Step 3: Write minimal implementation**

**12a.** `src/ctrlrunner/cli.py` — add the flag right after `--full-trace` (before the `-s`/`--no-capture` block from Task 5):

```python
    parser.add_argument(
        "--tb",
        choices=["auto", "long", "short", "line", "no", "native"],
        default=None,
        help="Traceback style: auto (filtered, default), long (full "
        "unfiltered), short (last frame only), line (one line), no "
        "(suppress body). native is accepted for pytest muscle memory and "
        "behaves identically to long. Overrides --full-trace when both are "
        "given.",
    )
```

**12b.** Resolve it right after the existing `full_trace` resolution (line 1164):

```python
    full_trace = bool(args.full_trace) or bool(config.get("full_trace", False))
    tb_style = args.tb or config.get("tb")
    if tb_style is None:
        tb_style = "long" if full_trace else "auto"
```

**12c.** Thread into both call sites, right after `full_trace=full_trace,` (from Task 5's edits to the same two spots):

`run_projects(...)`:
```python
                full_trace=full_trace,
                no_capture=no_capture,
                tb_style=tb_style,
```

`Orchestrator(...)`:
```python
            full_trace=full_trace,
            no_capture=no_capture,
            tb_style=tb_style,
```

**12d.** `src/ctrlrunner/config/projects.py` — `run_projects` signature, right after `no_capture=False,` (from Task 5):

```python
    full_trace=False,
    no_capture=False,
    tb_style="auto",
```

Per-project `Orchestrator(...)` call, right after `no_capture=no_capture,`:

```python
            full_trace=full_trace,
            no_capture=no_capture,
            tb_style=tb_style,
```

**12e.** `src/ctrlrunner/execution/orchestrator.py` — `__init__` signature, right after `no_capture: bool = False,` (from Task 4):

```python
        full_trace: bool = False,
        no_capture: bool = False,
        tb_style: str = "auto",
        import_timeout: float = IMPORT_PHASE_TIMEOUT,
```

`__init__` body, right after `self.no_capture = no_capture` (from Task 4):

```python
        self.no_capture = no_capture
        # --tb=<style>; "auto" (default) means "defer to self.full_trace",
        # exactly matching tb_format.format_filtered_exc()'s own resolution.
        self.tb_style = tb_style
```

`_spawn_slot`'s spawn-args tuple, right after `self.no_capture,` (from Task 4):

```python
                self.no_capture,
                self.tb_style,
            ),
        )
```

**12f.** `src/ctrlrunner/execution/worker.py` — `run_worker` signature, right after `no_capture: bool = False,` (from Task 3):

```python
    no_capture: bool = False,
    tb_style: str = "auto",
):
```

Call to `tb_format.set_full_trace` (line 909) — add the new call right after it:

```python
    tb_format.set_full_trace(full_trace)
    tb_format.set_tb_style(tb_style)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cli.TbStyleFlagTests tests.test_orchestrator_and_worker.TbStyleThreadingTests -v`
Expected: PASS.

Run both full files (capture to a file, don't tail-truncate):

Run: `python -m unittest tests.test_cli tests.test_orchestrator_and_worker > /tmp/task12_full.log 2>&1; tail -20 /tmp/task12_full.log`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add src/ctrlrunner/cli.py src/ctrlrunner/execution/orchestrator.py src/ctrlrunner/execution/worker.py src/ctrlrunner/config/projects.py tests/test_cli.py tests/test_orchestrator_and_worker.py
git commit -m "feat: add --tb CLI flag, threaded through Orchestrator and worker startup"
```

---

### Task 13: Full regression pass + manual smoke test

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full test suite exactly as CI does**

Run: `python -m unittest discover -s tests > /tmp/task13_full_suite.log 2>&1; tail -40 /tmp/task13_full_suite.log`
Expected: `OK`, with the total test count higher than this plan's starting point by the number of new tests added across Tasks 1-12.

- [ ] **Step 2: Confirm zero default-output change (except the intended capture fix)**

Run a real suite with no new flags, exactly as a user would today:

```bash
mkdir -p /tmp/ctrlrunner_smoke && cat > /tmp/ctrlrunner_smoke/test_demo.py <<'EOF'
from ctrlrunner import test

@test()
def test_pass_quiet():
    print("should not appear on the terminal")

@test()
def test_fail_noisy():
    print("should appear under this failure")
    assert 1 == 2
EOF
python -m ctrlrunner /tmp/ctrlrunner_smoke
```

Expected: `test_pass_quiet`'s print does NOT appear anywhere in the terminal output; `test_fail_noisy`'s failure block DOES include `should appear under this failure` under its traceback. Everything else (progress line format, summary totals line, exit code) matches today's shape exactly.

- [ ] **Step 3: Manually exercise each new flag once**

```bash
python -m ctrlrunner /tmp/ctrlrunner_smoke -v
python -m ctrlrunner /tmp/ctrlrunner_smoke -q
python -m ctrlrunner /tmp/ctrlrunner_smoke -s
python -m ctrlrunner /tmp/ctrlrunner_smoke -r A
python -m ctrlrunner /tmp/ctrlrunner_smoke --tb short
python -m ctrlrunner /tmp/ctrlrunner_smoke --tb line
python -m ctrlrunner /tmp/ctrlrunner_smoke --tb no
python -m ctrlrunner /tmp/ctrlrunner_smoke -v -q  # expect: usage error, exit 1
```

Expected: `-v` prints `PASSED`/`FAILED` lines for both tests; `-q` prints only the totals line + failure id; `-s` shows BOTH tests' print output live as they run (including the passing one); `-r A` adds "Short summary (passed)" listing `test_pass_quiet`; `--tb short`/`--tb line`/`--tb no` visibly shrink the failure's traceback; the last command exits 1 with the mutual-exclusion error message.

- [ ] **Step 4: Update graphify's graph**

Run: `graphify update .`

- [ ] **Step 5: Remove the temporary smoke directory**

```bash
rm -rf /tmp/ctrlrunner_smoke
```

(No commit for this task — it's verification-only. If Step 1 or Step 3 surfaces a regression, fix it as a new TDD cycle appended to the relevant earlier task's files before considering the plan complete.)
