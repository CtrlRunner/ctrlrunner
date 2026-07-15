"""
Failure tracebacks shown to test authors should start at THEIR code,
not at the runner's dispatch machinery -- pyrunner's equivalent of
pytest's __tracebackhide__. Filtering is display-only: the
exception object itself is untouched, and --full-trace (or
full_trace=true in pyrunner.toml) turns filtering off entirely.

State is module-level per worker process, same reasoning as
annotations.py/context_info.py: a worker runs exactly one test at a
time, and set_full_trace() is called once at worker startup.
"""

import sys
import traceback
from pathlib import Path

# The pyrunner package directory -- any frame whose file lives under it
# is runner machinery (worker dispatch, DI resolution, step contexts),
# not something a test author can act on.
_PKG_DIR = str(Path(__file__).resolve().parent.parent)

_full_trace = False


def set_full_trace(enabled: bool) -> None:
    global _full_trace
    _full_trace = bool(enabled)


def _filter_chain(te) -> None:
    """Drops pyrunner-internal frames from every link of the exception
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


def format_filtered_exc() -> str:
    """traceback.format_exc() with pyrunner-internal frames removed.
    Call from an except block, exactly like format_exc()."""
    exc = sys.exc_info()[1]
    if exc is None:
        return ""
    if _full_trace:
        return traceback.format_exc()
    try:
        te = traceback.TracebackException.from_exception(exc)
        _filter_chain(te)
        return "".join(te.format())
    except Exception:
        # Formatting must never mask the original failure.
        return traceback.format_exc()
