"""
Wraps a Playwright Page (or Locator) so common actions are automatically
recorded as pyrunner steps -- mirroring Playwright TS's built-in
action list (what shows up in its trace viewer / UI Mode timeline)
without requiring `with step(...)` around every call.

Duck-typed rather than importing playwright.sync_api directly, so
pyrunner's core package doesn't gain a hard dependency on Playwright --
this module is opt-in, only imported by test code that wants it.
"""

import functools

from ..core.steps import step

_AUTO_STEP_METHODS = {
    "goto",
    "click",
    "dblclick",
    "fill",
    "type",
    "press",
    "check",
    "uncheck",
    "select_option",
    "hover",
    "focus",
    "set_input_files",
    "drag_and_drop",
    "wait_for_selector",
    "wait_for_url",
    "screenshot",
    "tap",
    "clear",
}


def _format_call(name, args, kwargs) -> str:
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in kwargs.items()]
    return f"{name}({', '.join(parts)})"


def _looks_like_locator(value) -> bool:
    # Duck-typing: a Playwright Locator has both .click and .fill, which
    # a Page also has -- close enough to decide "wrap this too" without
    # importing playwright's types.
    return (
        hasattr(value, "click") and hasattr(value, "fill") and not isinstance(value, AutoStepPage)
    )


class AutoStepPage:
    def __init__(self, target):
        object.__setattr__(self, "_target", target)

    @property
    def __class__(self):
        # Report the wrapped object's class so isinstance() checks -- e.g.
        # playwright's expect() dispatch -- see through the wrapper, while
        # type(self) still reveals AutoStepPage.
        return type(self._target)

    def __getattr__(self, name):
        attr = getattr(self._target, name)
        if name.startswith("_"):
            # Internal attributes (e.g. playwright's _impl_obj) must pass
            # through raw -- wrapping them hands library internals an
            # AutoStepPage instead of the object they expect.
            return attr
        if name in _AUTO_STEP_METHODS and callable(attr):

            @functools.wraps(attr)
            def wrapper(*args, **kwargs):
                with step(_format_call(name, args, kwargs)):
                    return attr(*args, **kwargs)

            return wrapper

        if callable(attr):

            @functools.wraps(attr)
            def passthrough(*args, **kwargs):
                result = attr(*args, **kwargs)
                return AutoStepPage(result) if _looks_like_locator(result) else result

            return passthrough

        return AutoStepPage(attr) if _looks_like_locator(attr) else attr

    def __setattr__(self, name, value):
        setattr(self._target, name, value)

    def __repr__(self):
        return f"AutoStepPage({self._target!r})"


def auto_step(target):
    """Wrap a Playwright Page (or Locator) so its actions are
    automatically recorded as pyrunner steps."""
    return AutoStepPage(target)
