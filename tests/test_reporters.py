import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ctrlrunner.reporting.reporter import Result
from ctrlrunner.reporting.reporters import DotsReporter, JsonReporter, LineReporter, build_reporters


def _results():
    return [
        Result(test_id="mod::a", outcome="passed", error=None, duration=0.1, case_id="TC-1"),
        Result(
            test_id="mod::b",
            outcome="failed",
            error="boom",
            duration=0.2,
            case_id="TC-2",
            tags=("smoke",),
            attempts=2,
            artifacts=("shot.png",),
        ),
    ]


def _results_with_annotations():
    return [
        Result(test_id="mod::skip", outcome="skipped", error="n/a", duration=0.0),
        Result(test_id="mod::fixme", outcome="fixme", error="todo", duration=0.0),
        Result(test_id="mod::xfail", outcome="expected_failure", error="known bug", duration=0.1),
        Result(test_id="mod::pass", outcome="passed", error=None, duration=0.1),
        Result(test_id="mod::fail", outcome="failed", error="boom", duration=0.1),
    ]


class DotsReporterTests(unittest.TestCase):
    def test_prints_dot_and_f(self):
        reporter = DotsReporter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            for r in _results():
                reporter.on_test_end(r)
            reporter.on_run_end(_results(), 1.5)
        output = buf.getvalue()
        self.assertTrue(output.startswith(".F"))
        self.assertIn("2 tests, 1 passed, 1 failed", output)
        self.assertIn("mod::b", output)

    def test_prints_distinct_symbols_for_skip_fixme_xfail(self):
        reporter = DotsReporter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            for r in _results_with_annotations():
                reporter.on_test_end(r)
            reporter.on_run_end(_results_with_annotations(), 1.0)
        output = buf.getvalue()
        self.assertTrue(output.startswith("sfx.F"))
        summary_line = output.splitlines()[1]
        self.assertIn("2 skipped", summary_line)
        self.assertIn("1 expected failures", summary_line)


class LineReporterTests(unittest.TestCase):
    def test_shows_progress_and_failures(self):
        reporter = LineReporter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            reporter.on_run_start(2)
            reporter.on_test_start("mod::a")
            reporter.on_test_end(_results()[0])
            reporter.on_test_start("mod::b")
            reporter.on_test_end(_results()[1])
            reporter.on_run_end(_results(), 1.0)
        output = buf.getvalue()
        self.assertIn("[1/2] mod::a", output)
        self.assertIn("[2/2] mod::b", output)
        self.assertIn("\u2717 mod::b", output)
        self.assertIn("1 passed, 1 failed", output)

    def test_retry_attempts_do_not_inflate_counter_past_total(self):
        reporter = LineReporter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            reporter.on_run_start(1)
            reporter.on_test_start("mod::flaky")  # attempt 1
            reporter.on_test_start("mod::flaky")  # attempt 2 (retry)
            reporter.on_test_start("mod::flaky")  # attempt 3 (retry)
        output = buf.getvalue()
        self.assertNotIn("[2/1]", output)
        self.assertNotIn("[3/1]", output)
        self.assertIn("[1/1] mod::flaky", output)

    def test_reset_clears_seen_so_a_reused_instance_does_not_overshoot(self):
        # The reporter instance is reused across projects in a
        # multi-project run; without reset(), _seen keeps accumulating
        # test_ids from earlier projects and the progress counter
        # overshoots the second project's total (e.g. "[26/25]").
        reporter = LineReporter()
        buf = io.StringIO()
        with redirect_stdout(buf):
            reporter.on_run_start(25)
            for i in range(25):
                reporter.on_test_start(f"mod::project1_test_{i}")
        self.assertEqual(len(reporter._seen), 25)

        reporter.reset()
        self.assertEqual(reporter._seen, set())

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            reporter.on_run_start(3)
            reporter.on_test_start("mod::project2_test_0")
        output2 = buf2.getvalue()
        self.assertIn("[1/3]", output2)
        self.assertNotIn("[26/25]", output2)


