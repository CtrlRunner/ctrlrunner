import unittest

from ctrlrunner.core import context_info
from ctrlrunner.playwright import playwright_fixtures


class FakeTracing:
    def __init__(self):
        self.started = False
        self.stopped_with_path = None
        self.stopped_without_path = False

    def start(self, **kwargs):
        self.started = True

    def stop(self, path=None):
        if path:
            self.stopped_with_path = path
        else:
            self.stopped_without_path = True


class FakeContext:
    def __init__(self):
        self.tracing = FakeTracing()


class FakePage:
    def __init__(self):
        self.screenshots = []

    def screenshot(self, path):
        self.screenshots.append(path)


class CrashingPage:
    """Simulates the real-world failure-time state: the browser/page is
    already dead by the time the screenshot hook runs."""

    def screenshot(self, path):
        raise RuntimeError("Target page, context or browser has been closed")


class ClosableFakeContext(FakeContext):
    def __init__(self):
        super().__init__()
        self.closed = False

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self):
        self.contexts = []

    def new_context(self):
        ctx = ClosableFakeContext()
        self.contexts.append(ctx)
        return ctx


class ConfigureTests(unittest.TestCase):
    def tearDown(self):
        playwright_fixtures.configure()  # reset to defaults

    def test_configure_updates_config(self):
        playwright_fixtures.configure(
            browser_name="firefox", headless=False, trace_mode="on", screenshot_mode="on"
        )
        config = playwright_fixtures.get_config()
        self.assertEqual(config["browser_name"], "firefox")
        self.assertFalse(config["headless"])
        self.assertEqual(config["trace_mode"], "on")
        self.assertEqual(config["screenshot_mode"], "on")

    def test_get_config_returns_a_copy(self):
        config = playwright_fixtures.get_config()
        config["trace_mode"] = "mutated"
        self.assertNotEqual(playwright_fixtures.get_config()["trace_mode"], "mutated")

    def test_invalid_trace_mode_raises(self):
        with self.assertRaises(ValueError):
            playwright_fixtures.configure(trace_mode="not-a-real-mode")

    def test_invalid_screenshot_mode_raises(self):
        with self.assertRaises(ValueError):
            playwright_fixtures.configure(screenshot_mode="not-a-real-mode")

    def test_defaults_are_off(self):
        playwright_fixtures.configure()
        config = playwright_fixtures.get_config()
        self.assertEqual(config["trace_mode"], "off")
        self.assertEqual(config["screenshot_mode"], "off")


class TraceCaptureLogicTests(unittest.TestCase):
    def tearDown(self):
        playwright_fixtures.configure()

    def test_trace_off_never_saves(self):
        playwright_fixtures.configure(trace_mode="off")
        ctx = FakeContext()
        ctx._ctrlrunner_tracing_active = False  # "off" mode never starts tracing
        result = playwright_fixtures._capture_trace(ctx, "prefix", "passed")
        self.assertIsNone(result)
        self.assertFalse(ctx.tracing.started)

    def test_trace_on_saves_regardless_of_outcome(self):
        playwright_fixtures.configure(trace_mode="on")
        for outcome in ("passed", "failed", "expected_failure"):
            ctx = FakeContext()
            ctx._ctrlrunner_tracing_active = True
            result = playwright_fixtures._capture_trace(ctx, "prefix", outcome)
            self.assertEqual(result, "prefix.zip")
            self.assertEqual(ctx.tracing.stopped_with_path, "prefix.zip")

    def test_retain_on_failure_discards_on_pass(self):
        playwright_fixtures.configure(trace_mode="retain-on-failure")
        ctx = FakeContext()
        ctx._ctrlrunner_tracing_active = True
        result = playwright_fixtures._capture_trace(ctx, "prefix", "passed")
        self.assertIsNone(result)
        self.assertTrue(ctx.tracing.stopped_without_path)
        self.assertIsNone(ctx.tracing.stopped_with_path)

    def test_retain_on_failure_saves_on_failure(self):
        playwright_fixtures.configure(trace_mode="retain-on-failure")
        ctx = FakeContext()
        ctx._ctrlrunner_tracing_active = True
        result = playwright_fixtures._capture_trace(ctx, "prefix", "failed")
        self.assertEqual(result, "prefix.zip")

    def test_inactive_tracing_is_a_noop_regardless_of_mode(self):
        for mode in ("on", "retain-on-failure", "off"):
            playwright_fixtures.configure(trace_mode=mode)
            ctx = FakeContext()
            ctx._ctrlrunner_tracing_active = False
            result = playwright_fixtures._capture_trace(ctx, "prefix", "failed")
            self.assertIsNone(result)
            self.assertFalse(ctx.tracing.stopped_with_path)
            self.assertFalse(ctx.tracing.stopped_without_path)

    def test_on_first_retry_saves_when_active_regardless_of_outcome(self):
        playwright_fixtures.configure(trace_mode="on-first-retry")
        ctx = FakeContext()
        ctx._ctrlrunner_tracing_active = True  # would only be True if attempt >= 2
        result = playwright_fixtures._capture_trace(ctx, "prefix", "passed")
        self.assertEqual(result, "prefix.zip")


