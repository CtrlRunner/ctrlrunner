"""
Historical timing store (storage half; smart sharding is a separate
follow-up that consumes this data, gated on the true-parallelism
prerequisite already being in place, which it is).

A single consolidated SQLite file (not one-file-per-test -- deliberately,
per this project's Windows-CI-first principle: thousands of small files
is a known pain point for AV scanners and filesystem metadata overhead
on Windows CI runners). Written once per run/project via HistoryReporter
(just another ConsoleReporter, called from on_run_end -- never mid-run,
so a crashed/killed run can't corrupt the store mid-write; each write is
one SQLite transaction).
"""

import contextlib
import os
import sqlite3
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .reporters import ConsoleReporter

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL,
    project TEXT
);
CREATE TABLE IF NOT EXISTS test_runs (
    run_id TEXT,
    test_id TEXT,
    project TEXT,
    duration REAL,
    outcome TEXT,
    attempts INTEGER,
    retries_configured INTEGER,
    worker_id INTEGER,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_test_runs_test_id ON test_runs(test_id, project);
"""

# Rows recorded with these outcomes never actually executed (a
# fail-fast run writes a 0.0-duration row for every remaining queued
# test) -- the LPT median and the flake-score denominator must both be
# computed only from rows that ran, so every READ path filters them
# out here. Writes (record_run) deliberately do NOT filter -- history
# should still record everything for later inspection; only reads need
# the filter.
_NON_EXECUTED_OUTCOMES = ("not_run", "cancelled")
_NON_EXECUTED_OUTCOMES_SQL = ", ".join("?" for _ in _NON_EXECUTED_OUTCOMES)

# Duration reads additionally exclude skipped/
# fixme -- those rows record duration~0.0 for a test that never ran its
# body this time, and a conditionally-skipped test would otherwise get
# its LPT median (and near-timeout risk flag) dragged toward zero.
# Outcome reads (flake score) deliberately keep seeing them.
_NON_DURATION_OUTCOMES = ("not_run", "cancelled", "skipped", "fixme")
_NON_DURATION_OUTCOMES_SQL = ", ".join("?" for _ in _NON_DURATION_OUTCOMES)


class HistoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._open(db_path)
        except sqlite3.DatabaseError:
            # A truncated/garbage file (crashed run, disk error, or just
            # not sqlite) must not permanently brick every subsequent
            # run -- history is an optimization, and per this module's
            # own posture, hardening it never crashes an otherwise-
            # successful run. Quarantine the unreadable file for
            # post-mortem and start a fresh store in its place. A second
            # DatabaseError (or a rename failure) propagates: at that
            # point something is genuinely wrong with the location.
            with contextlib.suppress(Exception):
                self._conn.close()
            os.replace(db_path, db_path + ".corrupt")
            self._open(db_path)
        self._migrate_schema()
        # (OWASP A04) sqlite3.connect creates this file with the
        # process umask's default permissions, which on a shared machine
        # or CI runner can leave it group/world-readable -- a co-tenant
        # could then read timing data or poison the store's contents.
        # Lock it down to owner read/write only. Best-effort by design:
        # POSIX-only (Windows has no chmod bits that mean this), skipped
        # if the file somehow isn't there, and any OSError (e.g. a
        # filesystem that rejects chmod) is swallowed -- hardening the
        # history file must never crash an otherwise-successful run.
        if sys.platform != "win32":
            try:
                if os.path.exists(db_path):
                    os.chmod(db_path, 0o600)
            except OSError:
                pass

    def _open(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, timeout=10.0)
        # Multiple ctrlrunner processes could plausibly touch the same
        # history file (e.g. two CI jobs sharing a runner's workspace);
        # a busy_timeout means a brief lock contention waits and retries
        # instead of immediately raising "database is locked".
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate_schema(self):
        """`CREATE TABLE IF NOT EXISTS` in _SCHEMA is a no-op against a
        table that already exists from before a column was added to it
        here -- e.g. a reports/.history.db created before the
        worker_id column existed. Since this module's whole point is
        accumulating history across runs over time, such pre-existing
        on-disk databases are the expected common case, not an edge
        case. ADD COLUMN is the lightweight fix; guarded by checking
        PRAGMA table_info first since ALTER TABLE ADD COLUMN errors on
        a column that already exists.

        This check-then-act (check column existence, then ADD
        COLUMN) is racy across processes -- two ctrlrunner processes
        opening the same pre-migration database concurrently can both
        see the column missing and both attempt to add it, and the
        loser crashes with sqlite3.OperationalError: duplicate column
        name. Since the whole point is "already migrated" and
        "someone else just migrated it" are equivalent outcomes here,
        catch that specific error and treat it as a no-op instead of
        letting it crash the run."""
        cols = [row[1] for row in self._conn.execute("PRAGMA table_info(test_runs)")]
        if cols and "worker_id" not in cols:
            try:
                self._conn.execute("ALTER TABLE test_runs ADD COLUMN worker_id INTEGER")
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
                # Another process's migration won the race between our
                # PRAGMA check and our ALTER TABLE -- the column exists
                # now, which is exactly what we wanted, so treat this as
                # success rather than propagating the crash.

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def record_run(
        self,
        results: list,
        project: str | None = None,
        run_id: str | None = None,
        started_at: float | None = None,
    ) -> str:
        """Writes one `runs` row plus one `test_runs` row per result, all
        in a single transaction -- a run that gets interrupted before
        this is called (killed mid-test) simply never gets recorded,
        rather than leaving a partial/corrupt entry. Returns the run_id
        used (generated if not given)."""
        if not results:
            return run_id or ""

        run_id = run_id or str(uuid.uuid4())
        started_at = started_at if started_at is not None else time.time()
        # A per-result project (multi-project runs stamp this on every
        # Result already) wins over the explicit `project` argument;
        # falls back to whatever's given/None for a plain run.
        run_project = project
        for r in results:
            if getattr(r, "project", None):
                run_project = r.project
                break

        with self._conn:
            self._conn.execute(
                "INSERT INTO runs (run_id, started_at, project) VALUES (?, ?, ?)",
                (run_id, started_at, run_project),
            )
            self._conn.executemany(
                "INSERT INTO test_runs (run_id, test_id, project, duration, outcome, "
                "attempts, retries_configured, worker_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        r.test_id,
                        r.project,
                        r.duration,
                        r.outcome,
                        r.attempts,
                        r.retries_configured,
                        getattr(r, "worker_id", None),
                    )
                    for r in results
                ],
            )
        return run_id

    def get_durations(
        self, test_id: str, project: str | None = None, window: int = 20
    ) -> list[float]:
        """Most recent `window` durations for a test, newest first --
        the direct input section 4.8's LPT sharding weight and section
        4.9's flake-score window will both consume."""
        cur = self._conn.execute(
            "SELECT test_runs.duration FROM test_runs "
            "JOIN runs ON runs.run_id = test_runs.run_id "
            "WHERE test_runs.test_id = ? AND "
            "(test_runs.project = ? OR (test_runs.project IS NULL AND ? IS NULL)) AND "
            f"test_runs.outcome NOT IN ({_NON_DURATION_OUTCOMES_SQL}) "
            "ORDER BY runs.started_at DESC LIMIT ?",
            (test_id, project, project, *_NON_DURATION_OUTCOMES, window),
        )
        return [row[0] for row in cur.fetchall()]

    def get_outcomes(
        self, test_id: str, project: str | None = None, window: int = 20
    ) -> list[dict]:
        """Most recent `window` (outcome, attempts, retries_configured)
        rows for a test, newest first -- section 4.9's flake-score
        input."""
        cur = self._conn.execute(
            "SELECT test_runs.outcome, test_runs.attempts, test_runs.retries_configured "
            "FROM test_runs "
            "JOIN runs ON runs.run_id = test_runs.run_id "
            "WHERE test_runs.test_id = ? AND "
            "(test_runs.project = ? OR (test_runs.project IS NULL AND ? IS NULL)) AND "
            f"test_runs.outcome NOT IN ({_NON_EXECUTED_OUTCOMES_SQL}) "
            "ORDER BY runs.started_at DESC LIMIT ?",
            (test_id, project, project, *_NON_EXECUTED_OUTCOMES, window),
        )
        return [
            {"outcome": row[0], "attempts": row[1], "retries_configured": row[2]}
            for row in cur.fetchall()
        ]

    def list_test_ids(self, project: str | None = None) -> list[str]:
        """Every distinct test_id with at least one recorded run,
        scoped by project -- section 4.9's `ctrlrunner flaky-report`
        starting point (it needs to know what to compute scores for,
        without a live test collection at hand)."""
        cur = self._conn.execute(
            "SELECT DISTINCT test_id FROM test_runs WHERE "
            "(project = ? OR (project IS NULL AND ? IS NULL)) ORDER BY test_id",
            (project, project),
        )
        return [row[0] for row in cur.fetchall()]


@dataclass
class HistoryConfig:
    enabled: bool = True
    db_path: str | None = None
    window_runs: int = 20


def resolve_history_config(config: dict) -> HistoryConfig:
    section = config.get("history", {}) or {}

    enabled = section.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"[ctrlrunner.history].enabled must be a boolean, got {enabled!r}")
    # None (the default) means "derive from reports_dir" -- the CLI
    # caller resolves that, since HistoryConfig itself has no knowledge
    # of reports_dir. Only an explicitly-given non-string value is
    # invalid.
    db_path = section.get("db_path")
    if db_path is not None and not isinstance(db_path, str):
        raise ValueError(f"[ctrlrunner.history].db_path must be a string, got {db_path!r}")
    window_runs = section.get("window_runs", 20)
    if not isinstance(window_runs, int) or isinstance(window_runs, bool):
        raise ValueError(f"[ctrlrunner.history].window_runs must be an integer, got {window_runs!r}")
    if window_runs < 1:
        # window_runs feeds a SQLite LIMIT, where a negative value means
        # "no limit" -- a misconfiguration would silently defeat the
        # window instead of erroring.
        raise ValueError(
            f"[ctrlrunner.history].window_runs must be a positive integer, got {window_runs!r}"
        )

    return HistoryConfig(enabled=enabled, db_path=db_path, window_runs=window_runs)


