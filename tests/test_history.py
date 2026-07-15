import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from pyrunner.reporting.history import (
    HistoryReporter,
    HistoryStore,
    compute_near_timeout_test_ids,
    resolve_history_config,
)
from pyrunner.reporting.reporter import Result


def _result(
    test_id,
    outcome="passed",
    duration=1.0,
    attempts=1,
    retries_configured=None,
    project=None,
    worker_id=None,
):
    return Result(
        test_id=test_id,
        outcome=outcome,
        error=None,
        duration=duration,
        attempts=attempts,
        retries_configured=retries_configured,
        project=project,
        worker_id=worker_id,
    )


class HistoryStoreTests(unittest.TestCase):
    def test_creates_db_file_and_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "nested" / "history.db")
            store = HistoryStore(db_path)
            store.close()
            self.assertTrue(Path(db_path).exists())

    @unittest.skipIf(sys.platform == "win32", "POSIX file mode bits only")
    def test_db_file_is_owner_read_write_only(self):
        # M2 (OWASP A04): the history db must not be left
        # group/world-readable on a shared machine/CI runner.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            store = HistoryStore(db_path)
            store.close()
            self.assertEqual(stat.S_IMODE(os.stat(db_path).st_mode), 0o600)

    def test_corrupt_db_file_is_quarantined_and_store_recovers(self):
        # History is an optimization (LPT sharding, flaky stats) -- a
        # truncated/garbage .history.db from a previous crashed run must
        # not permanently brick every subsequent run. The store's own
        # posture ("hardening the history file must never crash an
        # otherwise-successful run") demands it recovers: quarantine the
        # unreadable file and start fresh.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            Path(db_path).write_bytes(b"this is not a sqlite database at all")
            with HistoryStore(db_path) as store:
                run_id = store.record_run([_result("mod::a")])
                self.assertIsNotNone(run_id)
            # the corrupt original is preserved for post-mortem, not lost
            self.assertTrue(Path(db_path + ".corrupt").exists())
            self.assertEqual(
                Path(db_path + ".corrupt").read_bytes(),
                b"this is not a sqlite database at all",
            )

    def test_record_run_writes_runs_and_test_runs_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                run_id = store.record_run([_result("mod::a"), _result("mod::b", outcome="failed")])
                cur = store._conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (run_id,))
                self.assertEqual(cur.fetchone()[0], 1)
                cur = store._conn.execute(
                    "SELECT COUNT(*) FROM test_runs WHERE run_id = ?", (run_id,)
                )
                self.assertEqual(cur.fetchone()[0], 2)

    def test_empty_results_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([])
                cur = store._conn.execute("SELECT COUNT(*) FROM runs")
                self.assertEqual(cur.fetchone()[0], 0)

    def test_get_durations_returns_newest_first_within_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                for i, dur in enumerate([1.0, 2.0, 3.0]):
                    store.record_run([_result("mod::a", duration=dur)], started_at=float(i))
                durations = store.get_durations("mod::a", window=10)
                self.assertEqual(durations, [3.0, 2.0, 1.0])

    def test_get_durations_respects_window_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                for i in range(5):
                    store.record_run([_result("mod::a", duration=float(i))], started_at=float(i))
                durations = store.get_durations("mod::a", window=2)
                self.assertEqual(len(durations), 2)
                self.assertEqual(durations, [4.0, 3.0])

    def test_get_durations_scoped_by_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", duration=1.0, project="smoke")])
                store.record_run([_result("mod::a", duration=99.0, project="regression")])
                self.assertEqual(store.get_durations("mod::a", project="smoke"), [1.0])
                self.assertEqual(store.get_durations("mod::a", project="regression"), [99.0])

    def test_get_durations_unknown_test_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                self.assertEqual(store.get_durations("mod::nonexistent"), [])

    def test_get_outcomes_includes_retries_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run(
                    [_result("mod::a", outcome="passed", attempts=2, retries_configured=1)]
                )
                outcomes = store.get_outcomes("mod::a")
                self.assertEqual(
                    outcomes, [{"outcome": "passed", "attempts": 2, "retries_configured": 1}]
                )

    def test_multiple_runs_accumulate_not_overwrite(self):
        # the key property that makes HistoryReporter safe to reuse
        # across multiple project runs unlike JsonReporter
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a")])
                store.record_run([_result("mod::b")])
                cur = store._conn.execute("SELECT COUNT(*) FROM runs")
                self.assertEqual(cur.fetchone()[0], 2)

    def test_list_test_ids_returns_distinct_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a")])
                store.record_run([_result("mod::a")])  # same test, second run
                store.record_run([_result("mod::b")])
                self.assertEqual(store.list_test_ids(), ["mod::a", "mod::b"])

    def test_list_test_ids_scoped_by_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", project="smoke")])
                store.record_run([_result("mod::b", project="regression")])
                self.assertEqual(store.list_test_ids(project="smoke"), ["mod::a"])
                self.assertEqual(store.list_test_ids(project="regression"), ["mod::b"])

    def test_list_test_ids_empty_store_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                self.assertEqual(store.list_test_ids(), [])

    def test_worker_id_column_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                run_id = store.record_run([_result("mod::a", worker_id=2)])
                cur = store._conn.execute(
                    "SELECT worker_id FROM test_runs WHERE run_id = ?", (run_id,)
                )
                self.assertEqual(cur.fetchone()[0], 2)

    def test_migrates_pre_worker_id_database_without_crashing(self):
        # Reproduces the reviewer-found bug: CREATE TABLE IF NOT EXISTS
        # is a no-op against a table that already exists from before
        # Task 10 added worker_id, so opening an old on-disk database
        # (the expected common case per this module's own docstring --
        # "accumulate across many runs over time") and calling
        # record_run() used to raise sqlite3.OperationalError: table
        # test_runs has no column named worker_id.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")

            # Simulate an old pre-Task-10 database: create the schema
            # exactly as it was before worker_id existed, bypassing
            # HistoryStore/_SCHEMA entirely.
            raw = sqlite3.connect(db_path)
            raw.executescript("""
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
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_test_runs_test_id ON test_runs(test_id, project);
            """)
            raw.commit()
            raw.close()

            with HistoryStore(db_path) as store:
                run_id = store.record_run([_result("mod::a", worker_id=3)])
                cur = store._conn.execute(
                    "SELECT worker_id FROM test_runs WHERE run_id = ?", (run_id,)
                )
                self.assertEqual(cur.fetchone()[0], 3)

    def test_migrate_schema_swallows_concurrent_duplicate_column_race(self):
        # _migrate_schema is check-then-act (PRAGMA table_info,
        # THEN ALTER TABLE) -- two processes racing to migrate the same
        # pre-existing db can both see the column missing and both
        # attempt to add it; the loser's ALTER TABLE hits sqlite's real
        # "duplicate column name" OperationalError. Simulated here
        # (without real multiprocessing) via a connection wrapper whose
        # PRAGMA table_info always reports the column missing -- exactly
        # what the losing process's check would have seen -- while its
        # ALTER TABLE call still goes to the real, already-migrated
        # connection and hits the genuine sqlite error.
        class _StaleCatalogConnection:
            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, sql, *args, **kwargs):
                if sql.strip().startswith("PRAGMA table_info"):
                    return [(0, "run_id", "TEXT", 0, None, 0)]  # worker_id "absent"
                return self._real.execute(sql, *args, **kwargs)

            def commit(self):
                self._real.commit()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path):
                pass  # first open fully migrates: worker_id column now exists on disk

            store = HistoryStore(db_path)
            store._conn = _StaleCatalogConnection(store._conn)
            store._migrate_schema()  # must not raise despite the real duplicate-column hit

    def test_get_durations_excludes_not_run_and_cancelled_rows(self):
        # A fail-fast run writes 0.0-duration not_run/cancelled rows
        # for the whole remainder of the suite; those rows never
        # actually executed and must not drag the median toward zero.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", outcome="passed", duration=9.0)])
                store.record_run([_result("mod::a", outcome="not_run", duration=0.0)])
                store.record_run([_result("mod::a", outcome="cancelled", duration=0.0)])
                durations = store.get_durations("mod::a", window=20)
        self.assertEqual(durations, [9.0])

    def test_get_durations_excludes_skipped_and_fixme_rows(self):
        # A conditionally-skipped test writes
        # duration~0.0 rows; those must not drag its LPT median toward
        # zero. get_outcomes keeps seeing them (flake-score denominator
        # semantics unchanged).
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", outcome="passed", duration=5.0)])
                store.record_run([_result("mod::a", outcome="skipped", duration=0.0)])
                store.record_run([_result("mod::a", outcome="fixme", duration=0.0)])
                store.record_run([_result("mod::a", outcome="passed", duration=7.0)])
                durations = store.get_durations("mod::a", window=20)
                outcomes = [r["outcome"] for r in store.get_outcomes("mod::a")]
        self.assertEqual(sorted(durations), [5.0, 7.0])
        self.assertIn("skipped", outcomes)
        self.assertIn("fixme", outcomes)

    def test_get_outcomes_excludes_not_run_and_cancelled_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run(
                    [_result("mod::a", outcome="passed", attempts=1, retries_configured=1)]
                )
                store.record_run(
                    [_result("mod::a", outcome="not_run", duration=0.0, retries_configured=1)]
                )
                outcomes = store.get_outcomes("mod::a")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["outcome"], "passed")

    def test_get_durations_default_window_matches_standardized_default(self):
        # get_durations() kept a dead window=10 default while
        # every other default in this codebase standardized on 20.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                for i in range(25):
                    store.record_run([_result("mod::a", duration=float(i))], started_at=float(i))
                durations = store.get_durations("mod::a")  # no window given
                self.assertEqual(len(durations), 20)


class ResolveHistoryConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = resolve_history_config({})
        self.assertTrue(cfg.enabled)
        self.assertIsNone(cfg.db_path)  # caller derives from reports_dir
        self.assertEqual(cfg.window_runs, 20)

    def test_reads_config_values(self):
        cfg = resolve_history_config(
            {
                "history": {
                    "enabled": False,
                    "db_path": "custom/path.db",
                    "window_runs": 5,
                }
            }
        )
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.db_path, "custom/path.db")
        self.assertEqual(cfg.window_runs, 5)

    def test_non_bool_enabled_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_history_config({"history": {"enabled": "yes"}})

    def test_non_string_db_path_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_history_config({"history": {"db_path": 123}})

    def test_non_integer_window_runs_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_history_config({"history": {"window_runs": "20"}})

    def test_non_positive_window_runs_raises_value_error(self):
        # window_runs feeds a SQLite LIMIT: a negative value means "no
        # limit" there (silently defeating the window) and zero returns
        # nothing -- both are configuration mistakes to reject up front.
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                resolve_history_config({"history": {"window_runs": bad}})


class HistoryReporterTests(unittest.TestCase):
    def test_on_run_end_writes_to_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            reporter = HistoryReporter(db_path)
            reporter.on_run_end([_result("mod::a"), _result("mod::b")], 1.5)

            with HistoryStore(db_path) as store:
                cur = store._conn.execute("SELECT COUNT(*) FROM test_runs")
                self.assertEqual(cur.fetchone()[0], 2)

    def test_reused_across_multiple_calls_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            reporter = HistoryReporter(db_path)
            reporter.on_run_end([_result("mod::a", project="p1")], 1.0)
            reporter.on_run_end([_result("mod::b", project="p2")], 1.0)

            with HistoryStore(db_path) as store:
                cur = store._conn.execute("SELECT COUNT(*) FROM runs")
                self.assertEqual(cur.fetchone()[0], 2)
                cur = store._conn.execute("SELECT DISTINCT project FROM runs ORDER BY project")
                self.assertEqual([r[0] for r in cur.fetchall()], ["p1", "p2"])

    def test_empty_results_does_not_create_a_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            reporter = HistoryReporter(db_path)
            reporter.on_run_end([], 0.0)
            with HistoryStore(db_path) as store:
                cur = store._conn.execute("SELECT COUNT(*) FROM runs")
                self.assertEqual(cur.fetchone()[0], 0)


