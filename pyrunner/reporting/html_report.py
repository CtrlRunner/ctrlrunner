"""
Static, self-contained HTML report, analogous to Playwright TS's
html-reporter package.

The page itself is a prebuilt React app (frontend/ in the repo root,
built with Vite into pyrunner/reporting/_static/report/index.html as a
single file with all JS/CSS inlined). render_html() only assembles the
report data and splices it into that prebuilt page as a
`window.__PYRUNNER_REPORT__ = {...}` script -- the same data contract
the old vanilla-JS renderer used, so consumers (and tests) that parse
the embedded JSON keep working.

Artifact handling:
    - "files" (default): every artifact (screenshots, trace zips, ...)
      is copied into <report_dir>/artifacts/, so the report + that
      directory together are portable as a unit.
    - "base64": only IMAGE artifacts are embedded inline as data: URIs
      (identified by MIME type, not extension). Non-image artifacts
      (trace zips in particular) are always copied as files regardless
      of this setting -- inlining a multi-MB trace would bloat the
      report for no benefit, since it can't be previewed inline anyway.

When a trace zip ends up file-copied under <report_dir>/artifacts/, the
trace-viewer web app bundled with the installed Playwright package is
also copied into <report_dir>/trace/, so the report can link straight to
an interactive trace view instead of just a raw zip download (see
_bundle_trace_viewer()).
"""

import base64
import datetime
import inspect
import json
import mimetypes
import re
import shutil
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from .reporter import Result

# Marker in the prebuilt page (emitted by frontend/index.html) that gets
# replaced with the report-data script. Kept as an HTML comment so the
# built asset stays a valid page even before injection.
_DATA_MARKER = "<!--PYRUNNER_DATA-->"

# Text content is escaped everywhere in this report, but artifact
# hrefs are not text -- they're rendered as a real <a href> (and
# sometimes an <img src>). A worker-supplied artifact string is not
# guaranteed to be a real file path (a plugin/worker could hand back
# anything), so "javascript:alert(1)" must never reach the DOM
# unsanitized: only relative paths (no scheme) and http/https/file are
# allowed as clickable hrefs. A single-letter "scheme" is a Windows
# drive letter (C:\...), not a URL scheme, so it's treated as safe.
_SAFE_HREF_SCHEMES = {"", "http", "https", "file"}


def _sanitize_href(href: str) -> str:
    scheme = urlsplit(href).scheme.lower()
    if len(scheme) == 1:  # Windows drive letter, e.g. "C:\..."
        return href
    if scheme not in _SAFE_HREF_SCHEMES:
        return "#"
    return href


def _relative_artifact_key(path: Path) -> str:
    """Keeps just enough of the original path (test dir / attempt-N /
    filename) to stay unique across tests without replicating the whole
    pyrunner-artifacts/ tree."""
    parts = path.parts[-3:] if len(path.parts) >= 3 else path.parts
    return "/".join(parts)


def _artifact_data_uri(path: Path, mime: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _process_artifacts(artifact_paths, artifact_mode: str, report_dir: Path | None) -> list:
    processed = []
    for raw in artifact_paths:
        src = Path(raw)
        if not src.exists():
            processed.append({"label": raw, "href": _sanitize_href(raw), "embedded": False})
            continue

        mime, _ = mimetypes.guess_type(str(src))
        is_image = bool(mime and mime.startswith("image/"))

        if artifact_mode == "base64" and is_image:
            processed.append(
                {"label": src.name, "href": _artifact_data_uri(src, mime), "embedded": True}
            )
        elif report_dir is not None:
            key = _relative_artifact_key(src)
            dest = report_dir / "artifacts" / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            processed.append({"label": src.name, "href": f"artifacts/{key}", "embedded": False})
        else:
            processed.append({"label": src.name, "href": _sanitize_href(raw), "embedded": False})
    return processed


def _has_copied_trace(rows: list[dict]) -> bool:
    return any(
        a["label"].endswith(".zip") and a["href"].startswith("artifacts/")
        for row in rows
        for a in row["artifacts"]
    )


def _bundle_trace_viewer(report_dir: Path) -> None:
    """Copies the trace-viewer web app bundled with the installed Playwright
    package into <report_dir>/trace/, so a trace.zip artifact opens as a
    full interactive view inside this report instead of just downloading --
    same approach Playwright's own Node html-reporter uses (see
    packages/playwright/src/reporters/html.ts in the playwright repo), just
    sourced from the Python package's driver instead of playwright-core."""
    try:
        import playwright
    except ImportError:
        return

    src = (
        Path(inspect.getfile(playwright)).parent
        / "driver"
        / "package"
        / "lib"
        / "vite"
        / "traceViewer"
    )
    if not src.is_dir():
        return

    dest = report_dir / "trace"
    dest_assets = dest / "assets"
    dest_assets.mkdir(parents=True, exist_ok=True)

    for f in src.iterdir():
        if f.is_dir() or f.suffix == ".map" or "watch" in f.name or "assets" in f.name:
            continue
        shutil.copy2(f, dest / f.name)

    assets_src = src / "assets"
    if assets_src.is_dir():
        for f in assets_src.iterdir():
            if f.suffix == ".map" or "xtermModule" in f.name:
                continue
            shutil.copy2(f, dest_assets / f.name)


def _result_to_dict(r: Result, artifact_mode: str, report_dir: Path | None) -> dict:
    return {
        "id": r.test_id,
        "caseId": r.case_id,
        "tags": sorted(r.tags),
        "outcome": r.outcome,
        "duration": round(r.duration, 3),
        "attempts": r.attempts,
        "error": r.error,
        "artifacts": _process_artifacts(r.artifacts, artifact_mode, report_dir),
        "steps": r.steps,
        "properties": r.properties,
        "groups": r.groups,
        "quarantined": r.quarantined,
        "quarantineReason": r.quarantine_reason,
        "nearTimeout": r.near_timeout,
        "workerRestartOverhead": r.worker_restart_overhead,
        "assertDetails": r.assert_details,
        "logs": r.logs,
        "workerId": r.worker_id,
        "flaky": r.flaky,
        "startedAt": r.started_at,
    }


def _load_static_page() -> str:
    page = (
        resources.files("pyrunner.reporting")
        .joinpath("_static/report/index.html")
        .read_text(encoding="utf-8")
    )
    if _DATA_MARKER not in page:
        raise RuntimeError(
            "Prebuilt report page is missing its data marker -- "
            "rebuild the frontend (cd frontend && npm run build)"
        )
    # The report must stay a single portable file: the Vite build inlines
    # all JS/CSS, and this guards against a config regression that would
    # silently reintroduce external asset references. (Match actual tags:
    # the inlined <style> keeps a vestigial rel="stylesheet" attribute,
    # and JS string literals may legitimately contain 'src="'.)
    if re.search(r"<script[^>]*\bsrc=", page) or re.search(r'<link[^>]*rel="stylesheet"', page):
        raise RuntimeError(
            "Prebuilt report page references external assets; "
            "expected a fully inlined single-file build"
        )
    return page


def render_html(
    results: list[Result],
    suite_name: str = "pyrunner",
    artifact_mode: str = "files",
    report_dir: str | None = None,
    coverage_summary: dict | None = None,
    run_started_at: float | None = None,
    run_duration: float | None = None,
    num_workers: int | None = None,
) -> str:
    """
    report_dir: where artifacts get copied to (as <report_dir>/artifacts/).
    If None, artifact paths are left as-is (reference wherever they
    already are -- not portable if the report is moved elsewhere).
    """
    if artifact_mode not in ("files", "base64"):
        raise ValueError(f"Unknown artifact_mode '{artifact_mode}', expected 'files' or 'base64'")

    report_dir_path = Path(report_dir) if report_dir else None
    if report_dir_path is not None:
        (report_dir_path / "artifacts").mkdir(parents=True, exist_ok=True)

    rows = [_result_to_dict(r, artifact_mode, report_dir_path) for r in results]

    if report_dir_path is not None and _has_copied_trace(rows):
        _bundle_trace_viewer(report_dir_path)

    # Preserve first-seen order across results so the dropdown's default
    # selection is deterministic and matches config declaration order
    # (compute_groups() emits dict keys in dimension-declaration order,
    # and dict insertion order is preserved from the first result that
    # has any groups at all).
    dimension_names = []
    for row in rows:
        for name in row["groups"]:
            if name not in dimension_names:
                dimension_names.append(name)

    data = {
        "suiteName": suite_name,
        "tests": rows,
        "dimensions": dimension_names,
        "coverage": coverage_summary,
        "generatedAt": datetime.datetime.now(datetime.UTC).isoformat(),
        "totalDuration": round(sum(r.duration for r in results), 3),
        "runStartedAt": run_started_at,
        "runDuration": run_duration,
        "numWorkers": num_workers,
    }
    data_json = json.dumps(data).replace("</", "<\\/")  # don't close </script> early

    page = _load_static_page()
    return page.replace(
        _DATA_MARKER,
        f"<script>window.__PYRUNNER_REPORT__ = {data_json};</script>",
        1,
    )
