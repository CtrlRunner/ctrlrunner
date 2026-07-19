"""
Runs inside a spawned child process. Executes its assigned tests
sequentially and streams progress back to the orchestrator over a
multiprocessing.Queue -- this is what lets the parent detect a hang
(no "started" message progressing past its deadline) and hard-kill via
the Job Object, instead of relying on an in-process signal/thread that
can itself get stuck.

Also where the eight per-test pytest_runtest_*/exception_interact
equivalents live -- ctrlrunner_runtest_logstart/setup/call/makereport/
exception_interact/teardown/logreport/logfinish, conftest-discovered
once per worker (see run_worker's import loop) and invoked from
_execute_test at the matching points in the attempt lifecycle. Unlike
ctrlrunner_configure/ctrlrunner_sessionfinish (config/addoption.py,
invoked from cli.py -- once, main process, around the whole run), these
fire once per test ATTEMPT, inside whichever worker process runs it.
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

from ..core import (
    annotations,
    assert_introspect,
    context_info,
    di,
    hookcompat,
    log_capture,
    tb_format,
)
from ..core import steps as steps_module
from ..core.di import FixtureResolver
from ..core.registry import get_fixtures, get_tests
from ..core.steps import step

ARTIFACTS_ROOT = Path("ctrlrunner-artifacts")

# ctrlrunner_runtest_logstart/setup/teardown/logreport -- the
# pytest_runtest_* equivalents. Collected once in run_worker() (this
# worker's own conftest import pass, right alongside ctrlrunner_addoption
# module-level get_option seeding) and read directly by _execute_test()
# below -- same per-process-global convention core/options.py's
# _options and playwright_fixtures.py's _config already use, so no
# extra parameter threading through _execute_test/_run_serial_group's
# two call sites.
_runtest_logstart_hooks: list = []
_runtest_setup_hooks: list = []
_runtest_teardown_hooks: list = []
_runtest_logreport_hooks: list = []
_runtest_call_hooks: list = []
_runtest_makereport_hooks: list = []
_runtest_exception_interact_hooks: list = []
_runtest_logfinish_hooks: list = []
_warning_recorded_hooks: list = []
_assertrepr_compare_hooks: list = []
_fixture_setup_hooks: list = []
_fixture_post_finalizer_hooks: list = []

_ALL_RUNTEST_HOOK_LISTS = (
    ("ctrlrunner_runtest_logstart", "_runtest_logstart_hooks"),
    ("ctrlrunner_runtest_setup", "_runtest_setup_hooks"),
    ("ctrlrunner_runtest_call", "_runtest_call_hooks"),
    ("ctrlrunner_runtest_makereport", "_runtest_makereport_hooks"),
    ("ctrlrunner_exception_interact", "_runtest_exception_interact_hooks"),
    ("ctrlrunner_runtest_teardown", "_runtest_teardown_hooks"),
    ("ctrlrunner_runtest_logreport", "_runtest_logreport_hooks"),
    ("ctrlrunner_runtest_logfinish", "_runtest_logfinish_hooks"),
    ("ctrlrunner_warning_recorded", "_warning_recorded_hooks"),
    ("ctrlrunner_assertrepr_compare", "_assertrepr_compare_hooks"),
    ("ctrlrunner_fixture_setup", "_fixture_setup_hooks"),
    ("ctrlrunner_fixture_post_finalizer", "_fixture_post_finalizer_hooks"),
)

# The pytest-shaped config/session backing item.config/item.session in
# per-test hooks -- built once per worker in run_worker() from the raw
# ctrlrunner.toml dict that rode the spawn args. Same per-process-global
# convention as core/options.py's _options.
_hook_config = hookcompat.Config({})
_hook_session = hookcompat.Session(config=_hook_config)


def _call_runtest_hooks(hooks, available: dict, propagate=()):
    """Calls each per-test hook with the pluggy-style NAMED subset of
    `available` it declares (see hookcompat.bind_hook_args), isolating
    unexpected exceptions so a broken hook can never affect the test
    it's observing -- same 'never silent, never fatal' rule
    capture_artifacts() follows for a broken on_failure callback. Two
    kinds ALWAYS escape: `propagate` lists per-call-site types (the
    setup hook passes SkipTest/FixmeTest so skip()/fixme() from a hook
    controls the outcome), and CompatibilityError -- a hook touching
    unported pytest machinery (or declaring an unknown parameter name)
    must fail the test loudly, with the recommendation in the failure
    text, not degrade to a warning. @hookimpl(tryfirst=/trylast=)
    ordering is honored via hookcompat.sort_hooks."""
    for hook in hookcompat.sort_hooks(hooks):
        try:
            hook(**hookcompat.bind_hook_args(hook, available))
        except propagate:
            raise
        except hookcompat.CompatibilityError as exc:
            # Returned, not raised: three of the four call sites sit
            # outside the outcome handlers, where a raise would crash
            # the whole worker instead of failing THIS test.
            return exc
        except Exception as exc:
            warnings_module.warn(
                f"{hook.__name__} raised {type(exc).__name__}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    return None


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
    #
    # conftest.py is the one exception: skip the alias entirely when
    # dotted_name is bare (no dot -- always true for a conftest.py that
    # sits directly in root_path.parent, see _dotted_module_name).
    # discover_conftests can legitimately surface several conftest.py
    # files at different directory levels in one run, only one of which
    # should ever answer a test file's plain `from conftest import x`
    # -- and that choice belongs to sys.path order (which
    # discover_conftests sets up root-highest-priority), not to
    # whichever conftest.py we happen to import_module_by_path first.
    # A bare setdefault("conftest", ...) here would permanently and
    # arbitrarily claim that sys.modules slot for THIS file, and since
    # Python's import machinery checks sys.modules before ever
    # consulting sys.path, that pre-seeding silently overrides the
    # sys.path ordering no matter how carefully it's built. There is
    # also no `import a.b; a.b.x` package-attribute case to preserve
    # here -- a bare (dot-less) dotted_name has no parent package for
    # that mechanism to apply to in the first place.
    is_bare_conftest = "." not in dotted_name and Path(path).name == "conftest.py"
    if not is_bare_conftest and sys.modules.setdefault(dotted_name, module) is module:
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
    affect the test result, it should just produce no artifact for that
    fixture -- but it does emit a RuntimeWarning (surfaced in the run
    summary and Result.warnings) so a misconfigured on_failure isn't
    silently invisible."""
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
        except Exception as exc:
            # A broken capture callback must never affect the test result,
            # but failing silently makes a misconfigured on_failure (e.g. the
            # wrong fixture value type) nearly impossible to notice -- the
            # step tree records it too, but that's easy to miss. A warning
            # surfaces it in the run summary and Result.warnings without
            # touching the outcome.
            warnings_module.warn(
                f"on_failure for fixture '{name}' raised {type(exc).__name__}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
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
    next_item=None,
    no_capture: bool = False,
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
    console_captured = None

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
        # The pytest-shaped per-test object (item.get_closest_marker,
        # .nodeid, .tags, .module, .cls, .config, .session, ...) built
        # fresh per attempt so .attempt is always current. See
        # core/hookcompat.py.
        hook_item = hookcompat.Item(
            test_id,
            attempt,
            tags=item.tags,
            properties=item.properties,
            func=item.func,
            cls_name=item.class_name,
            config=_hook_config,
            session=_hook_session,
        )
        # A CompatibilityError from any hook fails THIS test loudly,
        # with the recommendation in the failure text -- deferred into
        # the try block below where failure handling lives.
        pending_compat_error = _call_runtest_hooks(
            _runtest_logstart_hooks, {"nodeid": test_id, "location": hook_item.location}
        )

        function_stack = ExitStack()
        outcome, error, artifacts, assert_details = "passed", None, [], None
        resolved_all = {}
        capture_done = False
        # The "call" phase timing/exception for ctrlrunner_runtest_makereport
        # /exception_interact's CallInfo -- defaults cover a test that
        # skips before ever reaching the call hooks/test body (call_start
        # == call_stop, no exception). Only AssertionError/generic
        # Exception populate call_excinfo: skip()/fixme() aren't
        # "failures" in the screenshot-on-failure sense these two hooks
        # exist for.
        call_start = call_stop = time.time()
        call_excinfo = None
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
        log_cm = log_capture.capture_logs(forward_live=no_capture)
        # record=True collects every warning raised during the
        # attempt (they surface in reports/summary instead of stderr);
        # "always" so repeat warnings from loops are not deduped away.
        warn_cm = warnings_module.catch_warnings(record=True)
        with attempt_cm, log_cm as captured, warn_cm as wlist:
            warnings_module.simplefilter("always")
            try:
                try:
                    if pending_compat_error is not None:
                        raise pending_compat_error
                    # param(skip=...) skips before fixtures are resolved.
                    if item.skip_marker:
                        raise annotations.SkipTest(item.skip_marker.get("description"))
                    # skip()/fixme() raised by a setup hook must control
                    # the test's outcome exactly as from the test body --
                    # the SkipTest/FixmeTest handlers below catch them.
                    # (fail() needs no propagation: it sets state, not
                    # an exception.)
                    setup_compat_error = _call_runtest_hooks(
                        _runtest_setup_hooks,
                        {"item": hook_item},
                        propagate=(annotations.SkipTest, annotations.FixmeTest),
                    )
                    if setup_compat_error is not None:
                        raise setup_compat_error
                    values, resolved_all = resolver.resolve(
                        names_to_resolve, function_stack, item.fixture_param_overrides
                    )
                    # pytest's item.funcargs -- live resolved fixtures,
                    # visible to the teardown hook (still open there).
                    hook_item.funcargs = resolved_all
                    kwargs = {k: v for k, v in values.items() if k in item.params}
                    call_start = time.time()
                    # Notification hook (matches pytest_runtest_call): an
                    # exception here fails the test exactly like one from
                    # the test body itself -- no isolation, unlike the
                    # other per-test hooks.
                    for call_hook in _runtest_call_hooks:
                        call_hook(**hookcompat.bind_hook_args(call_hook, {"item": hook_item}))
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
                    call_excinfo = hookcompat.ExceptionInfo(e)
                    assert_details = assert_introspect.build_assert_details(e)
                    outcome, error, artifacts, capture_done = _finish_failure(
                        tb_format.format_filtered_exc(), test_id, attempt, resolved_all, fixtures
                    )
                    # ctrlrunner_assertrepr_compare's extra explanation
                    # lines (pytest_assertrepr_compare), appended to the
                    # failure text -- assert_details already carries them
                    # if a hook returned any.
                    if assert_details and assert_details.get("assertrepr_compare"):
                        error = "{}\n\n{}".format(
                            error, "\n".join(assert_details["assertrepr_compare"])
                        )
                except Exception as e:
                    call_excinfo = hookcompat.ExceptionInfo(e)
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
                call_stop = time.time()

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
                # Teardown hooks fire for EVERY outcome (pytest calls
                # pytest_runtest_teardown even for skipped items), and
                # before function_stack.close() so live fixture state is
                # still reachable. `nextitem` carries pytest(-xdist)
                # semantics: the next test in THIS worker's batch, None
                # for the last one; trim_args lets a hook declare just
                # (item).
                next_hook_item = None
                if next_item is not None:
                    next_hook_item = hookcompat.Item(
                        next_item.id,
                        1,  # hasn't run yet -- its first attempt is upcoming
                        tags=next_item.tags,
                        properties=next_item.properties,
                        func=next_item.func,
                        cls_name=next_item.class_name,
                        config=_hook_config,
                        session=_hook_session,
                    )
                teardown_compat_error = _call_runtest_hooks(
                    _runtest_teardown_hooks, {"item": hook_item, "nextitem": next_hook_item}
                )
                if teardown_compat_error is not None:
                    compat_text = f"CompatibilityError in teardown hook: {teardown_compat_error}"
                    outcome = "failed"
                    error = f"{error}\n\n{compat_text}" if error else compat_text
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
            if captured.get("stdout"):
                report_sections.append(("Captured stdout call", captured["stdout"]))
            if captured.get("stderr"):
                report_sections.append(("Captured stderr call", captured["stderr"]))
        # item.add_report_section(when, key, content) -- pytest's own
        # "Captured {key} {when}" title convention.
        for when, key, content in hook_item._report_sections:
            report_sections.append((f"Captured {key} {when}", content))

        report = hookcompat.TestReport(
            test_id,
            attempt,
            outcome,
            error,
            duration=time.time() - attempt_start,
            location=hook_item.location,
            sections=report_sections,
            user_properties=list(item.properties.items()),
            keywords=hook_item.keywords,
        )

        # ctrlrunner_runtest_makereport: fires once ctrlrunner's single
        # consolidated report for this attempt is ready (not per-phase,
        # like pytest's three calls -- see docs/hooks.md's documented
        # delta). A hook that returns a truthy, non-None value REPLACES
        # the report exception_interact/logreport receive -- the classic
        # `item.rep_call = report` pattern works too, since Item is a
        # plain mutable object a hook body can freely attach to.
        call_info = hookcompat.CallInfo(
            "call", call_excinfo, start=call_start, stop=call_stop, duration=call_stop - call_start
        )
        for makereport_hook in hookcompat.sort_hooks(_runtest_makereport_hooks):
            try:
                override = hookcompat.run_makereport_hook(
                    makereport_hook, {"item": hook_item, "call": call_info}, report
                )
            except hookcompat.CompatibilityError as exc:
                override = None
                compat_text = f"CompatibilityError in makereport hook: {exc}"
                outcome = "failed"
                error = f"{error}\n\n{compat_text}" if error else compat_text
            except Exception as exc:
                override = None
                warnings_module.warn(
                    f"{makereport_hook.__name__} raised {type(exc).__name__}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            if override is not None:
                report = override

        # ctrlrunner_exception_interact: pytest's screenshot/DOM-dump
        # hook, fired only for an actual failure -- live excinfo via
        # call_info.excinfo (None if the failure came from teardown
        # only, not the call phase itself).
        if outcome == "failed":
            interact_compat_error = _call_runtest_hooks(
                _runtest_exception_interact_hooks,
                {"node": hook_item, "call": call_info, "report": report},
            )
            if interact_compat_error is not None:
                compat_text = (
                    f"CompatibilityError in exception_interact hook: {interact_compat_error}"
                )
                error = f"{error}\n\n{compat_text}" if error else compat_text

        logreport_compat_error = _call_runtest_hooks(_runtest_logreport_hooks, {"report": report})
        if logreport_compat_error is not None:
            compat_text = f"CompatibilityError in logreport hook: {logreport_compat_error}"
            outcome = "failed"
            error = f"{error}\n\n{compat_text}" if error else compat_text

        logfinish_compat_error = _call_runtest_hooks(
            _runtest_logfinish_hooks, {"nodeid": test_id, "location": hook_item.location}
        )
        if logfinish_compat_error is not None:
            compat_text = f"CompatibilityError in logfinish hook: {logfinish_compat_error}"
            outcome = "failed"
            error = f"{error}\n\n{compat_text}" if error else compat_text

        # session.shouldstop/.shouldfail: real and settable (see
        # hookcompat.Session) -- any per-test hook this attempt ran
        # could have set one. Checked once per attempt (pytest checks
        # between items in its runtestloop; ctrlrunner has no
        # setup/call/teardown split to distinguish the two, so both
        # request the same cancellation). Sending this more than once
        # is harmless -- the orchestrator's cancel path is idempotent.
        _stop_reason = _hook_session.shouldstop or _hook_session.shouldfail
        if _stop_reason:
            result_queue.put(("shouldstop_requested", worker_id, str(_stop_reason)))

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
            # pytest_warning_recorded's `when` is one of
            # "config"/"collect"/"runtest" -- ctrlrunner only ever
            # captures warnings during test execution, so this is
            # always "runtest" (documented delta: config/collect-phase
            # warnings aren't captured at all today).
            # warning_message is the full warnings.WarningMessage (w
            # itself), matching pytest's real hookspec -- .category/
            # .filename/.lineno/.message are all real, not just w.message
            # (the bare warning instance).
            _call_runtest_hooks(
                _warning_recorded_hooks,
                {
                    "warning_message": w,
                    "when": "runtest",
                    "nodeid": test_id,
                    "location": (w.filename, w.lineno, test_id.split("::")[-1]),
                },
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
        console_captured,
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
    next_item_after_group=None,
    no_capture: bool = False,
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
            # nextitem within a serial group: the next member in
            # definition order; the last member's nextitem is whatever
            # follows the whole group in this worker's batch.
            member_pos = member_ids.index(tid)
            if member_pos + 1 < len(member_ids):
                member_next = tests_by_id[member_ids[member_pos + 1]]
            else:
                member_next = next_item_after_group
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
    options: dict | None = None,
    raw_config: dict | None = None,
    no_capture: bool = False,
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

    # Seed ctrlrunner_addoption values BEFORE the module-import loop
    # below -- module-level get_option(...) in test/conftest files must
    # see real values (this worker is a spawn'd fresh interpreter; the
    # dict rode the pickled args tuple). Always called: None resets the
    # store, so a stale value can never leak between configurations.
    from ..core.options import set_options

    set_options(options)

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

    global _hook_config, _hook_session
    for _, list_name in _ALL_RUNTEST_HOOK_LISTS:
        globals()[list_name] = []
    _hook_config = hookcompat.Config(raw_config)
    _hook_session = hookcompat.Session(config=_hook_config)
    make_parametrize_id_hooks: list = []
    generate_tests_hooks: list = []
    for path, dotted_name in modules:
        key = import_module_by_path(path, dotted_name)
        if path.name != "conftest.py":
            continue
        module = sys.modules[key]
        for hook_name, list_name in _ALL_RUNTEST_HOOK_LISTS:
            hook = getattr(module, hook_name, None)
            if hook is not None:
                globals()[list_name].append(hook)
        # Registered incrementally (conftests are always imported before
        # test modules -- see discover_and_import) so each is active
        # before any LATER test file's @parametrize/@test decoration
        # runs in this worker.
        hook = getattr(module, "ctrlrunner_make_parametrize_id", None)
        if hook is not None:
            make_parametrize_id_hooks.append(hook)
            from ..core.registry import set_make_parametrize_id_hooks

            set_make_parametrize_id_hooks(make_parametrize_id_hooks, _hook_config)
        hook = getattr(module, "ctrlrunner_generate_tests", None)
        if hook is not None:
            generate_tests_hooks.append(hook)
            from ..core.registry import set_generate_tests_hooks

            set_generate_tests_hooks(generate_tests_hooks, _hook_config)

    # Best-effort session.testscollected for per-test hooks: every test
    # this worker's imported modules registered (the full run total lives
    # in the orchestrator; a worker only ever sees its own imports).
    _hook_session.testscollected = len(get_tests())
    # assert_introspect.py lives in core/, which worker.py (execution/)
    # already imports -- registering the hooks THERE (rather than the
    # reverse) avoids a circular import.
    assert_introspect.set_assertrepr_compare_hooks(_assertrepr_compare_hooks, _hook_config)
    di.set_fixture_hooks(_fixture_setup_hooks, _fixture_post_finalizer_hooks, _hook_config)

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
            next_id = test_ids[index + 1] if index + 1 < len(test_ids) else None
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
            next_item_after_group=tests_by_id.get(test_ids[end]) if end < len(test_ids) else None,
            no_capture=no_capture,
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