class ComputeNearTimeoutTestIdsTests(unittest.TestCase):
    def test_flags_tests_above_80_percent_of_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::slow", duration=9.0)])
                store.record_run([_result("mod::fast", duration=1.0)])
                flags = compute_near_timeout_test_ids(
                    ["mod::slow", "mod::fast"],
                    {"mod::slow": 10.0, "mod::fast": 10.0},
                    store,
                    project=None,
                    window=20,
                )
        self.assertEqual(flags, {"mod::slow"})

    def test_no_history_flags_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                flags = compute_near_timeout_test_ids(
                    ["mod::unknown"],
                    {"mod::unknown": 10.0},
                    store,
                    project=None,
                    window=20,
                )
        self.assertEqual(flags, set())

    def test_custom_threshold_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", duration=6.0)])
                flags_default = compute_near_timeout_test_ids(
                    ["mod::a"],
                    {"mod::a": 10.0},
                    store,
                    project=None,
                    window=20,
                )
                flags_strict = compute_near_timeout_test_ids(
                    ["mod::a"],
                    {"mod::a": 10.0},
                    store,
                    project=None,
                    window=20,
                    threshold=0.5,
                )
        self.assertEqual(flags_default, set())  # 6.0/10.0 = 0.6, below default 0.8
        self.assertEqual(flags_strict, {"mod::a"})  # 0.6 >= 0.5

    def test_uses_median_across_recent_durations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                # median of [1.0, 9.0, 9.0] = 9.0 -> flagged;
                # a single low outlier can't drag it below threshold.
                store.record_run([_result("mod::a", duration=1.0)])
                store.record_run([_result("mod::a", duration=9.0)])
                store.record_run([_result("mod::a", duration=9.0)])
                flags = compute_near_timeout_test_ids(
                    ["mod::a"],
                    {"mod::a": 10.0},
                    store,
                    project=None,
                    window=20,
                )
        self.assertEqual(flags, {"mod::a"})

    def test_missing_timeout_is_never_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                store.record_run([_result("mod::a", duration=100.0)])
                flags = compute_near_timeout_test_ids(
                    ["mod::a"],
                    {},
                    store,
                    project=None,
                    window=20,
                )
        self.assertEqual(flags, set())


