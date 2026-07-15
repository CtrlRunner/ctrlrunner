import unittest

from ctrlrunner.core import annotations


class SkipFixmeTests(unittest.TestCase):
    def setUp(self):
        annotations.begin_test()

    def test_skip_raises_when_condition_true(self):
        with self.assertRaises(annotations.SkipTest) as ctx:
            annotations.skip(True, "not applicable")
        self.assertEqual(ctx.exception.description, "not applicable")

    def test_skip_does_not_raise_when_condition_false(self):
        annotations.skip(False, "should not raise")  # no exception

    def test_skip_default_condition_is_true(self):
        with self.assertRaises(annotations.SkipTest):
            annotations.skip()

    def test_fixme_raises_distinct_exception_type(self):
        with self.assertRaises(annotations.FixmeTest) as ctx:
            annotations.fixme(True, "needs fix")
        self.assertEqual(ctx.exception.description, "needs fix")

    def test_fixme_does_not_raise_when_condition_false(self):
        annotations.fixme(False, "irrelevant")


class FailAnnotationTests(unittest.TestCase):
    def setUp(self):
        annotations.begin_test()

    def test_fail_sets_expected_failure_state(self):
        annotations.fail(True, "JIRA-1", strict=True)
        state = annotations.get_expected_failure()
        self.assertTrue(state["active"])
        self.assertEqual(state["description"], "JIRA-1")
        self.assertTrue(state["strict"])

    def test_fail_does_nothing_when_condition_false(self):
        annotations.fail(False, "should not activate")
        state = annotations.get_expected_failure()
        self.assertFalse(state["active"])

    def test_fail_default_strict_is_true(self):
        annotations.fail(True, "desc")
        self.assertTrue(annotations.get_expected_failure()["strict"])

    def test_fail_non_strict(self):
        annotations.fail(True, "desc", strict=False)
        self.assertFalse(annotations.get_expected_failure()["strict"])

    def test_begin_test_resets_expected_failure_between_tests(self):
        annotations.fail(True, "leftover from previous test")
        self.assertTrue(annotations.get_expected_failure()["active"])
        annotations.begin_test()
        self.assertFalse(annotations.get_expected_failure()["active"])
        self.assertIsNone(annotations.get_expected_failure()["description"])

    def test_get_expected_failure_returns_a_copy_not_the_live_dict(self):
        state = annotations.get_expected_failure()
        state["active"] = True
        self.assertFalse(annotations.get_expected_failure()["active"])


class SlowAnnotationTests(unittest.TestCase):
    def setUp(self):
        annotations.begin_test()

    def test_slow_does_nothing_without_a_queue(self):
        annotations.slow(True, factor=3.0)  # no queue configured -> no-op, no crash

    def test_slow_puts_message_on_queue_when_condition_true(self):
        class FakeQueue:
            def __init__(self):
                self.items = []

            def put(self, item):
                self.items.append(item)

        q = FakeQueue()
        annotations.begin_test(queue=q, worker_id=1, test_id="mod::test_x")
        annotations.slow(True, factor=4.0)
        self.assertEqual(len(q.items), 1)
        kind, worker_id, test_id, factor = q.items[0]
        self.assertEqual(kind, "timeout_extended")
        self.assertEqual(worker_id, 1)
        self.assertEqual(test_id, "mod::test_x")
        self.assertEqual(factor, 4.0)

    def test_slow_does_nothing_when_condition_false(self):
        class FakeQueue:
            def __init__(self):
                self.items = []

            def put(self, item):
                self.items.append(item)

        q = FakeQueue()
        annotations.begin_test(queue=q, worker_id=1, test_id="mod::test_x")
        annotations.slow(False, factor=4.0)
        self.assertEqual(q.items, [])


if __name__ == "__main__":
    unittest.main()
