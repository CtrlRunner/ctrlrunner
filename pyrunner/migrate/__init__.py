"""
pytest -> pyrunner source migration.

Usage:
    python -m pyrunner.migrate tests/            # dry-run: diffs + report
    python -m pyrunner.migrate tests/ --write    # apply in place

Design:
    - libcst-based rewrite: formatting and comments are preserved,
      only the constructs being migrated are touched.
    - dry-run by default; --write applies changes in place (rely on git
      for rollback).
    - everything that has a direct pyrunner equivalent is converted;
      everything that doesn't gets a `# TODO(pyrunner-migrate): ...`
      comment at the exact spot plus an entry in the final report.

libcst is an optional dependency, needed only for migration, never at
test runtime:  pip install libcst
"""

from .report import FileReport, MigrationReport
from .runner import migrate_paths
from .scanner import scan

__all__ = ["migrate_paths", "scan", "FileReport", "MigrationReport"]
