"""
Resolves where a managed HTML report directory lives, and prunes old
timestamped ones so a long-running project doesn't accumulate one
directory per run forever.

Layout produced:

    <reports_root>/<report_name>[-<timestamp>]/
        report.html
        <artifacts_dir_name>/...
"""

import secrets
import shutil
import time
from pathlib import Path

# A directory younger than this is never pruned, even if the
# retention count (`keep`) would otherwise call for it -- a concurrent
# run could still be writing to it. Small enough to not meaningfully
# relax retention in normal (non-overlapping) usage, large enough to
# cover a realistic overlap between one run finishing and the next
# starting.
_PRUNE_GRACE_SECONDS = 2.0


def resolve_report_dir(
    reports_root: str = "reports",
    report_name: str = "html-report",
    timestamp: bool = False,
    keep: int = 10,
) -> Path:
    reports_root_path = Path(reports_root)
    reports_root_path.mkdir(parents=True, exist_ok=True)

    if timestamp:
        # time.strftime() only has second resolution, so two
        # runs started within the same second used to produce the
        # identical dir_name -- mkdir(exist_ok=True) then silently
        # merged them into one directory instead of creating two. A
        # short random suffix makes collisions negligible without
        # needing an existence-check-then-create loop (which would
        # itself race against a concurrent process).
        dir_name = f"{report_name}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        _prune_old_reports(reports_root_path, report_name, keep)
    else:
        dir_name = report_name

    report_dir = reports_root_path / dir_name
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def find_latest_report_dir(
    reports_root: str = "reports", report_name: str = "html-report"
) -> Path | None:
    """Read-only counterpart to resolve_report_dir(), for --last-failed
    (section 4.11): finds the most recently modified *existing* report
    directory (either the plain `<report_name>/` used when
    report_timestamp=false, or the newest `<report_name>-<timestamp>/`)
    without creating anything. Returns None if no report has ever been
    written -- deliberately never creates a directory here, unlike
    resolve_report_dir(), since v1 of this feature's design mistakenly
    reused resolve_report_dir() and would have minted a fresh, empty
    timestamped directory instead of finding the previous run's."""
    reports_root_path = Path(reports_root)
    if not reports_root_path.is_dir():
        return None

    candidates = []
    plain = reports_root_path / report_name
    if plain.is_dir():
        candidates.append(plain)
    prefix = f"{report_name}-"
    candidates.extend(
        p for p in reports_root_path.iterdir() if p.is_dir() and p.name.startswith(prefix)
    )
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _prune_old_reports(reports_root: Path, report_name: str, keep: int):
    """Keeps only the `keep - 1` most recent '<report_name>-<timestamp>'
    directories (the `- 1` makes room for the one this run is about to
    create), deleting older ones -- except any directory younger than
    `_PRUNE_GRACE_SECONDS`: a concurrent run may still be
    writing to it, so it's skipped even if it falls in the "excess"
    range. It may then outlive the requested `keep` count by one run's
    worth of directories, which is the safer failure mode."""
    if keep <= 0:
        return
    prefix = f"{report_name}-"
    candidates = sorted(
        (p for p in reports_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        key=lambda p: p.stat().st_mtime,
    )
    excess = candidates[: max(0, len(candidates) - (keep - 1))]
    now = time.time()
    for p in excess:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if now - mtime < _PRUNE_GRACE_SECONDS:
            continue
        # Containment guard: only ever rmtree paths that resolve to
        # somewhere strictly under reports_root. A symlink or otherwise
        # unexpected entry from iterdir() must not let this prune escape
        # the reports tree and delete something outside it.
        if not p.resolve().is_relative_to(reports_root.resolve()):
            continue
        shutil.rmtree(p, ignore_errors=True)
