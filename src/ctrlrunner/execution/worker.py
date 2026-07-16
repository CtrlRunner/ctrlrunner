"""
Runs inside a spawned child process. Executes its assigned tests
sequentially and streams progress back to the orchestrator over a
multiprocessing.Queue -- this is what lets the parent detect a hang
(no "started" message progressing past its deadline) and hard-kill via
the Job Object, instead of relying on an in-process signal/thread that
can itself get stuck.
"""

import contextlib
import hashlib
import importlib
import importlib.util
import inspect
import os
import sys
import time
import warnings as warnings_module
from contextlib import ExitStack, nullcontext
from pathlib import Path

from ..core import annotations, assert_introspect, context_info, log_capture, tb_format
from ..core import steps as steps_module
from ..core.di import FixtureResolver
from ..core.registry import get_fixtures, get_tests
from ..core.steps import step

ARTIFACTS_ROOT = Path("ctrlrunner-artifacts")


def module_name_for_path(path) -> str:
    """The sys.modules DICT KEY for `path` -- a hash of its resolved
    absolute path, deliberately NOT the dotted name this module is
    otherwise given (see import_module_by_path). Two projects that each
    happen to contain e.g. tests/test_x.py at the same relative
    location used to collide on the same dotted sys.modules key
    ("tests.test_x") -- project B's force_reload=True would then
    importlib.reload() project A's module (its __spec__/file still
    point at A's file), silently running project A's tests as if they
    were project B's. Hashing
    the resolved path instead gives every distinct file its own
    sys.modules slot regardless of how many projects/roots share the
    same relative directory layout."""
    resolved = str(Path(path).resolve())
    digest = hashlib.sha1(resolved.encode()).hexdigest()[:16]
    return f"_ctrlrunner_mod_{digest}"


