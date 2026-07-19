import contextlib
import logging
import multiprocessing as mp
import queue as queue_module
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config.tag_registry import (
    TagRegistry,
    TagValidationError,
    format_unregistered_tags_warning,
    validate_tags,
)
from ..core import hookcompat
from ..core.registry import get_tests
from ..core.selection import select_tests
from ..reporting.collection_summary import format_collection_summary
from ..reporting.events import EventEnvelope, result_to_public_dict
from ..reporting.grouping import DEFAULT_DIMENSIONS, GroupingDimension, compute_groups
from ..reporting.log_redaction import redact_log_entries
from ..reporting.reporter import JUnitReporter
from .fail_policy import FailPolicyState
from .jobobject import JobObject
from .quarantine import QuarantineConfig
from .sharding import lookup_median_durations
from .worker import import_module_by_path, run_worker
from .worker_budget import (
    Batch,
    ExecUnit,
    assign_worker_groups,
    build_units,
    group_aware_shard,
    order_units,
)

_log = logging.getLogger(__name__)

# Same formula already validated in the pytest-timeout/xdist world:
# watchdog_threshold = per_test_timeout + worker_restart_buffer.
# The buffer covers interpreter start + fixture setup time for the
# *replacement* worker spawned after a hard-kill, not the original one.
WORKER_RESTART_BUFFER = 5.0

# _finalize_slot's ceiling for waiting on a terminated-but-not-yet-
# reaped worker process. Windows process teardown (antivirus scanning
# every process exit, OS handle release) can take far longer under CI
# load than POSIX's near-instant SIGKILL reap. proc.join() already
# returns the instant the process actually exits, so this only bounds
# the rare slow-exit case -- it never slows the normal fast-exit path.
# Short poll interval (rather than one join(timeout=CEILING) call) so
# a run-level cancel can still cut the wait short instead of blocking
# the scheduler loop for the full ceiling.
FINALIZE_JOIN_CEILING = 10.0
FINALIZE_JOIN_POLL_INTERVAL = 0.5

# A generous, fixed upper bound for "still importing the suite's
# modules", used as the watchdog deadline from spawn until the worker's
# "ready" message arrives -- entirely separate from any per-test
# timeout. Suite import time (heavy deps, cold-AV-scanned Windows CI)
# must never be charged against the first test's own configured
# timeout budget; that coupling used to cause cascading false
# hard-kills (a healthy worker killed, requeued onto a fresh worker
# that pays the same import cost and dies again identically).
IMPORT_PHASE_TIMEOUT = 60.0

# How long the scheduler sleeps when no slot produced a message this
# pass -- short enough that timeout detection stays responsive, long
# enough not to busy-spin.
_POLL_INTERVAL = 0.05


def discover_conftests(root: str):
    """Finds every conftest.py that applies to `root`: every ANCESTOR
    directory's conftest.py (walking upward to a .git boundary or the
    filesystem root -- same convention as migrate/config_migrator.py's
    find_pyproject, so a run scoped to one subdirectory still picks up
    shared setup registered at the project root) PLUS every conftest.py
    at or below root itself. Returned shallowest first overall (farthest
    ancestor, ..., nearest ancestor, root's own, ..., deepest
    descendant), so shared fixtures defined at a higher directory level
    are registered before ones in subdirectories override or extend
    them. Test files never need to import these explicitly -- same
    convenience as pytest's conftest.py, but it's just a plain import
    list, not a plugin hook. Returns Path objects (not module names) --
    see import_module_by_path in worker.py for how each is actually
    imported.

    root may also be a single file (pytest-style `ctrlrunner tests/test_x.py`)
    -- conftest discovery then runs over its containing directory, same as
    if that directory had been passed as root."""
    root_path = Path(root).resolve()
    if root_path.is_file():
        root_path = root_path.parent
    if str(root_path.parent) not in sys.path:
        sys.path.insert(0, str(root_path.parent))

    ancestors: list[Path] = []
    directory = root_path.parent
    while True:
        candidate = directory / "conftest.py"
        if candidate.is_file():
            ancestors.append(candidate)
        if (directory / ".git").exists() or directory.parent == directory:
            break
        directory = directory.parent
    # Walked nearest -> farthest. sys.path.insert(0, ...) means whatever
    # is inserted LAST ends up at sys.path[0] (highest priority), so to
    # put the farthest ancestor (the project root, typically) at
    # sys.path[0] we must insert it LAST -- i.e. insert in the SAME
    # nearest -> farthest order the walk already produced. (A prior
    # version of this loop reversed that order, which put the NEAREST
    # ancestor at sys.path[0] instead -- backwards from the intent
    # below, and the exact bug behind a `from conftest import X` in a
    # test file resolving to a closer, unrelated conftest.py instead of
    # the project root's.) Highest priority for plain `import conftest`
    # -style statements a test file might use to reach a *non*-fixture
    # name defined there.
    #
    # ALWAYS promote to sys.path[0], even if the directory is already
    # present somewhere else in sys.path -- a dev/editable install (`uv
    # run`, `pip install -e .`) can already have the project root on
    # sys.path via a .pth file or similar, just far down the list
    # (after site-packages/.venv entries). A plain "insert only if
    # absent" guard would see it already present and leave it at that
    # low-priority position, silently defeating this whole ordering
    # scheme -- remove any existing occurrence first so the insert
    # actually re-establishes priority instead of being a no-op.
    for ancestor_dir in [a.parent for a in ancestors]:
        path_str = str(ancestor_dir)
        while path_str in sys.path:
            sys.path.remove(path_str)
        sys.path.insert(0, path_str)
    ancestors.reverse()  # shallowest (farthest) first, to match the return-order contract

    descendants = sorted(root_path.rglob("conftest.py"), key=lambda p: len(p.parts))
    return ancestors + descendants


def discover_modules(root: str):
    """root may be a directory (globbed for test_*.py) or a single file
    (pytest-style `ctrlrunner tests/test_x.py`), in which case only that
    file is returned -- Path.rglob() on a file path always yields
    nothing, which used to make a single-file root silently collect 0
    tests instead of running the file."""
    root_path = Path(root).resolve()
    if root_path.is_file():
        if str(root_path.parent.parent) not in sys.path:
            sys.path.insert(0, str(root_path.parent.parent))
        return [root_path]
    if str(root_path.parent) not in sys.path:
        sys.path.insert(0, str(root_path.parent))
    return sorted(root_path.rglob("test_*.py"))


def _dotted_module_name(root_path: Path, path: Path) -> str:
    """The human-readable dotted name (e.g. "suite.test_a") a file gets
    as its module's __name__ -- this is what test ids/JUnit classnames
    are built from (func.__module__), so it's computed exactly as
    before: relative to root_path.parent. It is NOT what a file is
    keyed under in sys.modules (see worker.import_module_by_path) --
    that's a deliberate split, kept entirely separate from this name.

    `path` is normally a descendant of root_path.parent (a test file or
    a conftest.py at/below root), for which relative_to() always
    succeeds -- unchanged from before. discover_conftests now also
    surfaces ANCESTOR conftest.py files (above root_path.parent, up to
    a .git boundary), which relative_to() can't express as a subpath;
    for those, fall back to <containing dir name>.conftest -- still
    unique enough for sys.modules aliasing purposes, and ancestor
    conftest.py files are never test files, so there's no existing test
    id/JUnit classname convention to preserve for them."""
    try:
        rel = path.relative_to(root_path.parent).with_suffix("")
    except ValueError:
        rel = Path(path.parent.name) / path.with_suffix("").name
    return ".".join(rel.parts)


