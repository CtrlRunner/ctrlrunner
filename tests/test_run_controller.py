import os
import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ctrlrunner.execution.coverage_support import CoverageConfig
from ctrlrunner.execution.orchestrator import discover_and_import
from ctrlrunner.execution.run_controller import (
    STATUS_IDLE,
    STATUS_RUNNING,
    LiveEventReporter,
    RunController,
)


class RunControllerTests(unittest.TestCase):
    def _make(self):
        return RunController("examples", num_workers=2, default_timeout=30.0)

    def _drain_until(self, q, event_type, timeout=10):
        """Collects broadcast events off `q` (keyed by their "type") until
        one matching `event_type` shows up -- mirrors the manual
        while-loop-until-run_end pattern the other tests in this class
        already use (see test_subscriber_receives_run_lifecycle_events),
        but keyed into a dict since coverage_ready arrives strictly after
        run_end and callers need to assert on either."""
        events = {}
        while event_type not in events:
            ev = q.get(timeout=timeout)
            events[ev["type"]] = ev
        return events

    def _make_coverage_test_dir(self, name):
        """A throwaway one-test suite, isolated from "examples" (used by
        every other test in this class), so a real coverage run has
        something small and fast to measure. `name` becomes the suite's
        subdirectory (and hence its dotted module name, e.g.
        "<name>.test_demo") -- each caller must pass a distinct value
        (mirrors test_orchestrator_and_worker.py's CoverageIntegrationTests
        using "tests"/"tests3"/"tests4" per test) so two suites created in
        the same process never register the same test id; the registry is
        one process-wide list, and without unique dotted names, a second
        suite's plain (non-force) __init__ discovery would collide with
        an earlier suite's still-registered id and raise "Duplicate test
        id". Returns the suite's root dir; the caller owns constructing a
        RunController against it."""
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        # start_run() calls clear_tests() then re-discovers with
        # force_reload=True scoped to whatever root the RunController
        # under test points at -- for this tmp dir, that correctly wipes
        # and repopulates only this suite's one test. But it also wipes
        # "examples"' registrations globally (the registry is one
        # process-wide list), and unlike this tmp dir, "examples" won't
        # get re-imported by a later test's plain (non-force) __init__
        # discovery, since it's already in sys.modules -- leaving
        # later tests in this class (e.g. test_list_tests_discovers_
        # without_running_anything, alphabetically after this one) with
        # a stale/empty registry. Restore it explicitly.
        self.addCleanup(discover_and_import, "examples", force_reload=True)

        test_dir = os.path.join(tmp_dir, name)
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "test_demo.py"), "w") as f:
            f.write("from ctrlrunner import test\n\n@test()\ndef test_ok():\n    assert 1 == 1\n")
        return tmp_dir, test_dir

    def test_coverage_ready_event_broadcast_when_enabled(self):
        tmp_dir, test_dir = self._make_coverage_test_dir("tests_coverage_enabled")
        data_dir = os.path.join(tmp_dir, ".coverage-data")
        os.makedirs(data_dir)
        coverage_config = CoverageConfig(
            enabled=True,
            data_dir=data_dir,
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )
        controller = RunController(test_dir, num_workers=1, coverage_config=coverage_config)
        q = controller.subscribe()
        controller.start_run()
        events = self._drain_until(q, "coverage_ready")
        self.assertIn("percent", events["coverage_ready"])
        self.assertTrue(controller.wait_until_idle(timeout=10))

    def test_no_coverage_ready_event_when_disabled(self):
        _tmp_dir, test_dir = self._make_coverage_test_dir("tests_coverage_disabled")
        controller = RunController(test_dir, num_workers=1)
        q = controller.subscribe()
        controller.start_run()
        events = self._drain_until(q, "run_end")
        self.assertNotIn("coverage_ready", events)
        self.assertTrue(controller.wait_until_idle(timeout=10))

    def test_list_tests_discovers_without_running_anything(self):
        rc = self._make()
        tests = rc.list_tests()
        self.assertGreater(len(tests), 0)
        self.assertTrue(all("id" in t and "caseId" in t and "tags" in t for t in tests))

    def test_initial_status_is_idle(self):
        rc = self._make()
        self.assertEqual(rc.get_status(), {"status": STATUS_IDLE})

    def test_start_run_transitions_to_running_then_back_to_idle(self):
        rc = self._make()
        started = rc.start_run(case_ids=["TC-001"])
        self.assertTrue(started)
        self.assertEqual(rc.get_status()["status"], STATUS_RUNNING)
        self.assertTrue(rc.wait_until_idle(timeout=10))
        self.assertEqual(rc.get_status(), {"status": STATUS_IDLE})

    def test_start_run_returns_false_if_already_running(self):
        rc = self._make()
        self.assertTrue(rc.start_run(case_ids=["TC-001"]))
        self.assertFalse(rc.start_run(case_ids=["TC-002"]))
        rc.wait_until_idle(timeout=10)

    def test_subscriber_receives_run_lifecycle_events(self):
        rc = self._make()
        q = rc.subscribe()
        rc.start_run(case_ids=["TC-001"])

        events = []
        while True:
            ev = q.get(timeout=10)
            events.append(ev)
            if ev["type"] == "run_end":
                break

        types = [e["type"] for e in events]
        self.assertEqual(types[0], "run_start")
        self.assertIn("test_start", types)
        self.assertIn("test_end", types)
        self.assertEqual(types[-1], "run_end")
        rc.wait_until_idle(timeout=10)

    def test_unsubscribe_stops_further_events(self):
        rc = self._make()
        q = rc.subscribe()
        rc.unsubscribe(q)
        rc.start_run(case_ids=["TC-001"])
        rc.wait_until_idle(timeout=10)
        self.assertTrue(q.empty())

    def test_cancel_stops_a_running_run(self):
        import time

        rc = self._make()
        rc.start_run(case_ids=["TC-003"])  # test_hangs: time.sleep(30)
        time.sleep(0.5)  # let the worker actually start the test first
        rc.cancel()
        self.assertTrue(rc.wait_until_idle(timeout=10))
        self.assertEqual(list(rc._last_results.values())[0].outcome, "cancelled")

    def test_list_tests_includes_groups_computed_by_default_module_dimension(self):
        rc = self._make()
        tests = rc.list_tests()
        self.assertTrue(all("groups" in t and "module" in t["groups"] for t in tests))

    def test_dimension_names_defaults_to_module(self):
        rc = self._make()
        self.assertEqual(rc.dimension_names(), ["module"])

    def test_custom_grouping_dimensions_used_for_list_and_names(self):
        from ctrlrunner.reporting.grouping import GroupingDimension

        dims = [GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"})]
        rc = RunController(
            "examples", num_workers=2, default_timeout=30.0, grouping_dimensions=dims
        )
        self.assertEqual(rc.dimension_names(), ["team"])
        tests = rc.list_tests()
        self.assertTrue(all("team" in t["groups"] for t in tests))
        self.assertTrue(all("module" not in t["groups"] for t in tests))

    def test_cancel_without_a_run_does_not_raise(self):
        rc = self._make()
        rc.cancel()  # no-op, must not crash

    def test_trace_mode_is_always_forced_on_regardless_of_input(self):
        rc = RunController(
            "examples",
            num_workers=2,
            default_timeout=30.0,
            playwright_config={"trace_mode": "off", "browser_name": "firefox"},
        )
        self.assertEqual(rc.playwright_config["trace_mode"], "on")
        self.assertEqual(rc.playwright_config["browser_name"], "firefox")

    def test_trace_mode_is_on_even_with_no_playwright_config(self):
        rc = self._make()
        self.assertEqual(rc.playwright_config["trace_mode"], "on")

    def test_options_default_to_empty_dict(self):
        rc = self._make()
        self.assertEqual(rc.options, {})

    def test_options_are_copied_not_referenced(self):
        source = {"env": "staging"}
        rc = RunController("examples", num_workers=2, default_timeout=30.0, options=source)
        source["env"] = "mutated"
        self.assertEqual(rc.options, {"env": "staging"})

    def test_set_num_workers_updates_num_workers(self):
        rc = self._make()
        rc.set_num_workers(5)
        self.assertEqual(rc.num_workers, 5)
        self.assertEqual(rc.num_workers_setting, 5)

    def test_default_num_workers_is_auto(self):
        with patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=9):
            rc = RunController("examples")
        self.assertEqual(rc.num_workers_setting, "auto")
        self.assertEqual(rc.num_workers, 8)

    def test_set_num_workers_accepts_auto_and_percent(self):
        rc = self._make()
        with patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=8):
            rc.set_num_workers("auto")
            self.assertEqual(rc.num_workers, 7)
            self.assertEqual(rc.num_workers_setting, "auto")
            rc.set_num_workers("50%")
            self.assertEqual(rc.num_workers, 4)
            self.assertEqual(rc.num_workers_setting, "50%")

    def test_set_num_workers_rejects_non_positive_or_non_int(self):
        rc = self._make()
        for bad in (0, -1, "3", 1.5, None):
            with self.assertRaises(ValueError):
                rc.set_num_workers(bad)

    @patch("ctrlrunner.execution.run_controller.PersistentTraceViewer.start", return_value=True)
    def test_start_run_starts_the_trace_viewer(self, mock_start):
        rc = self._make()
        rc.start_run(case_ids=["TC-001"])
        mock_start.assert_called_once()
        rc.wait_until_idle(timeout=10)

    def _fake_result(self, artifacts):
        return SimpleNamespace(
            test_id="mod::test",
            outcome="passed",
            duration=0.1,
            case_id=None,
            error=None,
            artifacts=artifacts,
            steps=[],
            groups={},
            quarantined=False,
            quarantine_reason=None,
            near_timeout=False,
            assert_details=None,
            logs=None,
        )

    def test_live_event_reporter_on_trace_fires_for_zip_artifact(self):
        on_trace = MagicMock()
        reporter = LiveEventReporter(broadcast=lambda ev: None, on_trace=on_trace)
        reporter.on_test_end(self._fake_result(["some/screenshot.png", "some/trace.zip"]))
        on_trace.assert_called_once_with("mod::test", "some/trace.zip")

    def test_live_event_reporter_on_trace_not_called_without_zip(self):
        on_trace = MagicMock()
        reporter = LiveEventReporter(broadcast=lambda ev: None, on_trace=on_trace)
        reporter.on_test_end(self._fake_result(["some/screenshot.png"]))
        on_trace.assert_not_called()

    def test_live_event_reporter_run_start_broadcasts_trace_viewer_url(self):
        events = []
        reporter = LiveEventReporter(
            broadcast=events.append, trace_viewer_url="http://127.0.0.1:1/"
        )
        reporter.on_run_start(3)
        self.assertEqual(events[0]["traceViewerUrl"], "http://127.0.0.1:1/")

    def test_live_event_reporter_includes_assert_details(self):
        events = []
        reporter = LiveEventReporter(broadcast=events.append)
        result = self._fake_result([])
        result.assert_details = {"expr": "x == y"}
        reporter.on_test_end(result)
        self.assertEqual(events[-1]["assertDetails"], {"expr": "x == y"})

    def test_live_event_reporter_includes_logs(self):
        events = []
        reporter = LiveEventReporter(broadcast=events.append)
        result = self._fake_result([])
        result.logs = [
            {"attempt": 1, "stdout": "x", "stderr": "", "records": [], "truncated": False}
        ]
        reporter.on_test_end(result)
        self.assertEqual(events[-1]["logs"][0]["stdout"], "x")

    def test_on_trace_ready_updates_last_traced_test_id_and_loads_trace(self):
        rc = self._make()
        with patch.object(rc.trace_viewer, "load_trace", return_value=True) as mock_load:
            rc._on_trace_ready("mod::test", "some/trace.zip")
        self.assertEqual(rc.last_traced_test_id, "mod::test")
        mock_load.assert_called_once_with("some/trace.zip")

    def test_last_traced_test_id_defaults_to_none(self):
        rc = self._make()
        self.assertIsNone(rc.last_traced_test_id)

    def test_last_results_snapshot_empty_before_any_run(self):
        rc = self._make()
        self.assertEqual(rc.last_results_snapshot(), {})

    def test_last_results_snapshot_reflects_last_run(self):
        rc = self._make()
        rc.start_run(case_ids=["TC-001"])
        rc.wait_until_idle(timeout=10)
        snapshot = rc.last_results_snapshot()
        self.assertEqual(len(snapshot), 1)
        result = next(iter(snapshot.values()))
        self.assertEqual(result["type"], "test_end")
        self.assertIn("outcome", result)

    @patch("ctrlrunner.execution.run_controller.Orchestrator")
    def test_start_run_passes_force_reload_true_to_orchestrator(self, mock_orch_cls):
        # UI Mode discovers tests once at startup; without force_reload
        # on every run, test files edited after the server started are
        # never picked up (H9) -- the two sibling call sites
        # (cli.py's --project/--last-failed paths) both pass this.
        mock_orch = MagicMock()
        mock_orch.run.return_value = SimpleNamespace(results=[])
        mock_orch_cls.return_value = mock_orch

        rc = self._make()
        rc.start_run(case_ids=["TC-001"])
        rc.wait_until_idle(timeout=10)

        _, kwargs = mock_orch_cls.call_args
        self.assertTrue(kwargs.get("force_reload"))

    @patch("ctrlrunner.execution.run_controller.Orchestrator")
    def test_run_thread_exception_still_emits_terminal_event(self, mock_orch_cls):
        # If the run thread raises before reaching on_run_end, the
        # frontend's controls (only re-enabled on a terminal event)
        # would stay wedged in "running" forever with no way to start
        # another run short of a page reload.
        mock_orch = MagicMock()
        mock_orch.run.side_effect = RuntimeError("boom")
        mock_orch_cls.return_value = mock_orch

        rc = self._make()
        q = rc.subscribe()
        rc.start_run(case_ids=["TC-001"])

        self.assertTrue(rc.wait_until_idle(timeout=10))
        self.assertEqual(rc.get_status(), {"status": STATUS_IDLE})

        events = []
        while True:
            events.append(q.get(timeout=5))
            if events[-1]["type"] == "run_end":
                break
        self.assertIn("error", events[-1])

    def test_last_results_snapshot_accumulates_across_separate_runs(self):
        # Regression test: running tests one at a time (e.g. each row's
        # own "Run" button in UI Mode) must not make earlier runs'
        # results disappear from the snapshot used to restore the page
        # after a reload.
        rc = self._make()
        rc.start_run(case_ids=["TC-001"])
        rc.wait_until_idle(timeout=10)
        rc.start_run(case_ids=["TC-002"])
        rc.wait_until_idle(timeout=10)
        snapshot = rc.last_results_snapshot()
        self.assertEqual(len(snapshot), 2)