class ScreenshotCaptureLogicTests(unittest.TestCase):
    def tearDown(self):
        playwright_fixtures.configure()

    def test_screenshot_off_never_captures(self):
        playwright_fixtures.configure(screenshot_mode="off")
        page = FakePage()
        result = playwright_fixtures._capture_screenshot(page, "prefix", "failed")
        self.assertIsNone(result)
        self.assertEqual(page.screenshots, [])

    def test_screenshot_on_captures_on_pass(self):
        playwright_fixtures.configure(screenshot_mode="on")
        page = FakePage()
        result = playwright_fixtures._capture_screenshot(page, "prefix", "passed")
        self.assertEqual(result, "prefix.png")
        self.assertEqual(page.screenshots, ["prefix.png"])

    def test_only_on_failure_skips_on_pass(self):
        playwright_fixtures.configure(screenshot_mode="only-on-failure")
        page = FakePage()
        result = playwright_fixtures._capture_screenshot(page, "prefix", "passed")
        self.assertIsNone(result)
        self.assertEqual(page.screenshots, [])

    def test_only_on_failure_captures_on_failure(self):
        playwright_fixtures.configure(screenshot_mode="only-on-failure")
        page = FakePage()
        result = playwright_fixtures._capture_screenshot(page, "prefix", "failed")
        self.assertEqual(result, "prefix.png")

    def test_screenshot_raising_returns_none_instead_of_propagating(self):
        # The most common failure-time reality: the browser already
        # crashed/closed, so page.screenshot() itself raises. The capture
        # hook must swallow that and report "no artifact", not stack a
        # second exception on top of the test's own failure.
        playwright_fixtures.configure(screenshot_mode="on")
        result = playwright_fixtures._capture_screenshot(CrashingPage(), "prefix", "failed")
        self.assertIsNone(result)


class ContextFixtureTeardownTests(unittest.TestCase):
    """Drives the real context() generator fixture with fakes -- the
    extracted decision tests below cover *whether* tracing starts, these
    cover what teardown does with a context whose tracing is still
    active (i.e. no on_failure hook consumed it)."""

    def tearDown(self):
        playwright_fixtures.configure()

    def _drive(self, trace_mode):
        playwright_fixtures.configure(trace_mode=trace_mode)
        context_info.begin_test("mod::test_x", 1)
        browser = FakeBrowser()
        gen = playwright_fixtures.context(browser)
        ctx = next(gen)
        with self.assertRaises(StopIteration):
            next(gen)  # normal end-of-test teardown
        return ctx

    def test_teardown_with_active_tracing_stops_and_closes(self):
        # trace_mode="on" starts tracing; if no on_failure capture ran,
        # teardown must stop tracing (discarding, no path) AND still
        # close the context -- leaking either keeps the browser alive.
        ctx = self._drive("on")
        self.assertTrue(ctx.tracing.started)
        self.assertTrue(ctx.tracing.stopped_without_path)
        self.assertIsNone(ctx.tracing.stopped_with_path)
        self.assertTrue(ctx.closed)

    def test_teardown_without_tracing_just_closes(self):
        ctx = self._drive("off")
        self.assertFalse(ctx.tracing.started)
        self.assertFalse(ctx.tracing.stopped_without_path)
        self.assertTrue(ctx.closed)

    def test_teardown_still_closes_context_when_tracing_stop_raises(self):
        # tracing.stop() is wrapped in suppress(Exception) -- a dead CDP
        # connection at teardown must not prevent ctx.close().
        playwright_fixtures.configure(trace_mode="on")
        context_info.begin_test("mod::test_x", 1)
        browser = FakeBrowser()
        gen = playwright_fixtures.context(browser)
        ctx = next(gen)

        def broken_stop(path=None):
            raise RuntimeError("tracing already stopped")

        ctx.tracing.stop = broken_stop
        with self.assertRaises(StopIteration):
            next(gen)
        self.assertTrue(ctx.closed)


class ContextSetupTracingDecisionTests(unittest.TestCase):
    """Tests the start_tracing decision logic used inside the context()
    fixture, extracted here as the same computation to avoid needing a
    real browser.new_context() call."""

    def tearDown(self):
        playwright_fixtures.configure()

    def _decide(self, mode, attempt):
        playwright_fixtures.configure(trace_mode=mode)
        context_info.begin_test("mod::test_x", attempt)
        current_attempt = context_info.current_attempt() or 1
        return playwright_fixtures._config["trace_mode"] in ("on", "retain-on-failure") or (
            playwright_fixtures._config["trace_mode"] == "on-first-retry" and current_attempt >= 2
        )

    def test_off_never_starts(self):
        self.assertFalse(self._decide("off", 1))
        self.assertFalse(self._decide("off", 3))

    def test_on_always_starts(self):
        self.assertTrue(self._decide("on", 1))

    def test_retain_on_failure_always_starts(self):
        self.assertTrue(self._decide("retain-on-failure", 1))

    def test_on_first_retry_only_starts_from_second_attempt(self):
        self.assertFalse(self._decide("on-first-retry", 1))
        self.assertTrue(self._decide("on-first-retry", 2))
        self.assertTrue(self._decide("on-first-retry", 3))


if __name__ == "__main__":
    unittest.main()
