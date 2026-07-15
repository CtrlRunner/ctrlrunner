import time
import unittest

from pyrunner.core.steps import begin_test, collect_steps, render_text, step


class StepTests(unittest.TestCase):
    def setUp(self):
        begin_test()

    def test_single_step_recorded_as_passed(self):
        with step("do something"):
            pass
        result = collect_steps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "do something")
        self.assertEqual(result[0].outcome, "passed")
        self.assertIsNone(result[0].error)

    def test_nested_steps_build_a_tree(self):
        with step("outer"):
            with step("inner-1"):
                pass
            with step("inner-2"):
                pass
        result = collect_steps()
        self.assertEqual(len(result), 1)
        outer = result[0]
        self.assertEqual(outer.name, "outer")
        self.assertEqual([c.name for c in outer.children], ["inner-1", "inner-2"])

    def test_multiple_top_level_steps_are_siblings(self):
        with step("first"):
            pass
        with step("second"):
            pass
        result = collect_steps()
        self.assertEqual([s.name for s in result], ["first", "second"])

    def test_failing_step_records_error_and_reraises(self):
        with self.assertRaises(ValueError), step("will fail"):
            raise ValueError("boom")
        result = collect_steps()
        self.assertEqual(result[0].outcome, "failed")
        self.assertIn("boom", result[0].error)

    def test_error_in_nested_step_does_not_mark_sibling_failed(self):
        try:
            with step("outer"):
                with step("child-ok"):
                    pass
                with step("child-fails"):
                    raise RuntimeError("nope")
        except RuntimeError:
            pass
        result = collect_steps()
        outer = result[0]
        child_ok, child_fails = outer.children
        self.assertEqual(child_ok.outcome, "passed")
        self.assertEqual(child_fails.outcome, "failed")
        # the exception propagates, so the outer step is also marked failed
        self.assertEqual(outer.outcome, "failed")

    def test_duration_is_nonnegative(self):
        with step("timed"):
            time.sleep(0.01)
        result = collect_steps()
        self.assertGreaterEqual(result[0].duration, 0.01)

    def test_begin_test_resets_state_between_tests(self):
        with step("from-test-one"):
            pass
        self.assertEqual(len(collect_steps()), 1)

        begin_test()
        self.assertEqual(collect_steps(), [])

        with step("from-test-two"):
            pass
        result = collect_steps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "from-test-two")

    def test_to_dict_serializes_tree(self):
        with step("outer"), step("inner"):
            pass
        result = collect_steps()
        d = result[0].to_dict()
        self.assertEqual(d["name"], "outer")
        self.assertEqual(len(d["children"]), 1)
        self.assertEqual(d["children"][0]["name"], "inner")

    def test_render_text_marks_pass_and_fail(self):
        try:
            with step("ok-step"):
                pass
            with step("bad-step"):
                raise ValueError("x")
        except ValueError:
            pass
        text = render_text(collect_steps())
        self.assertIn("\u2713 ok-step", text)
        self.assertIn("\u2717 bad-step", text)


if __name__ == "__main__":
    unittest.main()
