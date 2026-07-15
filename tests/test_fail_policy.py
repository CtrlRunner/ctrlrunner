import unittest

from pyrunner.execution.fail_policy import FailPolicyState, resolve_fail_policy


class FailPolicyStateTests(unittest.TestCase):
    def test_is_active_false_by_default(self):
        self.assertFalse(FailPolicyState().is_active())

    def test_is_active_true_when_any_field_set(self):
        self.assertTrue(FailPolicyState(max_failures=5).is_active())
        self.assertTrue(FailPolicyState(max_timeouts=3).is_active())
        self.assertTrue(FailPolicyState(stop_on_worker_crash=True).is_active())

    def test_record_failure_below_threshold_returns_none(self):
        state = FailPolicyState(max_failures=3)
        self.assertIsNone(state.record_failure())
        self.assertIsNone(state.record_failure())
        self.assertEqual(state.failure_count, 2)

    def test_record_failure_at_threshold_returns_reason(self):
        state = FailPolicyState(max_failures=2)
        self.assertIsNone(state.record_failure())
        self.assertEqual(state.record_failure(), "max_failures")

    def test_record_failure_unlimited_never_triggers(self):
        state = FailPolicyState(max_failures=0)
        for _ in range(100):
            self.assertIsNone(state.record_failure())

    def test_record_timeout_at_threshold_returns_reason(self):
        state = FailPolicyState(max_timeouts=1)
        self.assertEqual(state.record_timeout(), "max_timeouts")

    def test_record_worker_crash_returns_reason_only_when_enabled(self):
        self.assertIsNone(FailPolicyState(stop_on_worker_crash=False).record_worker_crash())
        self.assertEqual(
            FailPolicyState(stop_on_worker_crash=True).record_worker_crash(), "stop_on_worker_crash"
        )

    def test_counters_are_independent(self):
        state = FailPolicyState(max_failures=10, max_timeouts=10)
        state.record_failure()
        state.record_failure()
        state.record_timeout()
        self.assertEqual(state.failure_count, 2)
        self.assertEqual(state.timeout_count, 1)


class ResolveFailPolicyTests(unittest.TestCase):
    def test_defaults_when_nothing_configured(self):
        state = resolve_fail_policy({})
        self.assertEqual(state.max_failures, 0)
        self.assertEqual(state.max_timeouts, 0)
        self.assertFalse(state.stop_on_worker_crash)

    def test_config_values_are_read(self):
        state = resolve_fail_policy(
            {"fail_policy": {"max_failures": 5, "max_timeouts": 2, "stop_on_worker_crash": True}}
        )
        self.assertEqual(state.max_failures, 5)
        self.assertEqual(state.max_timeouts, 2)
        self.assertTrue(state.stop_on_worker_crash)

    def test_cli_overrides_config(self):
        state = resolve_fail_policy({"fail_policy": {"max_failures": 5}}, cli_max_failures=10)
        self.assertEqual(state.max_failures, 10)

    def test_fail_fast_is_sugar_for_max_failures_one(self):
        state = resolve_fail_policy({}, cli_fail_fast=True)
        self.assertEqual(state.max_failures, 1)

    def test_explicit_max_failures_wins_over_fail_fast(self):
        state = resolve_fail_policy({}, cli_max_failures=5, cli_fail_fast=True)
        self.assertEqual(state.max_failures, 5)

    def test_cli_stop_on_worker_crash_flag(self):
        state = resolve_fail_policy({}, cli_stop_on_worker_crash=True)
        self.assertTrue(state.stop_on_worker_crash)

    def test_fail_fast_wins_over_config_max_failures(self):
        # CLI > config precedence must hold for --fail-fast too --
        # a config-file max_failures must not silently outrank it.
        state = resolve_fail_policy({"fail_policy": {"max_failures": 5}}, cli_fail_fast=True)
        self.assertEqual(state.max_failures, 1)

    def test_explicit_cli_max_failures_zero_wins_over_fail_fast(self):
        # An explicit CLI --max-failures 0 ("explicitly unlimited") must
        # still win over --fail-fast sugar, distinguishing "not given"
        # from "given as 0".
        state = resolve_fail_policy({}, cli_max_failures=0, cli_fail_fast=True)
        self.assertEqual(state.max_failures, 0)

    def test_non_integer_max_failures_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_fail_policy({"fail_policy": {"max_failures": "5"}})

    def test_non_integer_max_timeouts_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_fail_policy({"fail_policy": {"max_timeouts": "3"}})

    def test_non_bool_stop_on_worker_crash_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_fail_policy({"fail_policy": {"stop_on_worker_crash": "yes"}})


if __name__ == "__main__":
    unittest.main()