class HistoryWriteProcessBoundaryTests(unittest.TestCase):
    """This is worth a dedicated
    assertion, not just an implicit consequence' -- HistoryReporter
    must only ever be joined as a console reporter in the MAIN process
    (cli.py), never passed into a worker, since worker.py has zero
    HistoryStore/HistoryReporter references by design (SQLite writes
    from multiple worker processes concurrently would need locking this
    codebase deliberately avoids -- see history.py's module docstring
    on 'written once per run/project via HistoryReporter... never
    mid-run')."""

    def test_worker_module_has_no_history_references(self):
        import inspect

        from pyrunner.execution import worker as worker_module

        source = inspect.getsource(worker_module)
        self.assertNotIn("HistoryStore", source)
        self.assertNotIn("HistoryReporter", source)
        self.assertNotIn("import history", source)

    def test_history_reporter_on_test_start_and_on_test_end_are_no_ops(self):
        # Even if a HistoryReporter were ever accidentally threaded into
        # a worker-facing path, per-test hooks are no-ops -- only
        # on_run_end (called exactly once, in the main process, after
        # workers have already finished) actually writes.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "history.db")
            reporter = HistoryReporter(db_path)
            reporter.on_run_start(5)  # must not raise, must not touch a db
            reporter.on_test_start("mod::a")
            reporter.on_test_end(_result("mod::a"))
            # Verify no db file was created -- if on_test_start or
            # on_test_end were mutated to open a HistoryStore, this would
            # fail (catching a per-test hook regression that the old
            # test would have silently missed).
            self.assertFalse(
                Path(db_path).exists(),
                f"on_test_start/on_test_end must not create db file; "
                f"found unexpected file at {db_path}",
            )


if __name__ == "__main__":
    unittest.main()
