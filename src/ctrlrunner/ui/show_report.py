"""
A tiny local static file server for
viewing a generated HTML report (and any artifacts/traces linked from
it) over http://, not file:// -- needed because a trace viewer fetches
the trace zip via XHR, which browsers block under file:// due to CORS,
and because it's a nicer one-command UX than double-clicking a file.
No new dependency: built entirely on stdlib http.server.
"""

import functools
import http.server
import threading
import webbrowser
from pathlib import Path
from typing import cast

from .localsec import host_allowed


class _ReportRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler already strips `..` from URL paths, but
    adds two things it doesn't do on its own:

      * Host-allowlisting (the DNS-rebinding defense the UI server also
        applies) -- without it, a page on any origin could point a
        rebound hostname at this loopback port and read served files.
      * Symlink containment -- stdlib resolves the URL against the served
        directory but does NOT resolve symlinks, so a symlink inside the
        report dir could otherwise point outside it and be served. We
        resolve the final path and confirm it's still under the root.
    """

    served_root: Path = Path()  # bound per-instance by serve_report()

    def _port(self) -> int:
        return cast("tuple[str, int]", self.server.server_address)[1]

    def do_GET(self):
        if not host_allowed(self.headers.get("Host"), self._port()):
            self.send_error(403, "Host not allowed")
            return
        super().do_GET()

    def do_HEAD(self):
        if not host_allowed(self.headers.get("Host"), self._port()):
            self.send_error(403, "Host not allowed")
            return
        super().do_HEAD()

    def translate_path(self, path):
        # stdlib maps the URL to a filesystem path (and blocks `..`); we
        # then fully resolve it (following symlinks) and refuse anything
        # that escapes the served root.
        fs_path = Path(super().translate_path(path)).resolve()
        root = self.served_root.resolve()
        if fs_path != root and root not in fs_path.parents:
            # Escapes the root (e.g. via a symlink) -- hand back a path
            # that can't exist so the request 404s instead of serving it.
            return str(root / "__ctrlrunner_denied__")
        return str(fs_path)


def serve_report(
    path: str,
    port: int = 0,
    open_browser: bool = True,
    block: bool = True,
    bind: str = "127.0.0.1",
):
    """Serves the directory containing `path` (or `path` itself if it's
    already a directory) at http://127.0.0.1:<port>/.

    block=True (CLI default): runs until Ctrl+C, returns None.
    block=False (tests / programmatic use): starts a background thread
    and returns (httpd, url) so the caller controls shutdown via
    httpd.shutdown() + httpd.server_close().
    """
    target = Path(path).resolve()
    if target.is_dir():
        directory = target
        report_name = "report.html"
    else:
        directory = target.parent
        report_name = target.name

    if not (directory / report_name).exists():
        raise FileNotFoundError(
            f"No report found at {directory / report_name}. Run tests with --html-report first."
        )

    # `port=0` is passed straight through to ThreadingHTTPServer,
    # which asks the OS to assign a free port atomically as part of the
    # one bind() this server actually keeps -- no separate
    # probe-then-close-then-rebind step (the old _find_free_port())
    # that left a window for another process to grab the same port in
    # between.
    handler_cls = type("BoundReportHandler", (_ReportRequestHandler,), {"served_root": directory})
    handler = functools.partial(handler_cls, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer((bind, port), handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/{report_name}"

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    if block:
        print(f"Serving {directory} at {url}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass  # Ctrl+C is the normal way to stop this
        finally:
            httpd.server_close()
        return None

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, url
