import socket
import tempfile
import unittest
import unittest.mock
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from ctrlrunner.reporting.reporter import JUnitReporter


class ReporterTests(unittest.TestCase):
    def test_add_result_stores_worker_id(self):
        # Result.worker_id lets history/reporting attribute a
        # result back to the worker slot that produced it.
        reporter = JUnitReporter()
        result = reporter.add_result(
            "mod::test_a",
            "passed",
            None,
            0.5,
            worker_id=3,
        )
        self.assertEqual(result.worker_id, 3)
        self.assertEqual(reporter.results[0].worker_id, 3)

    def test_add_result_worker_id_defaults_to_none(self):
        reporter = JUnitReporter()
        result = reporter.add_result("mod::test_a", "passed", None, 0.5)
        self.assertIsNone(result.worker_id)

    def test_add_result_stores_near_timeout(self):
        # Result.near_timeout marks a result whose actual duration
        # came close to (>= 80% of) its resolved timeout.
        reporter = JUnitReporter()
        result = reporter.add_result(
            "mod::test_a",
            "passed",
            None,
            1.9,
            near_timeout=True,
        )
        self.assertTrue(result.near_timeout)
        self.assertTrue(reporter.results[0].near_timeout)

    def test_add_result_near_timeout_defaults_to_false(self):
        reporter = JUnitReporter()
        result = reporter.add_result("mod::test_a", "passed", None, 0.5)
        self.assertFalse(result.near_timeout)

    def test_add_result_flaky_defaults_to_false(self):
        reporter = JUnitReporter()
        result = reporter.add_result("m::t", "passed", None, 0.1)
        self.assertFalse(result.flaky)

    def test_add_result_stores_started_at(self):
        reporter = JUnitReporter()
        result = reporter.add_result(
            "mod::test_a",
            "passed",
            None,
            0.5,
            started_at=1000000.5,
        )
        self.assertEqual(result.started_at, 1000000.5)
        self.assertEqual(reporter.results[0].started_at, 1000000.5)

    def test_add_result_started_at_defaults_to_none(self):
        reporter = JUnitReporter()
        result = reporter.add_result("mod::test_a", "passed", None, 0.5)
        self.assertIsNone(result.started_at)

    def test_add_result_stores_flaky_flag(self):
        reporter = JUnitReporter()
        result = reporter.add_result("m::t", "passed", None, 0.1, flaky=True)
        self.assertTrue(result.flaky)

    def test_junit_properties_include_flaky_when_set(self):
        reporter = JUnitReporter()
        reporter.add_result("m::t", "passed", None, 0.1, flaky=True)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            tree = ET.parse(path)
        props = {p.get("name"): p.get("value") for p in tree.getroot().iter("property")}
        self.assertEqual(props.get("flaky"), "true")

    def test_writes_valid_junit_with_properties(self):
        reporter = JUnitReporter()
        reporter.add_result(
            "mod::test_a",
            "passed",
            None,
            0.5,
            case_id="TC-1",
            tags=("smoke",),
            properties={"owner": "sdet"},
        )
        reporter.add_result(
            "mod::test_b[en]",
            "failed",
            "boom",
            1.2,
            case_id="TC-100-en",
            tags=("smoke", "i18n"),
            attempts=3,
            artifacts=("shot.png",),
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path), suite_name="mysuite")

            tree = ET.parse(path)
            root = tree.getroot()
            self.assertEqual(root.attrib["tests"], "2")
            self.assertEqual(root.attrib["failures"], "1")

            cases = {c.attrib["name"]: c for c in root.findall("testcase")}
            self.assertIn("test_a", cases)
            self.assertIn("test_b[en]", cases)

            props_a = {
                p.attrib["name"]: p.attrib["value"] for p in cases["test_a"].find("properties")
            }
            self.assertEqual(props_a["test_case_id"], "TC-1")
            self.assertEqual(props_a["tags"], "smoke")
            self.assertEqual(props_a["owner"], "sdet")

            props_b = {
                p.attrib["name"]: p.attrib["value"] for p in cases["test_b[en]"].find("properties")
            }
            self.assertEqual(props_b["test_case_id"], "TC-100-en")
            self.assertEqual(props_b["attempts"], "3")
            self.assertEqual(props_b["artifacts"], "shot.png")

            failure = cases["test_b[en]"].find("failure")
            self.assertIsNotNone(failure)
            self.assertEqual(failure.text, "boom")

    def test_steps_rendered_as_system_out(self):
        reporter = JUnitReporter()
        steps = [
            {
                "name": "outer",
                "outcome": "passed",
                "duration": 0.5,
                "error": None,
                "children": [
                    {
                        "name": "inner",
                        "outcome": "failed",
                        "duration": 0.1,
                        "error": "AssertionError: x",
                        "children": [],
                    },
                ],
            },
        ]
        reporter.add_result("mod::test_c", "failed", "boom", 0.6, steps=steps)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            tree = ET.parse(path)
            system_out = tree.getroot().find("testcase").find("system-out")
            self.assertIsNotNone(system_out)
            self.assertIn("outer", system_out.text)
            self.assertIn("inner", system_out.text)
            self.assertIn("AssertionError: x", system_out.text)

    def test_no_properties_block_when_no_metadata(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::plain", "passed", None, 0.1)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            tree = ET.parse(path)
            case = tree.getroot().find("testcase")
            self.assertIsNone(case.find("properties"))

    def test_skipped_outcome_uses_skipped_element_not_failure(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_skip", "skipped", "not applicable", 0.0)
        reporter.add_result("mod::test_fixme", "fixme", "needs fix", 0.0)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            root = ET.parse(path).getroot()
            self.assertEqual(root.attrib["skipped"], "2")
            self.assertEqual(root.attrib["failures"], "0")
            for case in root.findall("testcase"):
                self.assertIsNone(case.find("failure"))
                skipped_el = case.find("skipped")
                self.assertIsNotNone(skipped_el)

    def test_expected_failure_does_not_count_as_failure(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_xfail", "expected_failure", "JIRA-1: known bug", 0.1)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            root = ET.parse(path).getroot()
            self.assertEqual(root.attrib["failures"], "0")
            case = root.find("testcase")
            self.assertIsNone(case.find("failure"))
            props = {p.attrib["name"]: p.attrib["value"] for p in case.find("properties")}
            self.assertEqual(props["expected_failure"], "JIRA-1: known bug")

    def test_unexpected_pass_property_is_preserved_as_passed(self):
        reporter = JUnitReporter()
        reporter.add_result(
            "mod::test_x", "passed", None, 0.1, properties={"unexpected_pass": "true"}
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            root = ET.parse(path).getroot()
            self.assertEqual(root.attrib["failures"], "0")
            case = root.find("testcase")
            self.assertIsNone(case.find("failure"))
            props = {p.attrib["name"]: p.attrib["value"] for p in case.find("properties")}
            self.assertEqual(props["unexpected_pass"], "true")


class MultiProjectJUnitTests(unittest.TestCase):
    def test_default_stays_single_testsuite_even_with_project_set(self):
        # byte-shape backward compatibility: even if Result.project
        # happens to be populated, multi_project=False (the default)
        # must produce today's exact single-<testsuite> root.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter = JUnitReporter()
            reporter.add_result("mod::test_a", "passed", None, 0.1, project="smoke")
            reporter.write(str(path))
            root = ET.parse(path).getroot()
            self.assertEqual(root.tag, "testsuite")

    def test_multi_project_true_wraps_in_testsuites_per_project(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter = JUnitReporter()
            reporter.add_result("[smoke] mod::test_a", "passed", None, 0.1, project="smoke")
            reporter.add_result("[smoke] mod::test_b", "failed", "boom", 0.2, project="smoke")
            reporter.add_result(
                "[regression] mod::test_c", "passed", None, 0.3, project="regression"
            )
            reporter.write(str(path), multi_project=True)

            root = ET.parse(path).getroot()
            self.assertEqual(root.tag, "testsuites")
            suites = root.findall("testsuite")
            self.assertEqual(len(suites), 2)
            by_name = {s.get("name"): s for s in suites}
            self.assertEqual(by_name["smoke"].get("tests"), "2")
            self.assertEqual(by_name["smoke"].get("failures"), "1")
            self.assertEqual(by_name["regression"].get("tests"), "1")
            self.assertEqual(by_name["regression"].get("failures"), "0")

    def test_multi_project_testcase_classname_unaffected_by_id_prefix(self):
        # the [project] prefix sits before the module::name split point,
        # so classname/name parsing (rpartition on "::") is unaffected.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter = JUnitReporter()
            reporter.add_result("[smoke] pkg.mod::test_x", "passed", None, 0.1, project="smoke")
            reporter.write(str(path), multi_project=True)
            root = ET.parse(path).getroot()
            case = root.find("testsuite/testcase")
            self.assertEqual(case.get("classname"), "[smoke] pkg.mod")
            self.assertEqual(case.get("name"), "test_x")

    def test_multi_project_missing_project_falls_back_to_suite_name(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter = JUnitReporter()
            reporter.add_result("mod::test_a", "passed", None, 0.1)  # no project set
            reporter.write(str(path), suite_name="fallback-suite", multi_project=True)
            root = ET.parse(path).getroot()
            suite = root.find("testsuite")
            self.assertEqual(suite.get("name"), "fallback-suite")


class JUnitGoldenBytesTests(unittest.TestCase):
    """The JUnit XML is byte-compatible with a named external Teams
    parser -- until now that was only guarded by a root-tag check, so
    attribute order, indentation, and the XML declaration were all free
    to drift unnoticed. This pins the exact bytes produced for a small
    representative suite (one passed, one failed, one skipped test) so
    any future formatting change is caught immediately instead of
    silently breaking the downstream parser."""

    # timestamp/hostname are pinned via started_at + a gethostname patch
    # below; errors/timestamp/hostname were added deliberately for
    # pytest parity -- this golden update IS the intended
    # downstream-shape change, not accidental drift.
    GOLDEN = (
        b"<?xml version='1.0' encoding='utf-8'?>\n"
        b'<testsuite name="golden-suite" tests="3" failures="1" errors="0" skipped="1"'
        b' time="0.579" timestamp="2026-01-02T03:04:05" hostname="golden-host">\n'
        b'  <testcase classname="mod" name="test_fail" time="0.456">\n'
        b'    <failure message="test failed">AssertionError: boom</failure>\n'
        b"  </testcase>\n"
        b'  <testcase classname="mod" name="test_pass" time="0.123">\n'
        b"    <properties>\n"
        b'      <property name="test_case_id" value="C-1" />\n'
        b'      <property name="tags" value="smoke" />\n'
        b"    </properties>\n"
        b"  </testcase>\n"
        b'  <testcase classname="mod" name="test_skip" time="0.000">\n'
        b"    <properties>\n"
        b'      <property name="annotation" value="skipped" />\n'
        b"    </properties>\n"
        b'    <skipped message="not implemented" />\n'
        b"  </testcase>\n"
        b"</testsuite>"
    )

    def test_junit_xml_byte_for_byte_for_representative_suite(self):
        reporter = JUnitReporter()
        reporter.started_at = datetime(2026, 1, 2, 3, 4, 5).timestamp()
        reporter.add_result("mod::test_pass", "passed", None, 0.123, case_id="C-1", tags=("smoke",))
        reporter.add_result("mod::test_fail", "failed", "AssertionError: boom", 0.456)
        reporter.add_result("mod::test_skip", "skipped", "not implemented", 0.0)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            with unittest.mock.patch(
                "ctrlrunner.reporting.reporter.socket.gethostname", return_value="golden-host"
            ):
                reporter.write(str(path), suite_name="golden-suite")
            data = path.read_bytes()

        self.assertEqual(data, self.GOLDEN)


class XmlSanitizationTests(unittest.TestCase):
    """XML-1.0-illegal control chars in any user-supplied text
    (assert messages, ANSI-colored library output, property values, step
    names) must never produce an unparseable junit.xml -- one dirty
    failure message would otherwise take down CI's parse of the WHOLE
    report."""

    def _write_and_parse(self, **result_kwargs):
        reporter = JUnitReporter()
        kwargs = {
            "test_id": "mod::test_a",
            "outcome": "failed",
            "error": "boom",
            "duration": 0.1,
        }
        kwargs.update(result_kwargs)
        reporter.add_result(
            kwargs.pop("test_id"),
            kwargs.pop("outcome"),
            kwargs.pop("error"),
            kwargs.pop("duration"),
            **kwargs,
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            return ET.parse(path)

    def test_nul_byte_in_error_produces_parseable_xml(self):
        tree = self._write_and_parse(error="got b'\x00\x01' from device")
        failure = tree.getroot().find("testcase/failure")
        self.assertIn("#x00;", failure.text)

    def test_ansi_escape_in_error_produces_parseable_xml(self):
        tree = self._write_and_parse(error="ansi \x1b[31mred\x1b[0m output")
        failure = tree.getroot().find("testcase/failure")
        self.assertIn("#x1B;", failure.text)

    def test_control_char_in_property_value_sanitized(self):
        tree = self._write_and_parse(properties={"note": "bad\x08value"})
        props = {
            p.get("name"): p.get("value")
            for p in tree.getroot().findall("testcase/properties/property")
        }
        self.assertEqual(props["note"], "bad#x08;value")

    def test_control_char_in_step_text_sanitized(self):
        tree = self._write_and_parse(
            steps=[{"name": "step\x0bname", "outcome": "passed", "duration": 0.0}]
        )
        system_out = tree.getroot().find("testcase/system-out")
        self.assertIn("step#x0B;name", system_out.text)

    def test_control_char_in_skipped_message_sanitized(self):
        tree = self._write_and_parse(outcome="skipped", error="skip\x00msg")
        skipped = tree.getroot().find("testcase/skipped")
        self.assertEqual(skipped.get("message"), "skip#x00;msg")

    def test_normal_unicode_untouched(self):
        tree = self._write_and_parse(error="кирилиця ✓ ok")
        self.assertIn("кирилиця ✓ ok", tree.getroot().find("testcase/failure").text)


class AtomicWriteTests(unittest.TestCase):
    """junit.xml must be written write-once (tmp + os.replace,
    the same pattern JsonReporter already uses) -- a crash mid-write must
    never leave CI a truncated file, and a failed write must never
    clobber the previous run's report."""

    def test_existing_report_survives_failed_write(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_a", "passed", None, 0.1)

        def partial_then_fail(self_tree, dest, *args, **kwargs):
            # Simulate ET dying MID-write: whatever it was given (a path
            # today, a file object under the atomic pattern) ends up
            # truncated to garbage before the error surfaces.
            if hasattr(dest, "write"):
                dest.write(b"<partial")
            else:
                Path(dest).write_bytes(b"<partial")
            raise OSError("disk full")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            original = path.read_bytes()
            with (
                unittest.mock.patch.object(
                    ET.ElementTree, "write", autospec=True, side_effect=partial_then_fail
                ),
                self.assertRaises(OSError),
            ):
                reporter.write(str(path))
            self.assertEqual(path.read_bytes(), original)
            # no tmp-file droppings left behind either
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["report.xml"])

    def test_written_report_still_parses(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_a", "failed", "boom", 0.1)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            tree = ET.parse(path)
        self.assertEqual(tree.getroot().tag, "testsuite")


class SuiteMetadataTests(unittest.TestCase):
    """JUnit consumers (Datadog CI, Allure, Jenkins) expect
    timestamp/hostname/errors on <testsuite>; ctrlrunner emitted none."""

    def _suite_element(self, reporter):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            return ET.parse(path).getroot()

    def test_testsuite_carries_timestamp_hostname_errors(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_a", "passed", None, 0.1)
        suite = self._suite_element(reporter)
        self.assertEqual(suite.get("hostname"), socket.gethostname())
        self.assertEqual(suite.get("errors"), "0")
        # must be ISO 8601 -- datetime.fromisoformat is the contract
        datetime.fromisoformat(suite.get("timestamp"))

    def test_timestamp_reflects_reporter_construction_time(self):
        reporter = JUnitReporter()
        reporter.started_at = 1750000000.0
        suite = self._suite_element(reporter)
        expected = datetime.fromtimestamp(1750000000.0).isoformat(timespec="seconds")
        self.assertEqual(suite.get("timestamp"), expected)

    def test_result_infra_error_defaults_false(self):
        reporter = JUnitReporter()
        result = reporter.add_result("mod::test_a", "failed", "boom", 0.1)
        self.assertFalse(result.infra_error)
        flagged = reporter.add_result("mod::test_b", "failed", "crash", 0.1, infra_error=True)
        self.assertTrue(flagged.infra_error)


class DeterministicOrderTests(unittest.TestCase):
    """Testcase order must not depend on worker completion
    timing -- two identical runs should produce diff-identical reports."""

    def test_testcases_sorted_by_id_regardless_of_arrival(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_b", "passed", None, 0.1)
        reporter.add_result("mod::test_a", "passed", None, 0.1)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            names = [c.get("name") for c in ET.parse(path).getroot().findall("testcase")]
        self.assertEqual(names, ["test_a", "test_b"])

    def test_multi_project_suites_and_cases_sorted(self):
        reporter = JUnitReporter()
        reporter.add_result("mod::test_x", "passed", None, 0.1, project="web")
        reporter.add_result("mod::test_b", "passed", None, 0.1, project="api")
        reporter.add_result("mod::test_a", "passed", None, 0.1, project="api")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path), multi_project=True)
            root = ET.parse(path).getroot()
        self.assertEqual([s.get("name") for s in root.findall("testsuite")], ["api", "web"])
        api_names = [c.get("name") for c in root.findall("testsuite")[0].findall("testcase")]
        self.assertEqual(api_names, ["test_a", "test_b"])

    def test_add_result_arrival_order_preserved_in_memory(self):
        # in-memory `results` keeps arrival order -- history/console
        # consumers rely on it reflecting execution reality; only the
        # WRITTEN reports sort.
        reporter = JUnitReporter()
        reporter.add_result("mod::test_b", "passed", None, 0.1)
        reporter.add_result("mod::test_a", "passed", None, 0.1)
        self.assertEqual([r.test_id for r in reporter.results], ["mod::test_b", "mod::test_a"])


class JunitLogsTests(unittest.TestCase):
    """pytest's junit_logging equivalent -- captured
    stdout/stderr (Result.logs, populated when --logs is on) can be
    embedded in the JUnit XML. Off by default: today's exact shape."""

    LOGS = [
        {
            "attempt": 1,
            "stdout": "hello out",
            "stderr": "hello err",
            "records": [],
            "truncated": False,
        }
    ]

    def _case(self, reporter):
        reporter.add_result("mod::test_a", "failed", "boom", 0.1, logs=self.LOGS)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            return ET.parse(path).getroot().find("testcase")

    def test_off_by_default_keeps_todays_shape(self):
        case = self._case(JUnitReporter())
        self.assertIsNone(case.find("system-out"))
        self.assertIsNone(case.find("system-err"))

    def test_system_out_mode_embeds_both_streams_in_system_out(self):
        case = self._case(JUnitReporter(junit_logs="system-out"))
        text = case.find("system-out").text
        self.assertIn("hello out", text)
        self.assertIn("hello err", text)
        self.assertIsNone(case.find("system-err"))

    def test_split_mode_routes_stderr_to_system_err(self):
        case = self._case(JUnitReporter(junit_logs="split"))
        self.assertIn("hello out", case.find("system-out").text)
        self.assertIn("hello err", case.find("system-err").text)
        self.assertNotIn("hello err", case.find("system-out").text)

    def test_attempt_labels_present(self):
        case = self._case(JUnitReporter(junit_logs="system-out"))
        text = case.find("system-out").text
        self.assertIn("attempt 1 stdout", text)
        self.assertIn("attempt 1 stderr", text)

    def test_steps_and_logs_share_system_out(self):
        reporter = JUnitReporter(junit_logs="system-out")
        reporter.add_result(
            "mod::test_a",
            "failed",
            "boom",
            0.1,
            steps=[{"name": "step one", "outcome": "passed", "duration": 0.0}],
            logs=self.LOGS,
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            text = ET.parse(path).getroot().find("testcase/system-out").text
        self.assertIn("step one", text)
        self.assertIn("hello out", text)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            JUnitReporter(junit_logs="banana")


class JunitInfraErrorsTests(unittest.TestCase):
    """With junit_infra_errors=True, runner-synthesized
    failures (hard-kill timeout, worker crash) render as <error> and
    count in the errors attr -- "the infra broke" vs "the test failed".
    Default False keeps today's exact <failure> shape."""

    def _root(self, reporter):
        reporter.add_result("mod::test_real", "failed", "assert boom", 0.1)
        reporter.add_result("mod::test_killed", "failed", "Hard-killed", 0.1, infra_error=True)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "report.xml"
            reporter.write(str(path))
            return ET.parse(path).getroot()

    def test_default_keeps_failure_shape_and_zero_errors(self):
        root = self._root(JUnitReporter())
        self.assertEqual(root.get("errors"), "0")
        self.assertEqual(root.get("failures"), "2")
        for case in root.findall("testcase"):
            self.assertIsNotNone(case.find("failure"))
            self.assertIsNone(case.find("error"))

    def test_enabled_renders_error_element_and_counts(self):
        root = self._root(JUnitReporter(junit_infra_errors=True))
        self.assertEqual(root.get("errors"), "1")
        self.assertEqual(root.get("failures"), "1")
        cases = {c.get("name"): c for c in root.findall("testcase")}
        self.assertIsNotNone(cases["test_real"].find("failure"))
        self.assertIsNone(cases["test_real"].find("error"))
        error_el = cases["test_killed"].find("error")
        self.assertIsNotNone(error_el)
        self.assertIn("Hard-killed", error_el.text)
        self.assertIsNone(cases["test_killed"].find("failure"))


if __name__ == "__main__":
    unittest.main()
