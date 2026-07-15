import contextlib
import os
import re
import socket
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# XML 1.0 forbids these characters entirely -- ElementTree serializes
# them raw and the result is unparseable, so one dirty assert message
# (NUL bytes, ANSI color codes, ...) would take down CI's parse of the
# WHOLE junit.xml. Same approach as pytest's bin_xml_escape: replace
# each with a visible #xNN; escape.
_ILLEGAL_XML_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _sanitize_xml_text(value):
    if value is None:
        return None
    return _ILLEGAL_XML_RE.sub(lambda m: f"#x{ord(m.group()):02X};", str(value))


def result_sort_key(r):
    """Deterministic report order (JUnit + JSON writers): worker
    completion timing must not make two identical runs diff
    differently. In-memory `results` lists keep arrival order -- only
    the written reports sort."""
    return (r.project or "", r.test_id)


def _render_steps_text(steps, indent=0) -> str:
    lines = []
    for s in steps:
        marker = "\u2713" if s.get("outcome") == "passed" else "\u2717"
        lines.append(f"{'  ' * indent}{marker} {s.get('name')} ({s.get('duration', 0):.3f}s)")
        if s.get("error"):
            lines.append(f"{'  ' * (indent + 1)}{s['error']}")
        nested = _render_steps_text(s.get("children", []), indent + 1)
        if nested:
            lines.append(nested)
    return "\n".join(lines)


@dataclass
class Result:
    test_id: str
    outcome: str  # "passed" | "failed"
    error: str | None
    duration: float
    case_id: str | None = None
    tags: tuple = ()
    properties: dict[str, str] = field(default_factory=dict)
    attempts: int | None = None
    artifacts: tuple = ()
    steps: list = field(default_factory=list)
    groups: dict[str, str] = field(default_factory=dict)
    project: str | None = None
    retries_configured: int | None = None
    worker_restart_overhead: float | None = None
    quarantined: bool = False
    quarantine_reason: str | None = None
    worker_id: int | None = None
    near_timeout: bool = False
    assert_details: dict | None = None
    logs: list | None = None
    # True for failures the runner synthesized for infrastructure
    # events (hard-kill timeout, worker crash) rather than a test
    # assertion -- lets the JUnit writer distinguish <error> from
    # <failure> when junit_infra_errors is enabled.
    infra_error: bool = False
    # Python warnings captured during the test's attempts:
    # list of {attempt, category, message, filename, lineno}, or None.
    warnings: list | None = None
    # A "passed" outcome reached only after at
    # least one failed attempt this run -- Playwright-style flaky
    # signal. Kept as passed for JUnit/exit-code purposes by default
    # (see --fail-on-flaky); this is purely a visibility flag.
    flaky: bool = False
    # Timeline feature (2026-07-12): epoch seconds when this test's FIRST
    # attempt began (time.time() in worker.py, threaded through the
    # "finished" IPC message) -- None for synthetic results that never
    # actually started (cancelled/not_run/worker-crash-before-start).
    started_at: float | None = None


