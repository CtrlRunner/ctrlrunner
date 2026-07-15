import unittest

from ctrlrunner.execution.flaky import (
    FlakyStats,
    compute_flake_score,
    compute_flaky_report,
    format_flaky_report,
)
from ctrlrunner.execution.quarantine import QuarantineConfig


def _row(outcome, attempts, retries_configured):
    return {"outcome": outcome, "attempts": attempts, "retries_configured": retries_configured}


class ComputeFlakeScoreTests(unittest.TestCase):
    def test_no_rows_returns_none_score_zero_sample(self):
        score, n = compute_flake_score([])
        self.assertIsNone(score)
        self.assertEqual(n, 0)

    def test_no_retries_configured_rows_returns_none(self):
        rows = [_row("passed", 1, None), _row("passed", 1, None)]
        score, n = compute_flake_score(rows)
        self.assertIsNone(score)
        self.assertEqual(n, 0)

    def test_all_flaky_gives_score_one(self):
        rows = [_row("passed", 2, 1), _row("passed", 3, 1)]
        score, n = compute_flake_score(rows)
        self.assertEqual(score, 1.0)
        self.assertEqual(n, 2)

    def test_never_flaky_gives_score_zero(self):
        rows = [_row("passed", 1, 1), _row("passed", 1, 1)]
        score, n = compute_flake_score(rows)
        self.assertEqual(score, 0.0)

    def test_mixed_gives_fractional_score(self):
        rows = [
            _row("passed", 2, 1),
            _row("passed", 1, 1),
            _row("passed", 1, 1),
            _row("passed", 1, 1),
        ]
        score, n = compute_flake_score(rows)
        self.assertEqual(score, 0.25)
        self.assertEqual(n, 4)

    def test_final_failure_after_retries_is_not_flaky(self):
        # attempts > 1 but the test STILL failed -- that's a real
        # failure, not "passed on retry," so it must not count as flaky
        rows = [_row("failed", 3, 2)]
        score, n = compute_flake_score(rows)
        self.assertEqual(score, 0.0)

    def test_ineligible_rows_are_excluded_from_sample_size(self):
        rows = [_row("passed", 2, 1), _row("passed", 1, None)]  # second has no retries configured
        score, n = compute_flake_score(rows)
        self.assertEqual(n, 1)  # only the eligible one counted
        self.assertEqual(score, 1.0)


class _FakeStore:
    def __init__(self, ids_by_project, outcomes_by_test):
        self.ids_by_project = ids_by_project
        self.outcomes_by_test = outcomes_by_test

    def list_test_ids(self, project=None):
        return self.ids_by_project.get(project, [])

    def get_outcomes(self, test_id, project=None, window=20):
        return self.outcomes_by_test.get(test_id, [])