# Collection-phase conftest hooks (docs/hooks.md), discovered while
# importing conftests in discover_and_import(_multi) below and consumed
# by Orchestrator.run() (and, for ignore_collect, by the discovery
# functions themselves). Module-level per-process state, same convention
# as worker.py's _runtest_*_hooks; reset at the start of each discovery
# pass so multi-project force_reload runs never see stale hooks.
_COLLECTION_HOOK_NAMES = (
    "ctrlrunner_ignore_collect",
    "ctrlrunner_itemcollected",
    "ctrlrunner_collection_modifyitems",
    "ctrlrunner_collection_finish",
    "ctrlrunner_deselected",
)
_conftest_hooks: dict = {}
_make_parametrize_id_hooks: list = []
_generate_tests_hooks: list = []


def _register_conftest_hooks(module_key: str, raw_config: dict | None = None) -> None:
    module = sys.modules[module_key]
    for name in _COLLECTION_HOOK_NAMES:
        fn = getattr(module, name, None)
        if fn is not None:
            _conftest_hooks.setdefault(name, []).append(fn)
    # Registered incrementally, same reasoning as worker.py's own copy
    # of this pattern: conftests import before test modules (see
    # discover_and_import below), so each is active before any LATER
    # test file's @parametrize/@test decoration runs in THIS process --
    # which matters here specifically, since the ids Orchestrator.run()
    # selects/schedules by come from THIS (main-process) import, not
    # the worker's later re-import of the same files.
    fn = getattr(module, "ctrlrunner_make_parametrize_id", None)
    if fn is not None:
        from ..core.registry import set_make_parametrize_id_hooks

        _make_parametrize_id_hooks.append(fn)
        set_make_parametrize_id_hooks(_make_parametrize_id_hooks, hookcompat.Config(raw_config))
    fn = getattr(module, "ctrlrunner_generate_tests", None)
    if fn is not None:
        from ..core.registry import set_generate_tests_hooks

        _generate_tests_hooks.append(fn)
        set_generate_tests_hooks(_generate_tests_hooks, hookcompat.Config(raw_config))


def _apply_ignore_collect(module_paths: list, raw_config: dict | None) -> list:
    """ctrlrunner_ignore_collect(collection_path, config) -- pytest's
    firstresult semantics: the first hook returning non-None decides;
    True excludes the file from collection entirely (its module is
    never imported)."""
    hooks = _conftest_hooks.get("ctrlrunner_ignore_collect")
    if not hooks:
        return module_paths
    config = hookcompat.Config(raw_config)
    kept = []
    for p in module_paths:
        available = {"collection_path": p, "config": config}
        ignored = False
        for hook in hooks:
            result = hook(**hookcompat.bind_hook_args(hook, available))
            if result is not None:
                ignored = bool(result)
                break
        if not ignored:
            kept.append(p)
    return kept


def discover_and_import(
    root: str, force_reload: bool = False, raw_config: dict | None = None
) -> list:
    """Runs conftest + test module discovery and imports everything --
    the shared first step of a real run (Orchestrator.run()) and any
    discovery-only action (--list, UI Mode's RunController). Importing
    an already-imported module is normally a no-op (sys.modules cache),
    which is fine for a single run -- but when multiple projects share
    an overlapping tests_dir in the same CLI invocation, the registry
    gets cleared between projects (see projects.py/run_projects()) and
    a plain re-import would then register nothing for the second
    project. force_reload=True re-executes an already-imported module
    in place instead, re-running its @test/@fixture decorators against
    the freshly-cleared registry.

    Returns a list of (path, dotted_name) entries, threaded through to
    worker.import_module_by_path -- each file keeps its familiar dotted
    __name__ (and hence test id) but is keyed in sys.modules under a
    hash of its own resolved path, not that dotted name. That split
    fixes it: two projects with the same relative file layout (e.g.
    both containing tests/test_x.py) used to collide on the same
    dotted sys.modules key, so project B's force_reload could reload
    project A's module."""
    root_path = Path(root).resolve()
    _conftest_hooks.clear()
    _make_parametrize_id_hooks.clear()
    _generate_tests_hooks.clear()
    conftest_entries = [(p, _dotted_module_name(root_path, p)) for p in discover_conftests(root)]
    for p, dotted in conftest_entries:
        _register_conftest_hooks(
            import_module_by_path(p, dotted, force_reload=force_reload), raw_config
        )
    module_paths = _apply_ignore_collect(discover_modules(root), raw_config)
    module_entries = [(p, _dotted_module_name(root_path, p)) for p in module_paths]
    for p, dotted in module_entries:
        import_module_by_path(p, dotted, force_reload=force_reload)
    return conftest_entries + module_entries


def discover_and_import_multi(
    roots: list[str], force_reload: bool = False, raw_config: dict | None = None
) -> list:
    """Same as discover_and_import, but merges discovery across several
    root directories (a project's tests_dir can list more than one),
    de-duplicating modules reachable from more than one root. Dedup is
    keyed on each file's own resolved absolute path, not on the dotted
    name computed relative to its root -- two DIFFERENT files that
    happen to produce the same relative dotted name (the same class
    of collision) must never be treated as "the same module already
    seen" and silently dropped."""
    _conftest_hooks.clear()
    _make_parametrize_id_hooks.clear()
    _generate_tests_hooks.clear()
    seen = set()
    all_entries = []
    for root in roots:
        root_path = Path(root).resolve()
        # Conftests first (registering collection hooks), then modules
        # filtered through ignore_collect -- same two-phase order as
        # discover_and_import.
        for p in discover_conftests(root):
            resolved = p.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            dotted = _dotted_module_name(root_path, p)
            all_entries.append((p, dotted))
            _register_conftest_hooks(
                import_module_by_path(p, dotted, force_reload=force_reload), raw_config
            )
        for p in _apply_ignore_collect(discover_modules(root), raw_config):
            resolved = p.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            dotted = _dotted_module_name(root_path, p)
            all_entries.append((p, dotted))
            import_module_by_path(p, dotted, force_reload=force_reload)
    return all_entries


def _chunk(items, n):
    chunks = [[] for _ in range(n)]
    for i, item in enumerate(items):
        chunks[i % n].append(item)
    return [c for c in chunks if c]


def _trim_units(units, keep_ids) -> list:
    """The units of a killed slot, trimmed to the tests actually being
    requeued -- fully-finished units drop out, partially-run ones keep
    only their unfinished members (in original order)."""
    keep = set(keep_ids)
    trimmed = []
    for unit in units:
        kept = tuple(tid for tid in unit.test_ids if tid in keep)
        if kept:
            trimmed.append(
                ExecUnit(
                    key=unit.key,
                    kind=unit.kind,
                    test_ids=kept,
                    serial_retries=unit.serial_retries,
                )
            )
    return trimmed


@dataclass
class _WorkerSlot:
    """One live worker process and everything the scheduler needs to
    supervise it: its Job Object (for hard-kill of the whole process
    tree), its result queue, which tests it still owes results for, and
    its current watchdog deadline."""

    worker_id: int
    proc: mp.process.BaseProcess
    job: JobObject
    queue: "mp.Queue"
    remaining: list
    deadline: float
    killed: bool = False
    crashed: bool = False
    done: bool = False
    # The Batch this slot is running: unit boundaries (for
    # requeue-after-kill) and the worker-constraint label it was
    # sharded under (so a requeued leftover stays inside its group's
    # budget).
    units: list = field(default_factory=list)
    group: str | None = None
    dedicated: bool = False
    # The test the worker most recently sent "started" for -- under
    # serial-group buffering, remaining[0] is NOT necessarily the test
    # that hung (earlier members may have passed unemitted).
    current_test: str | None = None
    # True from spawn until the worker's "ready" message arrives --
    # the deadline is an import-phase budget while this is True, and a
    # real per-test budget once it flips False.
    importing: bool = True
    # Set instead of emitting "worker_terminated" immediately, so
    # the finalize loop can emit it AFTER the test_end(s) this
    # termination caused, not before.
    pending_terminated_reason: str | None = None


