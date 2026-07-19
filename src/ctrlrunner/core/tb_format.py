"""
Failure tracebacks shown to test authors should start at THEIR code,
not at the runner's dispatch machinery -- ctrlrunner's equivalent of
pytest's __tracebackhide__. Filtering is display-only: the
exception object itself is untouched, and --full-trace (or
full_trace=true in ctrlrunner.toml) turns filtering off entirely.
--tb=<style> layers five named styles (auto/long/short/line/no, plus
native as an alias for long) on top of that same filtering -- auto is
exactly today's pre-existing behavior, so a caller that never calls
set_tb_style() sees zero change.

State is module-level per worker process, same reasoning as
annotations.py/context_info.py: a worker runs exactly one test at a
time, and set_full_trace()/set_tb_style() are each called once at
worker startup.
"""

import sys
import traceback
from pathlib import Path

# The ctrlrunner package directory -- any frame whose file lives under it
# is runner machinery (worker dispatch, DI resolution, step contexts),
# not something a test author can act on.
_PKG_DIR = str(Path(__file__).resolve().parent.parent)

_full_trace = False
_tb_style = "auto"


def set_full_trace(enabled: bool) -> None:
    global _full_trace
    _full_trace = bool(enabled)


def set_tb_style(style: str) -> None:
    global _tb_style
    _tb_style = style


def _filter_chain(te) -> None:
    """Drops ctrlrunner-internal frames from every link of the exception
    chain (__cause__/__context__), keeping a link's full stack whenever
    filtering would leave it empty -- an all-internal traceback (a
    runner bug) must stay fully visible, never become a bare message."""
    seen = set()
    while te is not None and id(te) not in seen:
        seen.add(id(te))
        kept = [f for f in te.stack if not f.filename.startswith(_PKG_DIR)]
        if kept:
            te.stack = traceback.StackSummary.from_list(kept)
        te = te.__cause__ or te.__context__


def _trim_to_last_frame(te) -> None:
    """--tb=short: keeps only the single frame closest to where the
    exception was actually raised in each link of the chain -- the rest
    of the call stack is noise once you just want 'which line broke'."""
    seen = set()
    while te is not None and id(te) not in seen:
        seen.add(id(te))
        if te.stack:
            te.stack = traceback.StackSummary.from_list([te.stack[-1]])
        te = te.__cause__ or te.__context__


def _format_line(te) -> str:
    """--tb=line: pytest's single-line style, 'file:lineno: ExcType: msg'."""
    exc_only = "".join(te.format_exception_only()).strip()
    if not te.stack:
        return exc_only
    frame = te.stack[-1]
    return f"{frame.filename}:{frame.lineno}: {exc_only}"


def format_filtered_exc() -> str:
    """traceback.format_exc() with ctrlrunner-internal frames removed
    (or reshaped further, depending on the active --tb style). Call
    from an except block, exactly like format_exc()."""
    exc = sys.exc_info()[1]
    if exc is None:
        return ""

    style = _tb_style
    if style == "auto":
        style = "long" if _full_trace else "filtered"
    elif style == "native":
        style = "long"

    if style == "no":
        return ""

    try:
        te = traceback.TracebackException.from_exception(exc)
        if style == "long":
            return "".join(te.format())
        _filter_chain(te)
        if style == "short":
            _trim_to_last_frame(te)
            return "".join(te.format())
        if style == "line":
            return _format_line(te)
        return "".join(te.format())  # style == "filtered" (today's default)
    except Exception:
        # Formatting must never mask the original failure.
        return traceback.format_exc()
