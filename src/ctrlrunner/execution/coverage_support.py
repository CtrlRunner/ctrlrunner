"""Coverage.py integration support: config resolution and per-run data-dir
lifecycle. The `coverage` package itself is imported lazily inside
finalize_coverage() (see Task 2) and inside worker.py's run_worker() (see
Task 3) -- never at this module's top level -- so importing this module
never requires the optional 'coverage' extra to be installed.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CoverageConfig:
    """Resolved, run-scoped coverage configuration. The SAME instance is
    passed to every Orchestrator in a multi-project run (see Task 4's
    run_projects() threading), so `hard_kills` accumulates correctly
    across all projects sharing this one run."""

    enabled: bool
    data_dir: str
    html_dir: str | None
    source: list[str] | None
    fail_under: float | None
    fail_under_enforced: bool
    contexts: bool
    hard_kills: int = 0


def resolve_coverage_config(
    config: dict,
    *,
    cli_enabled: bool,
    cli_html_dir: str | None,
    report_dir: str,
    selection_filtered: bool,
) -> CoverageConfig | None:
    """Mirrors resolve_fail_policy()/resolve_quarantine_config(): reads
    config["coverage"], layers CLI flags on top (CLI wins on html_dir),
    raises ValueError on bad config. Returns None when coverage is off --
    callers must treat None as "feature fully inactive, zero overhead."
    """
    section = config.get("coverage", {}) or {}

    enabled = cli_enabled or bool(section.get("enabled", False))
    if not enabled:
        return None

    fail_under = section.get("fail_under")
    if fail_under is not None and (
        not isinstance(fail_under, (int, float)) or isinstance(fail_under, bool)
    ):
        raise ValueError(f"[ctrlrunner.coverage].fail_under must be a number, got {fail_under!r}")

    source = section.get("source")
    if source is not None and not (
        isinstance(source, list) and all(isinstance(s, str) for s in source)
    ):
        raise ValueError(f"[ctrlrunner.coverage].source must be a list of strings, got {source!r}")

    html_dir = cli_html_dir
    if html_dir is None:
        configured = section.get("html_dir")
        if configured:
            html_dir = configured

    return CoverageConfig(
        enabled=True,
        data_dir=os.path.join(report_dir, ".coverage-data"),
        html_dir=html_dir,
        source=source,
        fail_under=float(fail_under) if fail_under is not None else None,
        fail_under_enforced=not selection_filtered,
        contexts=bool(section.get("contexts", False)),
    )


def prepare_data_dir(coverage_config: CoverageConfig) -> None:
    """Purge and recreate the per-run data directory. Call once, before
    any worker is spawned -- a stale file left over from a previous
    crashed run in the same reports_dir would silently pollute combine()
    (see Task 2's finalize_coverage)."""
    # Containment guard: never rmtree the filesystem root or a path that
    # doesn't sit strictly under its own resolved parent. data_dir is
    # config-derived, so a misconfiguration must not turn this purge into
    # a catastrophic recursive delete.
    resolved = Path(coverage_config.data_dir).resolve()
    if resolved.parent == resolved or not resolved.is_relative_to(resolved.parent):
        raise ValueError(
            f"Refusing to purge unsafe coverage data_dir: {coverage_config.data_dir!r} "
            f"(resolved to {resolved})"
        )
    shutil.rmtree(resolved, ignore_errors=True)
    os.makedirs(coverage_config.data_dir, exist_ok=True)


@dataclass
class CoverageSummary:
    percent: float
    by_file: dict[str, float] | None
    html_dir: str | None
    hard_kills: int


def finalize_coverage(coverage_config: CoverageConfig) -> CoverageSummary:
    """Combine every worker's data file in coverage_config.data_dir,
    generate the optional HTML report, and compute the aggregate +
    per-file percentages. Call exactly once, after every worker process
    (across every project, in a multi-project run) has exited --
    combine() only sees whatever data files are already flushed to disk.
    """
    import io

    from coverage import Coverage

    cov = Coverage(
        data_file=os.path.join(coverage_config.data_dir, ".coverage"),
        source=coverage_config.source,
    )
    cov.combine(data_paths=[coverage_config.data_dir])
    cov.save()

    out = io.StringIO()
    try:
        percent = cov.report(file=out, ignore_errors=True)
    except Exception:
        # No data at all (e.g. every worker was hard-killed before saving,
        # or zero tests ran) -- report 0% rather than raising, matching
        # the "never let coverage reporting crash the run" posture.
        percent = 0.0

    by_file: dict[str, float] = {}
    for filename in cov.get_data().measured_files():
        try:
            _, statements, _, missing, _ = cov.analysis2(filename)
        except Exception:
            continue
        total = len(statements)
        if total == 0:
            continue
        covered = total - len(missing)
        by_file[filename] = round(100.0 * covered / total, 2)

    if coverage_config.html_dir:
        cov.html_report(directory=coverage_config.html_dir, ignore_errors=True)

    return CoverageSummary(
        percent=round(percent, 2),
        by_file=by_file or None,
        html_dir=coverage_config.html_dir,
        hard_kills=coverage_config.hard_kills,
    )