class JsonReporterTests(unittest.TestCase):
    def test_writes_expected_schema(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            reporter.on_run_end(_results(), 2.5)

            payload = json.loads(path.read_text())
            self.assertEqual(payload["stats"]["total"], 2)
            self.assertEqual(payload["stats"]["passed"], 1)
            self.assertEqual(payload["stats"]["failed"], 1)

            by_id = {t["id"]: t for t in payload["tests"]}
            self.assertEqual(by_id["mod::a"]["caseId"], "TC-1")
            self.assertEqual(by_id["mod::b"]["attempts"], 2)
            self.assertEqual(by_id["mod::b"]["artifacts"], ["shot.png"])
            self.assertEqual(by_id["mod::b"]["error"], "boom")

    def test_warnings_field_serialized(self):
        # Result.warnings reaches the JSON report.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            warns = [
                {
                    "attempt": 1,
                    "category": "DeprecationWarning",
                    "message": "legacy",
                    "filename": "t.py",
                    "lineno": 3,
                }
            ]
            results = [
                Result(test_id="mod::a", outcome="passed", error=None, duration=0.1, warnings=warns)
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["tests"][0]["warnings"], warns)

    def test_tests_array_sorted_by_project_then_id(self):
        # Report order must not depend on worker completion
        # timing -- identical runs must produce diff-identical reports.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            results = [
                Result(test_id="mod::b", outcome="passed", error=None, duration=0.1),
                Result(test_id="mod::a", outcome="passed", error=None, duration=0.1),
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual([t["id"] for t in payload["tests"]], ["mod::a", "mod::b"])

    def test_groups_field_is_serialized(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            results = [
                Result(
                    test_id="mod::a",
                    outcome="passed",
                    error=None,
                    duration=0.1,
                    groups={"module": "mod", "team": "backend"},
                )
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["tests"][0]["groups"], {"module": "mod", "team": "backend"})

    def test_project_field_and_top_level_projects_list(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            results = [
                Result(
                    test_id="[smoke] mod::a",
                    outcome="passed",
                    error=None,
                    duration=0.1,
                    project="smoke",
                ),
                Result(
                    test_id="[regression] mod::b",
                    outcome="passed",
                    error=None,
                    duration=0.1,
                    project="regression",
                ),
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["projects"], ["regression", "smoke"])
            # tests array is sorted by (project, id), so look
            # the entry up by id instead of relying on arrival position.
            by_id = {t["id"]: t for t in payload["tests"]}
            self.assertEqual(by_id["[smoke] mod::a"]["project"], "smoke")

    def test_projects_list_empty_when_no_project_set(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            reporter.on_run_end(_results(), 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["projects"], [])

    def test_stats_include_skipped_and_expected_failures(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            reporter.on_run_end(_results_with_annotations(), 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["stats"]["skipped"], 2)
            self.assertEqual(payload["stats"]["expectedFailures"], 1)
            self.assertEqual(payload["stats"]["passed"], 1)
            self.assertEqual(payload["stats"]["failed"], 1)

    def test_worker_restart_overhead_field_is_serialized(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            results = [
                Result(
                    test_id="mod::a",
                    outcome="passed",
                    error=None,
                    duration=0.1,
                    worker_restart_overhead=1.23,
                )
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["tests"][0]["workerRestartOverhead"], 1.23)

    def test_write_is_atomic_and_never_leaves_a_partial_file_on_crash(self):
        # results.json was written non-atomically -- a crash
        # mid-write (disk full, process killed) would leave a truncated
        # or half-written file, or clobber a previously good report.
        # Writing to a temp file in the same directory then os.replace()
        # over the final path means the final path only ever shows the
        # old complete file or the new complete file, never a partial
        # one.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            path.write_text('{"stats": {"total": 0}}')  # pre-existing "old" report
            reporter = JsonReporter(str(path))

            with (
                patch(
                    "ctrlrunner.reporting.reporters.json.dump",
                    side_effect=RuntimeError("simulated crash mid-write"),
                ),
                self.assertRaises(RuntimeError),
            ):
                reporter.on_run_end(_results(), 1.0)

            # the crash must not have clobbered the existing good file
            self.assertEqual(path.read_text(), '{"stats": {"total": 0}}')
            # and no stray temp file should be left behind in the dir
            leftover = [p.name for p in Path(tmp).iterdir() if p.name != "results.json"]
            self.assertEqual(leftover, [])

    def test_write_still_produces_correct_file_on_success(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            reporter.on_run_end(_results(), 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["stats"]["total"], 2)
            leftover = [p.name for p in Path(tmp).iterdir() if p.name != "results.json"]
            self.assertEqual(leftover, [])

    def test_coverage_summary_merged_into_stats_when_set(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            summary = SimpleNamespace(percent=87.5, by_file={"a.py": 90.0})
            reporter.set_coverage_summary(summary)
            reporter.on_run_end([], 1.0)

            payload = json.loads(path.read_text())
            self.assertEqual(payload["stats"]["coveragePercent"], 87.5)
            self.assertEqual(payload["stats"]["coverageByFile"], {"a.py": 90.0})

    def test_coverage_summary_absent_by_default(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            reporter.on_run_end([], 1.0)

            payload = json.loads(path.read_text())
            self.assertNotIn("coveragePercent", payload["stats"])
            self.assertNotIn("coverageByFile", payload["stats"])

    def test_coverage_by_file_omitted_when_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "results.json"
            reporter = JsonReporter(str(path))
            summary = SimpleNamespace(percent=100.0, by_file=None)
            reporter.set_coverage_summary(summary)
            reporter.on_run_end([], 1.0)

            payload = json.loads(path.read_text())
            self.assertEqual(payload["stats"]["coveragePercent"], 100.0)
            self.assertNotIn("coverageByFile", payload["stats"])


class BuildReportersTests(unittest.TestCase):
    def test_builds_requested_reporters_in_order(self):
        reporters = build_reporters(["line", "dots"])
        self.assertIsInstance(reporters[0], LineReporter)
        self.assertIsInstance(reporters[1], DotsReporter)

    def test_json_reporter_gets_output_path(self):
        reporters = build_reporters(["json"], json_output="custom.json")
        self.assertEqual(reporters[0].output_path, "custom.json")

    def test_unknown_reporter_name_raises(self):
        with self.assertRaises(ValueError):
            build_reporters(["not-a-real-reporter"])


class SummaryLinesFlakyTests(unittest.TestCase):
    def test_flaky_count_appears_in_summary(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [
            Result(test_id="m::a", outcome="passed", error=None, duration=0.1, flaky=True),
            Result(test_id="m::b", outcome="passed", error=None, duration=0.1, flaky=False),
        ]
        lines = _summary_lines(results, 1.0)
        self.assertIn("1 flaky", lines[0])

    def test_no_flaky_segment_when_zero(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result(test_id="m::a", outcome="passed", error=None, duration=0.1)]
        lines = _summary_lines(results, 1.0)
        self.assertNotIn("flaky", lines[0])


class SummaryLinesModuleBreakdownTests(unittest.TestCase):
    def test_breakdown_table_appears_with_two_or_more_modules(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [
            Result(
                test_id="mod_a::test_1",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"module": "mod_a"},
            ),
            Result(
                test_id="mod_a::test_2",
                outcome="failed",
                error="x",
                duration=0.1,
                groups={"module": "mod_a"},
            ),
            Result(
                test_id="mod_b::test_1",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"module": "mod_b"},
            ),
        ]
        lines = _summary_lines(results, 1.0)
        joined = "\n".join(lines)
        self.assertIn("mod_a", joined)
        self.assertIn("mod_b", joined)

    def test_no_breakdown_table_with_a_single_module(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [
            Result(
                test_id="mod_a::test_1",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"module": "mod_a"},
            ),
        ]
        lines = _summary_lines(results, 1.0)
        joined = "\n".join(lines)
        self.assertNotIn("mod_a", joined)

    def test_no_breakdown_table_when_groups_missing(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result(test_id="m::t", outcome="passed", error=None, duration=0.1)]
        lines = _summary_lines(results, 1.0)
        self.assertTrue(lines)


class CustomReporterLoaderTests(unittest.TestCase):
    """--reporter accepts 'module.path:ClassName'
    specs -- the class is imported and instantiated with no arguments.
    Load-time errors surface as ValueError, same as any bad --reporter
    value; runtime errors are already contained by the orchestrator's
    _safe_console_call."""

    def _write_module(self, tmp, body):
        Path(tmp, "custom_rep_mod.py").write_text(body)
        sys.path.insert(0, tmp)
        self.addCleanup(sys.path.remove, tmp)
        self.addCleanup(sys.modules.pop, "custom_rep_mod", None)

    def test_loads_reporter_from_module_colon_class_spec(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self._write_module(
                tmp,
                "class MyReporter:\n"
                "    def on_run_start(self, total): pass\n"
                "    def on_test_start(self, test_id): pass\n"
                "    def on_test_end(self, result): pass\n"
                "    def on_run_end(self, results, duration): pass\n",
            )
            reporters = build_reporters(["custom_rep_mod:MyReporter"])
        self.assertEqual(type(reporters[0]).__name__, "MyReporter")

    def test_unimportable_module_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            build_reporters(["no_such_module_xyz:Reporter"])
        self.assertIn("no_such_module_xyz", str(ctx.exception))

    def test_missing_class_raises_value_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self._write_module(tmp, "x = 1\n")
            with self.assertRaises(ValueError) as ctx:
                build_reporters(["custom_rep_mod:NoSuchClass"])
        self.assertIn("NoSuchClass", str(ctx.exception))

    def test_constructor_error_raises_value_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self._write_module(
                tmp,
                "class NeedsArgs:\n    def __init__(self, required): pass\n",
            )
            with self.assertRaises(ValueError) as ctx:
                build_reporters(["custom_rep_mod:NeedsArgs"])
        self.assertIn("no arguments", str(ctx.exception))

    def test_plain_unknown_name_error_unchanged(self):
        with self.assertRaises(ValueError):
            build_reporters(["definitely-not-a-reporter"])


if __name__ == "__main__":
    unittest.main()
