import unittest
from contextlib import ExitStack

from ctrlrunner.core import registry, tb_format
from ctrlrunner.core import steps as steps_module
from ctrlrunner.core.di import FixtureResolver


def _user_code_that_raises():
    raise ValueError("user-level boom")


def _user_code_chained():
    try:
        raise KeyError("original cause")
    except KeyError as e:
        raise RuntimeError("wrapper") from e


class TbFilterTests(unittest.TestCase):
    """Failure tracebacks start at the user's code -- frames
    from inside the ctrlrunner package are display-filtered (pytest's
    __tracebackhide__ equivalent). The exception object is untouched."""

    def setUp(self):
        registry.reset()
        steps_module.begin_test()

    def _formatted_through_di(self, user_fn):
        # Resolving a raising fixture routes the exception through real
        # ctrlrunner-internal frames (di.py's _resolve_one and the step
        # context), exactly like a fixture failure in a real run.
        @registry.fixture(scope="function")
        def boom_fixture():
            user_fn()

        resolver = FixtureResolver()
        stack = ExitStack()
        try:
            resolver.resolve(["boom_fixture"], stack)
        except Exception:
            return tb_format.format_filtered_exc()
        finally:
            stack.close()
        raise AssertionError("fixture did not raise")

    def test_user_frames_kept_runner_frames_dropped(self):
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("user-level boom", text)
        self.assertIn("_user_code_that_raises", text)
        self.assertIn("boom_fixture", text)
        self.assertNotIn("ctrlrunner/core/di.py", text)
        self.assertNotIn("_resolve_one", text)

    def test_all_internal_stack_kept_whole(self):
        # an exception whose EVERY frame is ctrlrunner-internal (a runner
        # bug) must keep its full stack -- never filter to nothing.
        import traceback as tb

        te = tb.TracebackException.from_exception(ValueError("runner bug"))
        internal = tb.FrameSummary(tb_format._PKG_DIR + "/core/di.py", 10, "_resolve_one")
        te.stack = tb.StackSummary.from_list([internal])
        tb_format._filter_chain(te)
        self.assertEqual(len(te.stack), 1)
        self.assertIn("di.py", "".join(te.format()))

    def test_chained_exceptions_preserved_and_filtered(self):
        text = self._formatted_through_di(_user_code_chained)
        self.assertIn("KeyError", text)
        self.assertIn("RuntimeError: wrapper", text)
        self.assertIn("direct cause", text)  # the chaining banner survives
        self.assertNotIn("ctrlrunner/core/di.py", text)

    def test_full_trace_mode_disables_filtering(self):
        tb_format.set_full_trace(True)
        self.addCleanup(tb_format.set_full_trace, False)
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", text)

    def test_no_active_exception_returns_empty(self):
        self.assertEqual(tb_format.format_filtered_exc(), "")


if __name__ == "__main__":
    unittest.main()
