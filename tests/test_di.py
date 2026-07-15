import unittest
from contextlib import ExitStack

from pyrunner.core import registry
from pyrunner.core import steps as steps_module
from pyrunner.core.di import FixtureResolver


class DiTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_resolves_plain_and_generator_fixtures(self):
        @registry.fixture(scope="function")
        def a():
            return "value-a"

        @registry.fixture(scope="function")
        def b(a):
            yield f"{a}-b"

        resolver = FixtureResolver()
        stack = ExitStack()
        values, resolved_all = resolver.resolve(["b"], stack)
        stack.close()

        self.assertEqual(values["b"], "value-a-b")
        # transitive dependency 'a' must also be tracked for on_failure lookups
        self.assertIn("a", resolved_all)
        self.assertIn("b", resolved_all)

    def test_session_scope_is_cached_across_resolve_calls(self):
        counter = {"n": 0}

        @registry.fixture(scope="session")
        def session_fixture():
            counter["n"] += 1
            return counter["n"]

        resolver = FixtureResolver()
        stack1 = ExitStack()
        values1, _ = resolver.resolve(["session_fixture"], stack1)
        stack1.close()

        stack2 = ExitStack()
        values2, _ = resolver.resolve(["session_fixture"], stack2)
        stack2.close()

        self.assertEqual(values1["session_fixture"], 1)
        self.assertEqual(values2["session_fixture"], 1)  # not recomputed
        self.assertEqual(counter["n"], 1)

    def test_function_scope_is_not_cached_across_resolve_calls(self):
        counter = {"n": 0}

        @registry.fixture(scope="function")
        def function_fixture():
            counter["n"] += 1
            return counter["n"]

        resolver = FixtureResolver()
        stack1 = ExitStack()
        values1, _ = resolver.resolve(["function_fixture"], stack1)
        stack1.close()

        stack2 = ExitStack()
        values2, _ = resolver.resolve(["function_fixture"], stack2)
        stack2.close()

        self.assertEqual(values1["function_fixture"], 1)
        self.assertEqual(values2["function_fixture"], 2)

    def test_generator_teardown_runs_on_stack_close(self):
        events = []

        @registry.fixture(scope="function")
        def with_teardown():
            events.append("setup")
            yield "value"
            events.append("teardown")

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["with_teardown"], stack)
        self.assertEqual(events, ["setup"])
        stack.close()
        self.assertEqual(events, ["setup", "teardown"])

    def test_diamond_dependency_shares_one_instance_per_call(self):
        # def test_x(page, context) where page itself depends on
        # context must resolve 'context' exactly once and inject the
        # SAME instance both directly and via 'page' -- not build it
        # twice (double setup/teardown cost, and worse, a different
        # instance silently threaded through, e.g. wrong context used
        # for failure-trace capture).
        build_count = {"context": 0}

        @registry.fixture(scope="function")
        def context():
            build_count["context"] += 1
            return object()

        @registry.fixture(scope="function")
        def page(context):
            return context

        resolver = FixtureResolver()
        stack = ExitStack()
        values, resolved_all = resolver.resolve(["page", "context"], stack)
        stack.close()

        self.assertEqual(build_count["context"], 1)
        self.assertIs(values["page"], values["context"])
        self.assertIs(resolved_all["page"], resolved_all["context"])

    def test_import_order_sensitive_parametrized_fixture_gives_actionable_error(self):
        # Simulates a test registered (via @test) BEFORE the
        # parametrized fixture it depends on was defined -- so
        # @test's fixture_param_map collection never saw it, no
        # fixture_param_overrides entry was recorded, and resolve()
        # later hits the parametrized fixture with no chosen value.
        # The resulting error must name the fixture and blame import
        # order, not "this should not happen" DI internals.
        @registry.fixture(scope="function", params=["chromium", "firefox"])
        def browser(request):
            return request.param

        resolver = FixtureResolver()
        stack = ExitStack()
        with self.assertRaises(ValueError) as ctx:
            # no fixture_param_overrides passed -- mirrors what @test
            # would have produced had it registered before 'browser'
            # existed
            resolver.resolve(["browser"], stack)
        stack.close()

        message = str(ctx.exception)
        self.assertIn("browser", message)
        self.assertIn("import order", message)

    def test_unknown_fixture_raises(self):
        resolver = FixtureResolver()
        stack = ExitStack()
        with self.assertRaises(ValueError):
            resolver.resolve(["nope"], stack)


