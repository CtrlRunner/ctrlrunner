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
        self.assertIn("      boom", output)

    def test_prints_multiline_error_indented_under_failure(self):
        reporter = DotsReporter()
        results = [
            Result(
                test_id="mod::c",
                outcome="failed",
                error="Traceback (most recent call last):\n  File x\nValueError: boom",
                duration=0.1,
            ),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            for r in results:
                reporter.on_test_end(r)
            reporter.on_run_end(results, 0.5)
        output = buf.getvalue()
        self.assertIn("  ✗ mod::c", output)
        self.assertIn("      Traceback (most recent call last):", output)
        self.assertIn("        File x", output)
        self.assertIn("      ValueError: boom", output)

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
        self.assertIn("      boom", output)

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
                    groups={"file": "mod.py", "team": "backend"},
                )
            ]
            reporter.on_run_end(results, 1.0)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["tests"][0]["groups"], {"file": "mod.py", "team": "backend"})

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


class SummaryLinesConsoleCapturedTests(unittest.TestCase):
    def test_console_captured_appears_indented_under_the_failure(self):
        from ctrlrunner.reporting.reporters import _summary_lines

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
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "failed", "boom", 0.1)]
        lines = _summary_lines(results, 1.0)
        joined = "\n".join(lines)
        self.assertNotIn("Captured stdout", joined)


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

    def test_dots_reporter_verbose_prints_a_line_per_test_including_passes(self):
        reporter = DotsReporter(verbosity="verbose")
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            reporter.on_test_end(Result("t::test_a", "passed", None, 0.1))
            reporter.on_test_end(Result("t::test_b", "failed", "boom", 0.1))
        finally:
            sys.stdout = old_stdout
        out = buf.getvalue()
        self.assertIn("PASSED t::test_a", out)
        self.assertIn("FAILED t::test_b", out)

    def test_dots_reporter_quiet_prints_nothing_per_test(self):
        reporter = DotsReporter(verbosity="quiet")
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            reporter.on_test_end(Result("t::test_a", "failed", "boom", 0.1))
        finally:
            sys.stdout = old_stdout
        self.assertEqual(buf.getvalue(), "")

    def test_quiet_summary_omits_error_text_and_by_file_table(self):
        from ctrlrunner.reporting.reporters import _summary_lines

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


class ReportCharsTests(unittest.TestCase):
    def test_default_omitted_matches_todays_output(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "failed", "boom", 0.1)]
        default = _summary_lines(results, 1.0)
        explicit_f = _summary_lines(results, 1.0, report_chars="f")
        self.assertEqual(default, explicit_f)

    def test_f_char_required_for_error_text_under_quiet(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "failed", "boom", 0.1)]
        quiet_no_r = _summary_lines(results, 1.0, verbosity="quiet")
        quiet_with_f = _summary_lines(results, 1.0, verbosity="quiet", report_chars="f")
        self.assertNotIn("boom", "\n".join(quiet_no_r))
        self.assertIn("boom", "\n".join(quiet_with_f))

    def test_s_char_lists_skipped_tests(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="s")
        joined = "\n".join(lines)
        self.assertIn("test_a", joined)
        self.assertIn("not ready", joined)

    def test_no_s_section_without_the_char(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="f")
        self.assertNotIn("not ready", "\n".join(lines))

    def test_x_char_lists_expected_failures(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "expected_failure", "known issue", 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="x")
        self.assertIn("known issue", "\n".join(lines))

    def test_p_char_lists_passed_test_ids(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_a", "passed", None, 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="p")
        self.assertIn("test_a", "\n".join(lines))

    def test_w_char_lists_warnings(self):
        from ctrlrunner.reporting.reporters import _summary_lines

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
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [
            Result("t::test_f", "failed", "boom", 0.1),
            Result("t::test_s", "skipped", "why", 0.1),
        ]
        lines = _summary_lines(results, 1.0, report_chars="a")
        joined = "\n".join(lines)
        self.assertIn("boom", joined)
        self.assertIn("why", joined)

    def test_capital_a_includes_passed(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        results = [Result("t::test_p", "passed", None, 0.1)]
        lines = _summary_lines(results, 1.0, report_chars="A")
        self.assertIn("test_p", "\n".join(lines))

    def test_build_reporters_threads_report_chars(self):
        reporters = build_reporters(["line"], report_chars="fs")
        self.assertEqual(reporters[0].report_chars, "fs")

    def test_dots_reporter_on_run_end_threads_report_chars(self):
        # DotsReporter.on_run_end and LineReporter.on_run_end are two
        # structurally-parallel call sites that both forward
        # self.report_chars into _summary_lines() -- the brief's tests
        # above only exercise _summary_lines() directly plus
        # build_reporters()'s attribute threading onto "line", so
        # neither on_run_end call site actually proves the constructor
        # arg makes it into the printed summary. Cover both here.
        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        reporter = DotsReporter(report_chars="s")
        buf = io.StringIO()
        with redirect_stdout(buf):
            reporter.on_run_end(results, 1.0)
        self.assertIn("not ready", buf.getvalue())

    def test_line_reporter_on_run_end_threads_report_chars(self):
        results = [Result("t::test_a", "skipped", "not ready", 0.1)]
        reporter = LineReporter(report_chars="s")
        buf = io.StringIO()
        with redirect_stdout(buf):
            reporter.on_run_end(results, 1.0)
        self.assertIn("not ready", buf.getvalue())

    def test_capital_p_prints_captured_stdout_for_passed_test(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        # Review gap (Task 9): the "P" in chars and r.logs branch that
        # walks Result.logs entries and prints entry["stdout"] had zero
        # coverage. Build a Result the way worker.py's captured_logs /
        # final_logs would populate it -- a list of per-attempt dicts.
        results = [
            Result(
                "t::test_a",
                "passed",
                None,
                0.1,
                logs=[{"attempt": 1, "stdout": "hello from a passed test", "stderr": ""}],
            )
        ]
        lines = _summary_lines(results, 1.0, report_chars="P")
        joined = "\n".join(lines)
        self.assertIn("test_a", joined)
        self.assertIn("hello from a passed test", joined)

    def test_lowercase_p_does_not_print_captured_stdout(self):
        from ctrlrunner.reporting.reporters import _summary_lines

        # Proves the capital/lowercase distinction is real: lowercase "p"
        # lists the passed test id but must never dump its logs, even
        # when logs are populated.
        results = [
            Result(
                "t::test_a",
                "passed",
                None,
                0.1,
                logs=[{"attempt": 1, "stdout": "hello from a passed test", "stderr": ""}],
            )
        ]
        lines = _summary_lines(results, 1.0, report_chars="p")
        joined = "\n".join(lines)
        self.assertIn("test_a", joined)
        self.assertNotIn("hello from a passed test", joined)


if __name__ == "__main__":
    unittest.main()
