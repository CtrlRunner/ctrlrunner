"""
Built-in Playwright fixtures with trace/screenshot capture controlled
entirely by --trace/--screenshot/--browser/--headed CLI flags or
ctrlrunner.toml -- no per-project fixture code needed. Mirrors Playwright
TS's CLI (https://playwright.dev/docs/test-cli) trace/screenshot modes.

Usage -- just import the fixture you need, no wiring required:

    from ctrlrunner.playwright.playwright_fixtures import page

    @test(timeout=15)
    def test_x(page):
        page.goto("https://example.com")   # auto-recorded as a step too

Modes:
    --trace off|on|retain-on-failure|on-first-retry   (default: off)
    --screenshot off|on|only-on-failure                (default: off)
    --browser chromium|firefox|webkit                  (default: chromium)
    --headed                                            (default: headless)

Requires the `playwright` package -- lazily imported inside the fixture
bodies, so importing this module doesn't fail if playwright isn't
installed and you're not actually using these fixtures.
"""

import contextlib

from ..core import context_info
from ..core.registry import fixture
from .playwright_actions import auto_step

_config = {
    "browser_name": "chromium",
    "headless": True,
    "trace_mode": "off",  # off | on | retain-on-failure | on-first-retry
    "screenshot_mode": "off",  # off | on | only-on-failure
}

_VALID_TRACE_MODES = {"off", "on", "retain-on-failure", "on-first-retry"}
_VALID_SCREENSHOT_MODES = {"off", "on", "only-on-failure"}


def configure(
    browser_name: str = "chromium",
    headless: bool = True,
    trace_mode: str = "off",
    screenshot_mode: str = "off",
):
    if trace_mode not in _VALID_TRACE_MODES:
        raise ValueError(
            f"Unknown trace mode '{trace_mode}', expected one of {sorted(_VALID_TRACE_MODES)}"
        )
    if screenshot_mode not in _VALID_SCREENSHOT_MODES:
        raise ValueError(
            f"Unknown screenshot mode '{screenshot_mode}', "
            f"expected one of {sorted(_VALID_SCREENSHOT_MODES)}"
        )
    _config["browser_name"] = browser_name
    _config["headless"] = headless
    _config["trace_mode"] = trace_mode
    _config["screenshot_mode"] = screenshot_mode


def get_config() -> dict:
    return dict(_config)


@fixture(scope="session")
def playwright_instance():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@fixture(scope="session")
def browser(playwright_instance):
    launcher = getattr(playwright_instance, str(_config["browser_name"]))
    b = launcher.launch(headless=_config["headless"])
    yield b
    b.close()


def _capture_trace(context_value, prefix, outcome):
    """Registered with always_capture=True so this always runs, then
    decides for itself (based on the current trace_mode + outcome +
    whether tracing was actually started for this attempt) whether to
    save, discard, or no-op."""
    if not getattr(context_value, "_ctrlrunner_tracing_active", False):
        return None

    mode = _config["trace_mode"]
    if mode == "retain-on-failure" and outcome != "failed":
        with contextlib.suppress(Exception):
            context_value.tracing.stop()
        context_value._ctrlrunner_tracing_active = False
        return None

    path = f"{prefix}.zip"
    context_value.tracing.stop(path=path)
    context_value._ctrlrunner_tracing_active = False
    return path


@fixture(scope="function", on_failure=_capture_trace, always_capture=True)
def context(browser):
    mode = _config["trace_mode"]
    ctx = browser.new_context()
    attempt = context_info.current_attempt() or 1

    start_tracing = mode in ("on", "retain-on-failure") or (
        mode == "on-first-retry" and attempt >= 2
    )
    ctx._ctrlrunner_tracing_active = start_tracing
    if start_tracing:
        ctx.tracing.start(screenshots=True, snapshots=True)

    yield ctx

    if getattr(ctx, "_ctrlrunner_tracing_active", False):
        with contextlib.suppress(Exception):
            ctx.tracing.stop()
    ctx.close()


def _capture_screenshot(page_value, prefix, outcome):
    mode = _config["screenshot_mode"]
    if mode == "off":
        return None
    if mode == "only-on-failure" and outcome != "failed":
        return None
    path = f"{prefix}.png"
    try:
        page_value.screenshot(path=path)
    except Exception:
        return None
    return path


@fixture(scope="function", on_failure=_capture_screenshot, always_capture=True)
def page(context):
    p = context.new_page()
    yield auto_step(p)