def compute_near_timeout_test_ids(
    test_ids: list[str],
    timeouts: dict,
    history_store: "HistoryStore",
    project: str | None = None,
    window: int = 20,
    threshold: float = 0.8,
) -> set[str]:
    """Section 4.8's hang-risk heuristic: flags a test_id whose median
    historical duration sits at or above `threshold` (default 80%) of
    its configured timeout -- a `--list json` consumer's early warning
    that a test is one slow CI runner away from a hard-kill, without
    needing to actually run it. A test with no history yet is never
    flagged (nothing to compare against), and a test with no configured
    timeout is never flagged (nothing to compare it to).

    A pure function over already-fetched durations, matching lpt_shard's
    style -- the only place list output genuinely needs history, since a list
    command has no live duration of its own, only past ones."""
    flagged: set[str] = set()
    for test_id in test_ids:
        durations = history_store.get_durations(test_id, project=project, window=window)
        if not durations:
            continue
        median = statistics.median(durations)
        timeout = timeouts.get(test_id)
        if timeout and median >= threshold * timeout:
            flagged.add(test_id)
    return flagged


class HistoryReporter(ConsoleReporter):
    """Records one run's results to a HistoryStore on_run_end. Safe to
    reuse the same instance across multiple Orchestrator.run() calls
    (e.g. one project after another in run_projects()) -- each call
    generates its own run_id and INSERTs new rows; unlike JsonReporter's
    single-file overwrite, SQLite writes are naturally additive, so no
    special multi-project handling is needed here."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def on_run_start(self, total):
        pass

    def on_test_start(self, test_id):
        pass

    def on_test_end(self, result):
        pass

    def on_run_end(self, results, duration):
        if not results:
            return
        with HistoryStore(self.db_path) as store:
            store.record_run(results)
