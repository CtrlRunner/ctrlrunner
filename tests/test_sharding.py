import unittest

from ctrlrunner.execution.orchestrator import _chunk
from ctrlrunner.execution.sharding import lookup_median_durations, lpt_shard


class LptShardTests(unittest.TestCase):
    def test_empty_test_list_returns_empty(self):
        self.assertEqual(lpt_shard([], 4, {}), [])

    def test_no_history_at_all_matches_round_robin_chunking_exactly(self):
        # the degeneration property the module docstring claims: with
        # every duration unknown, LPT must produce byte-identical
        # batches to today's plain round-robin _chunk().
        test_ids = [f"mod::test_{i}" for i in range(10)]
        for n in (1, 2, 3, 4, 7):
            lpt_result = lpt_shard(test_ids, n, {})
            chunk_result = _chunk(test_ids, min(n, len(test_ids)))
            self.assertEqual(lpt_result, chunk_result, f"mismatch at num_workers={n}")

    def test_slow_test_does_not_share_a_worker_with_other_slow_tests(self):
        # 1 very slow test + 4 fast ones, 2 workers -- LPT should isolate
        # the slow one onto its own worker rather than pairing it with
        # another slow test the way round-robin easily could by chance.
        test_ids = ["slow_a", "slow_b", "fast_1", "fast_2", "fast_3", "fast_4"]
        durations = {
            "slow_a": 100.0,
            "slow_b": 100.0,
            "fast_1": 1.0,
            "fast_2": 1.0,
            "fast_3": 1.0,
            "fast_4": 1.0,
        }
        bins = lpt_shard(test_ids, 2, durations)
        self.assertEqual(len(bins), 2)
        # the two slow tests must end up in DIFFERENT bins
        bin_of_a = next(i for i, b in enumerate(bins) if "slow_a" in b)
        bin_of_b = next(i for i, b in enumerate(bins) if "slow_b" in b)
        self.assertNotEqual(bin_of_a, bin_of_b)

    def test_unknown_duration_test_gets_median_fallback_not_zero(self):
        test_ids = ["known_a", "known_b", "unknown"]
        durations = {"known_a": 10.0, "known_b": 20.0}  # "unknown" absent entirely
        bins = lpt_shard(test_ids, 3, durations)
        # every test lands in its own bin (3 workers, 3 tests) --
        # confirms "unknown" wasn't given a zero weight that would have
        # made bin-assignment order differ in a detectable way
        self.assertEqual(sum(len(b) for b in bins), 3)

    def test_more_workers_than_tests_caps_bin_count(self):
        bins = lpt_shard(["a", "b"], 5, {})
        self.assertEqual(len(bins), 2)

    def test_none_duration_value_treated_same_as_absent(self):
        test_ids = ["a", "b"]
        durations = {"a": 5.0, "b": None}
        bins = lpt_shard(test_ids, 2, durations)
        self.assertEqual(sum(len(b) for b in bins), 2)

    def test_zero_duration_value_is_not_treated_as_absent(self):
        # `durations.get(tid) or fallback` is falsy-coercion on a
        # real 0.0 median (a genuinely fast/instant test), wrongly
        # replacing it with the fallback weight -- only None/absent
        # should mean "no history". With test_ids=["zero", "a", "b"]
        # and durations {"zero": 0.0, "a": 10.0, "b": 10.0} (fallback,
        # if wrongly applied, would be median([0.0, 10.0, 10.0]) ==
        # 10.0), the fixed LPT packing must treat 'zero' as weight 0.0
        # (sorted last, greedily bin-packed onto whichever worker got
        # 'a' first) -- NOT as if it too were weight 10.0 (which would
        # instead pair 'zero' with 'b').
        test_ids = ["zero", "a", "b"]
        durations = {"zero": 0.0, "a": 10.0, "b": 10.0}
        bins = lpt_shard(test_ids, 2, durations)

        bin_of_zero = next(i for i, b in enumerate(bins) if "zero" in b)
        bin_of_a = next(i for i, b in enumerate(bins) if "a" in b)
        bin_of_b = next(i for i, b in enumerate(bins) if "b" in b)

        self.assertEqual(bin_of_zero, bin_of_a)
        self.assertNotEqual(bin_of_zero, bin_of_b)
        self.assertEqual(len(bins[bin_of_b]), 1)


class LookupMedianDurationsTests(unittest.TestCase):
    class _FakeStore:
        def __init__(self, data):
            self.data = data  # test_id -> list of durations

        def get_durations(self, test_id, project=None, window=20):
            return self.data.get(test_id, [])

    def test_computes_median_of_returned_durations(self):
        store = self._FakeStore({"mod::a": [1.0, 2.0, 3.0]})
        result = lookup_median_durations(["mod::a"], store, project=None, window=10)
        self.assertEqual(result["mod::a"], 2.0)

    def test_no_history_gives_none(self):
        store = self._FakeStore({})
        result = lookup_median_durations(["mod::a"], store, project=None, window=10)
        self.assertIsNone(result["mod::a"])

    def test_looks_up_every_requested_test_id(self):
        store = self._FakeStore({"mod::a": [1.0], "mod::b": [2.0]})
        result = lookup_median_durations(
            ["mod::a", "mod::b", "mod::c"], store, project=None, window=10
        )
        self.assertEqual(set(result), {"mod::a", "mod::b", "mod::c"})


if __name__ == "__main__":
    unittest.main()
