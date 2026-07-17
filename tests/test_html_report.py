import json
import re
import tempfile
import unittest
from importlib import resources
from pathlib import Path

from ctrlrunner.reporting.html_report import render_html
from ctrlrunner.reporting.reporter import Result


def _extract_embedded_data(html_str):
    m = re.search(r"window\.__CTRLRUNNER_REPORT__ = (.*?);</script>", html_str, re.DOTALL)
    # Undo the "</" -> "<\/" escaping applied to keep the JSON inert
    # inside its <script> tag; json.loads accepts "<\/" too, but be
    # explicit that the payload round-trips.
    return json.loads(m.group(1))


class PrebuiltPageTests(unittest.TestCase):
    """Guards for the committed Vite build (src/ctrlrunner/reporting/_static/).

    The page is built from frontend/ and committed; these catch the
    "changed frontend/src but forgot to run npm run build" failure mode.
    """

    def _page(self):
        return (
            resources.files("ctrlrunner.reporting")
            .joinpath("_static/report/index.html")
            .read_text(encoding="utf-8")
        )

    def test_prebuilt_page_exists_with_data_marker(self):
        page = self._page()
        self.assertIn("<!--CTRLRUNNER_DATA-->", page)

    def test_prebuilt_page_is_fully_inlined(self):
        # Match actual tags, not raw substrings: the inlined <style>
        # keeps a vestigial rel="stylesheet" attribute, and JS string
        # literals may legitimately contain 'src="'.
        page = self._page()
        self.assertIsNone(re.search(r"<script[^>]*\bsrc=", page))
        self.assertIsNone(re.search(r'<link[^>]*rel="stylesheet"', page))