class FixtureProfilingStepTests(unittest.TestCase):
    """Fixture setup/teardown timing rides the existing step tree."""

    def setUp(self):
        registry.reset()
        steps_module.begin_test()

    def test_plain_fixture_records_a_setup_step(self):
        @registry.fixture(scope="function")
        def resource():
            return "value"

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["resource"], stack)
        stack.close()

        recorded = steps_module.collect_steps()
        names = [s.name for s in recorded]
        self.assertIn("fixture:resource:setup", names)

    def test_generator_fixture_records_setup_and_teardown_steps(self):
        @registry.fixture(scope="function")
        def resource():
            yield "value"

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["resource"], stack)
        stack.close()  # triggers teardown

        names = [s.name for s in steps_module.collect_steps()]
        self.assertIn("fixture:resource:setup", names)
        self.assertIn("fixture:resource:teardown", names)

    def test_normal_generator_exhaustion_is_not_recorded_as_a_failed_step(self):
        # the critical edge case: StopIteration is how a generator
        # fixture signals "teardown complete," not an error -- it must
        # never surface as a failed step just because it's technically
        # an Exception subclass.
        @registry.fixture(scope="function")
        def resource():
            yield "value"
            # falls off the end -> StopIteration on the next next() call

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["resource"], stack)
        stack.close()

        recorded = steps_module.collect_steps()
        teardown_step = next(s for s in recorded if s.name == "fixture:resource:teardown")
        self.assertEqual(teardown_step.outcome, "passed")
        self.assertIsNone(teardown_step.error)

    def test_genuine_teardown_error_is_recorded_but_swallowed(self):
        @registry.fixture(scope="function")
        def resource():
            yield "value"
            raise RuntimeError("teardown exploded")

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["resource"], stack)
        stack.close()  # must not raise -- teardown errors never mask the test result

        recorded = steps_module.collect_steps()
        teardown_step = next(s for s in recorded if s.name == "fixture:resource:teardown")
        self.assertEqual(teardown_step.outcome, "failed")
        self.assertIn("teardown exploded", teardown_step.error)

    def test_setup_and_teardown_steps_appear_for_multiple_fixtures_by_name(self):
        @registry.fixture(scope="function")
        def a():
            yield "a"

        @registry.fixture(scope="function")
        def b(a):
            yield f"{a}-b"

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["b"], stack)
        stack.close()

        names = [s.name for s in steps_module.collect_steps()]
        self.assertIn("fixture:a:setup", names)
        self.assertIn("fixture:a:teardown", names)
        self.assertIn("fixture:b:setup", names)
        self.assertIn("fixture:b:teardown", names)

    def test_session_scoped_fixture_setup_only_recorded_once(self):
        @registry.fixture(scope="session")
        def resource():
            return "value"

        resolver = FixtureResolver()
        stack1 = ExitStack()
        resolver.resolve(["resource"], stack1)
        stack1.close()
        steps_module.begin_test()  # simulates the next test's reset

        stack2 = ExitStack()
        resolver.resolve(["resource"], stack2)  # cached, no setup step this time
        stack2.close()

        names = [s.name for s in steps_module.collect_steps()]
        self.assertNotIn("fixture:resource:setup", names)


class TeardownErrorCollectionTests(unittest.TestCase):
    """Teardown exceptions must not vanish -- the resolver
    records them so the worker can surface them on the owning test's
    result (stack.close() itself still never raises)."""

    def setUp(self):
        registry.reset()
        steps_module.begin_test()

    def test_failing_teardown_recorded_and_drained(self):
        @registry.fixture(scope="function")
        def broken():
            yield "value"
            raise RuntimeError("teardown boom")

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["broken"], stack)
        stack.close()

        errors = resolver.drain_teardown_errors()
        self.assertEqual(len(errors), 1)
        name, tb = errors[0]
        self.assertEqual(name, "broken")
        self.assertIn("RuntimeError: teardown boom", tb)
        # drained means drained
        self.assertEqual(resolver.drain_teardown_errors(), [])

    def test_clean_teardown_records_nothing(self):
        @registry.fixture(scope="function")
        def fine():
            yield "value"

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["fine"], stack)
        stack.close()
        self.assertEqual(resolver.drain_teardown_errors(), [])

    def test_session_scope_teardown_error_drained_after_close_session(self):
        # The worker relies on close_session() (end of its batch) to
        # flush session-scoped teardown failures into teardown_errors --
        # the only drain point where a session fixture's failure can
        # surface at all.
        @registry.fixture(scope="session")
        def sess_broken():
            yield "value"
            raise RuntimeError("session teardown boom")

        resolver = FixtureResolver()
        stack = ExitStack()
        resolver.resolve(["sess_broken"], stack)
        stack.close()
        self.assertEqual(resolver.drain_teardown_errors(), [])  # not torn down yet
        resolver.close_session()
        errors = resolver.drain_teardown_errors()
        self.assertEqual([n for n, _ in errors], ["sess_broken"])
        self.assertIn("session teardown boom", errors[0][1])

    def test_setup_failure_still_tears_down_already_resolved_siblings(self):
        # If the second of two fixtures blows up during setup, the first
        # one is already live on the function stack -- its teardown must
        # still run when the worker closes the stack, or a failed setup
        # leaks the resources of every fixture resolved before it.
        events = []

        @registry.fixture(scope="function")
        def fine_first():
            events.append("setup")
            yield "value"
            events.append("teardown")

        @registry.fixture(scope="function")
        def boom_second():
            raise RuntimeError("setup boom")
            yield  # pragma: no cover

        resolver = FixtureResolver()
        stack = ExitStack()
        with self.assertRaises(RuntimeError):
            resolver.resolve(["fine_first", "boom_second"], stack)
        self.assertEqual(events, ["setup"])
        stack.close()
        self.assertEqual(events, ["setup", "teardown"])
        # a setup failure is not a *teardown* error -- nothing recorded
        self.assertEqual(resolver.drain_teardown_errors(), [])

    def test_module_scope_teardown_error_also_recorded(self):
        @registry.fixture(scope="module")
        def mod_broken():
            yield "value"
            raise ValueError("module teardown boom")

        resolver = FixtureResolver()
        resolver.begin_module("mod_a")
        stack = ExitStack()
        resolver.resolve(["mod_broken"], stack)
        stack.close()
        self.assertEqual(resolver.drain_teardown_errors(), [])  # not torn down yet
        resolver.begin_module("mod_b")  # module switch closes module stack
        errors = resolver.drain_teardown_errors()
        self.assertEqual([n for n, _ in errors], ["mod_broken"])


if __name__ == "__main__":
    unittest.main()
