"""
A lightweight reproducibility bundle written
next to results.json -- pyrunner/Python versions, the resolved run
config, the CLI invocation, the git SHA (best-effort), and which test
ids failed. Not a replacement for results.json (which has full
per-test detail) -- this is the "what do I need to tell someone to
reproduce this exact run" summary in one small file.
"""

import contextlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version


def _pyrunner_version() -> str:
    try:
        return version("pyrunner")
    except PackageNotFoundError:
        return "unknown"


def _git_sha(cwd: str | None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_manifest(
    *,
    argv: list[str],
    root: str,
    num_workers: int,
    timeout: float,
    import_timeout: float,
    order: str,
    seed: int | None,
    total_tests: int,
    failed_test_ids: list[str],
    cwd: str | None = None,
) -> dict:
    return {
        "pyrunnerVersion": _pyrunner_version(),
        "pythonVersion": sys.version.split()[0],
        "platform": platform.platform(),
        "argv": list(argv),
        "gitSha": _git_sha(cwd),
        "root": root,
        "numWorkers": num_workers,
        "timeout": timeout,
        "importTimeout": import_timeout,
        "order": order,
        "seed": seed,
        "totalTests": total_tests,
        "failedTestIds": list(failed_test_ids),
    }


def write_manifest(path: str, manifest: dict) -> None:
    """Same atomic-write contract as JsonReporter/JUnitReporter: a crash
    mid-write must never leave CI a truncated or partial manifest."""
    output_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, prefix=".run-manifest-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise
