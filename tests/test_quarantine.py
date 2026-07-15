import unittest

from ctrlrunner.execution.quarantine import QuarantineConfig, resolve_quarantine_config


class QuarantineConfigTests(unittest.TestCase):
    def test_is_quarantined_true_for_listed_id(self):
        cfg = QuarantineConfig(test_ids={"mod::test_a"})
        self.assertTrue(cfg.is_quarantined("mod::test_a"))

    def test_is_quarantined_false_for_unlisted_id(self):
        cfg = QuarantineConfig(test_ids={"mod::test_a"})
        self.assertFalse(cfg.is_quarantined("mod::test_b"))


class ResolveQuarantineConfigTests(unittest.TestCase):
    def test_parses_test_ids_and_reason(self):
        cfg = resolve_quarantine_config(
            {"quarantine": {"test_ids": ["mod::a", "mod::b"], "reason": "JIRA-123"}}
        )
        self.assertEqual(cfg.test_ids, {"mod::a", "mod::b"})
        self.assertEqual(cfg.reason, "JIRA-123")

    def test_missing_reason_is_none(self):
        cfg = resolve_quarantine_config({"quarantine": {"test_ids": ["mod::a"]}})
        self.assertIsNone(cfg.reason)

    def test_empty_test_ids_list_still_returns_a_config(self):
        cfg = resolve_quarantine_config({"quarantine": {"test_ids": []}})
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.test_ids, set())

    def test_non_list_test_ids_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_quarantine_config({"quarantine": {"test_ids": "mod::test_a"}})

    def test_non_string_reason_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_quarantine_config({"quarantine": {"test_ids": ["mod::a"], "reason": 123}})


if __name__ == "__main__":
    unittest.main()
