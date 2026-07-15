import os
import tempfile
import time
import unittest
from pathlib import Path

from ctrlrunner.reporting.report_paths import (
    _PRUNE_GRACE_SECONDS,
    _prune_old_reports,
    find_latest_report_dir,
    resolve_report_dir,
)


class ResolveReportDirTests(unittest.TestCase):
    def test_creates_static_directory_without_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = resolve_report_dir(tmp, "html-report", timestamp=False, keep=10)
            self.assertEqual(report_dir, Path(tmp) / "html-report")
            self.assertTrue(report_dir.exists())

    def test_reusing_static_directory_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d1 = resolve_report_dir(tmp, "html-report", timestamp=False, keep=10)
            d2 = resolve_report_dir(tmp, "html-report", timestamp=False, keep=10)
            self.assertEqual(d1, d2)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_timestamped_directory_includes_report_name_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            self.assertTrue(report_dir.name.startswith("html-report-"))
            self.assertTrue(report_dir.exists())

    def test_retention_keeps_only_the_configured_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = []
            for _ in range(5):
                d = resolve_report_dir(tmp, "html-report", timestamp=True, keep=3)
                dirs.append(d)
                time.sleep(1.05)  # ensure distinct second-resolution timestamps

            remaining = [p for p in Path(tmp).iterdir() if p.is_dir()]
            self.assertEqual(len(remaining), 3)
            # the three most recently created should be the ones kept
            remaining_names = {p.name for p in remaining}
            expected_names = {d.name for d in dirs[-3:]}
            self.assertEqual(remaining_names, expected_names)

    def test_keep_zero_disables_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(3):
                resolve_report_dir(tmp, "html-report", timestamp=True, keep=0)
                time.sleep(1.05)
            remaining = [p for p in Path(tmp).iterdir() if p.is_dir()]
            self.assertEqual(len(remaining), 3)

    def test_two_timestamped_calls_within_the_same_second_do_not_collide(self):
        # The timestamp has only second resolution, so two runs
        # started within the same second used to produce the identical
        # dir_name; mkdir(exist_ok=True) then silently merged them into
        # one directory instead of erroring or creating two.
        with tempfile.TemporaryDirectory() as tmp:
            d1 = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            d2 = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            self.assertNotEqual(d1, d2)
            self.assertTrue(d1.exists())
            self.assertTrue(d2.exists())

    def test_prune_skips_directories_within_the_grace_window(self):
        # keep=1 must not prune a directory a concurrent run
        # could still be writing to. Two directories created back to
        # back (no artificial delay) are both "recent" -- neither should
        # be deleted even though keep=1 would otherwise only retain one.
        with tempfile.TemporaryDirectory() as tmp:
            d1 = resolve_report_dir(tmp, "html-report", timestamp=True, keep=1)
            d2 = resolve_report_dir(tmp, "html-report", timestamp=True, keep=1)
            self.assertTrue(d1.exists())
            self.assertTrue(d2.exists())

    def test_prune_skips_candidate_resolving_outside_reports_root(self):
        # Containment guard: a candidate whose real path escapes
        # reports_root (here via a symlink to an outside directory) must
        # never be rmtree'd, while a legitimate in-root candidate is
        # still pruned as normal.
        with tempfile.TemporaryDirectory() as tmp:
            reports_root = Path(tmp) / "reports"
            reports_root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            sentinel = outside / "keep-me.txt"
            sentinel.write_text("do not delete")

            # A symlink candidate pointing outside the reports tree.
            escaping = reports_root / "html-report-00000000-000000-aaaaaa"
            escaping.symlink_to(outside, target_is_directory=True)
            # A legitimate in-root candidate that should still be pruned.
            legit = reports_root / "html-report-00000000-000000-bbbbbb"
            legit.mkdir()

            old = time.time() - (_PRUNE_GRACE_SECONDS + 60)
            os.utime(outside, (old, old))
            os.utime(legit, (old, old))

            _prune_old_reports(reports_root, "html-report", keep=1)

            self.assertTrue(outside.exists())
            self.assertTrue(sentinel.exists())
            self.assertFalse(legit.exists())

    def test_untimestamped_and_timestamped_reports_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = resolve_report_dir(tmp, "html-report", timestamp=False, keep=10)
            stamped_dir = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            self.assertNotEqual(static_dir, stamped_dir)
            self.assertTrue(static_dir.exists())
            self.assertTrue(stamped_dir.exists())


class FindLatestReportDirTests(unittest.TestCase):
    def test_no_reports_root_at_all_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_latest_report_dir(str(Path(tmp) / "nonexistent"), "html-report"))

    def test_reports_root_exists_but_empty_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_latest_report_dir(tmp, "html-report"))

    def test_does_not_create_anything(self):
        # the whole point of this being a separate, read-only function
        # from resolve_report_dir()
        with tempfile.TemporaryDirectory() as tmp:
            find_latest_report_dir(tmp, "html-report")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_finds_the_static_untimestamped_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolve_report_dir(tmp, "html-report", timestamp=False, keep=10)
            found = find_latest_report_dir(tmp, "html-report")
            self.assertEqual(found, Path(tmp) / "html-report")

    def test_finds_the_most_recent_timestamped_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(3):
                resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
                time.sleep(1.05)
            latest = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            found = find_latest_report_dir(tmp, "html-report")
            self.assertEqual(found, latest)

    def test_does_not_mint_a_fresh_empty_directory_with_timestamp_mode(self):
        # the exact v1 design bug this function exists to fix: reusing
        # resolve_report_dir() for --last-failed would create a NEW
        # empty timestamped dir and never find the previous run's.
        with tempfile.TemporaryDirectory() as tmp:
            first = resolve_report_dir(tmp, "html-report", timestamp=True, keep=10)
            found = find_latest_report_dir(tmp, "html-report")
            self.assertEqual(found, first)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
