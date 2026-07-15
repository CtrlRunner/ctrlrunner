import unittest

from ctrlrunner.core import steps as steps_module
from ctrlrunner.playwright.playwright_actions import AutoStepPage, auto_step


class FakeLocator:
    def __init__(self, log):
        self._log = log

    def click(self):
        self._log.append("locator.click")

    def fill(self, value):
        self._log.append(f"locator.fill:{value}")


class FakePage:
    def __init__(self):
        self.log = []
        self.title_value = "Example Domain"

    def goto(self, url):
        self.log.append(f"goto:{url}")

    def click(self, selector):
        self.log.append(f"click:{selector}")

    def fill(self, selector, value):
        self.log.append(f"fill:{selector}:{value}")

    def title(self):
        return self.title_value

    def locator(self, selector):
        return FakeLocator(self.log)


class AutoStepTests(unittest.TestCase):
    def setUp(self):
        steps_module.begin_test()

    def test_wraps_page_actions_as_steps(self):
        page = auto_step(FakePage())
        page.goto("https://example.com")
        page.click("#submit")

        recorded = steps_module.collect_steps()
        names = [s.name for s in recorded]
        self.assertEqual(
            names,
            [
                "goto('https://example.com')",
                "click('#submit')",
            ],
        )

    def test_non_action_methods_are_not_wrapped_as_steps(self):
        page = auto_step(FakePage())
        result = page.title()
        self.assertEqual(result, "Example Domain")
        self.assertEqual(steps_module.collect_steps(), [])

    def test_action_still_executes_on_the_underlying_target(self):
        fake = FakePage()
        page = auto_step(fake)
        page.fill("#user", "alice")
        self.assertEqual(fake.log, ["fill:#user:alice"])

    def test_locator_return_value_is_also_wrapped(self):
        page = auto_step(FakePage())
        locator = page.locator("#button")
        self.assertIsInstance(locator, AutoStepPage)
        locator.click()
        names = [s.name for s in steps_module.collect_steps()]
        self.assertEqual(names, ["click()"])

    def test_kwargs_are_included_in_step_label(self):
        class FakePageWithKwargs:
            def click(self, selector, timeout=None):
                pass

        page = auto_step(FakePageWithKwargs())
        page.click("#btn", timeout=5000)
        names = [s.name for s in steps_module.collect_steps()]
        self.assertEqual(names, ["click('#btn', timeout=5000)"])

    def test_wrapper_is_transparent_to_isinstance(self):
        fake = FakePage()
        page = auto_step(fake)
        self.assertIsInstance(page, FakePage)
        locator = page.locator("#button")
        self.assertIsInstance(locator, FakeLocator)

    def test_type_still_reveals_wrapper_and_double_wrap_guard_holds(self):
        page = auto_step(FakePage())
        self.assertIs(type(page), AutoStepPage)
        self.assertIsInstance(page, AutoStepPage)
        locator = page.locator("#button")
        self.assertIs(type(locator), AutoStepPage)

    def test_private_attributes_pass_through_unwrapped(self):
        class FakeImpl:
            def click(self):
                pass

            def fill(self):
                pass

        class PageWithImpl(FakePage):
            def __init__(self):
                super().__init__()
                self._impl_obj = FakeImpl()

        fake = PageWithImpl()
        page = auto_step(fake)
        self.assertIs(page._impl_obj, fake._impl_obj)

    def test_failing_action_propagates_and_marks_step_failed(self):
        class FailingPage:
            def click(self, selector):
                raise RuntimeError("element not found")

        page = auto_step(FailingPage())
        with self.assertRaises(RuntimeError):
            page.click("#missing")
        recorded = steps_module.collect_steps()
        self.assertEqual(recorded[0].outcome, "failed")


if __name__ == "__main__":
    unittest.main()