def import_module_by_path(path, dotted_name: str, force_reload: bool = False) -> str:
    """Imports the file at `path`, giving the resulting module object a
    human-readable `__name__` of `dotted_name` (test ids are built from
    func.__module__, so this is what keeps test ids/JUnit classnames
    exactly as readable as before) -- but stores it in sys.modules
    under module_name_for_path(path)'s hash-of-resolved-path key
    instead of under `dotted_name` itself. That's what fixes it: two
    different files that happen to produce the SAME
    `dotted_name` (two projects with the same relative layout) still
    get separate sys.modules entries, so a force_reload targeting one
    can never touch the other's module object.

    Importing an already-imported path again is a no-op unless
    force_reload=True, in which case the SAME module object is
    re-executed in place (the same mechanism importlib.reload() uses),
    re-running its @test/@fixture decorators against a freshly-cleared
    registry. Returns the sys.modules key used."""
    key = module_name_for_path(path)
    existing = sys.modules.get(key)
    if existing is not None:
        if force_reload:
            # Not an assert: `python -O` would strip it, and a missing
            # spec/loader here must fail loudly, not silently skip the
            # reload and leave a stale module registered.
            if existing.__spec__ is None or existing.__spec__.loader is None:
                raise RuntimeError(f"Cannot force-reload {path}: module has no import spec/loader.")
            existing.__spec__.loader.exec_module(existing)
        return key
    spec = importlib.util.spec_from_file_location(dotted_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    # Without a dotted-name alias, user code
    # that does `import tests.test_x` re-executes the file into a SECOND
    # module object with its own globals -- the classic importlib-mode
    # double-import. setdefault keeps the split intact: if the dotted name is
    # already taken (another root's file, or the user imported first),
    # it is never clobbered.
    if sys.modules.setdefault(dotted_name, module) is module:
        parent_name, _, child = dotted_name.rpartition(".")
        if parent_name:
            # `import a.b; a.b.x` resolves a.b as an ATTRIBUTE of the
            # package -- normally set by the import machinery, which the
            # alias bypasses. Best-effort; a package that fails to
            # import just means the attribute shortcut isn't available.
            with contextlib.suppress(Exception):
                parent = importlib.import_module(parent_name)
                if not hasattr(parent, child):
                    setattr(parent, child, module)
    return key


def _safe_test_dir(test_id: str) -> str:
    return test_id.replace("::", "__").replace("[", "_").replace("]", "").replace("/", "_")


def _call_on_failure(on_failure, value, prefix, outcome):
    """Calls on_failure with (value, prefix) for older 2-arg callbacks,
    or (value, prefix, outcome) for callbacks that accept the outcome --
    lets built-in fixtures (trace/screenshot modes) make outcome-aware
    decisions (e.g. "retain-on-failure") without breaking any existing
    2-arg on_failure callback."""
    try:
        accepts_outcome = len(inspect.signature(on_failure).parameters) >= 3
    except (TypeError, ValueError):
        accepts_outcome = False
    args = (value, prefix, outcome) if accepts_outcome else (value, prefix)
    return on_failure(*args)


def capture_artifacts(
    test_id: str,
    attempt: int,
    resolved_all: dict,
    fixtures: dict,
    artifacts_root: Path = ARTIFACTS_ROOT,
    only_always: bool = False,
    outcome: str = "failed",
) -> list:
    """Calls on_failure for every resolved fixture that defines one.
    When only_always=True (test passed), only fixtures with
    always_capture=True are called -- e.g. a trace saved for every test,
    not just failures. Never raises: a broken capture callback must not
    affect the test result, it should just silently produce no artifact
    for that fixture."""
    captured = []
    test_dir = artifacts_root / _safe_test_dir(test_id) / f"attempt-{attempt}"
    for name, value in resolved_all.items():
        fx = fixtures.get(name)
        if fx is None or fx.on_failure is None:
            continue
        if only_always and not fx.always_capture:
            continue
        try:
            test_dir.mkdir(parents=True, exist_ok=True)
            prefix = str(test_dir / name)
            with step(f"capture:{name}"):
                path = _call_on_failure(fx.on_failure, value, prefix, outcome)
            if path:
                captured.append(str(path))
        except Exception:
            pass  # a broken capture callback must never affect the test result
    return captured


# Playwright's expect() appends the matched element's full Aria snapshot
# to the AssertionError text (playwright/_impl/_assertions.py, fed by
# received.ariaSnapshot from the server). Matched textually so the worker
# gains no Playwright dependency.
_ARIA_SNAPSHOT_MARKER = "\nAria snapshot:\n"
ARIA_SNAPSHOT_FILENAME = "aria-snapshot.yml"


def _extract_aria_snapshot(tb, test_id, attempt, artifacts_root: Path = ARTIFACTS_ROOT):
    """Splits a Playwright Aria snapshot off the end of a failure
    traceback and writes it to the test's artifact dir. Returns
    (possibly trimmed tb, artifact path or None). Never raises: failing
    to save the snapshot must not affect failure reporting -- the tb is
    returned untrimmed in that case."""
    if _ARIA_SNAPSHOT_MARKER not in tb:
        return tb, None
    try:
        head, snapshot = tb.rsplit(_ARIA_SNAPSHOT_MARKER, 1)
        test_dir = artifacts_root / _safe_test_dir(test_id) / f"attempt-{attempt}"
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / ARIA_SNAPSHOT_FILENAME
        with step("capture:aria-snapshot"):
            path.write_text(snapshot.rstrip() + "\n", encoding="utf-8")
        trimmed = f"{head.rstrip()}\n(Aria snapshot attached as {ARIA_SNAPSHOT_FILENAME})"
        return trimmed, str(path)
    except Exception:
        return tb, None


def _trim_aria_snapshot_from_steps(step_dicts):
    """Step errors carry the raw exception text (steps.py records
    f"{type}: {exc}"), which for a Playwright expect() failure includes
    the full Aria snapshot -- already saved as an artifact by
    _extract_aria_snapshot, so keep step errors short. Recurses into
    children; returns the same list for inline use."""
    for s in step_dicts:
        err = s.get("error")
        if err and _ARIA_SNAPSHOT_MARKER in err:
            head = err.split(_ARIA_SNAPSHOT_MARKER, 1)[0]
            s["error"] = f"{head.rstrip()}\n(Aria snapshot attached as {ARIA_SNAPSHOT_FILENAME})"
        _trim_aria_snapshot_from_steps(s.get("children") or [])
    return step_dicts


def _finish_failure(tb, test_id, attempt, resolved_all, fixtures):
    """Shared outcome/artifact logic for a failed attempt -- used by
    both the AssertionError and generic Exception handlers so that
    AssertionError-only introspection doesn't require duplicating this
    block."""
    expected = annotations.get_expected_failure()
    if expected["active"]:
        return "expected_failure", expected["description"] or tb, [], False
    tb, snapshot_path = _extract_aria_snapshot(tb, test_id, attempt)
    artifacts = capture_artifacts(test_id, attempt, resolved_all, fixtures, outcome="failed")
    if snapshot_path:
        artifacts.append(snapshot_path)
    return "failed", tb, artifacts, True


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
):
    """Runs one test -- fixture resolution, the per-test retry loop,
    artifact/log capture -- and RETURNS its 13-field "finished" tuple
    instead of putting it on the queue. Individual tests put it
    immediately; serial groups buffer non-final group attempts so a
    re-run test never emits two "finished" messages ("started" IS still
    emitted per attempt from inside this function -- that's what resets
    the orchestrator's watchdog deadline)."""
    module_name = test_id.split("::")[0]
    resolver.begin_module(module_name)
    # A module switch just tore down the PREVIOUS module's fixtures --
    # any errors from that belong to the run, not to this (unrelated)
    # test, so flush them before this test's own teardown drain below.
    for name, tb in resolver.drain_teardown_errors():
        result_queue.put(("session_teardown_failed", worker_id, name, tb))

    autouse_names = [n for n, fx in fixtures.items() if fx.autouse and n not in item.params]
    names_to_resolve = item.params + autouse_names

    max_attempts = (item.retries or 0) + 1
    first_attempt_start = time.time()
    attempt = 0
    # near_timeout must compare a SINGLE attempt's own duration
    # to its own per-attempt timeout budget, not the sum across
    # every retry -- the orchestrator's watchdog deadline is reset
    # fresh per attempt (see the "started" message below), so a
    # retried test that used, say, 50% of its budget on each of
    # two attempts previously got flagged "came close to
    # hard-kill" off a 100%+ AGGREGATE duration despite no single
    # attempt ever being close.
    max_attempt_duration = 0.0
    # Only wrap each attempt in its own
    # "attempt N" step when retries are actually configured for this
    # test -- the overwhelmingly common case (no retries) keeps
    # today's exact flat step-tree shape, no extra nesting layer
    # nobody asked for. Decided once, upfront, from item.retries
    # alone, not from whether a retry actually ends up happening
    # this particular run, so the tree's shape stays predictable.
    wrap_attempts = max_attempts > 1

    # begin_test() now runs ONCE per test, not once per attempt --
    # previously every retry wiped out the previous attempt's step
    # tree entirely; now all attempts accumulate into one tree
    # (each under its own "attempt N" step when wrap_attempts),
    # so a flaky test's full retry history is visible in one place,
    # not just its final attempt.
    steps_module.begin_test()
    captured_logs: list = []
    all_warnings: list = []
    teardown_failed = False

    if cov is not None and coverage_config is not None and coverage_config.contexts:
        cov.switch_context(test_id)

    while True:
        attempt += 1
        attempt_start = time.time()
        context_info.begin_test(test_id, attempt)
        # A fresh "started" message per attempt resets the orchestrator's
        # watchdog deadline, so a retried test gets its full timeout again
        # on each attempt rather than sharing one deadline across all of them.
        result_queue.put(("started", worker_id, test_id, attempt_start))

        function_stack = ExitStack()
        outcome, error, artifacts, assert_details = "passed", None, [], None
        resolved_all = {}
        capture_done = False
        annotations.begin_test(result_queue, worker_id, test_id)
        # param(xfail=...) rides the existing runtime fail() pipeline --
        # re-applied per attempt because begin_test() above resets it.
        if item.expected_failure:
            annotations.fail(
                True,
                item.expected_failure.get("description"),
                item.expected_failure.get("strict", True),
            )

        attempt_cm = step(f"attempt {attempt}") if wrap_attempts else nullcontext()
        log_cm = log_capture.capture_logs() if logs_mode != "off" else nullcontext(None)
        # record=True collects every warning raised during the
        # attempt (they surface in reports/summary instead of stderr);
        # "always" so repeat warnings from loops are not deduped away.
        warn_cm = warnings_module.catch_warnings(record=True)
        with attempt_cm, log_cm as captured, warn_cm as wlist:
            warnings_module.simplefilter("always")
            try:
                try:
                    # param(skip=...) skips before fixtures are resolved.
                    if item.skip_marker:
                        raise annotations.SkipTest(item.skip_marker.get("description"))
                    values, resolved_all = resolver.resolve(
                        names_to_resolve, function_stack, item.fixture_param_overrides
                    )
                    kwargs = {k: v for k, v in values.items() if k in item.params}
                    with step("test body"):
                        item.func(**kwargs)
                except annotations.SkipTest as e:
                    outcome, error = "skipped", e.description
                except annotations.FixmeTest as e:
                    outcome, error = "fixme", e.description
                # Populated for ANY AssertionError, including ones that
                # `_finish_failure` below turns into "expected_failure"
                # (a fail()-annotated test) rather than "failed" -- this
                # is intentional: the data is still correct and useful,
                # we just don't gate its capture on the eventual outcome.
                except AssertionError as e:
                    assert_details = assert_introspect.build_assert_details(e)
                    outcome, error, artifacts, capture_done = _finish_failure(
                        tb_format.format_filtered_exc(), test_id, attempt, resolved_all, fixtures
                    )
                except Exception:
                    outcome, error, artifacts, capture_done = _finish_failure(
                        tb_format.format_filtered_exc(), test_id, attempt, resolved_all, fixtures
                    )
                else:
                    expected = annotations.get_expected_failure()
                    if expected["active"] and expected["strict"]:
                        outcome = "failed"
                        error = (
                            f"Unexpected pass while marked fail(): {expected['description'] or ''}"
                        )
                        # strict=False -> stays "passed"; flagged via property below

                # Fixtures with always_capture=True (e.g. "save a trace for
                # every test") still get their artifact even when the test
                # didn't hit the on_failure path above. This MUST happen
                # before function_stack.close() below -- Playwright
                # objects (context/page) are already closed once their own
                # generator teardown runs, so capturing from them after
                # that point fails with "Target ... has been closed".
                if not capture_done and outcome not in ("skipped", "fixme"):
                    artifacts = capture_artifacts(
                        test_id,
                        attempt,
                        resolved_all,
                        fixtures,
                        only_always=True,
                        outcome=outcome,
                    )
            finally:
                function_stack.close()

        # A teardown that raised must not produce a silent
        # false-pass. function_stack.close() above ran function-scoped
        # teardowns; anything they raised is waiting in the resolver.
        td_errors = resolver.drain_teardown_errors()
        if td_errors:
            teardown_failed = True
            td_text = "\n\n".join(f"Fixture '{n}' teardown failed:\n{tb}" for n, tb in td_errors)
            if outcome == "passed" and strict_teardown:
                outcome = "failed"
                error = f"Test passed but fixture teardown failed:\n\n{td_text}"
            elif outcome == "failed":
                error = f"{error or ''}\n\nAdditionally, fixture teardown failed:\n\n{td_text}"

        for w in wlist[: max(0, 100 - len(all_warnings))]:
            all_warnings.append(
                {
                    "attempt": attempt,
                    "category": w.category.__name__,
                    "message": str(w.message),
                    "filename": w.filename,
                    "lineno": w.lineno,
                }
            )

        if captured is not None:
            keep_logs = logs_mode == "on" or (
                logs_mode == "only-on-failure" and outcome == "failed"
            )
            if keep_logs:
                captured_logs.append({"attempt": attempt, **captured})

        max_attempt_duration = max(max_attempt_duration, time.time() - attempt_start)

        # expected_failure is final by design (the test is *supposed* to
        # fail) -- retrying it can't improve the outcome, only burn
        # attempts. A strict xfail that unexpectedly passes reports
        # "failed" and still retries as usual.
        if outcome in ("skipped", "fixme", "expected_failure"):
            break  # never retried
        if outcome == "passed" or attempt >= max_attempts:
            break

    duration = time.time() - first_attempt_start
    attempt_steps = steps_module.collect_steps()
    final_logs = captured_logs or None

    # Runtime record_property() values from the final attempt ride
    # the same extra_props channel the unexpected_pass flag already
    # uses -- merged into Result.properties orchestrator-side.
    extra_properties = context_info.collect_properties()
    final_expected = annotations.get_expected_failure()
    if outcome == "passed" and final_expected["active"] and not final_expected["strict"]:
        extra_properties["unexpected_pass"] = "true"
    if teardown_failed:
        extra_properties["teardown_failed"] = "true"

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
    )


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
):
    """Runs a @test_class(serial=True) group: members in definition
    order; a failure restarts the WHOLE group from its first test while
    group-retry budget remains, and on the final attempt skips every
    member after the failure instead.

    The one-finished-per-test-id contract: non-final attempts buffer
    their finished tuples and discard them on failure; only the final
    attempt (or a fully-passing earlier one, flushed at the end)
    reaches the queue. With no retries configured budget is 1, every
    attempt is final, and behavior is streaming -- exactly the plain
    path plus skip-on-fail.

    attempts_used: group attempts already consumed on a previous worker
    (a hard-killed attempt counts -- the orchestrator tracks this and
    passes it through run_worker), so a requeued group never exceeds
    its total budget.

    Session/module fixtures are NOT re-created between group attempts
    inside one worker (same process, same resolver); only a
    kill-requeued attempt gets a fresh process and fresh fixtures.
    """
    first = tests_by_id[member_ids[0]]
    class_label = first.class_name or first.serial_group
    budget = max(1, first.serial_retries + 1 - attempts_used)

    for offset in range(1, budget + 1):
        g_attempt = attempts_used + offset
        final = offset == budget
        buffered = []
        failed_at = None
        for tid in member_ids:
            if failed_at is not None:
                if not final:
                    break  # restart the whole group on the next attempt
                # skip-on-fail, final attempt only ("started" first keeps
                # every consumer's start/end pairing intact)
                skip_started_at = time.time()
                result_queue.put(("started", worker_id, tid, skip_started_at))
                result_queue.put(
                    (
                        "finished",
                        worker_id,
                        tid,
                        "skipped",
                        f"skipped: earlier test '{failed_at}' in serial group "
                        f"'{class_label}' failed",
                        0.0,
                        g_attempt,
                        [],
                        [],
                        {},
                        0.0,
                        None,
                        None,
                        None,
                        skip_started_at,
                    )
                )
                continue
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
            )
            # members report the GROUP attempt number (a member that
            # passed on group attempt 2 reports attempts=2 even though
            # it never failed itself -- Playwright semantics)
            msg = msg[:6] + (g_attempt,) + msg[7:]
            if final:
                result_queue.put(msg)
            else:
                buffered.append(msg)
            if msg[3] == "failed":
                # only "failed" fails the group -- skipped/fixme/
                # expected_failure members don't trigger skip-on-fail
                failed_at = tid
        if failed_at is None:
            for msg in buffered:
                result_queue.put(msg)
            return


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
):
    # Put THIS process in its own new process group (pgid == its
    # own pid) before anything else -- in particular before any
    # Playwright browser/Node helper gets launched below. This has to
    # happen from inside the worker itself: POSIX only allows changing
    # a *different* process's pgid before that process has exec'd, and
    # by the time the parent's JobObject.assign() runs (right after
    # Process.start() returns) this interpreter has already exec'd.
    # JobObject.terminate() on POSIX kills this whole group via
    # os.killpg(), which is what actually reaches orphaned
    # browser/node processes -- a plain os.kill(pid, SIGKILL) only
    # kills this one PID.
    if sys.platform != "win32":
        with contextlib.suppress(Exception):
            os.setpgid(0, 0)

    tb_format.set_full_trace(full_trace)

    if playwright_config:
        from ..playwright import playwright_fixtures

        playwright_fixtures.configure(**playwright_config)

    # Coverage instrumentation MUST start before any of this worker's
    # assigned test modules are imported below -- coverage.py can only
    # see execution that happens after cov.start(), and Python runs all
    # module-level code (imports, class/def statements, decorators,
    # module-level constants) at import time, not at test-call time. If
    # this block ran after the import loop, every module-level statement
    # in the code under test would be invisible to coverage.py and only
    # function bodies actually invoked during the test loop would be
    # recorded, producing a badly-undercounted percentage.
    cov = None
    if coverage_config is not None and coverage_config.enabled:
        from coverage import Coverage

        cov = Coverage(
            data_file=os.path.join(coverage_config.data_dir, ".coverage"),
            data_suffix=True,
            source=coverage_config.source,
        )
        cov.start()

    for path, dotted_name in modules:
        import_module_by_path(path, dotted_name)

    # Signal "imports are done, real test execution starts now" --
    # the orchestrator holds off starting the first test's own timeout
    # clock until this arrives, using a separate generous import-phase
    # budget instead. Without this, a heavy-deps/cold-AV-scanned import
    # that takes longer than (first_test_timeout + restart buffer)
    # gets the healthy worker hard-killed, requeued, and it dies again
    # identically on the replacement -- a cascade of false timeouts
    # with zero real test failures.
    result_queue.put(("ready", worker_id, time.time()))

    tests_by_id = {t.id: t for t in get_tests()}
    fixtures = get_fixtures()
    resolver = FixtureResolver()

    serial_attempts_used = serial_attempts_used or {}
    index = 0
    while index < len(test_ids):
        test_id = test_ids[index]
        item = tests_by_id[test_id]
        if item.serial_group is None:
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
                )
            )
            index += 1
            continue
        # Maximal consecutive run of the same serial group (contiguity
        # is guaranteed by unit construction in the orchestrator).
        end = index
        while end < len(test_ids) and tests_by_id[test_ids[end]].serial_group == item.serial_group:
            end += 1
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
        )
        index = end

    if cov is not None:
        cov.stop()
        cov.save()

    resolver.close_session()
    # Module/session-scoped teardowns run after the last test,
    # so their failures can't be pinned on any single result -- stream
    # them as run-level events instead of dropping them.
    for name, tb in resolver.drain_teardown_errors():
        result_queue.put(("session_teardown_failed", worker_id, name, tb))
    result_queue.put(("worker_done", worker_id))
