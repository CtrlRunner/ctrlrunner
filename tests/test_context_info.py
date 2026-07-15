import unittest

from pyrunner.core import context_info


class ContextInfoTests(unittest.TestCase):
    def test_begin_test_sets_id_and_attempt(self):
        context_info.begin_test("mod::test_x", 2)
        self.assertEqual(context_info.current_test_id(), "mod::test_x")
        self.assertEqual(context_info.current_attempt(), 2)

    def test_values_update_on_subsequent_calls(self):
        context_info.begin_test("mod::test_a", 1)
        context_info.begin_test("mod::test_b", 3)
        self.assertEqual(context_info.current_test_id(), "mod::test_b")
        self.assertEqual(context_info.current_attempt(), 3)


class RecordPropertyTests(unittest.TestCase):
    """pytest's record_property equivalent -- runtime per-test
    metadata that lands in Result.properties (JUnit <property>, JSON)."""

    def test_record_property_collected_for_current_test(self):
        context_info.begin_test("mod::test_x", 1)
        context_info.record_property("testrail", "C123")
        self.assertEqual(context_info.collect_properties(), {"testrail": "C123"})

    def test_begin_test_resets_properties(self):
        context_info.begin_test("mod::test_x", 1)
        context_info.record_property("a", "1")
        context_info.begin_test("mod::test_x", 2)
        self.assertEqual(context_info.collect_properties(), {})

    def test_values_and_keys_coerced_to_str(self):
        context_info.begin_test("mod::test_x", 1)
        context_info.record_property(7, 42)
        self.assertEqual(context_info.collect_properties(), {"7": "42"})

    def test_collect_returns_a_copy(self):
        context_info.begin_test("mod::test_x", 1)
        context_info.record_property("a", "1")
        snapshot = context_info.collect_properties()
        snapshot["b"] = "2"
        self.assertEqual(context_info.collect_properties(), {"a": "1"})


if __name__ == "__main__":
    unittest.main()
