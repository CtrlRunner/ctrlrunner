"""
Programmatic control over test runs --
list discoverable tests, start a run in the background, query live
status, cancel it -- independent of any HTTP/web code, so it's testable
entirely on its own. The UI server is a thin HTTP wrapper
around this.
"""

import dataclasses
import queue
import sys
import threading
import time

from ..config.tag_registry import format_unregistered_tags_warning, validate_tags
from ..core.registry import clear_tests, get_tests
from ..reporting.grouping import DEFAULT_DIMENSIONS, compute_groups
from ..reporting.reporters import ConsoleReporter
from ..ui.trace_viewer import PersistentTraceViewer
from .orchestrator import Orchestrator, discover_and_import
from .worker_budget import resolve_num_workers

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"


def _result_to_event(result) -> dict:
    """Shared shape between the live `test_end` SSE event and
    RunController.last_results_snapshot() -- the frontend renders both
    identically, so a test's row looks the same whether its status just
    arrived live or was restored after a page reload."""
    return {
        "type": "test_end",
        "id": result.test_id,
        "outcome": result.outcome,
        "duration": round(result.duration, 3),
        "caseId": result.case_id,
        "error": result.error,
        "artifacts": list(result.artifacts),
        "steps": result.steps,
        "groups": dict(result.groups),
        "quarantined": result.quarantined,
        "quarantineReason": result.quarantine_reason,
        "nearTimeout": result.near_timeout,
        "assertDetails": result.assert_details,
        "logs": result.logs,
    }


class LiveEventReporter(ConsoleReporter):
    """Turns orchestrator lifecycle hooks into plain dict events, handed
    to a broadcast callback -- the UI server fans these out to every
    connected SSE stream."""

    def __init__(self, broadcast, trace_viewer_url=None, on_trace=None):
        self._broadcast = broadcast
        self._trace_viewer_url = trace_viewer_url
        self._on_trace = on_trace

    def on_run_start(self, total):
        self._broadcast(
            {"type": "run_start", "total": total, "traceViewerUrl": self._trace_viewer_url}
        )

    def on_test_start(self, test_id):
        self._broadcast({"type": "test_start", "id": test_id})

    def on_test_end(self, result):
        self._broadcast(_result_to_event(result))
        if self._on_trace:
            trace_path = next((p for p in result.artifacts if p.endswith(".zip")), None)
            if trace_path:
                self._on_trace(result.test_id, trace_path)

    def on_run_end(self, results, duration):
        passed = sum(1 for r in results if r.outcome == "passed")
        failed = sum(1 for r in results if r.outcome == "failed")
        self._broadcast(
            {
                "type": "run_end",
                "duration": round(duration, 3),
                "total": len(results),
                "passed": passed,
                "failed": failed,
            }
        )


