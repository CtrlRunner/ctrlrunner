"""
Pluggable console reporters, modeled on Playwright TS's reporter set.
The orchestrator calls these hooks as tests run (on_test_start/on_test_end)
and once at the end (on_run_end) -- they're independent of the JUnit
reporter, which stays focused on the Teams-pipeline-compatible XML file.
Multiple can run at once, e.g. --reporter line,json.
"""

import contextlib
import importlib
import json
import os
import sys
import tempfile

from .events import result_to_public_dict
from .reporter import Result, result_sort_key


class ConsoleReporter:
    def on_run_start(self, total: int):
        pass

    def on_test_start(self, test_id: str):
        pass

    def on_test_end(self, result: Result):
        pass

    def on_run_end(self, results: list[Result], duration: float):
        pass


def _summary_lines(results, duration):
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(
        1
        for r in results
        if r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")
    )
    expected = sum(1 for r in results if r.outcome == "expected_failure")

    parts = [f"{len(results)} tests", f"{passed} passed", f"{failed} failed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if expected:
        parts.append(f"{expected} expected failures")
    flaky_count = sum(1 for r in results if getattr(r, "flaky", False))
    if flaky_count:
        parts.append(f"{flaky_count} flaky")
    warning_count = sum(len(r.warnings or []) for r in results)
    if warning_count:
        # Captured Python warnings -- details live in the
        # JSON/HTML reports' per-test `warnings` field.
        parts.append(f"{warning_count} warning(s) captured")
    lines = [", ".join(parts) + f" ({duration:.2f}s)"]

    for r in results:
        if r.outcome == "failed":
            suffix = f"  [{r.case_id}]" if r.case_id else ""
            lines.append(f"  \u2717 {r.test_id}{suffix}")

    by_module: dict[str, list] = {}
    for r in results:
        module = r.groups.get("module") if r.groups else None
        if module is None:
            continue
        by_module.setdefault(module, []).append(r)

    if len(by_module) >= 2:
        lines.append("")
        lines.append("By module:")
        name_width = max(len(m) for m in by_module) if by_module else 0
        for module in sorted(by_module):
            module_results = by_module[module]
            m_total = len(module_results)
            m_passed = sum(1 for r in module_results if r.outcome == "passed")
            m_failed = sum(1 for r in module_results if r.outcome == "failed")
            lines.append(
                f"  {module.ljust(name_width)}  {m_total:>3} total  "
                f"{m_passed:>3} passed  {m_failed:>3} failed"
            )

    return lines


_SYMBOLS = {
    "passed": ".",
    "failed": "F",
    "skipped": "s",
    "fixme": "f",
    "expected_failure": "x",
    "cancelled": "c",
    "not_run": "n",
    "quarantined_failure": "q",
}


class DotsReporter(ConsoleReporter):
    """One character per test: '.' pass, 'F' fail, 's' skip, 'f' fixme,
    'x' expected failure (matches the common xfail convention)."""

    def on_test_end(self, result: Result):
        sys.stdout.write(_SYMBOLS.get(result.outcome, "?"))
        sys.stdout.flush()

    def on_run_end(self, results, duration):
        sys.stdout.write("\n")
        for line in _summary_lines(results, duration):
            print(line)


class LineReporter(ConsoleReporter):
    """Overwrites a single progress line as tests run, printing failures
    as they happen below it -- same idea as Playwright TS's 'line'."""

    def __init__(self):
        self._total = 0
        self._seen = set()

    def reset(self):
        """Clears per-run progress state. The reporter instance is
        reused across projects in a multi-project run (see cli.py's
        multi-project loop), so without this, `_seen` keeps accumulating
        test_ids from earlier projects and the "[n/total]" progress
        counter overshoots the next project's total (e.g. "[26/25]").
        TODO(cli.py owner): call reporter.reset() at the top of each
        per-project run in the multi-project loop (cli.py:613-616) --
        this file cannot call it itself since it has no visibility into
        the per-project loop boundary.
        """
        self._total = 0
        self._seen = set()

    def on_run_start(self, total: int):
        self._total = total

    def on_test_start(self, test_id: str):
        # A retried test sends multiple "started" events for the same
        # test_id; count unique tests, not attempts, so the fraction
        # never overshoots the total.
        self._seen.add(test_id)
        text = f"[{len(self._seen)}/{self._total}] {test_id}"
        sys.stdout.write("\r" + text + " " * max(0, 80 - len(text)))
        sys.stdout.flush()

    def on_test_end(self, result: Result):
        if result.outcome == "failed":
            sys.stdout.write("\n")
            print(f"  \u2717 {result.test_id}")

    def on_run_end(self, results, duration):
        sys.stdout.write("\n")
        for line in _summary_lines(results, duration):
            print(line)


class JsonReporter(ConsoleReporter):
    """Machine-readable summary, loosely modeled on Playwright TS's json
    reporter (flat stats + test list rather than its full nested suite
    tree, which nothing downstream here needs)."""

    def __init__(self, output_path: str = "results.json"):
        self.output_path = output_path
        self._coverage_summary = None
        self._suite_properties: dict = {}

    def set_coverage_summary(self, summary) -> None:
        """Optional capability, duck-typed via hasattr() at the call site
        (same pattern cli.py already uses for _ResetOnRunStartReporter's
        `reset`). Call once, after finalize_coverage() runs, before
        on_run_end()."""
        self._coverage_summary = summary

    def set_suite_properties(self, suite_properties: dict) -> None:
        """Same duck-typed optional-capability pattern as
        set_coverage_summary: the orchestrator (or cli) hands over
        record_suite_property() values before on_run_end()."""
        self._suite_properties = dict(suite_properties or {})

    def on_run_end(self, results, duration, suite_properties=None):
        if suite_properties is not None:
            self._suite_properties = dict(suite_properties)
        passed = sum(1 for r in results if r.outcome == "passed")
        failed = sum(1 for r in results if r.outcome == "failed")
        skipped = sum(
            1
            for r in results
            if r.outcome in ("skipped", "fixme", "cancelled", "not_run", "quarantined_failure")
        )
        expected_failures = sum(1 for r in results if r.outcome == "expected_failure")
        projects = sorted({r.project for r in results if r.project})
        payload = {
            "stats": {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "expectedFailures": expected_failures,
                "duration": round(duration, 3),
            },
            "projects": projects,
            # record_suite_property() values (run-level metadata).
            "suiteProperties": dict(self._suite_properties),
            # The exact same per-test shape the `test_end` event
            # payload carries -- one schema for streaming and reporting,
            # built by one function. Sorted so report order never
            # depends on worker completion timing.
            "tests": [result_to_public_dict(r) for r in sorted(results, key=result_sort_key)],
        }
        if self._coverage_summary is not None:
            payload["stats"]["coveragePercent"] = self._coverage_summary.percent
            if self._coverage_summary.by_file is not None:
                payload["stats"]["coverageByFile"] = self._coverage_summary.by_file
        # Write to a temp file in the same directory then
        # os.replace() over the final path -- consistent with the
        # history store's transactional care. A crash mid-write (or a
        # concurrent reader) then only ever sees the old complete file
        # or the new complete file, never a truncated/partial one.
        output_dir = os.path.dirname(os.path.abspath(self.output_path)) or "."
        fd, tmp_path = tempfile.mkstemp(
            dir=output_dir, prefix=".results-", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.output_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
            raise


REPORTER_REGISTRY = {"line": LineReporter, "dots": DotsReporter, "json": JsonReporter}


def _load_custom_reporter(spec: str):
    """Loads a user-supplied reporter from a 'module.path:ClassName'
    spec (--reporter my_pkg.reporters:SlackReporter). The class must be
    constructible with no arguments and duck-type ConsoleReporter's four
    hooks. Errors raise ValueError so the CLI reports them like any
    other bad --reporter value. A reporter that raises AT RUNTIME is
    already contained by the orchestrator (_safe_console_call disables
    it for the run) -- this only validates load time."""
    module_name, _, class_name = spec.partition(":")
    if not module_name or not class_name:
        raise ValueError(
            f"Invalid custom reporter spec {spec!r} -- expected 'module.path:ClassName'"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ValueError(
            f"Could not import custom reporter module '{module_name}' "
            f"(from spec {spec!r}): {e}"
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(
            f"Module '{module_name}' has no attribute '{class_name}' "
            f"(from custom reporter spec {spec!r})"
        )
    try:
        return cls()
    except Exception as e:
        raise ValueError(
            f"Could not instantiate custom reporter {spec!r} -- the class must "
            f"be constructible with no arguments: {e}"
        ) from e


def build_reporters(names: list[str], json_output: str = "results.json") -> list[ConsoleReporter]:
    reporters = []
    for name in names:
        if ":" in name:
            reporters.append(_load_custom_reporter(name))
            continue
        cls = REPORTER_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown reporter '{name}'. Available: {', '.join(REPORTER_REGISTRY)}, "
                f"or a custom 'module.path:ClassName' spec"
            )
        if name == "json":
            reporters.append(JsonReporter(json_output))
        else:
            reporters.append(cls())
    return reporters