class JUnitReporter:
    """Emits standard JUnit XML so the existing JUnit-XML-to-Teams pipeline
    keeps working unchanged regardless of what runs the tests.

    Each <testcase> gets a <properties> block carrying the test case ID
    and any other metadata (tags, custom properties) -- this is what lets
    downstream tooling (Teams message, TestRail/Jira sync) resolve a
    result back to a case ID without parsing test names, and it works
    the same way for parametrized tests since each parameter set already
    resolved its own case_id at registration time.
    """

    JUNIT_LOGS_MODES = ("off", "system-out", "split")

    def __init__(self, junit_logs: str = "off", junit_infra_errors: bool = False):
        if junit_logs not in self.JUNIT_LOGS_MODES:
            raise ValueError(
                f"junit_logs must be one of {self.JUNIT_LOGS_MODES}, got {junit_logs!r}"
            )
        # True renders runner-synthesized failures (timeout
        # hard-kill, worker crash) as <error> instead of <failure> and
        # counts them in the errors attr. Off by default -- the existing
        # Teams pipeline parses <failure> only.
        self.junit_infra_errors = bool(junit_infra_errors)
        # (pytest junit_logging equivalent) "system-out" embeds each
        # attempt's captured stdout+stderr in <system-out>; "split"
        # routes stderr to <system-err> instead. Logs exist on a Result
        # only when --logs capture was on for that test.
        self.junit_logs = junit_logs
        self.results: list[Result] = []
        # <testsuite timestamp=...>: the reporter is constructed at run
        # start, so construction time is the run's start time.
        self.started_at = time.time()
        # record_suite_property() values -- run-level metadata,
        # rendered as a <properties> block under every <testsuite> (a
        # multi-project run shares one set) and as suiteProperties in
        # the JSON report.
        self.suite_properties: dict[str, str] = {}

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
        )
        self.results.append(result)
        return result

    def _build_testcase(self, suite_el, r, suite_name):
        classname, _, name = r.test_id.rpartition("::")
        case = ET.SubElement(
            suite_el,
            "testcase",
            {
                "classname": _sanitize_xml_text(classname or suite_name),
                "name": _sanitize_xml_text(name),
                "time": f"{r.duration:.3f}",
            },
        )

        props = {}
        if r.case_id:
            props["test_case_id"] = r.case_id
        if r.tags:
            props["tags"] = ",".join(sorted(r.tags))
        if r.attempts and r.attempts > 1:
            props["attempts"] = str(r.attempts)
        if r.artifacts:
            props["artifacts"] = ",".join(r.artifacts)
        if r.outcome in ("skipped", "fixme"):
            props["annotation"] = r.outcome
        if r.outcome == "expected_failure":
            props["expected_failure"] = r.error or "true"
        if r.quarantined:
            props["quarantined"] = "true"
            if r.quarantine_reason:
                props["quarantine_reason"] = r.quarantine_reason
        if r.flaky:
            props["flaky"] = "true"
        props.update(r.properties)

        if props:
            properties_el = ET.SubElement(case, "properties")
            for key, value in props.items():
                ET.SubElement(
                    properties_el,
                    "property",
                    {"name": _sanitize_xml_text(key), "value": _sanitize_xml_text(value)},
                )

        # "failed" is a real build-breaking failure. "expected_failure"
        # (fail()) and "skipped"/"fixme" (skip()/fixme()) are all
        # deliberately excluded from <failure> so they don't break CI --
        # that's the whole point of marking them.
        if r.outcome == "failed":
            if r.infra_error and self.junit_infra_errors:
                error_el = ET.SubElement(case, "error", {"message": "infrastructure failure"})
                error_el.text = _sanitize_xml_text(r.error or "")
            else:
                failure = ET.SubElement(case, "failure", {"message": "test failed"})
                failure.text = _sanitize_xml_text(r.error or "")
        elif r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure"):
            skipped_el = ET.SubElement(case, "skipped")
            if r.error:
                skipped_el.set("message", _sanitize_xml_text(r.error))

        out_parts = []
        if r.steps:
            out_parts.append(_render_steps_text(r.steps))
        err_parts = []
        if self.junit_logs != "off" and r.logs:
            for entry in r.logs:
                label = f"attempt {entry.get('attempt', '?')}"
                if entry.get("stdout"):
                    out_parts.append(f"--- {label} stdout ---\n{entry['stdout']}")
                if entry.get("stderr"):
                    target = err_parts if self.junit_logs == "split" else out_parts
                    target.append(f"--- {label} stderr ---\n{entry['stderr']}")
        if out_parts:
            system_out = ET.SubElement(case, "system-out")
            system_out.text = _sanitize_xml_text("\n".join(out_parts))
        if err_parts:
            system_err = ET.SubElement(case, "system-err")
            system_err.text = _sanitize_xml_text("\n".join(err_parts))

    def _build_testsuite(self, name, results):
        total = len(results)
        failures = sum(1 for r in results if r.outcome == "failed")
        skipped = sum(
            1
            for r in results
            if r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")
        )
        errors = sum(1 for r in results if r.infra_error and self.junit_infra_errors)
        failures -= errors
        suite = ET.Element(
            "testsuite",
            {
                "name": name,
                "tests": str(total),
                "failures": str(failures),
                "errors": str(errors),
                "skipped": str(skipped),
                "time": f"{sum(r.duration for r in results):.3f}",
                "timestamp": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
                "hostname": socket.gethostname(),
            },
        )
        if self.suite_properties:
            props_el = ET.SubElement(suite, "properties")
            for key, value in sorted(self.suite_properties.items()):
                ET.SubElement(
                    props_el,
                    "property",
                    {"name": _sanitize_xml_text(key), "value": _sanitize_xml_text(value)},
                )
        for r in results:
            self._build_testcase(suite, r, name)
        return suite

    def write(self, path: str, suite_name: str = "pyrunner", multi_project: bool = False):
        """multi_project=True wraps output in <testsuites> with one
        <testsuite> per distinct Result.project, standards-correct
        JUnit for a multi-project run. Default False keeps today's
        exact single-<testsuite> shape unconditionally -- existing CI
        integrations (Teams pipeline) parse a single-<testsuite> root
        and must never see it change unless multi-project genuinely
        applies to this run."""
        ordered = sorted(self.results, key=result_sort_key)
        if not multi_project:
            tree = ET.ElementTree(self._build_testsuite(suite_name, ordered))
        else:
            projects = []
            by_project = {}
            for r in ordered:
                key = r.project or suite_name
                if key not in by_project:
                    projects.append(key)
                    by_project[key] = []
                by_project[key].append(r)
            root = ET.Element("testsuites")
            for name in projects:
                root.append(self._build_testsuite(name, by_project[name]))
            tree = ET.ElementTree(root)

        ET.indent(tree, space="  ")
        # Write-once like results.json (see JsonReporter.on_run_end): a
        # crash mid-write must never leave CI a truncated junit.xml, and
        # a failed write must never clobber the previous run's report.
        target = Path(path)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.resolve().parent), prefix=".junit-", suffix=".xml.tmp"
        )
        try:
            with os.fdopen(fd, "wb") as f:
                tree.write(f, encoding="utf-8", xml_declaration=True)
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
