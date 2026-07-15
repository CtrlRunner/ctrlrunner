"""
Launches Playwright's own trace viewer for a given trace.zip, rather
than reimplementing DOM-snapshot rendering, network waterfalls, or the
action timeline ourselves. Playwright ships a complete, actively
maintained trace viewer as part of the `playwright` package
(`playwright show-trace <file>`, which starts its own local server and
opens a browser tab) -- shelling out to it is far more valuable than a
partial reimplementation of years of someone else's engineering.
"""

import os
import re
import shutil
import subprocess
import threading


def playwright_cli_available() -> bool:
    return shutil.which("playwright") is not None


def open_trace(path: str) -> bool:
    """Launches `playwright show-trace <path>` in the background.
    Returns False (does nothing) if the `playwright` CLI isn't on PATH
    -- the caller is expected to surface that to the user rather than
    fail silently."""
    if not playwright_cli_available():
        return False
    subprocess.Popen(
        ["playwright", "show-trace", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


_LISTENING_RE = re.compile(r"https?://[\d.]+:(\d+)")


class PersistentTraceViewer:
    """One long-lived `playwright show-trace --stdin` server for a whole
    UI Mode session, instead of a new browser window per test. `--stdin`
    puts the CLI's own server in a mode where writing a trace path to its
    stdin pushes a live update to whatever page is already looking at it
    (over the server's internal websocket) -- the same mechanism
    Playwright's own UI Mode uses for its embedded, ever-updating trace
    panel. The server's HTTP page is a plain, iframe-embeddable static
    app (no X-Frame-Options), so the UI Mode frontend can embed it
    directly instead of us reimplementing any part of the trace
    viewer."""

    def __init__(self):
        self._proc = None
        self.url = None
        self.port = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = 10.0) -> bool:
        if self.is_running:
            return True
        if not playwright_cli_available():
            return False

        # The CLI unconditionally tries to open a system browser tab once
        # the server is up (`--host`/`--port` implies that) -- fine for
        # a one-off `show-trace`, wrong here since we embed the page
        # ourselves via iframe and don't want a second, unembedded copy
        # popping up alongside it. There's no dedicated public flag to
        # suppress that; the CLI's own source only skips it when
        # CLAUDECODE or COPILOT_CLI is set (its "don't open a browser
        # for an agent" escape hatch) -- reusing that here, scoped to
        # only this subprocess's environment.
        env = {**os.environ, "CLAUDECODE": "1"}
        proc = subprocess.Popen(
            ["playwright", "show-trace", "--host", "127.0.0.1", "--port", "0", "--stdin"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        found = threading.Event()

        def _read_startup_line():
            if proc.stdout is None:  # guaranteed non-None by stdout=PIPE, but don't assert
                return
            for line in proc.stdout:
                m = _LISTENING_RE.search(line)
                if m:
                    self.port = int(m.group(1))
                    self.url = f"http://127.0.0.1:{self.port}/"
                    found.set()
                    return

        threading.Thread(target=_read_startup_line, daemon=True).start()
        found.wait(timeout)

        if not found.is_set():
            proc.terminate()
            return False

        self._proc = proc
        return True

    def load_trace(self, path: str) -> bool:
        if not self.is_running:
            return False
        # `path` is written verbatim as one line of the --stdin
        # protocol -- a newline (or other control character) in it
        # would inject an extra "load this trace" command of the
        # attacker's choosing. Reject outright rather than stripping,
        # since a path that legitimately contains one is bogus anyway.
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
            return False
        if self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(path + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            return False
        return True

    def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