class ComputeFlakyReportTests(unittest.TestCase):
    def test_sorted_most_flaky_first(self):
        store = _FakeStore(
            {None: ["mod::stable", "mod::flaky"]},
            {
                "mod::stable": [_row("passed", 1, 1)],
                "mod::flaky": [_row("passed", 2, 1)],
            },
        )
        stats = compute_flaky_report(store)
        self.assertEqual([s.test_id for s in stats], ["mod::flaky", "mod::stable"])

    def test_no_sample_sorts_last_not_first(self):
        store = _FakeStore(
            {None: ["mod::no_history", "mod::flaky"]},
            {
                "mod::no_history": [],
                "mod::flaky": [_row("passed", 2, 1)],
            },
        )
        stats = compute_flaky_report(store)
        self.assertEqual([s.test_id for s in stats], ["mod::flaky", "mod::no_history"])
        self.assertIsNone(stats[1].flake_score)

    def test_quarantine_info_attached_when_test_is_quarantined(self):
        store = _FakeStore({None: ["mod::a"]}, {"mod::a": [_row("passed", 2, 1)]})
        qc = QuarantineConfig(test_ids={"mod::a"}, reason="JIRA-1")
        stats = compute_flaky_report(store, quarantine_config=qc)
        self.assertTrue(stats[0].quarantined)
        self.assertEqual(stats[0].quarantine_reason, "JIRA-1")

    def test_unquarantined_test_has_no_quarantine_info(self):
        store = _FakeStore({None: ["mod::a"]}, {"mod::a": [_row("passed", 2, 1)]})
        qc = QuarantineConfig(test_ids={"mod::other"}, reason="JIRA-1")
        stats = compute_flaky_report(store, quarantine_config=qc)
        self.assertFalse(stats[0].quarantined)
        self.assertIsNone(stats[0].quarantine_reason)

    def test_consider_unquarantine_flagged_when_score_dropped_with_enough_sample(self):
        rows = [_row("passed", 1, 1)] * 10  # 10 clean runs, score 0.0
        store = _FakeStore({None: ["mod::a"]}, {"mod::a": rows})
        qc = QuarantineConfig(test_ids={"mod::a"})
        stats = compute_flaky_report(store, quarantine_config=qc)
        self.assertTrue(stats[0].consider_unquarantine)

    def test_consider_unquarantine_not_flagged_with_tiny_sample(self):
        rows = [_row("passed", 1, 1)] * 2  # only 2 runs -- too small to suggest anything
        store = _FakeStore({None: ["mod::a"]}, {"mod::a": rows})
        qc = QuarantineConfig(test_ids={"mod::a"})
        stats = compute_flaky_report(store, quarantine_config=qc)
        self.assertFalse(stats[0].consider_unquarantine)

    def test_consider_unquarantine_never_set_for_non_quarantined_test(self):
        rows = [_row("passed", 1, 1)] * 10
        store = _FakeStore({None: ["mod::a"]}, {"mod::a": rows})
        stats = compute_flaky_report(store)  # no quarantine config at all
        self.assertFalse(stats[0].consider_unquarantine)

    def test_project_scoping_passed_through(self):
        store = _FakeStore({"smoke": ["mod::a"]}, {"mod::a": [_row("passed", 1, 1)]})
        stats = compute_flaky_report(store, project="smoke")
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].project, "smoke")


class FormatFlakyReportTests(unittest.TestCase):
    def test_empty_stats_text_gives_a_helpful_message(self):
        out = format_flaky_report([], fmt="text")
        self.assertIn("No history data", out)

    def test_text_format_includes_percentage_and_sample_size(self):
        stats = [
            FlakyStats(
                test_id="mod::a",
                project=None,
                flake_score=0.5,
                sample_size=4,
                quarantined=False,
                quarantine_reason=None,
            )
        ]
        out = format_flaky_report(stats, fmt="text")
        self.assertIn("50%", out)
        self.assertIn("n=4", out)
        self.assertIn("mod::a", out)

    def test_text_format_shows_quarantine_and_unquarantine_hint(self):
        stats = [
            FlakyStats(
                test_id="mod::a",
                project=None,
                flake_score=0.0,
                sample_size=10,
                quarantined=True,
                quarantine_reason="JIRA-1",
                consider_unquarantine=True,
            )
        ]
        out = format_flaky_report(stats, fmt="text")
        self.assertIn("quarantined: JIRA-1", out)
        self.assertIn("consider un-quarantining", out)

    def test_json_format_is_valid_json_with_expected_keys(self):
        import json

        stats = [
            FlakyStats(
                test_id="mod::a",
                project="smoke",
                flake_score=0.25,
                sample_size=4,
                quarantined=False,
                quarantine_reason=None,
            )
        ]
        out = format_flaky_report(stats, fmt="json")
        data = json.loads(out)
        self.assertEqual(data[0]["testId"], "mod::a")
        self.assertEqual(data[0]["flakeScore"], 0.25)
        self.assertEqual(data[0]["project"], "smoke")

    def test_json_format_none_score_serializes_as_null(self):
        import json

        stats = [
            FlakyStats(
                test_id="mod::a",
                project=None,
                flake_score=None,
                sample_size=0,
                quarantined=False,
                quarantine_reason=None,
            )
        ]
        out = format_flaky_report(stats, fmt="json")
        data = json.loads(out)
        self.assertIsNone(data[0]["flakeScore"])


if __name__ == "__main__":
    unittest.main()
