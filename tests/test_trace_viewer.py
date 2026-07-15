import unittest
from unittest.mock import MagicMock, patch

from pyrunner.ui.trace_viewer import PersistentTraceViewer, open_trace, playwright_cli_available


class TraceViewerTests(unittest.TestCase):
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_cli_available_true_when_on_path(self, _mock_which):
        self.assertTrue(playwright_cli_available())

    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value=None)
    def test_cli_available_false_when_missing(self, _mock_which):
        self.assertFalse(playwright_cli_available())

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_open_trace_launches_subprocess_when_cli_available(self, _mock_which, mock_popen):
        result = open_trace("trace.zip")
        self.assertTrue(result)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertEqual(args, ["playwright", "show-trace", "trace.zip"])

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value=None)
    def test_open_trace_returns_false_without_spawning_when_cli_missing(
        self, _mock_which, mock_popen
    ):
        result = open_trace("trace.zip")
        self.assertFalse(result)
        mock_popen.assert_not_called()


class PersistentTraceViewerTests(unittest.TestCase):
    def _mock_process(self, stdout_lines, running=True):
        proc = MagicMock()
        proc.stdout = iter(stdout_lines)
        proc.stdin = MagicMock()
        proc.poll.return_value = None if running else 0
        return proc

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_start_parses_port_from_listening_line(self, _mock_which, mock_popen):
        mock_popen.return_value = self._mock_process(
            ["\n", "Listening on http://127.0.0.1:54321\n"]
        )
        viewer = PersistentTraceViewer()

        self.assertTrue(viewer.start(timeout=2))

        self.assertEqual(viewer.port, 54321)
        self.assertEqual(viewer.url, "http://127.0.0.1:54321/")
        self.assertTrue(viewer.is_running)
        args = mock_popen.call_args[0][0]
        self.assertEqual(
            args, ["playwright", "show-trace", "--host", "127.0.0.1", "--port", "0", "--stdin"]
        )

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value=None)
    def test_start_returns_false_without_spawning_when_cli_missing(self, _mock_which, mock_popen):
        viewer = PersistentTraceViewer()
        self.assertFalse(viewer.start(timeout=2))
        mock_popen.assert_not_called()
        self.assertFalse(viewer.is_running)

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_start_returns_false_and_terminates_when_no_listening_line_before_timeout(
        self, _mock_which, mock_popen
    ):
        mock_popen.return_value = self._mock_process([])
        viewer = PersistentTraceViewer()

        self.assertFalse(viewer.start(timeout=0.05))

        self.assertFalse(viewer.is_running)
        mock_popen.return_value.terminate.assert_called_once()

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_start_is_idempotent_when_already_running(self, _mock_which, mock_popen):
        mock_popen.return_value = self._mock_process(["\n", "Listening on http://127.0.0.1:1\n"])
        viewer = PersistentTraceViewer()
        viewer.start(timeout=2)

        self.assertTrue(viewer.start(timeout=2))
        mock_popen.assert_called_once()

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_load_trace_writes_path_and_flushes(self, _mock_which, mock_popen):
        mock_popen.return_value = self._mock_process(["\n", "Listening on http://127.0.0.1:1\n"])
        viewer = PersistentTraceViewer()
        viewer.start(timeout=2)

        self.assertTrue(viewer.load_trace("some/trace.zip"))

        mock_popen.return_value.stdin.write.assert_called_once_with("some/trace.zip\n")
        mock_popen.return_value.stdin.flush.assert_called_once()

    def test_load_trace_returns_false_when_never_started(self):
        viewer = PersistentTraceViewer()
        self.assertFalse(viewer.load_trace("some/trace.zip"))

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_load_trace_rejects_path_with_embedded_newline(self, _mock_which, mock_popen):
        # A newline in `path` would inject an extra line into the
        # --stdin protocol (each line is a separate "load this trace"
        # command) -- reject rather than writing it through verbatim.
        mock_popen.return_value = self._mock_process(["\n", "Listening on http://127.0.0.1:1\n"])
        viewer = PersistentTraceViewer()
        viewer.start(timeout=2)

        self.assertFalse(viewer.load_trace("some/trace.zip\nmalicious-command"))
        mock_popen.return_value.stdin.write.assert_not_called()

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_load_trace_rejects_path_with_control_characters(self, _mock_which, mock_popen):
        mock_popen.return_value = self._mock_process(["\n", "Listening on http://127.0.0.1:1\n"])
        viewer = PersistentTraceViewer()
        viewer.start(timeout=2)

        self.assertFalse(viewer.load_trace("some/trace.zip\x00"))
        mock_popen.return_value.stdin.write.assert_not_called()

    @patch("pyrunner.ui.trace_viewer.subprocess.Popen")
    @patch("pyrunner.ui.trace_viewer.shutil.which", return_value="/usr/bin/playwright")
    def test_stop_terminates_running_process(self, _mock_which, mock_popen):
        mock_popen.return_value = self._mock_process(["\n", "Listening on http://127.0.0.1:1\n"])
        viewer = PersistentTraceViewer()
        viewer.start(timeout=2)

        viewer.stop()

        mock_popen.return_value.terminate.assert_called_once()
        self.assertFalse(viewer.is_running)

    def test_stop_without_start_does_not_raise(self):
        viewer = PersistentTraceViewer()
        viewer.stop()  # no-op, must not crash


if __name__ == "__main__":
    unittest.main()
