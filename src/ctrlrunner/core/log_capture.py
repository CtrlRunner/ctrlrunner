"""
Buffered stdout/stderr + logging capture for one test attempt, used by
worker.py when logs != "off". Follows the same "capture
unconditionally during the attempt, decide what to keep after the
outcome is known" two-phase shape as capture_artifacts() -- the
decision of whether to keep or discard a buffer lives in worker.py,
not here.

Never calls logging.basicConfig() and never touches the user's own
handlers/formatters/levels -- it only adds one root-logger handler for
the duration of the `with` block and removes exactly that object
afterward, restoring stdout/stderr to their original objects in a
`finally`. Cannot hang: everything here is synchronous, in-process, no
threads, no I/O beyond in-memory buffer appends.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager

_MAX_STREAM_BYTES = 5 * 1024 * 1024  # 5MB
_HANDLER_MARKER = "_ctrlrunner_log_capture"


class _BoundedBuffer:
    """A tail-keeping, byte-capped text buffer -- a chatty test must
    not OOM the worker. Keeps the LAST max_bytes of output, not the
    first, since the end of a failure's output is usually the most
    diagnostic part."""

    def __init__(self, max_bytes: int = _MAX_STREAM_BYTES):
        self._max_bytes = max_bytes
        self._chunks: list[str] = []
        self._size = 0
        self.truncated = False

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._chunks.append(text)
        self._size += len(text.encode("utf-8", errors="replace"))
        while self._size > self._max_bytes and len(self._chunks) > 1:
            dropped = self._chunks.pop(0)
            self._size -= len(dropped.encode("utf-8", errors="replace"))
            self.truncated = True
        return len(text)

    def getvalue(self) -> str:
        text = "".join(self._chunks)
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > self._max_bytes:
            self.truncated = True
            return encoded[-self._max_bytes :].decode("utf-8", errors="ignore")
        return text


class _Tee:
    """Writes to both the bounded buffer and the original stream, so
    worker output printed directly to stdout/stderr (outside any
    captured test) stays visible in the real console/log, not just
    captured. Implements write/flush explicitly and delegates
    everything else (isatty, encoding, buffer, ...) to the original
    stream via __getattr__, so code that probes those attributes
    doesn't break."""

    def __init__(self, original, buffer: _BoundedBuffer):
        self._original = original
        self._buffer = buffer

    def write(self, text):
        self._buffer.write(text)
        return self._original.write(text)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


class _CaptureHandler(logging.Handler):
    """Appends one dict per log record to a plain list. Never raises:
    record.getMessage() can raise if args don't match the format
    string (or have mutated since) -- wrapped, degrading to the raw
    record.msg."""

    def __init__(self, records: list):
        super().__init__()
        self._records = records
        setattr(self, _HANDLER_MARKER, True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self._records.append(
            {
                "level": record.levelname,
                "name": record.name,
                "message": message,
                "time": record.created,
            }
        )


@contextmanager
def capture_logs(max_stream_bytes: int = _MAX_STREAM_BYTES):
    """Captures stdout, stderr, and Python logging records for the
    duration of the `with` block. Yields a dict that is filled in as
    output arrives and is fully populated only once the block exits:
    {"stdout": str, "stderr": str, "records": [...], "truncated": bool}.
    """
    stdout_buffer = _BoundedBuffer(max_stream_bytes)
    stderr_buffer = _BoundedBuffer(max_stream_bytes)
    records: list = []
    handler = _CaptureHandler(records)

    result: dict = {"stdout": "", "stderr": "", "records": records, "truncated": False}

    root_logger = logging.getLogger()
    # Defensive: clear any handler left behind by a previous capture
    # that somehow didn't get torn down (should be unreachable given
    # the try/finally below, but keeps handler count bounded across
    # many attempts even if it ever happens).
    for existing in list(root_logger.handlers):
        if getattr(existing, _HANDLER_MARKER, False):
            root_logger.removeHandler(existing)

    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(original_stdout, stdout_buffer)
    sys.stderr = _Tee(original_stderr, stderr_buffer)
    root_logger.addHandler(handler)
    try:
        yield result
    finally:
        root_logger.removeHandler(handler)
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        result["stdout"] = stdout_buffer.getvalue()
        result["stderr"] = stderr_buffer.getvalue()
        result["truncated"] = stdout_buffer.truncated or stderr_buffer.truncated
