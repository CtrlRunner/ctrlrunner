import io
import json
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.request
from pathlib import Path

from ctrlrunner.ui.ui_server import _QuietHTTPServer, serve_ui


class QuietHTTPServerTests(unittest.TestCase):
    """A page reload aborts the browser's in-flight EventSource
    connection with a TCP reset -- normal client behavior, not a server
    bug -- which the stdlib's default handle_error() would otherwise log
    as a scary traceback on every reload. _QuietHTTPServer suppresses
    just that expected noise."""

    def _server(self):
        return _QuietHTTPServer.__new__(_QuietHTTPServer)  # no socket needed for handle_error()

    def test_suppresses_connection_reset_and_broken_pipe(self):
        server = self._server()
        for exc_cls in (ConnectionResetError, BrokenPipeError):
            try:
                raise exc_cls("simulated client-abort")
            except exc_cls:
                stderr = io.StringIO()
                with unittest.mock.patch("sys.stderr", stderr):
                    server.handle_error(None, ("127.0.0.1", 0))
                self.assertEqual(stderr.getvalue(), "")

    def test_still_logs_unrelated_errors(self):
        server = self._server()
        try:
            raise ValueError("a real bug")
        except ValueError:
            stderr = io.StringIO()
            with unittest.mock.patch("sys.stderr", stderr):
                server.handle_error(None, ("127.0.0.1", 0))
            self.assertIn("ValueError", stderr.getvalue())


class ServeUICtrlCTests(unittest.TestCase):
    def test_ctrl_c_calls_controller_cancel_before_exiting(self):
        # Non-daemon worker processes block interpreter exit until
        # tests finish or hard-timeout -- Ctrl+C must invoke the same
        # cancel machinery the "Cancel" button in the UI uses so a run
        # in progress doesn't wedge process shutdown.
        mock_controller = unittest.mock.MagicMock()
        with (
            unittest.mock.patch(
                "ctrlrunner.ui.ui_server.RunController", return_value=mock_controller
            ),
            unittest.mock.patch.object(
                _QuietHTTPServer, "serve_forever", side_effect=KeyboardInterrupt
            ),
            unittest.mock.patch.object(_QuietHTTPServer, "server_close"),
        ):
            serve_ui("examples", port=0, open_browser=False, block=True)

        mock_controller.cancel.assert_called_once()
        mock_controller.trace_viewer.stop.assert_called_once()