class LastResultsThreadSafetyTests(unittest.TestCase):
    """_last_results is written from the background run thread and
    read from last_results_snapshot() at any time -- without sharing
    the same lock, a snapshot mid-write can raise 'dictionary changed
    size during iteration'."""

    def test_concurrent_snapshot_reads_during_writes_do_not_raise(self):
        import sys

        rc = RunController.__new__(RunController)  # bypass __init__ (no discovery needed)
        rc._lock = threading.Lock()
        rc._last_results = {}
        errors = []

        def make_result(i):
            return SimpleNamespace(
                test_id=f"mod::test_{i}",
                outcome="passed",
                duration=0.0,
                case_id=None,
                error=None,
                artifacts=[],
                steps=[],
                groups={},
                quarantined=False,
                quarantine_reason=None,
                near_timeout=False,
                assert_details=None,
                logs=None,
            )

        def writer():
            for i in range(50000):
                with rc._lock:
                    rc._last_results[f"mod::test_{i}"] = make_result(i)

        def reader():
            for _ in range(2000):
                try:
                    rc.last_results_snapshot()
                except RuntimeError as e:
                    errors.append(e)

        # A tiny switch interval makes the parent thread's iteration
        # over _last_results far more likely to be preempted mid-loop
        # by the writer thread -- without it, this race can go
        # unnoticed for a very long time on a lightly-loaded machine
        # despite being a real bug (this is what actually surfaced it
        # in production: a busy UI Mode server, not a quiet dev box).
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-5)
        try:
            t1 = threading.Thread(target=writer)
            t2 = threading.Thread(target=reader)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        finally:
            sys.setswitchinterval(old_interval)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
