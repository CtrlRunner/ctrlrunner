"""
Local HTTP server exposing
RunController over a small JSON API, plus a Server-Sent-Events stream
for live run progress. No WebSocket library needed -- SSE (server ->
browser only) is exactly what's needed here, since the browser only
ever needs to *receive* progress; commands (run/cancel) are plain POST
requests. Built entirely on stdlib http.server.
"""

import json
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

from ..execution.run_controller import STATUS_RUNNING, RunController
from .localsec import (
    TOKEN_HEADER,
    host_allowed,
    new_session_token,
    origin_allowed,
    token_matches,
)
from .ui_frontend import render_ui_html

# Files a failure screenshot/trace link in the frontend can point to
# (`ctrlrunner-artifacts/<test>/attempt-N/...`, relative to the process's
# cwd -- see worker.py's ARTIFACTS_ROOT). Resolved once at import time
# so every request checks containment against the same absolute root.
ARTIFACTS_ROOT = Path("ctrlrunner-artifacts").resolve()


class _QuietHTTPServer(ThreadingHTTPServer):
    """A page reload tears down the browser's in-flight EventSource
    connection (and any stray reconnect attempt) with a TCP reset --
    normal client-abort behavior, not a server bug. The stdlib's default
    handle_error() doesn't know that and dumps a full traceback to
    stderr for it. Swallow just that specific, expected noise; anything
    else still prints the normal way so real bugs stay visible."""

    session_token: str = ""  # set by serve_ui(); read by tests/programmatic callers

    def handle_error(self, request, client_address):
        exc_type = sys.exc_info()[0]
        if exc_type is not None and issubclass(exc_type, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class UIRequestHandler(BaseHTTPRequestHandler):
    controller: RunController = cast(RunController, None)  # bound per-instance by serve_ui()
    # Per-launch secret embedded in the served page (see serve_ui) and
    # required on every state-changing POST -- the local-process/CSRF
    # gate. Overridden on the bound handler subclass; this default makes
    # the class importable/usable without a token in tests that don't
    # exercise the POST paths.
    session_token: str = ""
    ui_html: str = ""

    def log_message(self, format, *args):
        pass  # keep stdout clean; the CLI prints its own status lines

    def _port(self) -> int:
        return cast("tuple[str, int]", self.server.server_address)[1]

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body_str, status=200):
        body = body_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Host-allowlisting on every request (GETs included) is the
        # DNS-rebinding defense: a rebound request carries the attacker's
        # own hostname in Host, which isn't one of our loopback names.
        # GETs need no Origin/token check beyond this -- they're not
        # state-changing, and the browser's same-origin policy already
        # blocks a cross-site page from READING any response we don't
        # send CORS headers for (we send none).
        if not host_allowed(self.headers.get("Host"), self._port()):
            self.send_error(403, "Host not allowed")
            return
        if self.path in ("/", "/index.html"):
            self._send_html(self.ui_html)
        elif self.path == "/api/tests":
            self._send_json(
                {
                    "tests": self.controller.list_tests(),
                    "dimensions": self.controller.dimension_names(),
                    # numWorkers = the resolved concrete int each run
                    # uses; numWorkersSetting = the raw spelling it came
                    # from ("auto", "50%", or an int).
                    "numWorkers": self.controller.num_workers,
                    "numWorkersSetting": self.controller.num_workers_setting,
                    "traceViewerUrl": self.controller.trace_viewer.url
                    if self.controller.trace_viewer.is_running
                    else None,
                    "lastTracedTestId": self.controller.last_traced_test_id,
                    "lastResults": self.controller.last_results_snapshot(),
                }
            )
        elif self.path == "/api/status":
            self._send_json(self.controller.get_status())
        elif self.path == "/api/events":
            self._stream_events()
        elif self.path.startswith("/ctrlrunner-artifacts/"):
            self._serve_artifact()
        else:
            self.send_error(404)

    def _serve_artifact(self):
        """Serves failure screenshots/other artifacts the frontend
        links to (`<a href="ctrlrunner-artifacts/...">`) -- without this,
        every such link 404s (only .zip traces work, via the separate
        POST /api/view-trace path). Resolves the requested path and
        confirms it's still under ARTIFACTS_ROOT before serving, so a
        `..` component can't escape the artifacts directory."""
        url_path = unquote(urlparse(self.path).path)
        relative = url_path[len("/ctrlrunner-artifacts/") :]
        candidate = (ARTIFACTS_ROOT / relative).resolve()
        try:
            candidate.relative_to(ARTIFACTS_ROOT)
        except ValueError:
            self.send_error(403, "Path escapes the artifacts directory")
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        import mimetypes

        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Layered gate for state-changing endpoints (see localsec.py):
        #   1. Host allowlist  -> blocks DNS rebinding.
        #   2. Origin/Referer  -> blocks a cross-site page's fetch(),
        #      validated against our OWN bound port (not the request's
        #      Host, which was the previous bypass).
        #   3. Content-Type    -> a cross-site <form> can't send
        #      application/json without a CORS preflight it can't satisfy.
        #   4. Session token   -> a page that never saw the token (or a
        #      different local process/user) can't forge this header.
        port = self._port()
        if not host_allowed(self.headers.get("Host"), port):
            self.send_error(403, "Host not allowed")
            return
        if not origin_allowed(self.headers.get("Origin"), self.headers.get("Referer"), port):
            self.send_error(403, "Cross-origin request rejected")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip().lower() != "application/json":
                self.send_error(400, "Content-Type must be application/json")
                return
            raw = self.rfile.read(length)
        else:
            raw = b"{}"

        if not token_matches(self.headers.get(TOKEN_HEADER), self.session_token):
            self.send_error(403, "Missing or invalid session token")
            return
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if self.path == "/api/run":
            started = self.controller.start_run(
                test_ids=body.get("testIds"),
                case_ids=body.get("caseIds"),
                tags=body.get("tags"),
            )
            self._send_json({"started": started}, 200 if started else 409)
        elif self.path == "/api/cancel":
            self.controller.cancel()
            self._send_json({"cancelled": True})
        elif self.path == "/api/view-trace":
            path = body.get("path", "")
            if path and any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
                self._send_json({"loaded": False})
                return
            loaded = self.controller.trace_viewer.load_trace(path) if path else False
            if loaded and body.get("testId"):
                self.controller.last_traced_test_id = body["testId"]
            self._send_json({"loaded": loaded})
        elif self.path == "/api/config":
            if self.controller.get_status()["status"] == STATUS_RUNNING:
                self._send_json({"error": "Cannot change config while a run is in progress."}, 400)
                return
            try:
                self.controller.set_num_workers(body["numWorkers"])
            except (KeyError, ValueError) as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json(
                {
                    "numWorkers": self.controller.num_workers,
                    "numWorkersSetting": self.controller.num_workers_setting,
                }
            )
        else:
            self.send_error(404)

    def _stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = self.controller.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.controller.unsubscribe(q)