class Orchestrator:
    def __init__(
        self,
        root: str,
        num_workers: int,
        default_timeout: float,
        test_ids=None,
        case_ids=None,
        case_id_prefixes=None,
        tags=None,
        exclude_tags=None,
        grep=None,
        grep_not=None,
        console_reporters=None,
        cancel_event=None,
        playwright_config=None,
        options=None,
        logs_mode: str = "off",
        tag_registry: TagRegistry | None = None,
        event_subscribers=None,
        grouping_dimensions: list[GroupingDimension] | None = None,
        extra_roots: list[str] | None = None,
        force_reload: bool = False,
        project: str | None = None,
        multi_project: bool = False,
        fail_policy: FailPolicyState | None = None,
        history_store=None,
        history_window: int = 20,
        quarantine: QuarantineConfig | None = None,
        coverage_config=None,
        log_redaction=None,
        worker_constraints=None,
        fully_parallel: bool = False,
        junit_logs: str = "off",
        junit_infra_errors: bool = False,
        strict_teardown: bool = True,
        full_trace: bool = False,
        no_capture: bool = False,
        tb_style: str = "auto",
        import_timeout: float = IMPORT_PHASE_TIMEOUT,
        order: str = "declared",
        seed: int | None = None,
        raw_config: dict | None = None,
    ):
        self.root = root
        self.extra_roots = extra_roots or []
        self.force_reload = force_reload
        self.num_workers = num_workers
        self.default_timeout = default_timeout
        # The resolved ctrlrunner.toml dict, threaded into each worker
        # (it rides the spawn args tuple, so it must stay picklable) --
        # backs the pytest-shaped item.config/item.session objects the
        # per-test conftest hooks receive (core/hookcompat.py).
        self.raw_config = raw_config or {}
        # Scoped worker budgets ([ctrlrunner.workers] specs) and the
        # fully_parallel default (False = file-grouped scheduling:
        # a file's tests run in definition order in one worker).
        self.worker_constraints = worker_constraints or []
        self.fully_parallel = fully_parallel
        # True (default) fails a passing test whose fixture
        # teardown raised; False keeps the old outcome but stamps a
        # teardown_failed property.
        self.strict_teardown = strict_teardown
        # True disables display-filtering of ctrlrunner-internal
        # traceback frames (--full-trace).
        self.full_trace = full_trace
        # True disables output buffering entirely (-s / --capture=no):
        # test stdout/stderr/logging is tee'd live to the real stream
        # again, same as before this feature existed.
        self.no_capture = no_capture
        # --tb=<style>; "auto" (default) means "defer to self.full_trace",
        # exactly matching tb_format.format_filtered_exc()'s own resolution.
        self.tb_style = tb_style
        # The suite-import watchdog budget --
        # IMPORT_PHASE_TIMEOUT is only the default; heavy-deps suites on
        # cold-AV-scanned CI can legitimately need more.
        self.import_timeout = import_timeout
        # Unit-scheduling order -- "declared"
        # (today's behavior), "alpha", or "random" (needs `seed`). See
        # order_units() in worker_budget.py for why this reorders
        # ExecUnits, never raw tests.
        self.order = order
        self.seed = seed
        # dedicated group -> reserved slot count, populated per run by
        # group_aware_shard; consulted by the fill loop's eligibility
        # check.
        self._reservations: dict[str, int] = {}
        # serial unit key -> group attempts consumed so far, counted
        # from each attempt's first-member "started" message. Lives
        # orchestrator-side because a hard-killed worker takes its own
        # attempt bookkeeping down with it; passed into each fresh
        # worker so a requeued group never exceeds its total budget.
        self._unit_attempts_used: dict[str, int] = {}
        self.reporter = JUnitReporter(junit_logs=junit_logs, junit_infra_errors=junit_infra_errors)
        self.console_reporters = console_reporters or []
        self.event_subscribers = event_subscribers or []
        # Always a real threading.Event -- created internally if the
        # caller didn't supply one (the plain CLI-run case), so fail
        # policies (below) always have something to .set() without
        # every call site needing a None-check. UI Mode's Cancel button
        # still works exactly as before when it supplies its own.
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        # First-reason-wins, mirrors fail_policy.cancel_reason -- set
        # when a conftest hook requests session.shouldstop/.shouldfail
        # (see _handle_message's "shouldstop_requested" branch).
        self._shouldstop_reason: str | None = None
        self.playwright_config = playwright_config
        # ctrlrunner_addoption values (CLI > [ctrlrunner.options] >
        # declared default, merged by the CLI) -- passed to every worker
        # so get_option(...) works there, including at module level.
        self.options = options
        self.logs_mode = logs_mode
        self.tag_registry = tag_registry
        self.grouping_dimensions = grouping_dimensions or DEFAULT_DIMENSIONS
        self.project = project
        # Only wrap JUnit in <testsuites> when 2+ projects are actually
        # active THIS run -- a single-project or no-project run keeps
        # today's exact JUnit shape, so existing case_id-based CI
        # integrations (Teams pipeline, TestRail sync) never see a
        # format change unless multi-project is genuinely in use.
        self.multi_project = multi_project
        # Shared across every project's Orchestrator in a multi-project
        # run (run_projects() passes the same instance to each), so
        # --max-failures/--max-timeouts count across the WHOLE
        # invocation rather than resetting per project.
        self.fail_policy = fail_policy
        # Optional: a HistoryStore (ctrlrunner/history.py) enables LPT
        # duration-weighted scheduling instead of plain round-robin --
        # see run()'s use of group_aware_shard(), which applies LPT via
        # worker_budget._lpt_shard_weighted() when durations are non-empty.
        # None (the default) means today's exact _chunk() round-robin,
        # unchanged.
        self.history_store = history_store
        self.history_window = history_window
        # test_id -> timestamp when it was
        # requeued onto a fresh worker after a timeout hard-kill.
        # Consumed the moment the NEW worker's "started" message for
        # that test_id arrives (see _handle_message), turning into an
        # observed worker_restart_overhead on its eventual Result --
        # purely informational, feeding future tuning of
        # WORKER_RESTART_BUFFER against real data instead of guesswork.
        self._pending_restart_at = {}
        self._restart_overhead_for_result = {}
        self.quarantine = quarantine
        self.coverage_config = coverage_config
        # Compiled secret-redaction patterns applied to captured logs
        # before they're stored in any Result (and thus any report). None
        # = no redaction (the default for programmatic callers); the CLI
        # resolves and passes the configured set.
        self.log_redaction = log_redaction
        self.selection_filters = dict(
            test_ids=test_ids,
            case_ids=case_ids,
            case_id_prefixes=case_id_prefixes,
            tags=tags,
            exclude_tags=exclude_tags,
            grep=grep,
            grep_not=grep_not,
        )
        # Every test_id that has received a REAL "started" message
        # this run -- used to decide whether a cancelled/not_run/crash
        # test_end needs a synthetic test_start emitted immediately
        # before it, so every test_end has a preceding test_start.
        self._started_test_ids = set()
        # Timeline report: epoch seconds from each test's real
        # "started" IPC message, keyed by test_id -- lets a synthetic
        # timeout-kill/crash result for the test that was actually
        # running recover a real started_at instead of leaving it None
        # (which would otherwise drop it from the Gantt timeline as a
        # gap even though it visibly consumed wall-clock time).
        self._test_started_at: dict[str, float] = {}
        # EventSubscribers/ConsoleReporters that raised once already
        # this run -- id()-keyed so a single bad one is disabled (one
        # log line, then silence) without affecting any other
        # subscriber/reporter or requiring it to be hashable.
        self._disabled_subscribers = set()
        self._disabled_console_reporters = set()

    def _trigger_policy_cancel(self, reason: str) -> None:
        """Crossing a fail-policy threshold reuses the exact same
        cancel_event/hard-kill path as UI Mode's Cancel button -- no new
        kill mechanism. `cancel_reason` (first reason wins) is what lets
        _report_cancelled() later distinguish a policy-triggered stop
        ('not_run') from a plain external cancel ('cancelled').

        If cancel_event is ALREADY set (an external UI/user cancel
        fired first), a policy trip crossing its own threshold shortly
        after must not overwrite that with a policy reason -- doing so
        would make _report_cancelled() report 'not_run' for tests that
        were actually stopped by the user, not by a policy."""
        if (
            self.fail_policy is not None
            and self.fail_policy.cancel_reason is None
            and not self.cancel_event.is_set()
        ):
            self.fail_policy.cancel_reason = reason
        self.cancel_event.set()

    def _apply_quarantine(self, test_id: str, outcome: str):
        """Returns (effective_outcome, is_quarantined, reason).

        A quarantined test's genuine failure becomes 'quarantined_failure'
        -- distinct from 'failed', excluded from fail-policy counters and
        the exit code (both derive purely from the outcome STRING, so
        nothing downstream needs special-casing: a fail_policy check of
        `outcome == "failed"` is simply False once this has run).
        `quarantined` is set whenever the test_id is on the list, pass or
        fail, so it stays visible in reports even on a run where it
        happens to pass."""
        if self.quarantine is None or not self.quarantine.is_quarantined(test_id):
            return outcome, False, None
        effective = "quarantined_failure" if outcome == "failed" else outcome
        return effective, True, self.quarantine.reason

    def _emit(self, event_type: str, payload: dict) -> None:
        """Builds an EventEnvelope and hands it to every registered
        EventSubscriber. Called alongside (never instead of) the
        existing direct ConsoleReporter calls -- see events.py's module
        docstring for why these are two separate, independently stable
        interfaces rather than one changing the other.

        Each subscriber is called in its own try/except -- a buggy
        or third-party EventSubscriber must never have crash-the-run
        power (events are observe-only). One exception gets one log
        line and disables that subscriber for the rest of this run;
        every other subscriber keeps receiving events normally."""
        if not self.event_subscribers:
            return  # skip building an envelope nobody's listening for
        envelope = EventEnvelope(
            type=event_type, timestamp=time.time(), payload=payload, project=self.project
        )
        for sub in self.event_subscribers:
            if id(sub) in self._disabled_subscribers:
                continue
            try:
                sub.on_event(envelope)
            except Exception:
                _log.exception(
                    "Orchestrator: EventSubscriber %r raised from on_event() -- "
                    "disabling it for the rest of this run",
                    sub,
                )
                self._disabled_subscribers.add(id(sub))

    def _safe_console_call(self, method, *args) -> None:
        """Runs one ConsoleReporter method call, catching any
        exception so a broken reporter (or a history store that's
        locked/corrupt -- see on_run_end in run()) can't unwind out of
        the scheduler and orphan live worker slots, nor stop other
        reporters (JUnit/JSON/HTML/history) from doing their own job.
        One log line, then that specific reporter is disabled for the
        rest of this run -- every other reporter is unaffected."""
        cr = method.__self__
        if id(cr) in self._disabled_console_reporters:
            return
        try:
            method(*args)
        except Exception:
            _log.exception(
                "Orchestrator: console reporter %r raised from %s() -- disabling it "
                "for the rest of this run",
                cr,
                method.__name__,
            )
            self._disabled_console_reporters.add(id(cr))

    def _ensure_test_start_emitted(self, test_id: str) -> None:
        """A cancelled/not_run/hard-killed/crashed test_end can fire
        for a test that never actually received a real "started"
        message (it was still queued, or its slot died before reaching
        it). Emits a synthetic test_start immediately before such a
        test_end so every test_end a consumer sees is guaranteed a
        preceding test_start for the same test_id -- documented
        ordering an "open tests per worker" state machine can rely on."""
        if test_id in self._started_test_ids:
            return
        self._started_test_ids.add(test_id)
        for cr in self.console_reporters:
            self._safe_console_call(cr.on_test_start, test_id)
        self._emit("test_start", {"id": test_id})

    def _fire_collection_hooks(self, all_tests, selected):
        """ctrlrunner_itemcollected / ctrlrunner_deselected /
        ctrlrunner_collection_modifyitems / ctrlrunner_collection_finish
        -- pytest's collection-phase hooks, fired in the main process
        around select_tests(). modifyitems receives Item shims and may
        reorder/remove entries (mapped back to the real TestItems by
        nodeid) and add_marker() tags (written through). Hook errors
        propagate -- collection-phase misconfiguration aborts the run
        loudly, same policy as ctrlrunner_configure."""
        hooks = _conftest_hooks
        if not any(hooks.get(name) for name in _COLLECTION_HOOK_NAMES[1:]):
            return selected
        config = hookcompat.Config(self.raw_config)
        session = hookcompat.Session(config=config, testscollected=len(all_tests))

        def shim(t):
            return hookcompat.Item(
                t.id,
                0,  # collection phase -- nothing has run yet
                tags=t.tags,
                properties=t.properties,
                func=t.func,
                cls_name=t.class_name,
                config=config,
                session=session,
            )

        for fn in hooks.get("ctrlrunner_itemcollected", []):
            for t in all_tests:
                fn(**hookcompat.bind_hook_args(fn, {"item": shim(t)}))

        deselected_hooks = hooks.get("ctrlrunner_deselected", [])
        if deselected_hooks:
            selected_ids = {t.id for t in selected}
            removed = [shim(t) for t in all_tests if t.id not in selected_ids]
            if removed:
                for fn in deselected_hooks:
                    fn(**hookcompat.bind_hook_args(fn, {"items": removed}))

        modify_hooks = hooks.get("ctrlrunner_collection_modifyitems", [])
        if modify_hooks:
            by_id = {t.id: t for t in selected}
            shims = [shim(t) for t in selected]
            available = {"session": session, "config": config, "items": shims}
            for fn in modify_hooks:
                fn(**hookcompat.bind_hook_args(fn, available))
            reordered = []
            for s in shims:
                t = by_id.get(s.nodeid)
                if t is None:
                    continue  # a hook appended an unknown entry -- nothing to run
                t.tags |= s.tags  # add_marker() write-through
                reordered.append(t)
            selected = reordered

        for fn in hooks.get("ctrlrunner_collection_finish", []):
            fn(**hookcompat.bind_hook_args(fn, {"session": session}))
        return selected

    @staticmethod
    def _result_payload(result) -> dict:
        # The `test_end` payload IS the JSON reporter's per-test
        # entry -- one schema for streaming and reporting, built by one
        # function (schema v2; v1 shipped an independently-shaped
        # snake_case payload here).
        return result_to_public_dict(result)

    def run(self):
        if self.extra_roots:
            modules = discover_and_import_multi(
                [self.root] + self.extra_roots,
                force_reload=self.force_reload,
                raw_config=self.raw_config,
            )
        else:
            modules = discover_and_import(
                self.root, force_reload=self.force_reload, raw_config=self.raw_config
            )
        all_tests = get_tests()

        if self.tag_registry is not None:
            unregistered = validate_tags(all_tests, self.tag_registry)
            if unregistered:
                message = format_unregistered_tags_warning(unregistered)
                if self.tag_registry.strict:
                    raise TagValidationError(message)
                print(f"Warning: {message}", file=sys.stderr)

        tests = select_tests(all_tests, **self.selection_filters)
        tests = self._fire_collection_hooks(all_tests, tests)
        self.items_by_id = {t.id: t for t in tests}
        self.groups_by_id = {
            t.id: compute_groups(t, self.grouping_dimensions, self.root) for t in tests
        }

        test_ids = [t.id for t in tests]
        timeouts = {
            t.id: (t.timeout if t.timeout is not None else self.default_timeout) for t in tests
        }

        # Fires for every --reporter choice (including json, which never
        # prints anything else on its own) -- not a ConsoleReporter
        # method, deliberately.
        print(format_collection_summary(tests))

        for cr in self.console_reporters:
            self._safe_console_call(cr.on_run_start, len(test_ids))
        self._emit("run_start", {"total": len(test_ids)})
        run_start = time.time()

        if not test_ids:
            pending = []
        else:
            durations = (
                lookup_median_durations(
                    test_ids, self.history_store, self.project, self.history_window
                )
                if self.history_store is not None
                else {}
            )
            constraints_by_id = assign_worker_groups(tests, self.worker_constraints)
            units, constraints_by_unit = build_units(tests, constraints_by_id, self.fully_parallel)
            units = order_units(units, self.order, self.seed)
            plan = group_aware_shard(
                units,
                constraints_by_unit,
                self.num_workers,
                durations,
                warn=lambda m: print(f"Warning: {m}", file=sys.stderr),
            )
            pending = plan.batches
            self._reservations = plan.reservations
            if self.order != "declared":
                self.reporter.suite_properties["order"] = self.order
                if self.order == "random":
                    self.reporter.suite_properties["seed"] = str(self.seed)
        self._unit_attempts_used = {}
        results_before = len(self.reporter.results)
        self._run_scheduler(pending, modules, timeouts)
        self._reconcile_results(test_ids, results_before)

        run_duration = time.time() - run_start
        self.run_duration = run_duration
        # Timeline feature: exposed alongside run_duration so
        # the HTML report can position bars on an absolute time axis.
        self.run_start = run_start
        passed = sum(1 for r in self.reporter.results if r.outcome == "passed")
        failed = sum(1 for r in self.reporter.results if r.outcome == "failed")
        # Each reporter's on_run_end is independent -- a locked or
        # corrupt history store raising here must not stop JUnit/JSON/
        # HTML reporters (also on_run_end) from writing their own
        # output. _safe_console_call logs once and disables just the
        # reporter that raised.
        for cr in self.console_reporters:
            # Hand record_suite_property() values to reporters that
            # can carry them (duck-typed, same pattern as
            # set_coverage_summary) before their on_run_end write.
            if hasattr(cr, "set_suite_properties"):
                self._safe_console_call(cr.set_suite_properties, self.reporter.suite_properties)
            self._safe_console_call(cr.on_run_end, self.reporter.results, run_duration)
        self._emit(
            "run_end",
            {
                "total": len(self.reporter.results),
                "passed": passed,
                "failed": failed,
                "duration": run_duration,
            },
        )

        return self.reporter

    def _reconcile_results(self, selected_ids, results_before) -> None:
        """Safety belt for the exactly-once result contract: every
        selected test must have produced exactly one Result. The
        slot.remaining bookkeeping is what guarantees it; if a future
        regression breaks that, fail loudly per-test here instead of
        silently shipping a report with holes (and count nothing twice
        without at least an error in the log)."""
        reported_ids = [r.test_id for r in self.reporter.results[results_before:]]
        reported_set = set(reported_ids)
        for tid in selected_ids:
            if tid in reported_set:
                continue
            _log.error("Internal invariant violation: %s produced no result", tid)
            self._ensure_test_start_emitted(tid)
            result = self.reporter.add_result(
                tid,
                "failed",
                "Internal error: test produced no result (ctrlrunner bug -- please "
                "report). Marked failed so the run cannot silently pass with "
                "missing tests.",
                0.0,
                groups=self.groups_by_id.get(tid, {}),
                project=self.project,
            )
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_end, result)
            self._emit("test_end", self._result_payload(result))
        if len(reported_ids) != len(reported_set):
            dupes = sorted({t for t in reported_ids if reported_ids.count(t) > 1})
            _log.error("Internal invariant violation: duplicate results for %s", dupes)

    def _is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    # ------------------------------------------------------------------
    # Concurrent slot scheduler.
    #
    # Up to num_workers _WorkerSlots are alive at once, each with its
    # own process, Job Object, result queue, and per-test watchdog
    # deadline. One loop polls every live slot's queue non-blockingly;
    # per-slot timeout/kill/requeue semantics are exactly what the old
    # sequential _run_batch enforced, just tracked per slot. This is a
    # control-flow restructuring, not a new execution model: one Job
    # Object per worker, hard-kill on deadline, requeue of a killed
    # batch's leftover tests onto a fresh worker.
    # ------------------------------------------------------------------

    def _run_scheduler(self, pending, modules, timeouts):
        slots = []

        try:
            self._run_scheduler_loop(pending, slots, modules, timeouts)
        finally:
            # Guarantee every still-live slot is terminated and
            # finalized even if something above raised an exception
            # that escaped every try/except already in place (console
            # reporter and EventSubscriber errors are caught at their
            # own call sites; this is defense-in-depth for anything
            # else) -- a scheduler crash must never leak worker
            # processes.
            for slot in slots:
                with contextlib.suppress(Exception):
                    if not slot.done:
                        slot.job.terminate()
                with contextlib.suppress(Exception):
                    self._finalize_slot(slot, timeouts)

    def _run_scheduler_loop(self, pending, slots, modules, timeouts):
        while pending or slots:
            # Cancellation: terminate everything alive, mark everything
            # not-yet-finished (both live remainders and never-started
            # pending batches) as 'cancelled', then stop scheduling.
            # The branch always `break`s below, so it can only ever run
            # once per call -- no separate guard needed.
            if self._is_cancelled():
                for slot in slots:
                    slot.job.terminate()
                    slot.killed = True
                for slot in slots:
                    self._finalize_slot(slot, timeouts)
                    # test_end(s) for this worker's remaining tests
                    # must precede its worker_terminated event, not
                    # follow it.
                    self._report_cancelled(slot.remaining)
                    self._emit(
                        "worker_terminated",
                        {"workerId": slot.worker_id, "reason": "cancelled"},
                    )
                slots.clear()
                for batch in pending:
                    self._report_cancelled(batch.test_ids)
                pending.clear()
                break

            # Fill free slots from pending (first eligible batch under
            # the dedicated-reservation budgets; plain FIFO when no
            # dedicated groups are in play).
            while pending and len(slots) < self.num_workers:
                idx = self._next_spawnable_index(pending, slots)
                if idx is None:
                    break  # nothing eligible this pass -- fall through to polling
                # Timeline report: worker_id is the row a
                # test lands on in the HTML report's Gantt chart, which
                # pre-seeds exactly num_workers rows -- so this must be a
                # bounded, reused 1..num_workers lane index, not a
                # monotonic per-spawn counter (that produced phantom rows
                # once any slot was reused after freeing up).
                used_lanes = {s.worker_id for s in slots}
                lane = next(i for i in range(1, self.num_workers + 1) if i not in used_lanes)
                slots.append(self._spawn_slot(pending.pop(idx), modules, timeouts, lane))

            progressed = False
            now = time.time()

            for slot in slots:
                if self._is_cancelled():
                    break  # the next outer-loop pass's cancellation branch handles every slot

                # Drain whatever this slot has produced so far -- but
                # re-check cancellation after every single message, not
                # just once per outer pass. A fail-policy threshold can
                # be crossed (and cancel_event.set()) from inside
                # _handle_message itself; without this check, a burst of
                # already-queued "finished" messages (e.g. several fast
                # tests in one worker) would all get processed before
                # the outer loop's own cancellation check ever runs,
                # letting a run blow straight past --max-failures.
                if self._drain_queue_once(slot, timeouts):
                    progressed = True

                if slot.done or self._is_cancelled():
                    # If cancellation happened mid-drain, leave slot.done
                    # as-is (don't let a "process already exited on its
                    # own" check below mark it done via the wrong path --
                    # possibly with unread messages still sitting in its
                    # queue). The next outer-loop pass's cancellation
                    # branch is what actually finalizes every slot in
                    # that case, uniformly.
                    continue

                if now > slot.deadline:
                    slot.job.terminate()  # kills worker + any orphaned browser/node processes
                    slot.killed = True
                    slot.done = True
                    slot.pending_terminated_reason = "timeout"
                    progressed = True
                elif not slot.proc.is_alive():
                    exitcode = slot.proc.exitcode
                    if not slot.killed and exitcode not in (0, None):
                        # Genuine crash: the process exited on its own
                        # with a nonzero code, as opposed to slot.killed
                        # (our own job.terminate() call, tracked
                        # separately above). Distinct from a timeout --
                        # the worker never hung, it died outright, e.g.
                        # an unhandled exception at import time in one
                        # of its assigned test modules.
                        slot.crashed = True
                        slot.pending_terminated_reason = "crashed"
                        if self.fail_policy is not None:
                            reason = self.fail_policy.record_worker_crash()
                            if reason:
                                self._trigger_policy_cancel(reason)
                    slot.done = True
                    progressed = True

            # Finalize finished slots and requeue killed batches' leftovers.
            still_alive = []
            for slot in slots:
                if not slot.done:
                    still_alive.append(slot)
                    continue
                self._finalize_slot(slot, timeouts)
                if slot.crashed:
                    self._report_worker_crash(slot.remaining, slot.proc.exitcode, slot.worker_id)
                elif slot.killed and self._is_cancelled():
                    self._report_cancelled(slot.remaining)
                elif slot.killed and slot.remaining:
                    requeued_units = self._handle_timeout_kill(slot, timeouts)
                    if requeued_units:
                        # Requeue onto a fresh worker so one stuck test
                        # can't take down everything scheduled after it.
                        # Unit boundaries and the batch's constraint
                        # label survive the requeue, so a capped/
                        # dedicated group's leftover stays ONE batch
                        # inside its group's budget.
                        requeue_time = time.time()
                        for unit in requeued_units:
                            for tid in unit.test_ids:
                                self._pending_restart_at[tid] = requeue_time
                        pending.append(
                            Batch(
                                units=requeued_units,
                                group=slot.group,
                                dedicated=slot.dedicated,
                            )
                        )
                # worker_terminated fires AFTER the test_end(s) this
                # termination caused, not before -- a consumer tracking
                # "open tests per worker" would otherwise see the
                # worker die while a test it was running still looked
                # in-flight.
                if slot.pending_terminated_reason is not None:
                    payload = {
                        "workerId": slot.worker_id,
                        "reason": slot.pending_terminated_reason,
                    }
                    if slot.pending_terminated_reason == "crashed":
                        payload["exitcode"] = slot.proc.exitcode
                    self._emit("worker_terminated", payload)
            # In-place mutation, not rebinding -- `slots` is the SAME
            # list object _run_scheduler's try/finally holds a
            # reference to, so its cleanup pass sees exactly the
            # slots still alive right now, not a stale snapshot from
            # before this pass's finalizations.
            slots[:] = still_alive

            if not progressed:
                time.sleep(_POLL_INTERVAL)

    def _drain_queue_once(self, slot: "_WorkerSlot", timeouts) -> bool:
        """Reads every message currently available on slot.queue without
        blocking, dispatching each to _handle_message. Returns True if
        at least one message was read. Used both during normal per-pass
        scheduling and as a final post-mortem drain right before
        finalizing a dead/killed/cancelled slot (see _finalize_slot) --
        a worker's last "finished" message can still be sitting unread
        at the exact moment is_alive() goes False, a fail-policy trip
        stops the drain loop, or a slot gets terminated -- losing it
        either drops a test's Result entirely or mislabels an
        already-completed test as not_run/crashed."""
        progressed = False
        while True:
            try:
                msg = slot.queue.get_nowait()
            except queue_module.Empty:
                break
            except Exception:
                # A corrupt/unpicklable message must not vanish with
                # no trace -- log it once, then stop draining this pass
                # (same "give up on this queue for now" behavior as
                # before, just diagnosable instead of silent; a silent
                # drop here used to manifest minutes later as a fake
                # watchdog timeout on a perfectly healthy worker).
                _log.exception(
                    "Orchestrator: corrupt/unpicklable message on worker %s's result "
                    "queue -- dropping the rest of this drain pass",
                    slot.worker_id,
                )
                break
            progressed = True
            self._handle_message(slot, msg, timeouts)
            if slot.done or self._is_cancelled():
                break
        return progressed

    def _next_spawnable_index(self, pending, slots):
        """Index of the first pending batch allowed to spawn right now,
        or None. Enforces dedicated-mode reservations from both sides:
        a dedicated group never exceeds its reserved slot count, and
        the pool (everything else, cap batches included) never eats
        into slots reserved for a dedicated group that still has work
        (a pending batch or a live slot -- a live slot can still time
        out and requeue). A fully drained dedicated group releases its
        reservation back to the pool."""
        if not self._reservations:
            return 0 if pending else None

        live_dedicated: dict[str, int] = {}
        live_pool = 0
        for slot in slots:
            if slot.dedicated:
                live_dedicated[slot.group] = live_dedicated.get(slot.group, 0) + 1
            else:
                live_pool += 1

        active_groups = {b.group for b in pending if b.dedicated}
        active_groups.update(g for g in live_dedicated)
        reserved = sum(self._reservations.get(g, 0) for g in active_groups)
        pool_budget = self.num_workers - reserved

        for idx, batch in enumerate(pending):
            if batch.dedicated:
                if live_dedicated.get(batch.group, 0) < self._reservations.get(batch.group, 0):
                    return idx
            elif live_pool < pool_budget:
                return idx
        return None

    def _spawn_slot(self, batch: Batch, modules, timeouts, worker_id) -> _WorkerSlot:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        job = JobObject()
        test_ids = batch.test_ids
        serial_attempts_used = {
            u.key: self._unit_attempts_used.get(u.key, 0) for u in batch.units if u.kind == "serial"
        }
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
                self.tb_style,
            ),
        )
        proc.start()
        # Not an assert (`python -O` strips those): a None pid slipping
        # into job.assign() would silently disable the hard-kill path.
        if proc.pid is None:
            raise RuntimeError("worker process has no pid immediately after start()")
        job.assign(proc.pid)  # must happen before the worker launches a browser
        self._emit("worker_spawned", {"workerId": worker_id})
        return _WorkerSlot(
            worker_id=worker_id,
            proc=proc,
            job=job,
            queue=q,
            remaining=list(test_ids),
            # Import-phase budget, not the first test's own timeout
            # -- see _handle_message's "ready" branch for when this
            # gets replaced by the real per-test deadline.
            deadline=time.time() + self.import_timeout,
            units=list(batch.units),
            group=batch.group,
            dedicated=batch.dedicated,
        )

    def _handle_message(self, slot: _WorkerSlot, msg, timeouts):
        kind = msg[0]
        if kind == "ready":
            # Imports are done -- start the real per-test watchdog
            # clock now, instead of having charged import time against
            # the first test's timeout from the moment of spawn.
            _, _wid, ts = msg
            slot.importing = False
            first_test = slot.remaining[0] if slot.remaining else None
            if first_test is not None:
                slot.deadline = ts + timeouts[first_test] + WORKER_RESTART_BUFFER
        elif kind == "started":
            _, _wid, test_id, ts = msg
            slot.importing = False
            slot.deadline = ts + timeouts[test_id] + WORKER_RESTART_BUFFER
            slot.current_test = test_id
            self._test_started_at[test_id] = ts
            # Every serial group attempt restarts from its first member,
            # and the worker always emits "started" before running a
            # test -- so first-member starteds count group attempts with
            # no protocol change (a later hung attempt is thereby
            # already counted when the kill path checks the budget).
            for unit in slot.units or ():
                if unit.kind == "serial" and unit.test_ids[0] == test_id:
                    self._unit_attempts_used[unit.key] = (
                        self._unit_attempts_used.get(unit.key, 0) + 1
                    )
                    break
            self._started_test_ids.add(test_id)
            if test_id in self._pending_restart_at:
                requeue_time = self._pending_restart_at.pop(test_id)
                self._restart_overhead_for_result[test_id] = max(0.0, ts - requeue_time)
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_start, test_id)
            self._emit("test_start", {"id": test_id, "workerId": slot.worker_id})
        elif kind == "timeout_extended":
            _, _wid, tid, factor = msg
            slot.deadline = time.time() + timeouts[tid] * factor + WORKER_RESTART_BUFFER
        elif kind == "suite_property":
            # record_suite_property() -- run-level metadata. Streams
            # per call, so a later hard-kill of the worker can't lose it
            # (the xdist failure mode this API is measured against).
            _, _wid, key, value = msg
            self.reporter.suite_properties[key] = value
        elif kind == "shouldstop_requested":
            # A conftest hook set session.shouldstop/.shouldfail (see
            # core/hookcompat.py's Session) -- reuses the exact same
            # cancel_event/hard-kill path fail-policy thresholds and
            # UI Mode's Cancel button already use, no new kill
            # mechanism. First reason wins, same as fail_policy's own
            # cancel_reason -- see _report_cancelled.
            _, _wid, reason = msg
            if self._shouldstop_reason is None and not self.cancel_event.is_set():
                self._shouldstop_reason = reason
            self.cancel_event.set()
        elif kind == "session_teardown_failed":
            # A module/session-scoped fixture's teardown ran
            # after (or between) tests, so its failure can't be pinned
            # on one result -- warn loudly and record it as run-level
            # metadata so reports carry the evidence.
            _, _wid, name, tb = msg
            _log.warning("Worker %s: fixture '%s' teardown failed:\n%s", slot.worker_id, name, tb)
            last_line = tb.strip().splitlines()[-1] if tb.strip() else "teardown failed"
            self.reporter.suite_properties[f"teardown_error:{name}"] = last_line
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
            item = self.items_by_id.get(test_id)
            merged_properties = {**(item.properties if item else {}), **extra_props}
            # Mask obvious secrets in captured logs before they reach
            # any Result/report. In-place on the worker's log dicts, which
            # are freshly deserialized from the queue and owned by us now.
            logs = redact_log_entries(logs, self.log_redaction)
            outcome, is_quarantined, quarantine_reason = self._apply_quarantine(test_id, outcome)
            # This test's WORST SINGLE ATTEMPT
            # finished at or above 80% of its resolved per-attempt
            # timeout -- a per-result "came close to being hard-killed"
            # flag. Compares max_attempt_duration (one attempt's
            # own elapsed time), not the aggregate `duration` summed
            # across every retry -- the orchestrator's watchdog
            # deadline is reset fresh per attempt (see the "started"
            # branch above), so only a single attempt's own duration is
            # ever actually compared to that budget in reality.
            near_timeout = max_attempt_duration >= 0.8 * timeouts[test_id]
            # A test that failed at least once
            # this run but whose FINAL attempt passed. Computed from the
            # already-quarantine-adjusted `outcome` -- quarantine only
            # ever turns "failed" into "quarantined_failure", never
            # touches "passed", so this check is safe to run after it.
            flaky = outcome == "passed" and attempts is not None and attempts > 1
            result = self.reporter.add_result(
                # The RAW test_id is the identity used for
                # history/quarantine/rerun/flaky joins -- `project`
                # (below) is the sole disambiguator for multi-project
                # runs. Baking a "[project] " prefix into this field
                # broke every one of those joins, since each of them
                # queries with the raw id.
                test_id,
                outcome,
                error,
                duration,
                case_id=item.case_id if item else None,
                tags=item.tags if item else (),
                properties=merged_properties,
                attempts=attempts,
                artifacts=artifacts,
                steps=test_steps,
                groups=self.groups_by_id.get(test_id, {}),
                project=self.project,
                retries_configured=item.retries if item else None,
                worker_restart_overhead=self._restart_overhead_for_result.pop(test_id, None),
                quarantined=is_quarantined,
                quarantine_reason=quarantine_reason,
                worker_id=slot.worker_id,
                near_timeout=near_timeout,
                assert_details=assert_details,
                logs=logs,
                warnings=captured_warnings,
                flaky=flaky,
                started_at=started_at,
                console_captured=console_captured,
            )
            self._test_started_at.pop(test_id, None)
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_end, result)
            self._emit("test_end", self._result_payload(result))
            if test_id in slot.remaining:
                slot.remaining.remove(test_id)
            if outcome == "failed" and self.fail_policy is not None:
                reason = self.fail_policy.record_failure()
                if reason:
                    self._trigger_policy_cancel(reason)
        elif kind == "worker_done":
            slot.done = True
            slot.pending_terminated_reason = "completed"

    def _finalize_slot(self, slot: _WorkerSlot, timeouts):
        if slot.killed and self.coverage_config is not None:
            # Coverage data for this worker's current batch is lost --
            # job.terminate() kills the process before it reaches its own
            # cov.stop()/cov.save() in worker.py.
            self.coverage_config.hard_kills += 1
        # B1/B2: a worker's last "finished" message can still be
        # sitting unread in its queue at the exact moment we decide to
        # finalize the slot (clean exit, crash, timeout-kill, or
        # cancellation) -- drain it one last time so that result isn't
        # silently lost (no Result row at all) or the test isn't
        # mislabeled not_run/crashed underneath a result that actually
        # arrived just before/as the process went away.
        self._drain_queue_once(slot, timeouts)
        slot.proc.join(timeout=2)
        if slot.proc.is_alive():
            # join() timed out and the process is somehow still
            # alive (e.g. stuck in atexit/teardown after we already
            # terminated it) -- escalate instead of silently leaving a
            # lingering process behind.
            _log.warning(
                "Orchestrator: worker %s still alive after join() following "
                "termination -- escalating",
                slot.worker_id,
            )
            with contextlib.suppress(Exception):
                slot.job.terminate()
            deadline = time.monotonic() + FINALIZE_JOIN_CEILING
            while slot.proc.is_alive() and time.monotonic() < deadline:
                if self._is_cancelled():
                    break  # don't make a user-requested stop wait on this
                slot.proc.join(timeout=FINALIZE_JOIN_POLL_INTERVAL)
            if slot.proc.is_alive():
                _log.warning(
                    "Orchestrator: worker %s still alive %.0fs after "
                    "termination -- giving up; process/handles may be "
                    "reclaimed by the OS later",
                    slot.worker_id,
                    FINALIZE_JOIN_CEILING,
                )
        slot.job.close()
        # Close the queue too -- otherwise its file descriptors
        # accumulate over a run with many timeout/requeue cycles.
        with contextlib.suppress(Exception):
            slot.queue.close()

    def _report_cancelled(self, test_ids):
        # A policy-triggered stop (--max-failures/--max-timeouts/
        # --stop-on-worker-crash, or a conftest hook setting
        # session.shouldstop/.shouldfail) reuses this exact same path
        # but reports a distinct outcome ('not_run') and message from a
        # plain external cancel ('cancelled', e.g. UI Mode's Stop
        # button) -- so a CI dashboard can tell "we stopped ourselves
        # on purpose" apart from "someone hit Stop."
        cancel_reason = self.fail_policy.cancel_reason if self.fail_policy is not None else None
        if cancel_reason:
            outcome = "not_run"
            message = f"Run stopped: {cancel_reason} threshold reached"
        elif self._shouldstop_reason:
            outcome = "not_run"
            message = f"Run stopped: {self._shouldstop_reason}"
        else:
            outcome = "cancelled"
            message = "Run was cancelled"
        for test_id in test_ids:
            item = self.items_by_id.get(test_id)
            # Most of these tests never received a real "started"
            # message (they were still queued) -- synthesize one so
            # every test_end has a preceding test_start.
            self._ensure_test_start_emitted(test_id)
            result = self.reporter.add_result(
                test_id,
                outcome,
                message,
                0.0,
                case_id=item.case_id if item else None,
                tags=item.tags if item else (),
                properties=item.properties if item else None,
                groups=self.groups_by_id.get(test_id, {}),
                project=self.project,
                retries_configured=item.retries if item else None,
            )
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_end, result)
            self._emit("test_end", self._result_payload(result))

    def _handle_timeout_kill(self, slot: _WorkerSlot, timeouts) -> list:
        """Reporting + requeue decision for a hard-killed slot. Returns
        the ExecUnits to requeue onto a fresh worker (empty = nothing).

        The stuck test is slot.current_test, NOT remaining[0]: under
        serial-group buffering, earlier members may have passed without
        their results being emitted yet, so remaining[0] can be a test
        that already ran fine.

        A stuck SERIAL unit with group-retry budget left emits nothing
        (the killed attempt was already counted via its first member's
        "started") and requeues WHOLE; out of budget, the stuck test
        fails and every other still-unreported member is skipped --
        never requeued individually. Other units in the same batch
        requeue trimmed to their unfinished members, as always.
        """
        if slot.importing:
            # No test ever started: keep the import-budget semantics --
            # blame remaining[0], requeue the rest (a serial unit missing
            # its blamed first member requeues as the same unit minus it;
            # no group attempt was consumed since nothing started).
            stuck = slot.remaining[0]
            self._report_timeout_kill(stuck, timeouts, slot.worker_id, importing=True)
            return _trim_units(slot.units, slot.remaining[1:])

        stuck = slot.current_test if slot.current_test in slot.remaining else slot.remaining[0]
        stuck_unit = next((u for u in slot.units if stuck in u.test_ids), None)

        if stuck_unit is None or stuck_unit.kind != "serial":
            self._report_timeout_kill(stuck, timeouts, slot.worker_id)
            leftover = [tid for tid in slot.remaining if tid != stuck]
            return _trim_units(slot.units, leftover)

        other_ids = [tid for tid in slot.remaining if tid not in stuck_unit.test_ids]
        other_units = _trim_units([u for u in slot.units if u.key != stuck_unit.key], other_ids)

        used = self._unit_attempts_used.get(stuck_unit.key, 0)
        if used < stuck_unit.serial_retries + 1:
            # Budget remains: the hung attempt consumed one group
            # attempt and reported nothing -- requeue the whole unit.
            return [stuck_unit] + other_units

        self._report_timeout_kill(stuck, timeouts, slot.worker_id)
        skipped = [tid for tid in stuck_unit.test_ids if tid in slot.remaining and tid != stuck]
        self._report_serial_skips(skipped, stuck, stuck_unit, slot.worker_id)
        return other_units

    def _report_serial_skips(self, test_ids, stuck_test, unit, worker_id):
        for test_id in test_ids:
            item = self.items_by_id.get(test_id)
            # Most of these never got a real "started" message.
            self._ensure_test_start_emitted(test_id)
            result = self.reporter.add_result(
                test_id,
                "skipped",
                f"skipped: test '{stuck_test}' in serial group was hard-killed "
                f"on its final group attempt",
                0.0,
                case_id=item.case_id if item else None,
                tags=item.tags if item else (),
                properties=item.properties if item else None,
                groups=self.groups_by_id.get(test_id, {}),
                project=self.project,
                retries_configured=item.retries if item else None,
                worker_id=worker_id,
                started_at=self._test_started_at.get(test_id),
            )
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_end, result)
            self._emit("test_end", self._result_payload(result))

    def _report_timeout_kill(self, stuck_test, timeouts, worker_id, importing=False):
        item = self.items_by_id.get(stuck_test)
        outcome, is_quarantined, quarantine_reason = self._apply_quarantine(stuck_test, "failed")
        # A worker hard-killed while still importing never actually
        # hung on this test -- say so, instead of blaming a timeout the
        # test itself never got a chance to run against.
        if importing:
            message = (
                f"Worker hard-killed after exceeding the {self.import_timeout}s "
                f"suite-import budget -- no test in this batch had started running yet."
            )
            duration = self.import_timeout
        else:
            message = (
                f"Hard-killed after exceeding timeout "
                f"({timeouts[stuck_test]}s + {WORKER_RESTART_BUFFER}s restart buffer)"
            )
            # Timeline report: the worker doesn't actually get killed
            # until the watchdog deadline (start + timeout +
            # WORKER_RESTART_BUFFER) fires, not at the configured
            # timeout mark -- using the configured timeout here under-
            # sized the Gantt bar and left a rendering gap for the real
            # WORKER_RESTART_BUFFER seconds the lane was genuinely stuck.
            started = self._test_started_at.get(stuck_test)
            duration = (
                time.time() - started
                if started is not None
                else timeouts[stuck_test] + WORKER_RESTART_BUFFER
            )
        result = self.reporter.add_result(
            stuck_test,
            outcome,
            message,
            duration,
            case_id=item.case_id if item else None,
            tags=item.tags if item else (),
            properties=item.properties if item else None,
            groups=self.groups_by_id.get(stuck_test, {}),
            project=self.project,
            retries_configured=item.retries if item else None,
            quarantined=is_quarantined,
            quarantine_reason=quarantine_reason,
            worker_id=worker_id,
            worker_restart_overhead=self._restart_overhead_for_result.pop(stuck_test, None),
            infra_error=True,
            started_at=self._test_started_at.get(stuck_test),
        )
        for cr in self.console_reporters:
            self._safe_console_call(cr.on_test_end, result)
        self._emit("test_end", self._result_payload(result))
        if outcome == "failed" and self.fail_policy is not None:
            # A timeout kill is always also a failure -- both counters
            # see it, since --max-failures and --max-timeouts are
            # independent thresholds over overlapping signals. Neither
            # fires for a quarantined test (outcome is
            # 'quarantined_failure' by this point, not 'failed').
            reasons = [self.fail_policy.record_failure(), self.fail_policy.record_timeout()]
            for reason in reasons:
                if reason:
                    self._trigger_policy_cancel(reason)

    def _report_worker_crash(self, remaining, exitcode, worker_id):
        # Deliberately NOT requeued (unlike a timeout kill's leftover
        # batch) -- a worker crash is a more suspicious signal (e.g. an
        # import-time error in the test module), and retrying onto a
        # fresh worker risks an infinite crash loop if it's deterministic.
        for test_id in remaining:
            item = self.items_by_id.get(test_id)
            outcome, is_quarantined, quarantine_reason = self._apply_quarantine(test_id, "failed")
            # As in _report_cancelled -- most of these tests never
            # got a real "started" message.
            self._ensure_test_start_emitted(test_id)
            result = self.reporter.add_result(
                test_id,
                outcome,
                f"Worker process crashed (exit code {exitcode}) before this test "
                f"could run or finish -- check for an import-time error in its "
                f"test module or a segfault in a native dependency.",
                0.0,
                case_id=item.case_id if item else None,
                tags=item.tags if item else (),
                properties=item.properties if item else None,
                groups=self.groups_by_id.get(test_id, {}),
                project=self.project,
                retries_configured=item.retries if item else None,
                quarantined=is_quarantined,
                quarantine_reason=quarantine_reason,
                worker_id=worker_id,
                infra_error=True,
                started_at=self._test_started_at.get(test_id),
            )
            for cr in self.console_reporters:
                self._safe_console_call(cr.on_test_end, result)
            self._emit("test_end", self._result_payload(result))
            if outcome == "failed" and self.fail_policy is not None:
                reason = self.fail_policy.record_failure()
                if reason:
                    self._trigger_policy_cancel(reason)
