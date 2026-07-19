import traceback
import unittest
from contextlib import ExitStack

from ctrlrunner.core import registry, tb_format
from ctrlrunner.core import steps as steps_module
from ctrlrunner.core.di import FixtureResolver


def _user_code_that_raises():
    raise ValueError("user-level boom")


def _raise_key_error():
    raise KeyError("original cause")


def _user_code_chained():
    try:
        _raise_key_error()
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

    def test_tb_style_auto_matches_todays_default(self):
        tb_format.set_tb_style("auto")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("user-level boom", text)
        self.assertNotIn("ctrlrunner/core/di.py", text)

    def test_tb_style_long_shows_full_unfiltered_trace(self):
        tb_format.set_tb_style("long")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", text)

    def test_tb_style_native_matches_long(self):
        tb_format.set_tb_style("native")
        self.addCleanup(tb_format.set_tb_style, "auto")
        native_text = self._formatted_through_di(_user_code_that_raises)
        tb_format.set_tb_style("long")
        long_text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", native_text)
        self.assertEqual(native_text.count("di.py"), long_text.count("di.py"))

    def test_tb_style_short_keeps_only_the_last_frame(self):
        tb_format.set_tb_style("short")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("user-level boom", text)
        self.assertNotIn("boom_fixture", text)

    def test_tb_style_short_trims_every_link_of_a_chained_exception(self):
        tb_format.set_tb_style("short")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_chained)
        # both the RuntimeError link and its KeyError __cause__ link must
        # each be trimmed to a single frame -- not just the outermost link.
        # _raise_key_error's own frame is two calls deep (boom_fixture ->
        # _user_code_chained -> _raise_key_error) specifically so that an
        # untrimmed __cause__ link is *observable*: if only the top-level
        # exception were trimmed (chain-walk turned into a no-op), the
        # KeyError link would keep its full 2-frame stack and the total
        # frame count below would be 3, not 2.
        self.assertIn("KeyError", text)
        self.assertIn("RuntimeError: wrapper", text)
        self.assertNotIn("boom_fixture", text)
        self.assertEqual(text.count('File "'), 2)

    def test_tb_style_line_is_a_single_line_with_file_and_message(self):
        tb_format.set_tb_style("line")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("ValueError: user-level boom", text)

    def test_tb_style_no_returns_empty(self):
        tb_format.set_tb_style("no")
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertEqual(text, "")

    def test_full_trace_flag_still_works_when_tb_style_is_auto(self):
        # backward compatibility: --full-trace alone (no --tb) still means
        # "full unfiltered" via the pre-existing set_full_trace() path.
        tb_format.set_full_trace(True)
        tb_format.set_tb_style("auto")
        self.addCleanup(tb_format.set_full_trace, False)
        self.addCleanup(tb_format.set_tb_style, "auto")
        text = self._formatted_through_di(_user_code_that_raises)
        self.assertIn("di.py", text)

    def test_format_line_falls_back_to_exc_only_when_stack_is_empty(self):
        # _format_line's "if not te.stack" branch is unreachable through
        # format_filtered_exc() in practice (a real except block always has
        # at least one frame, and _filter_chain never empties a stack it
        # can't refill) -- so it's exercised directly here, the same way
        # test_all_internal_stack_kept_whole hand-builds a TracebackException.
        te = traceback.TracebackException.from_exception(ValueError("bare"))
        te.stack = traceback.StackSummary.from_list([])
        line = tb_format._format_line(te)
        self.assertEqual(line, "ValueError: bare")


if __name__ == "__main__":
    unittest.main()