class RunController:
    def __init__(
        self,
        root: str,
        num_workers: int | str = "auto",
        default_timeout: float = 30.0,
        playwright_config: dict | None = None,
        tag_registry=None,
        grouping_dimensions=None,
        quarantine=None,
        coverage_config=None,
        worker_constraints=None,
        fully_parallel: bool = False,
        strict_teardown: bool = True,
    ):
        self.root = root
        # Keep both the raw spelling ("auto"/"50%"/int -- what the UI
        # shows and re-saves) and the resolved concrete int (what each
        # run's Orchestrator receives).
        self.num_workers_setting = num_workers
        self.num_workers = resolve_num_workers(num_workers)
        self.default_timeout = default_timeout
        self.worker_constraints = worker_constraints or []
        self.fully_parallel = fully_parallel
        self.strict_teardown = strict_teardown
        # UI Mode always captures a trace for every test, pass or fail,
        # regardless of pyrunner.toml's/--trace's CI-oriented setting --
        # otherwise "View Trace" has nothing to show for most runs (the
        # CLI default is "off", and even "retain-on-failure" hides traces
        # for passing tests), and the live UI's whole point is to let you
        # watch what a test just did. Copy rather than mutate the
        # caller-owned dict.
        self.playwright_config = dict(playwright_config or {})
        self.playwright_config["trace_mode"] = "on"
        self.grouping_dimensions = grouping_dimensions or DEFAULT_DIMENSIONS
        self.quarantine = quarantine
        self.coverage_config = coverage_config
        # UI Mode always treats unregistered tags as a warning, never a
        # hard failure, regardless of pyrunner.toml's strict_tags --
        # blocking the whole live UI because of a config strictness
        # setting would be a bad local-dev experience, and strict mode's
        # "zero tests run" purpose is a CI-gating concern the CLI path
        # already covers. Force a non-strict copy here rather than
        # trusting every caller to pass one in already non-strict.
        self.tag_registry = (
            dataclasses.replace(tag_registry, strict=False) if tag_registry is not None else None
        )

        self._lock = threading.Lock()
        self._status = STATUS_IDLE
        self._thread = None
        self._cancel_event = None
        self._last_results = {}
        self.trace_viewer = PersistentTraceViewer()
        self.last_traced_test_id = None

        self._subscribers = []
        self._subscribers_lock = threading.Lock()

        self._discover()

    def _discover(self):
        """Imports test/conftest modules once at startup so list_tests()
        works before any run has happened. Re-importing an
        already-imported module is a no-op (sys.modules cache), so this
        is safe to call again without duplicating registered tests."""
        discover_and_import(self.root)

        if self.tag_registry is not None:
            unregistered = validate_tags(get_tests(), self.tag_registry)
            if unregistered:
                print(f"Warning: {format_unregistered_tags_warning(unregistered)}", file=sys.stderr)

    def list_tests(self) -> list:
        return [
            {
                "id": t.id,
                "caseId": t.case_id,
                "tags": sorted(t.tags),
                "groups": compute_groups(t, self.grouping_dimensions, self.root),
            }
            for t in get_tests()
        ]

    def dimension_names(self) -> list:
        return [d.name for d in self.grouping_dimensions]

    def last_results_snapshot(self) -> dict:
        """Every test's most recent result keyed by test id, accumulated
        across runs (not just the latest one), in the same shape as a
        `test_end` SSE event -- lets the frontend restore the full test
        list's dots/details after a page reload, even if the tests were
        run individually across several separate runs rather than all at
        once."""
        # _last_results is written from the background run thread
        # (see start_run()'s _run()) while this can be called from the
        # HTTP-handling thread at any time -- without sharing the same
        # lock every sibling structure here already uses, a snapshot
        # mid-write could raise "dictionary changed size during
        # iteration".
        with self._lock:
            items = list(self._last_results.items())
        return {tid: _result_to_event(r) for tid, r in items}

    def _on_trace_ready(self, test_id: str, path: str) -> None:
        self.last_traced_test_id = test_id
        self.trace_viewer.load_trace(path)

    def set_num_workers(self, n) -> None:
        """Takes effect on the next start_run() call -- each run
        constructs a fresh Orchestrator from self.num_workers, so there's
        nothing to do to an in-flight run. Accepts every num_workers
        spelling ('auto', 'N%', positive int); anything else raises
        ValueError (resolve_num_workers rejects bools/floats/other
        strings; None is rejected here rather than defaulting to auto --
        a caller passing None is a bug, e.g. a null in the UI's POST
        body, not a request for auto)."""
        if n is None:
            raise ValueError("num_workers must be a positive integer, 'auto', or 'N%', got None")
        self.num_workers = resolve_num_workers(n)
        self.num_workers_setting = n

    def get_status(self) -> dict:
        with self._lock:
            return {"status": self._status}

    def subscribe(self) -> "queue.Queue":
        q = queue.Queue()
        with self._subscribers_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._subscribers_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _broadcast(self, event: dict) -> None:
        with self._subscribers_lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(event)

    def start_run(self, test_ids=None, case_ids=None, tags=None) -> bool:
        """Returns False (does nothing) if a run is already in progress."""
        with self._lock:
            if self._status == STATUS_RUNNING:
                return False
            self._status = STATUS_RUNNING
            self._cancel_event = threading.Event()
            cancel_event = self._cancel_event

        # Started synchronously here (not inside _run()'s background
        # thread) so it's guaranteed ready -- or definitively failed to
        # start -- before the first test_start/test_end event can
        # possibly fire, and the traceViewerUrl on this run's run_start
        # event is always accurate.
        self.trace_viewer.start()

        def _run():
            try:
                # The registry already holds this process's __init__-time
                # _discover() registrations; force_reload=True below
                # importlib.reload()s those same already-imported
                # modules, re-executing their @test decorators -- without
                # clearing first, that's a second registration of every
                # test, tripping the duplicate-id guard. Same
                # clear-then-force-reload pairing projects.py's
                # run_projects() uses between projects.
                clear_tests()
                if self.coverage_config is not None:
                    from .coverage_support import prepare_data_dir

                    prepare_data_dir(self.coverage_config)
                orch = Orchestrator(
                    self.root,
                    self.num_workers,
                    self.default_timeout,
                    test_ids=test_ids,
                    case_ids=case_ids,
                    tags=tags,
                    console_reporters=[
                        LiveEventReporter(
                            self._broadcast,
                            trace_viewer_url=self.trace_viewer.url,
                            on_trace=self._on_trace_ready,
                        )
                    ],
                    cancel_event=cancel_event,
                    playwright_config=self.playwright_config,
                    tag_registry=self.tag_registry,
                    grouping_dimensions=self.grouping_dimensions,
                    quarantine=self.quarantine,
                    coverage_config=self.coverage_config,
                    # Re-discover on every run (not just once at server
                    # startup) so test files edited while the UI server
                    # has been sitting open get picked up -- matching
                    # the two sibling force_reload=True call sites
                    # (cli.py's --project and --last-failed paths).
                    force_reload=True,
                    worker_constraints=self.worker_constraints,
                    fully_parallel=self.fully_parallel,
                    strict_teardown=self.strict_teardown,
                )
                reporter = orch.run()
                if self.coverage_config is not None:
                    from .coverage_support import finalize_coverage

                    summary = finalize_coverage(self.coverage_config)
                    self._broadcast(
                        {
                            "type": "coverage_ready",
                            "percent": summary.percent,
                            "htmlDir": summary.html_dir,
                        }
                    )
                with self._lock:
                    for r in reporter.results:
                        self._last_results[r.test_id] = r
            except Exception as e:
                # Every run_start must be paired with a terminal event --
                # the frontend only re-enables its controls on run_end,
                # so an exception here (with no except, only finally)
                # used to wedge the UI forever until a manual reload.
                self._broadcast(
                    {
                        "type": "run_end",
                        "duration": 0.0,
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": str(e),
                    }
                )
            finally:
                with self._lock:
                    self._status = STATUS_IDLE

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        """Test helper: blocks until the current run finishes or timeout
        elapses. Returns True if idle, False if it timed out."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.get_status()["status"] == STATUS_IDLE:
                return True
            time.sleep(0.05)
        return False
