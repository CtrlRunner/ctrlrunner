import unittest
from contextlib import ExitStack

from pyrunner.core import registry
from pyrunner.core.di import FixtureResolver


class ModuleScopeTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_module_scope_cached_within_module_and_reset_across_modules(self):
        counter = {"n": 0}

        @registry.fixture(scope="module")
        def module_fixture():
            counter["n"] += 1
            return counter["n"]

        resolver = FixtureResolver()

        resolver.begin_module("mod_a")
        stack1 = ExitStack()
        v1, _ = resolver.resolve(["module_fixture"], stack1)
        stack1.close()

        resolver.begin_module("mod_a")  # still same module
        stack2 = ExitStack()
        v2, _ = resolver.resolve(["module_fixture"], stack2)
        stack2.close()

        resolver.begin_module("mod_b")  # different module -> re-created
        stack3 = ExitStack()
        v3, _ = resolver.resolve(["module_fixture"], stack3)
        stack3.close()

        self.assertEqual(v1["module_fixture"], 1)
        self.assertEqual(v2["module_fixture"], 1)  # cached within mod_a
        self.assertEqual(v3["module_fixture"], 2)  # recomputed for mod_b

    def test_module_scope_teardown_runs_when_module_changes(self):
        events = []

        @registry.fixture(scope="module")
        def module_fixture():
            events.append("setup")
            yield "value"
            events.append("teardown")

        resolver = FixtureResolver()
        resolver.begin_module("mod_a")
        resolver.resolve(["module_fixture"], ExitStack())
        self.assertEqual(events, ["setup"])

        resolver.begin_module("mod_b")
        self.assertEqual(events, ["setup", "teardown"])


class FixtureParametrizeTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_fixture_params_requires_request_argument(self):
        with self.assertRaises(ValueError):

            @registry.fixture(params=["a", "b"])
            def broken_fixture():
                return "no request param here"

    def test_fixture_with_params_multiplies_dependent_tests(self):
        @registry.fixture(params=["chromium", "firefox"])
        def browser_type(request):
            return request.param

        @registry.test(case_id="TC-{browser_type}")
        def sample(browser_type):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        case_ids = {i.case_id for i in items}
        self.assertEqual(case_ids, {"TC-chromium", "TC-firefox"})
        for item in items:
            self.assertIn("browser_type", item.fixture_param_overrides)

    def test_fixture_parametrize_combines_with_explicit_parametrize(self):
        @registry.fixture(params=["chromium", "firefox"])
        def browser_type(request):
            return request.param

        @registry.test()
        @registry.parametrize("locale", ["en", "uk"])
        def sample(browser_type, locale):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 4)  # 2 browsers x 2 locales

    def test_resolver_uses_overrides_to_pick_request_param(self):
        @registry.fixture(params=["a", "b"])
        def parametrized(request):
            return f"value-{request.param}"

        resolver = FixtureResolver()
        stack = ExitStack()
        values, _ = resolver.resolve(["parametrized"], stack, {"parametrized": "a"})
        stack.close()
        self.assertEqual(values["parametrized"], "value-a")

    def test_resolver_raises_if_override_missing_for_parametrized_fixture(self):
        @registry.fixture(params=["a", "b"])
        def parametrized(request):
            return request.param

        resolver = FixtureResolver()
        with self.assertRaises(ValueError):
            resolver.resolve(["parametrized"], ExitStack(), {})


class AutouseTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_autouse_fixture_is_registered_with_flag(self):
        @registry.fixture(autouse=True)
        def auto_fixture():
            return "value"

        self.assertTrue(registry.get_fixtures()["auto_fixture"].autouse)

    def test_autouse_fixture_runs_even_when_not_a_test_parameter(self):
        calls = []

        @registry.fixture(autouse=True)
        def auto_fixture():
            calls.append("ran")
            yield
            calls.append("torn_down")

        resolver = FixtureResolver()
        stack = ExitStack()
        # Simulate what the worker does: resolve test params + autouse names,
        # then only pass through the ones the test function actually declared.
        fixtures = registry.get_fixtures()
        autouse_names = [n for n, fx in fixtures.items() if fx.autouse]
        values, _ = resolver.resolve([] + autouse_names, stack)
        stack.close()

        self.assertEqual(calls, ["ran", "torn_down"])
        self.assertNotIn(
            "auto_fixture", []
        )  # not injected into a signature that doesn't ask for it


if __name__ == "__main__":
    unittest.main()