class HtmlReportTests(unittest.TestCase):
    def test_embeds_all_results_as_json(self):
        results = [
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
        out = render_html(results, suite_name="my-suite")
        data = _extract_embedded_data(out)

        self.assertEqual(data["suiteName"], "my-suite")
        self.assertEqual(len(data["tests"]), 2)
        by_id = {t["id"]: t for t in data["tests"]}
        self.assertEqual(by_id["mod::a"]["caseId"], "TC-1")
        self.assertEqual(by_id["mod::b"]["attempts"], 2)
        # "shot.png" doesn't exist on disk in this test -> falls back to a
        # raw reference rather than being copied or embedded
        self.assertEqual(
            by_id["mod::b"]["artifacts"],
            [{"label": "shot.png", "href": "shot.png", "embedded": False}],
        )

    def test_script_suite_name_stays_inert_json(self):
        # The suite name reaches the page only through the JSON payload
        # (the React app sets document.title from it); a hostile name must
        # not be able to open a live <script> context of its own.
        out = render_html([], suite_name="<script>alert(1)</script>")
        data = _extract_embedded_data(out)
        self.assertEqual(data["suiteName"], "<script>alert(1)</script>")
        payload = out.split("window.__CTRLRUNNER_REPORT__ = ", 1)[1]
        self.assertNotIn("<script>alert(1)</script>", payload.split("</script>")[0])

    def test_js_line_separators_in_error_text_stay_inert_in_script(self):
        # U+2028/U+2029 are valid inside JSON strings but are *line
        # terminators* in JavaScript source: unescaped inside the inline
        # <script>, they end the statement mid-string and the whole
        # window.__CTRLRUNNER_REPORT__ assignment throws, blanking the
        # report. json.dumps leaves them raw, so render_html must escape
        # them explicitly (same class of guard as the "</" escaping).
        results = [
            Result(
                test_id="mod::a",
                outcome="failed",
                error="line1 line2 line3",
                duration=0.1,
            )
        ]
        out = render_html(results)
        # The payload must still round-trip...
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["error"], "line1 line2 line3")
        # ...and the raw separator chars must not appear anywhere in the
        # page (they're only ever introduced via the JSON payload).
        self.assertNotIn(" ", out)
        self.assertNotIn(" ", out)

    def test_script_tag_in_error_text_does_not_break_out_of_json_script(self):
        results = [
            Result(
                test_id="mod::a",
                outcome="failed",
                error="</script><script>evil()</script>",
                duration=0.1,
            )
        ]
        out = render_html(results)
        # the raw closing tag sequence must not appear unescaped inside the
        # embedded JSON blob (it's escaped to <\/script> to stay inside <script>)
        payload = out.split("window.__CTRLRUNNER_REPORT__ = ", 1)[1]
        self.assertNotIn("</script><script>evil()", payload.split("</script>")[0])

    def test_produces_a_single_self_contained_html_document(self):
        out = render_html([])
        self.assertTrue(out.strip().lower().startswith("<!doctype html>"))
        self.assertIn("<style", out)
        self.assertIn("<script", out)
        # no external script/style dependencies
        self.assertIsNone(re.search(r"<script[^>]*\bsrc=", out))
        self.assertIsNone(re.search(r'<link[^>]*rel="stylesheet"', out))

    def test_data_marker_is_consumed_by_injection(self):
        out = render_html([])
        self.assertNotIn("<!--CTRLRUNNER_DATA-->", out)
        self.assertIn("window.__CTRLRUNNER_REPORT__ = ", out)

    def test_empty_results_still_renders_valid_document(self):
        out = render_html([], suite_name="empty")
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"], [])

    def test_report_metadata_fields_present(self):
        results = [
            Result(test_id="mod::a", outcome="passed", error=None, duration=1.5),
            Result(test_id="mod::b", outcome="failed", error="x", duration=0.5),
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["totalDuration"], 2.0)
        self.assertIn("generatedAt", data)

    def test_run_level_timing_fields_embedded_when_passed(self):
        out = render_html(
            [],
            run_started_at=1000.0,
            run_duration=5.25,
            num_workers=4,
        )
        data = _extract_embedded_data(out)
        self.assertEqual(data["runStartedAt"], 1000.0)
        self.assertEqual(data["runDuration"], 5.25)
        self.assertEqual(data["numWorkers"], 4)

    def test_run_level_timing_fields_default_to_none(self):
        out = render_html([])
        data = _extract_embedded_data(out)
        self.assertIsNone(data["runStartedAt"])
        self.assertIsNone(data["runDuration"])
        self.assertIsNone(data["numWorkers"])

    def test_dimensions_list_reflects_result_groups_in_first_seen_order(self):
        results = [
            Result(
                test_id="mod::a",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"file": "mod.py", "team": "backend"},
            ),
            Result(
                test_id="mod::b",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"file": "mod.py", "team": "frontend", "owner": "bob"},
            ),
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["dimensions"], ["file", "team", "owner"])

    def test_dimensions_list_empty_when_no_groups_present(self):
        results = [Result(test_id="mod::a", outcome="passed", error=None, duration=0.1)]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["dimensions"], [])

    def test_groups_field_present_on_each_test(self):
        results = [
            Result(
                test_id="mod::a",
                outcome="passed",
                error=None,
                duration=0.1,
                groups={"file": "mod.py"},
            )
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["groups"], {"file": "mod.py"})

    def test_invalid_artifact_mode_raises(self):
        with self.assertRaises(ValueError):
            render_html([], artifact_mode="not-a-real-mode")

    def test_worker_restart_overhead_field_present_on_each_test(self):
        results = [
            Result(
                test_id="mod::a",
                outcome="passed",
                error=None,
                duration=0.1,
                worker_restart_overhead=1.23,
            )
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["workerRestartOverhead"], 1.23)

    def test_near_timeout_field_present_on_each_test(self):
        results = [
            Result(test_id="mod::a", outcome="passed", error=None, duration=1.9, near_timeout=True)
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertTrue(data["tests"][0]["nearTimeout"])

    def test_worker_id_flaky_and_started_at_fields_present_on_each_test(self):
        results = [
            Result(
                test_id="mod::a",
                outcome="passed",
                error=None,
                duration=0.5,
                worker_id=2,
                flaky=True,
                started_at=1000000.5,
            )
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        row = data["tests"][0]
        self.assertEqual(row["workerId"], 2)
        self.assertTrue(row["flaky"])
        self.assertEqual(row["startedAt"], 1000000.5)

    def test_near_timeout_badge_shipped_in_page(self):
        # The React renderer's badge label is a string literal that
        # survives minification -- its presence means the near-timeout
        # UI shipped in the self-contained document.
        out = render_html([])
        self.assertIn("near timeout", out)

    def test_embeds_assert_details_when_present(self):
        results = [
            Result(
                test_id="mod::c",
                outcome="failed",
                error="boom",
                duration=0.1,
                assert_details={"expr": "a == b", "op": "==", "left": {"repr": "1", "type": "int"}},
            ),
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["assertDetails"]["expr"], "a == b")

    def test_assert_details_rendering_is_present_in_page(self):
        # CSS class names are string literals in the bundle, stable under
        # minification (unlike the old renderAssertDetails() symbol names).
        out = render_html([])
        self.assertIn("assert-details", out)

    def test_embeds_logs_when_present(self):
        results = [
            Result(
                test_id="mod::d",
                outcome="failed",
                error="boom",
                duration=0.1,
                logs=[
                    {
                        "attempt": 1,
                        "stdout": "captured output",
                        "stderr": "",
                        "records": [],
                        "truncated": False,
                    }
                ],
            ),
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["logs"][0]["stdout"], "captured output")

    def test_logs_rendering_is_present_in_page(self):
        out = render_html([])
        self.assertIn("test-logs", out)

    def test_embeds_warnings_when_present(self):
        results = [
            Result(
                test_id="mod::e",
                outcome="failed",
                error="boom",
                duration=0.1,
                warnings=[
                    {
                        "attempt": 1,
                        "category": "RuntimeWarning",
                        "message": "on_failure for fixture 'custom_page' raised "
                        "AttributeError: 'dict' object has no attribute 'screenshot'",
                        "filename": "worker.py",
                        "lineno": 170,
                    }
                ],
            ),
        ]
        out = render_html(results)
        data = _extract_embedded_data(out)
        self.assertEqual(data["tests"][0]["warnings"][0]["category"], "RuntimeWarning")
        self.assertIn(
            "on_failure for fixture 'custom_page'", data["tests"][0]["warnings"][0]["message"]
        )

    def test_labels_rendering_is_present_in_page(self):
        # New-report feature guard: the label pill class and the filter
        # query hint must ship in the page.
        out = render_html([])
        self.assertIn("label-row", out)


class ArtifactModeTests(unittest.TestCase):
    def _make_artifact_files(self, tmp):
        source_dir = Path(tmp) / "ctrlrunner-artifacts" / "mod__test_x" / "attempt-1"
        source_dir.mkdir(parents=True)
        image_path = source_dir / "page.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepngbytes")
        trace_path = source_dir / "context.zip"
        trace_path.write_bytes(b"PK\x03\x04faketracebytes")
        return image_path, trace_path

    def test_files_mode_copies_both_images_and_traces_into_report_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            image_path, trace_path = self._make_artifact_files(tmp)
            report_dir = Path(tmp) / "report"
            report_dir.mkdir()

            results = [
                Result(
                    test_id="mod::test_x",
                    outcome="failed",
                    error="x",
                    duration=0.1,
                    artifacts=(str(image_path), str(trace_path)),
                )
            ]
            out = render_html(results, artifact_mode="files", report_dir=str(report_dir))
            data = _extract_embedded_data(out)
            artifacts = data["tests"][0]["artifacts"]

            for a in artifacts:
                self.assertFalse(a["embedded"])
                self.assertTrue((report_dir / a["href"]).exists())

    def test_trace_zip_bundles_trace_viewer_into_report_dir(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            _image_path, trace_path = self._make_artifact_files(tmp)
            report_dir = Path(tmp) / "report"
            report_dir.mkdir()

            results = [
                Result(
                    test_id="mod::test_x",
                    outcome="failed",
                    error="x",
                    duration=0.1,
                    artifacts=(str(trace_path),),
                )
            ]
            render_html(results, artifact_mode="files", report_dir=str(report_dir))

            self.assertTrue((report_dir / "trace" / "index.html").exists())
            self.assertTrue((report_dir / "trace" / "assets").is_dir())

    def test_no_trace_zip_skips_trace_viewer_bundle(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            image_path, _trace_path = self._make_artifact_files(tmp)
            report_dir = Path(tmp) / "report"
            report_dir.mkdir()

            results = [
                Result(
                    test_id="mod::test_x",
                    outcome="passed",
                    error=None,
                    duration=0.1,
                    artifacts=(str(image_path),),
                )
            ]
            render_html(results, artifact_mode="files", report_dir=str(report_dir))

            self.assertFalse((report_dir / "trace").exists())

    def test_base64_mode_embeds_images_but_copies_traces(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            image_path, trace_path = self._make_artifact_files(tmp)
            report_dir = Path(tmp) / "report"
            report_dir.mkdir()

            results = [
                Result(
                    test_id="mod::test_x",
                    outcome="failed",
                    error="x",
                    duration=0.1,
                    artifacts=(str(image_path), str(trace_path)),
                )
            ]
            out = render_html(results, artifact_mode="base64", report_dir=str(report_dir))
            data = _extract_embedded_data(out)
            by_label = {a["label"]: a for a in data["tests"][0]["artifacts"]}

            self.assertTrue(by_label["page.png"]["embedded"])
            self.assertTrue(by_label["page.png"]["href"].startswith("data:image/png;base64,"))

            self.assertFalse(by_label["context.zip"]["embedded"])
            self.assertFalse(by_label["context.zip"]["href"].startswith("data:"))
            self.assertTrue((report_dir / by_label["context.zip"]["href"]).exists())
            # the trace file itself must not have been copied into the report
            # dir as a base64 blob -- it should just be a plain file copy
            self.assertEqual(
                (report_dir / by_label["context.zip"]["href"]).read_bytes(),
                trace_path.read_bytes(),
            )

    def test_missing_artifact_file_falls_back_to_raw_reference(self):
        results = [
            Result(
                test_id="mod::test_x",
                outcome="failed",
                error="x",
                duration=0.1,
                artifacts=("/nonexistent/path/shot.png",),
            )
        ]
        out = render_html(results, artifact_mode="files", report_dir=None)
        data = _extract_embedded_data(out)
        artifact = data["tests"][0]["artifacts"][0]
        self.assertEqual(artifact["href"], "/nonexistent/path/shot.png")
        self.assertFalse(artifact["embedded"])

    def test_javascript_scheme_artifact_href_is_neutralized_when_missing(self):
        # A worker-supplied artifact string is not necessarily a real
        # file path -- "javascript:alert(1)" doesn't exist on disk, so it
        # falls into the "missing artifact" raw-reference branch. Left
        # unsanitized, that raw string becomes the <a href> and the link
        # is click-to-execute in the rendered report.
        results = [
            Result(
                test_id="mod::test_x",
                outcome="failed",
                error="x",
                duration=0.1,
                artifacts=("javascript:alert(1)",),
            )
        ]
        out = render_html(results, artifact_mode="files", report_dir=None)
        data = _extract_embedded_data(out)
        artifact = data["tests"][0]["artifacts"][0]
        self.assertFalse(artifact["href"].startswith("javascript:"))

    def test_no_report_dir_leaves_paths_unchanged_in_files_mode(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            image_path, _ = self._make_artifact_files(tmp)
            results = [
                Result(
                    test_id="mod::test_x",
                    outcome="failed",
                    error="x",
                    duration=0.1,
                    artifacts=(str(image_path),),
                )
            ]
            out = render_html(results, artifact_mode="files", report_dir=None)
            data = _extract_embedded_data(out)
            artifact = data["tests"][0]["artifacts"][0]
            self.assertEqual(artifact["href"], str(image_path))

    def test_coverage_summary_embedded_when_present(self):
        out = render_html([], coverage_summary={"percent": 82.345, "htmlDir": None})
        data = _extract_embedded_data(out)
        self.assertEqual(data["coverage"]["percent"], 82.345)

    def test_coverage_summary_html_dir_embedded_when_present(self):
        out = render_html([], coverage_summary={"percent": 90.0, "htmlDir": "/tmp/coverage-html"})
        data = _extract_embedded_data(out)
        self.assertEqual(data["coverage"]["htmlDir"], "/tmp/coverage-html")

    def test_coverage_summary_absent_by_default(self):
        out = render_html([])
        data = _extract_embedded_data(out)
        self.assertIsNone(data["coverage"])


if __name__ == "__main__":
    unittest.main()
