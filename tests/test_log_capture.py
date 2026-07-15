import io
import logging
import sys
import unittest

from ctrlrunner.core import log_capture


class CaptureLogsTests(unittest.TestCase):
    def test_captures_stdout_and_stderr(self):
        with log_capture.capture_logs() as result:
            print("hello stdout")
            print("hello stderr", file=sys.stderr)
        self.assertIn("hello stdout", result["stdout"])
        self.assertIn("hello stderr", result["stderr"])

    def test_captures_logging_records(self):
        logger = logging.getLogger("myapp.db")
        with log_capture.capture_logs() as result:
            logger.warning("connection slow: %s", "10.0.0.1")
        self.assertEqual(len(result["records"]), 1)
        rec = result["records"][0]
        self.assertEqual(rec["level"], "WARNING")
        self.assertEqual(rec["name"], "myapp.db")
        self.assertEqual(rec["message"], "connection slow: 10.0.0.1")
        self.assertIsInstance(rec["time"], float)

    def test_restores_stdout_stderr_and_handler_after_exit(self):
        original_stdout, original_stderr = sys.stdout, sys.stderr
        root = logging.getLogger()
        handlers_before = list(root.handlers)
        with log_capture.capture_logs():
            pass
        self.assertIs(sys.stdout, original_stdout)
        self.assertIs(sys.stderr, original_stderr)
        self.assertEqual(root.handlers, handlers_before)

    def test_tees_to_the_original_stdout(self):
        fake_stdout = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = fake_stdout
        try:
            with log_capture.capture_logs() as result:
                print("visible on both")
        finally:
            sys.stdout = old_stdout
        self.assertIn("visible on both", fake_stdout.getvalue())
        self.assertIn("visible on both", result["stdout"])

    def test_truncates_oversized_stream_and_marks_truncated(self):
        with log_capture.capture_logs(max_stream_bytes=10) as result:
            print("0123456789ABCDEF", end="")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 10)
        self.assertTrue(result["stdout"].endswith("F"))

    def test_bounded_buffer_pops_chunks_across_multiple_writes(self):
        with log_capture.capture_logs(max_stream_bytes=10) as result:
            for chunk in ("01234", "56789", "ABCDE"):
                sys.stdout.write(chunk)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 10)
        self.assertTrue(result["stdout"].endswith("E"))
        self.assertNotIn("0", result["stdout"])

    def test_handles_bad_format_args_without_raising(self):
        # WARNING, not INFO: the root logger's default level is
        # WARNING, and Logger.isEnabledFor() filters BEFORE a LogRecord
        # is even created -- an INFO call under default logging config
        # never reaches any handler at all, which isn't what this test
        # is actually about (capture_logs() deliberately never touches
        # logger levels, so the test must use a level that passes the
        # default threshold on its own).
        logger = logging.getLogger("myapp.bad")
        with log_capture.capture_logs() as result:
            logger.warning("value: %s and %s", "only_one")
        self.assertEqual(len(result["records"]), 1)
        self.assertIn("value: %s and %s", result["records"][0]["message"])

    def test_removes_stale_marked_handler_left_by_a_previous_capture(self):
        stale = log_capture._CaptureHandler([])
        logging.getLogger().addHandler(stale)
        try:
            with log_capture.capture_logs():
                handlers = [
                    h
                    for h in logging.getLogger().handlers
                    if getattr(h, log_capture._HANDLER_MARKER, False)
                ]
                self.assertEqual(len(handlers), 1)
        finally:
            logging.getLogger().removeHandler(stale)

    def test_restores_state_even_if_the_wrapped_code_raises(self):
        original_stdout = sys.stdout
        try:
            with log_capture.capture_logs():
                raise ValueError("boom")
        except ValueError:
            pass
        self.assertIs(sys.stdout, original_stdout)

    def test_concurrent_writers_stay_bounded_and_do_not_crash(self):
        # A test body may legitimately spawn threads that print; the
        # bounded buffer's size bookkeeping has no lock, so this pins the
        # contract that matters: no exception escapes, the capture stays
        # bounded to (roughly) the configured cap, and truncation is
        # flagged. Byte-exact bounds under interleaving are NOT promised.
        import threading

        cap = 1024
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()  # keep the tee's echo out of the suite output
        try:
            with log_capture.capture_logs(max_stream_bytes=cap) as result:

                def writer():
                    for _ in range(200):
                        print("x" * 50)

                threads = [threading.Thread(target=writer) for _ in range(4)]
                for t in threads:
                    t.start()
                print("main thread writes too")
                for t in threads:
                    t.join()
        finally:
            sys.stdout = old_stdout

        self.assertTrue(result["truncated"])
        # generous slack: bounded means "didn't keep everything" (40KB
        # was written), not a byte-exact cap under concurrent writers
        self.assertLess(len(result["stdout"].encode()), cap * 4)


if __name__ == "__main__":
    unittest.main()
