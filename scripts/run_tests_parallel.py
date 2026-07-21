#!/usr/bin/env python3
"""Run ctrlrunner's own tests/ suite in parallel, one OS subprocess per test file.

Deliberately does not use ctrlrunner itself or pytest to run these tests (see
docs/development.md) and adds no new dependency: each test file is run as a
plain ``python -m unittest tests.<module>`` subprocess.

The driver process uses a ThreadPoolExecutor purely to manage several
concurrent blocking subprocess.run() calls -- it never touches test code or
cwd itself. tests/test_cli.py and tests/test_backward_compatibility.py call
os.chdir() in setUp/tearDown, which is process-global state; that's safe here
because each chdir happens inside its own spawned unittest subprocess with its
own OS-level cwd, not inside the driver's threads. Do not "fix" this into
multiprocessing/ProcessPoolExecutor -- it isn't needed and only adds
spawn-safety/pickling concerns that subprocess-per-file sidesteps entirely.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

_SUMMARY_RE = re.compile(r"Ran (\d+) tests? in ([\d.]+)s")
_RESULT_RE = re.compile(r"^(OK|FAILED)\s*(?:\(([^)]*)\))?\s*$", re.MULTILINE)


def discover_files(tests_dir: Path) -> list[Path]:
    return sorted(tests_dir.glob("test*.py"))


def _weight(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def compute_buckets(files: list[Path], n: int) -> list[list[Path]]:
    """Greedy largest-first-onto-min-loaded-bucket (LPT-lite by line count).

    Same shape as src/ctrlrunner/execution/sharding.py's duration-based LPT
    bin-packing, duplicated rather than imported: importing the package under
    test to run its own test suite would undercut the "avoids the irony"
    rationale in docs/development.md.
    """
    n = max(1, min(n, len(files)))
    sized = sorted(files, key=lambda p: (-_weight(p), p.name))
    buckets: list[list[Path]] = [[] for _ in range(n)]
    loads = [0] * n
    for f in sized:
        idx = loads.index(min(loads))
        buckets[idx].append(f)
        loads[idx] += _weight(f)
    return [b for b in buckets if b]


@dataclass
class FileResult:
    path: Path
    returncode: int
    duration: float
    output: str
    summary: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.summary:
            return "CRASH"
        return self.summary.get("status", "CRASH")


def parse_summary(output: str) -> dict | None:
    m_ran = _SUMMARY_RE.search(output)
    m_res = _RESULT_RE.search(output)
    if not (m_ran and m_res):
        return None
    total, duration = int(m_ran.group(1)), float(m_ran.group(2))
    counts: dict[str, int] = {}
    if m_res.group(2):
        for part in m_res.group(2).split(","):
            name, _, val = part.strip().partition("=")
            if name and val:
                counts[name.strip()] = int(val)
    return {"total": total, "duration": duration, "status": m_res.group(1), **counts}


def run_one(path: Path, verbose: bool) -> FileResult:
    module = f"tests.{path.stem}"
    cmd = [sys.executable, "-m", "unittest"]
    if verbose:
        cmd.append("-v")
    cmd.append(module)
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = proc.stdout + proc.stderr
    summary = parse_summary(output) or {}
    duration = summary.get("duration", 0.0)
    return FileResult(
        path=path, returncode=proc.returncode, duration=duration, output=output, summary=summary
    )


def run_bucket(bucket: list[Path], verbose: bool, print_lock: threading.Lock, quiet: bool):
    results = []
    for path in bucket:
        result = run_one(path, verbose)
        results.append(result)
        if not quiet or result.returncode != 0:
            with print_lock:
                rel = result.path.relative_to(REPO_ROOT)
                print(f"==== {rel}  {result.duration:.2f}s ====")
                print(result.output.rstrip())
                print("-" * 75)
    return results


def format_summary_table(results: list[FileResult]) -> str:
    lines = []
    header = f"{'file':<45} {'total':>6} {'fail':>5} {'err':>5} {'skip':>5} {'time':>8}  verdict"
    lines.append(header)
    lines.append("-" * len(header))
    totals = {"total": 0, "failures": 0, "errors": 0, "skipped": 0, "duration": 0.0}
    for r in sorted(results, key=lambda r: str(r.path)):
        s = r.summary
        total = s.get("total", 0)
        failures = s.get("failures", 0)
        errors = s.get("errors", 0)
        skipped = s.get("skipped", 0)
        duration = s.get("duration", 0.0)
        totals["total"] += total
        totals["failures"] += failures
        totals["errors"] += errors
        totals["skipped"] += skipped
        totals["duration"] += duration
        rel = r.path.relative_to(REPO_ROOT)
        lines.append(
            f"{str(rel):<45} {total:>6} {failures:>5} {errors:>5} {skipped:>5} "
            f"{duration:>7.2f}s  {r.status}"
        )
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<45} {totals['total']:>6} {totals['failures']:>5} {totals['errors']:>5} "
        f"{totals['skipped']:>5} {totals['duration']:>7.2f}s"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=getattr(os, "process_cpu_count", os.cpu_count)() or 1,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true", help="only show non-passing files")
    parser.add_argument("--dry-run", action="store_true", help="print bucket assignment and exit")
    parser.add_argument("patterns", nargs="*", help="test file stems to run (default: all)")
    args = parser.parse_args(argv)

    files = discover_files(TESTS_DIR)
    if args.patterns:
        wanted = set(args.patterns)
        files = [f for f in files if f.stem in wanted]
        if not files:
            print(f"No test files matched: {args.patterns}", file=sys.stderr)
            return 2

    buckets = compute_buckets(files, args.workers)

    if args.dry_run:
        for i, bucket in enumerate(buckets):
            weight = sum(_weight(f) for f in bucket)
            names = ", ".join(f.name for f in bucket)
            print(f"worker {i}: {weight} lines -- {names}")
        return 0

    print_lock = threading.Lock()
    all_results: list[FileResult] = []
    with ThreadPoolExecutor(max_workers=len(buckets)) as pool:
        futures = [
            pool.submit(run_bucket, bucket, args.verbose, print_lock, args.quiet)
            for bucket in buckets
        ]
        for future in as_completed(futures):
            all_results.extend(future.result())

    print()
    print(format_summary_table(all_results))

    overall_rc = 0 if all(r.returncode == 0 for r in all_results) else 1
    print()
    print("OK" if overall_rc == 0 else "FAILED")
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