class UIServerTests(unittest.TestCase):
    def setUp(self):
        self.httpd, self.url, self.controller = serve_ui(
            "examples", num_workers=2, timeout=30.0, port=0, open_browser=False, block=False
        )

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.controller.trace_viewer.stop()

    def test_index_serves_the_frontend_html(self):
        resp = urllib.request.urlopen(self.url, timeout=3)
        self.assertEqual(resp.status, 200)
        body = resp.read()
        self.assertIn(b"run-all-btn", body)
        self.assertIn(b"EventSource", body)

    def test_api_tests_lists_discovered_tests(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertGreater(len(data["tests"]), 0)
        self.assertTrue(all("id" in t for t in data["tests"]))

    def test_api_tests_includes_dimensions_and_per_test_groups(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertEqual(data["dimensions"], ["file"])
        self.assertTrue(all("groups" in t and "file" in t["groups"] for t in data["tests"]))

    def test_api_tests_includes_num_workers(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertEqual(data["numWorkers"], 2)
        self.assertEqual(data["numWorkersSetting"], 2)

    def test_api_tests_includes_trace_viewer_url_as_null_before_any_run(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertIsNone(data["traceViewerUrl"])

    def test_api_tests_includes_last_traced_test_id_as_null_before_any_run(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertIsNone(data["lastTracedTestId"])

    def test_api_tests_includes_empty_last_results_before_any_run(self):
        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertEqual(data["lastResults"], {})

    def test_api_tests_includes_last_results_after_a_run(self):
        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-001"]}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        self.controller.wait_until_idle(timeout=10)

        resp = urllib.request.urlopen(self.url + "api/tests", timeout=3)
        data = json.loads(resp.read())
        self.assertEqual(len(data["lastResults"]), 1)
        result = next(iter(data["lastResults"].values()))
        self.assertEqual(result["type"], "test_end")

    def test_api_status_reports_idle_initially(self):
        resp = urllib.request.urlopen(self.url + "api/status", timeout=3)
        self.assertEqual(json.loads(resp.read()), {"status": "idle"})

    def test_api_run_starts_a_run_and_returns_200(self):
        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-001"]}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.read()), {"started": True})
        self.assertTrue(self.controller.wait_until_idle(timeout=10))

    def test_api_run_returns_409_when_already_running(self):
        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-003"]}).encode(),  # test_hangs
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)

        req2 = urllib.request.Request(
            self.url + "api/run",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req2, timeout=3)
            self.fail("expected HTTPError 409")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 409)

        self.controller.cancel()
        self.controller.wait_until_idle(timeout=10)

    def test_api_cancel_stops_a_running_run(self):
        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-003"]}).encode(),  # test_hangs: sleep(30)
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        time.sleep(0.3)

        cancel_req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(cancel_req, timeout=3)
        self.assertEqual(json.loads(resp.read()), {"cancelled": True})
        self.assertTrue(self.controller.wait_until_idle(timeout=10))

    def test_events_stream_delivers_full_run_lifecycle(self):
        events = []

        def listen():
            resp = urllib.request.urlopen(self.url + "api/events", timeout=10)
            while len(events) < 4:
                line = resp.readline().decode().strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        t = threading.Thread(target=listen)
        t.start()
        time.sleep(0.3)  # let the subscription register before the run starts

        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-001"]}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        t.join(timeout=10)

        types = [e["type"] for e in events]
        self.assertEqual(types, ["run_start", "test_start", "test_end", "run_end"])

    def test_run_start_event_includes_trace_viewer_url_key(self):
        events = []

        def listen():
            resp = urllib.request.urlopen(self.url + "api/events", timeout=10)
            while len(events) < 1:
                line = resp.readline().decode().strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        t = threading.Thread(target=listen)
        t.start()
        time.sleep(0.3)

        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-001"]}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        t.join(timeout=10)

        self.assertIn("traceViewerUrl", events[0])
        self.controller.wait_until_idle(timeout=10)

    def test_unknown_path_returns_404(self):
        try:
            urllib.request.urlopen(self.url + "not-a-real-path", timeout=3)
            self.fail("expected HTTPError 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_view_trace_pushes_path_into_the_persistent_trace_viewer(self):
        with unittest.mock.patch.object(
            self.controller.trace_viewer, "load_trace", return_value=True
        ) as mock_load:
            req = urllib.request.Request(
                self.url + "api/view-trace",
                data=json.dumps({"path": "some/trace.zip"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Ctrlrunner-Token": self.httpd.session_token,
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=3)
            self.assertEqual(json.loads(resp.read()), {"loaded": True})
            mock_load.assert_called_once_with("some/trace.zip")

    def test_view_trace_without_path_returns_loaded_false(self):
        req = urllib.request.Request(
            self.url + "api/view-trace",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        self.assertEqual(json.loads(resp.read()), {"loaded": False})

    def test_view_trace_with_test_id_updates_last_traced_test_id(self):
        with unittest.mock.patch.object(
            self.controller.trace_viewer, "load_trace", return_value=True
        ):
            req = urllib.request.Request(
                self.url + "api/view-trace",
                data=json.dumps({"path": "some/trace.zip", "testId": "mod::test"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Ctrlrunner-Token": self.httpd.session_token,
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(self.controller.last_traced_test_id, "mod::test")

    def test_view_trace_does_not_update_last_traced_test_id_when_load_fails(self):
        with unittest.mock.patch.object(
            self.controller.trace_viewer, "load_trace", return_value=False
        ):
            req = urllib.request.Request(
                self.url + "api/view-trace",
                data=json.dumps({"path": "some/trace.zip", "testId": "mod::test"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Ctrlrunner-Token": self.httpd.session_token,
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        self.assertIsNone(self.controller.last_traced_test_id)

    def test_test_end_event_includes_artifacts_and_steps(self):
        events = []

        def listen():
            resp = urllib.request.urlopen(self.url + "api/events", timeout=10)
            while len(events) < 4:
                line = resp.readline().decode().strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        t = threading.Thread(target=listen)
        t.start()
        time.sleep(0.3)

        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-400"]}).encode(),  # has nested steps
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        t.join(timeout=10)

        test_end = next(e for e in events if e["type"] == "test_end")
        self.assertIn("artifacts", test_end)
        self.assertIn("steps", test_end)
        self.assertGreater(len(test_end["steps"]), 0)

    def test_api_config_updates_num_workers(self):
        req = urllib.request.Request(
            self.url + "api/config",
            data=json.dumps({"numWorkers": 7}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        self.assertEqual(json.loads(resp.read()), {"numWorkers": 7, "numWorkersSetting": 7})
        self.assertEqual(self.controller.num_workers, 7)

    def test_api_config_accepts_auto(self):
        req = urllib.request.Request(
            self.url + "api/config",
            data=json.dumps({"numWorkers": "auto"}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        data = json.loads(resp.read())
        self.assertEqual(data["numWorkersSetting"], "auto")
        self.assertIsInstance(data["numWorkers"], int)
        self.assertGreaterEqual(data["numWorkers"], 1)
        self.assertEqual(self.controller.num_workers_setting, "auto")

    def test_api_config_rejects_garbage_string(self):
        req = urllib.request.Request(
            self.url + "api/config",
            data=json.dumps({"numWorkers": "banana"}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_config_rejects_invalid_num_workers(self):
        req = urllib.request.Request(
            self.url + "api/config",
            data=json.dumps({"numWorkers": 0}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_config_rejects_change_while_running(self):
        req = urllib.request.Request(
            self.url + "api/run",
            data=json.dumps({"caseIds": ["TC-003"]}).encode(),  # test_hangs
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        time.sleep(0.3)

        config_req = urllib.request.Request(
            self.url + "api/config",
            data=json.dumps({"numWorkers": 3}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(config_req, timeout=3)
            self.fail("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

        self.controller.cancel()
        self.controller.wait_until_idle(timeout=10)

    def test_state_changing_post_rejected_when_origin_is_cross_site(self):
        # A hostile page's fetch() would set Origin to its own site --
        # the server binds 127.0.0.1 but has no CSRF token, so this
        # Origin check is the only thing standing between a malicious
        # page and starting/cancelling runs on a developer's machine.
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_state_changing_post_allowed_when_origin_matches_host(self):
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": self.url.rstrip("/"),
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        self.assertEqual(json.loads(resp.read()), {"cancelled": True})

    def test_state_changing_post_rejected_without_session_token(self):
        # The token is the gate against a different local process/user
        # (which can send a correct Host and omit Origin). No token -> 403.
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_state_changing_post_rejected_with_wrong_session_token(self):
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Ctrlrunner-Token": "not-the-token"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_post_rejected_when_host_header_is_rebound_hostname(self):
        # DNS-rebinding: attacker.tld resolves to 127.0.0.1 so the socket
        # connects, but the browser sends the attacker's hostname in Host,
        # which isn't one of our loopback names -> 403, even with a token.
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Host": "attacker.tld",
                "X-Ctrlrunner-Token": self.httpd.session_token,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_get_rejected_when_host_header_is_rebound_hostname(self):
        # GETs are Host-allowlisted too -- rebinding must not be able to
        # read /api/tests etc. cross-site.
        req = urllib.request.Request(
            self.url + "api/tests",
            headers={"Host": "attacker.tld"},
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 403")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_post_without_content_type_json_is_rejected(self):
        # Cross-site <form> submissions can only use a handful of
        # "simple" Content-Types (e.g. text/plain) without triggering a
        # CORS preflight -- requiring application/json means a form-based
        # CSRF POST can never reach the JSON body this handler expects.
        req = urllib.request.Request(
            self.url + "api/cancel",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_view_trace_rejects_path_with_embedded_newline(self):
        with unittest.mock.patch.object(
            self.controller.trace_viewer, "load_trace", return_value=True
        ) as mock_load:
            req = urllib.request.Request(
                self.url + "api/view-trace",
                data=json.dumps({"path": "some/trace.zip\nrm -rf /"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Ctrlrunner-Token": self.httpd.session_token,
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=3)
            self.assertEqual(json.loads(resp.read()), {"loaded": False})
            mock_load.assert_not_called()

    def test_get_serves_artifact_file_under_artifacts_root(self):
        # Self-contained: write the artifact this test serves rather than
        # relying on a real @test run having populated it already (no
        # test in this suite runs examples/test_selftest.py::test_fails
        # unfiltered, so ctrlrunner-artifacts/ isn't guaranteed to exist
        # on a fresh checkout).
        from ctrlrunner.ui.ui_server import ARTIFACTS_ROOT

        artifact_dir = ARTIFACTS_ROOT / "examples.test_selftest__test_fails" / "attempt-1"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "fake_page.png"
        artifact_path.write_bytes(b"fake-png-bytes")
        self.addCleanup(artifact_path.unlink)

        resp = urllib.request.urlopen(
            self.url
            + "ctrlrunner-artifacts/examples.test_selftest__test_fails/attempt-1/fake_page.png",
            timeout=3,
        )
        self.assertEqual(resp.status, 200)

    def test_get_artifact_rejects_path_traversal(self):
        try:
            urllib.request.urlopen(
                self.url + "ctrlrunner-artifacts/../cli.py",
                timeout=3,
            )
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))

    def test_get_artifact_rejects_percent_encoded_traversal(self):
        # _serve_artifact unquote()s the URL before the containment
        # check -- percent-encoding is exactly how ".." sneaks past
        # naive prefix filters, so the decoded form must hit the same
        # resolve()-based wall as the literal one.
        try:
            urllib.request.urlopen(
                self.url + "ctrlrunner-artifacts/%2e%2e/cli.py",
                timeout=3,
            )
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_get_artifact_rejects_symlink_escaping_artifacts_root(self):
        # `..` is stripped by resolve(), but a symlink INSIDE the
        # artifacts root pointing outside it resolves to an external
        # path -- the same threat show_report.py already tests for.
        from ctrlrunner.ui.ui_server import ARTIFACTS_ROOT

        ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
        link = ARTIFACTS_ROOT / "escape-link.py"
        target = Path(__file__).resolve()  # any real file outside the root
        link.symlink_to(target)
        self.addCleanup(link.unlink)
        try:
            urllib.request.urlopen(
                self.url + "ctrlrunner-artifacts/escape-link.py",
                timeout=3,
            )
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))

    def test_get_artifact_returns_404_for_missing_file(self):
        try:
            urllib.request.urlopen(
                self.url + "ctrlrunner-artifacts/does/not/exist.png",
                timeout=3,
            )
            self.fail("expected HTTPError 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
