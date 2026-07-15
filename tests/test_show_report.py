import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ctrlrunner.ui.show_report import serve_report


class NoPortProbeTests(unittest.TestCase):
    def test_no_separate_probe_then_bind_helper_exists(self):
        # _find_free_port() used to bind a throwaway socket to port 0,
        # close it, and return the port number for a SECOND, separate
        # socket (ThreadingHTTPServer) to bind to -- a probe-then-bind
        # window where another process could grab the same port in
        # between (H11b). ThreadingHTTPServer(("127.0.0.1", 0)) hands
        # back the OS-assigned port atomically from the one socket that
        # actually stays bound, so the standalone probe helper should
        # no longer exist.
        import ctrlrunner.ui.show_report as show_report_module

        self.assertFalse(hasattr(show_report_module, "_find_free_port"))


class ServeReportTests(unittest.TestCase):
    def test_raises_if_report_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(FileNotFoundError):
            serve_report(str(Path(tmp) / "report.html"), open_browser=False, block=False)

    def test_serves_report_file_over_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.html"
            report_path.write_text("<html>hello ctrlrunner</html>", encoding="utf-8")

            httpd, url = serve_report(str(report_path), port=0, open_browser=False, block=False)
            try:
                resp = urllib.request.urlopen(url, timeout=2)
                self.assertEqual(resp.status, 200)
                self.assertIn("hello ctrlrunner", resp.read().decode())
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_accepts_directory_path_and_defaults_to_report_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "report.html").write_text("<html>dir-served</html>", encoding="utf-8")

            httpd, url = serve_report(tmp, port=0, open_browser=False, block=False)
            try:
                resp = urllib.request.urlopen(url, timeout=2)
                self.assertIn("dir-served", resp.read().decode())
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_serves_artifacts_alongside_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "report.html").write_text("<html></html>", encoding="utf-8")
            artifacts_dir = Path(tmp) / "ctrlrunner-artifacts"
            artifacts_dir.mkdir()
            (artifacts_dir / "shot.png").write_bytes(b"fake-png-bytes")

            httpd, url = serve_report(
                str(Path(tmp) / "report.html"), port=0, open_browser=False, block=False
            )
            try:
                artifact_url = url.rsplit("/", 1)[0] + "/ctrlrunner-artifacts/shot.png"
                resp = urllib.request.urlopen(artifact_url, timeout=2)
                self.assertEqual(resp.read(), b"fake-png-bytes")
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_rejects_rebound_host_header(self):
        # DNS-rebinding defense: a request whose Host isn't one of this
        # server's loopback names is refused, so a rebound attacker
        # hostname can't be used to read served files.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "report.html").write_text("<html>secret</html>", encoding="utf-8")
            httpd, url = serve_report(
                str(Path(tmp) / "report.html"), port=0, open_browser=False, block=False
            )
            try:
                req = urllib.request.Request(url, headers={"Host": "attacker.tld"})
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=2)
                self.assertEqual(ctx.exception.code, 403)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_symlink_escaping_root_is_not_served(self):
        # stdlib blocks `..` but does NOT resolve symlinks; a symlink
        # inside the served dir pointing outside it must not leak the
        # target's contents.
        with tempfile.TemporaryDirectory() as served, tempfile.TemporaryDirectory() as secret_dir:
            (Path(served) / "report.html").write_text("<html></html>", encoding="utf-8")
            secret = Path(secret_dir) / "secret.txt"
            secret.write_text("TOP SECRET", encoding="utf-8")
            link = Path(served) / "leak.txt"
            try:
                os.symlink(secret, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported here")

            httpd, url = serve_report(
                str(Path(served) / "report.html"), port=0, open_browser=False, block=False
            )
            try:
                leak_url = url.rsplit("/", 1)[0] + "/leak.txt"
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(leak_url, timeout=2)
                self.assertEqual(ctx.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_does_not_open_browser_when_disabled(self):
        # Just verifies open_browser=False doesn't crash / doesn't attempt
        # to launch anything -- actually opening a browser isn't
        # observable/testable in this environment.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "report.html").write_text("<html></html>", encoding="utf-8")
            httpd, url = serve_report(
                str(Path(tmp) / "report.html"), port=0, open_browser=False, block=False
            )
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
