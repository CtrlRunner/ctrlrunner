"""
test.step()-equivalent for pyrunner: a context manager (not a decorator,
since Playwright TS's steps are inline blocks inside a test body, not
separate functions) that records a named, timed, nestable span.

    with step("Log in"):
        with step("Fill credentials"):
            page.fill("#user", "alice")
            page.fill("#pass", "secret")
        with step("Submit"):
            page.click("#submit")

This captures name, duration, pass/fail, and nesting -- the same shape
Playwright TS shows in its trace viewer and HTML report step tree. It
does NOT auto-wrap every Playwright API call/assertion into its own step
the way Playwright TS's internal instrumentation does; that requires
patching Playwright's API surface itself, which is out of scope here.
Explicit `with step(...)` blocks only.

State is module-level rather than passed around explicitly because a
worker process runs exactly one test at a time (see worker.py) -- there
is never more than one "current test" per process, so there's nothing to
disambiguate.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Step:
    name: str
    start: float
    end: float | None = None
    error: str | None = None
    children: list["Step"] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return (self.end - self.start) if self.end is not None else 0.0

    @property
    def outcome(self) -> str:
        return "failed" if self.error else "passed"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration": round(self.duration, 3),
            "outcome": self.outcome,
            "error": self.error,
            "children": [c.to_dict() for c in self.children],
        }


_stack: list[Step] = []
_roots: list[Step] = []


@contextmanager
def step(name: str):
    s = Step(name=name, start=time.time())
    if _stack:
        _stack[-1].children.append(s)
    else:
        _roots.append(s)
    _stack.append(s)
    try:
        yield s
    except Exception as exc:
        s.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        s.end = time.time()
        _stack.pop()


def begin_test():
    """Called by the worker right before each test attempt."""
    _stack.clear()
    _roots.clear()


def collect_steps() -> list[Step]:
    """Called by the worker right after each test attempt to grab the
    recorded tree for that attempt (steps do not persist across tests)."""
    return list(_roots)


def render_text(steps: list[Step], indent: int = 0) -> str:
    """Plain-text tree rendering, used for JUnit <system-out> since JUnit
    has no native nested-step schema."""
    lines = []
    for s in steps:
        marker = "\u2713" if s.outcome == "passed" else "\u2717"
        lines.append(f"{'  ' * indent}{marker} {s.name} ({s.duration:.3f}s)")
        if s.error:
            lines.append(f"{'  ' * (indent + 1)}{s.error}")
        lines.append(render_text(s.children, indent + 1))
    return "\n".join(line for line in lines if line)