def serve_ui(
    root: str,
    num_workers: int | str = "auto",
    timeout: float = 30.0,
    port: int = 0,
    open_browser: bool = True,
    block: bool = True,
    playwright_config: dict | None = None,
    tag_registry=None,
    grouping_dimensions=None,
    quarantine=None,
    bind: str = "127.0.0.1",
    worker_constraints=None,
    fully_parallel: bool = False,
    strict_teardown: bool = True,
):
    controller = RunController(
        root,
        num_workers,
        timeout,
        playwright_config=playwright_config,
        tag_registry=tag_registry,
        grouping_dimensions=grouping_dimensions,
        quarantine=quarantine,
        worker_constraints=worker_constraints,
        fully_parallel=fully_parallel,
        strict_teardown=strict_teardown,
    )
    token = new_session_token()
    handler_cls = type(
        "BoundUIRequestHandler",
        (UIRequestHandler,),
        {
            "controller": controller,
            "session_token": token,
            "ui_html": render_ui_html(token),
        },
    )
    httpd = _QuietHTTPServer((bind, port or 0), handler_cls)
    # Exposed for programmatic callers/tests that need to send the token
    # on state-changing POSTs (the browser gets it embedded in the page).
    httpd.session_token = token
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    if block:
        print(f"ctrlrunner UI Mode at {url}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass  # Ctrl+C is the normal way to stop this
        finally:
            # Without this, a run started just before Ctrl+C leaves its
            # non-daemon worker processes alive after the interpreter
            # would otherwise exit -- they block process exit until the
            # tests finish or hard-kill on their own timeout, bypassing
            # the cancel machinery that exists for exactly this case.
            controller.cancel()
            httpd.server_close()
            controller.trace_viewer.stop()
        return None

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, url, controller
