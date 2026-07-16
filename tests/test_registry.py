import unittest

from ctrlrunner.core import registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_plain_test_registration(self):
        @registry.test(timeout=5, tags={"smoke"}, case_id="TC-1")
        def sample(page):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertTrue(item.id.endswith("::sample"))
        self.assertEqual(item.timeout, 5)
        self.assertEqual(item.tags, {"smoke"})
        self.assertEqual(item.case_id, "TC-1")
        self.assertEqual(item.params, ["page"])
        # retries wasn't given -> stays the "unset" sentinel, resolved to
        # 0 downstream by the worker, not baked in at registration time
        self.assertIsNone(item.retries)

    def test_unset_timeout_and_retries_stay_none_sentinel(self):
        @registry.test()
        def sample():
            pass

        item = registry.get_tests()[0]
        self.assertIsNone(item.timeout)
        self.assertIsNone(item.retries)

    def test_source_path_is_populated_from_the_defining_file(self):
        @registry.test()
        def sample():
            pass

        item = registry.get_tests()[0]
        self.assertIsNotNone(item.source_path)
        self.assertEqual(item.source_path.name, "test_registry.py")

    def test_source_path_survives_parametrize_partial_binding(self):
        @registry.test()
        @registry.parametrize("locale", ["en-US"])
        def sample(locale):
            pass

        item = registry.get_tests()[0]
        # the bound func is a functools.partial (no __code__ of its own);
        # source_path must come from the original function, not the partial
        self.assertEqual(item.source_path.name, "test_registry.py")

    def test_fixture_registration_supports_generator_and_plain(self):
        @registry.fixture(scope="session")
        def plain_fixture():
            return 42

        @registry.fixture(scope="function")
        def gen_fixture():
            yield 1

        fixtures = registry.get_fixtures()
        self.assertEqual(fixtures["plain_fixture"].scope, "session")
        self.assertEqual(fixtures["gen_fixture"].scope, "function")

    def test_always_capture_flag_defaults_false_and_can_be_set(self):
        @registry.fixture(on_failure=lambda v, p: None)
        def default_fixture():
            pass

        @registry.fixture(on_failure=lambda v, p: None, always_capture=True)
        def always_fixture():
            pass

        fixtures = registry.get_fixtures()
        self.assertFalse(fixtures["default_fixture"].always_capture)
        self.assertTrue(fixtures["always_fixture"].always_capture)

    def test_parametrize_expands_into_multiple_items_with_dynamic_case_id(self):
        @registry.test(case_id="TC-100-{locale}", tags={"i18n"})
        @registry.parametrize("locale", ["en-US", "uk-UA"])
        def sample(locale, page):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        case_ids = {i.case_id for i in items}
        self.assertEqual(case_ids, {"TC-100-en-US", "TC-100-uk-UA"})
        # the parametrized arg must be bound and removed from remaining params
        for item in items:
            self.assertNotIn("locale", item.params)
            self.assertIn("page", item.params)

    def test_parametrize_cartesian_product_when_stacked(self):
        @registry.test()
        @registry.parametrize("b", [1, 2])
        @registry.parametrize("a", ["x", "y"])
        def sample(a, b):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 4)

    def test_double_test_decorator_application_raises(self):
        # Applying @test twice to the same function should be
        # caught the same way @parametrize already catches a bad
        # decorator order, via the shared _ctrlrunner_registered guard.
        def sample():
            pass

        decorated = registry.test()(sample)
        with self.assertRaises(TypeError):
            registry.test()(decorated)

    def test_wrong_decorator_order_raises_clear_error(self):
        with self.assertRaises((TypeError, ValueError)):

            @registry.parametrize("locale", ["en-US"])
            @registry.test(case_id="TC-100-{locale}")
            def sample(locale):
                pass

    def test_template_case_id_without_parametrize_raises(self):
        with self.assertRaises(ValueError):

            @registry.test(case_id="TC-{missing}")
            def sample():
                pass

    def test_duplicate_test_id_from_two_undecorated_classes_raises(self):
        # @test methods with the same name in two different
        # UNDECORATED classes in one module both register as
        # 'module::method_name' -- must raise loudly instead of the
        # second silently clobbering the first (which would run the
        # second test's body twice under one id, and drop the first
        # test entirely from selection/history).
        class _:
            @registry.test()
            def test_a(self):
                pass

        with self.assertRaises(ValueError):

            class _:
                @registry.test()
                def test_a(self):
                    pass

    def test_duplicate_parametrize_suffix_collision_raises(self):
        # "-".join(str(v) for v in values) collapses
        # ("a-b", "c") and ("a", "b-c") to the same "[a-b-c]" suffix.
        with self.assertRaises(ValueError):

            @registry.test()
            @registry.parametrize("x,y", [("a-b", "c"), ("a", "b-c")])
            def sample(x, y):
                pass

    def test_parametrize_id_suffix_stable_for_object_without_custom_repr(self):
        # A plain object() has no custom __str__/__repr__, so
        # str(value) would embed Python's default
        # "<...object at 0x...>" repr -- different every process start.
        # The id suffix must instead use a stable, deterministic label.
        class Plain:
            pass

        a, b = Plain(), Plain()

        @registry.test()
        @registry.parametrize("thing", [a, b])
        def sample(thing):
            pass

        ids = sorted(i.id for i in registry.get_tests())
        self.assertEqual(len(ids), 2)
        for test_id in ids:
            self.assertNotIn("0x", test_id)
            self.assertIn("Plain", test_id)

        # re-registering identical parametrize values in a fresh
        # process-equivalent run (here: same run, but the point is the
        # id string itself, not object identity) must produce the exact
        # same suffixes -- i.e. deterministic given position, not
        # dependent on memory addresses.
        self.assertTrue(any(i.endswith("[Plain0]") for i in ids))
        self.assertTrue(any(i.endswith("[Plain1]") for i in ids))

    def test_retries_default_and_explicit(self):
        @registry.test()
        def default_retries():
            pass

        @registry.test(retries=3)
        def custom_retries():
            pass

        items = {i.func.__name__: i for i in registry.get_tests()}
        self.assertIsNone(items["default_retries"].retries)
        self.assertEqual(items["custom_retries"].retries, 3)


class TestClassTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_class_tags_and_method_tags_are_unioned(self):
        @registry.test_class(tags={"smoke"})
        class Suite:
            @registry.test(tags={"regression"})
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.tags, {"smoke", "regression"})

    def test_class_properties_merge_method_wins_on_conflict(self):
        @registry.test_class(properties={"owner": "team_a", "priority": "p2"})
        class Suite:
            @registry.test(properties={"owner": "team_b"})
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.properties, {"owner": "team_b", "priority": "p2"})

    def test_method_timeout_wins_over_class_timeout(self):
        @registry.test_class(timeout=30)
        class Suite:
            @registry.test(timeout=60)
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.timeout, 60)

    def test_class_timeout_used_when_method_does_not_set_it(self):
        @registry.test_class(timeout=30)
        class Suite:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.timeout, 30)

    def test_neither_method_nor_class_timeout_stays_none(self):
        @registry.test_class()
        class Suite:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertIsNone(item.timeout)  # resolved downstream, same as a plain top-level test

    def test_method_retries_wins_over_class_retries(self):
        @registry.test_class(retries=1)
        class Suite:
            @registry.test(retries=5)
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.retries, 5)

    def test_class_retries_used_when_method_does_not_set_it(self):
        @registry.test_class(retries=2)
        class Suite:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.retries, 2)

    def test_id_is_rewritten_to_include_class_name(self):
        @registry.test_class()
        class LoginTests:
            @registry.test()
            def test_valid_login(self):
                pass

        item = registry.get_tests()[0]
        self.assertTrue(item.id.endswith("::LoginTests.test_valid_login"))
        self.assertEqual(item.class_name, "LoginTests")

    def test_two_classes_same_method_name_no_longer_collide(self):
        # the exact latent bug this feature's design surfaced and fixes
        # as a side effect: two @test_class-wrapped classes in the same
        # module with an identically-named method must not collide.
        @registry.test_class()
        class SuiteA:
            @registry.test()
            def test_a(self):
                pass

        @registry.test_class()
        class SuiteB:
            @registry.test()
            def test_a(self):
                pass

        ids = {i.id for i in registry.get_tests()}
        self.assertEqual(len(ids), 2)
        self.assertTrue(any(i.endswith("SuiteA.test_a") for i in ids))
        self.assertTrue(any(i.endswith("SuiteB.test_a") for i in ids))

    def test_applies_to_every_test_method_in_the_class(self):
        @registry.test_class(tags={"smoke"})
        class Suite:
            @registry.test()
            def test_a(self):
                pass

            @registry.test()
            def test_b(self):
                pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.tags == {"smoke"} for i in items))

    def test_applies_to_every_parametrized_variant(self):
        @registry.test_class(tags={"smoke"})
        class Suite:
            @registry.test()
            @registry.parametrize("locale", ["en-US", "uk-UA"])
            def test_a(self, locale):
                pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.tags == {"smoke"} for i in items))
        self.assertTrue(all(i.class_name == "Suite" for i in items))

    def test_staticmethod_test_inside_test_class_raises(self):
        # A @test-decorated @staticmethod silently escaped the
        # class merge with no error before this fix (getattr on the
        # staticmethod object doesn't see _ctrlrunner_items, which lives
        # on the wrapped function) -- must now raise loudly instead.
        with self.assertRaises(TypeError):

            @registry.test_class(tags={"smoke"})
            class Suite:
                @staticmethod
                @registry.test()
                def test_a():
                    pass

    def test_class_with_no_test_methods_raises(self):
        with self.assertRaises(ValueError):

            @registry.test_class(tags={"smoke"})
            class EmptySuite:
                def helper(self):
                    pass

    def test_applying_test_class_twice_raises(self):
        with self.assertRaises(TypeError):

            @registry.test_class()
            @registry.test_class()
            class Suite:
                @registry.test()
                def test_a(self):
                    pass

    def test_untouched_top_level_tests_are_unaffected(self):
        # a plain function-level test in a module that also happens to
        # use @test_class elsewhere must keep today's exact id format
        @registry.test()
        def top_level_test():
            pass

        item = registry.get_tests()[0]
        self.assertTrue(item.id.endswith("::top_level_test"))
        self.assertIsNone(item.class_name)

    def test_self_is_bound_to_none_not_a_real_instance(self):
        @registry.test_class()
        class Suite:
            @registry.test()
            def test_a(self):
                assert self is None

        item = registry.get_tests()[0]
        item.func()  # must not raise

    def test_self_does_not_leak_into_fixture_resolution_params(self):
        @registry.test_class()
        class Suite:
            @registry.test()
            def test_a(self, page):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.params, ["page"])
        self.assertNotIn("self", item.params)

    def test_using_self_for_state_raises_attribute_error(self):
        # the enforcement mechanism, not just documentation: attempting
        # to use self as instance state fails loudly rather than
        # silently "working" on a per-test-fresh instance.
        @registry.test_class()
        class Suite:
            @registry.test()
            def test_a(self):
                self.counter = 1  # noqa -- deliberately misusing self

        item = registry.get_tests()[0]
        with self.assertRaises(AttributeError):
            item.func()

    def test_methods_without_self_also_work(self):
        # not every method needs 'self' -- only stripped/bound when the
        # literal first parameter is named 'self'.
        @registry.test_class(tags={"smoke"})
        class Suite:
            @registry.test()
            def test_a(page):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.params, ["page"])

    def test_nested_class_inside_test_class_body_raises(self):
        with self.assertRaises(TypeError):

            @registry.test_class()
            class Outer:
                @registry.test()
                def test_a(self):
                    pass

                class Inner:
                    @registry.test()
                    def test_b(self):
                        pass

    def test_applying_test_class_to_a_subclass_raises(self):
        # The subclass case the docstring already claims is
        # covered (via getattr's MRO walk) had no dedicated test.
        @registry.test_class()
        class Base:
            @registry.test()
            def test_a(self):
                pass

        with self.assertRaises(TypeError):

            @registry.test_class()
            class Sub(Base):
                pass


class TestClassWorkersTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_workers_stamped_on_every_item_with_default_cap_mode(self):
        @registry.test_class(workers=2)
        class Grouped:
            @registry.test()
            def test_a(self):
                pass

            @registry.test()
            def test_b(self):
                pass

        for item in registry.get_tests():
            self.assertEqual(item.workers, 2)
            self.assertEqual(item.workers_mode, "cap")

    def test_explicit_dedicated_mode_is_stamped(self):
        @registry.test_class(workers=3, workers_mode="dedicated")
        class Grouped:
            @registry.test()
            def test_a(self):
                pass

        self.assertEqual(registry.get_tests()[0].workers_mode, "dedicated")

    def test_plain_test_class_leaves_workers_fields_none(self):
        @registry.test_class()
        class Plain:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertIsNone(item.workers)
        self.assertIsNone(item.workers_mode)

    def test_workers_zero_raises(self):
        with self.assertRaises(ValueError):

            @registry.test_class(workers=0)
            class Bad:
                @registry.test()
                def test_a(self):
                    pass

    def test_workers_bool_raises(self):
        with self.assertRaises(ValueError):

            @registry.test_class(workers=True)
            class Bad:
                @registry.test()
                def test_a(self):
                    pass

    def test_workers_mode_without_workers_raises(self):
        with self.assertRaises(ValueError):

            @registry.test_class(workers_mode="dedicated")
            class Bad:
                @registry.test()
                def test_a(self):
                    pass

    def test_unknown_workers_mode_raises(self):
        with self.assertRaises(ValueError):

            @registry.test_class(workers=2, workers_mode="exclusive")
            class Bad:
                @registry.test()
                def test_a(self):
                    pass


class TestClassSerialTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_serial_stamps_module_qualified_group_on_every_item(self):
        @registry.test_class(serial=True)
        class Flow:
            @registry.test()
            def test_a(self):
                pass

            @registry.test()
            def test_b(self):
                pass

        items = registry.get_tests()
        module = items[0].id.split("::")[0]
        for item in items:
            self.assertEqual(item.serial_group, f"{module}::Flow")
            self.assertEqual(item.serial_retries, 0)

    def test_serial_retries_come_from_the_class_and_items_keep_retries_none(self):
        # group retries must NOT flow into item.retries -- the worker's
        # per-test retry loop stays single-attempt for serial members;
        # the group loop owns all retrying.
        @registry.test_class(serial=True, retries=2)
        class Flow:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertEqual(item.serial_retries, 2)
        self.assertIsNone(item.retries)

    def test_serial_stamps_parametrized_variants_too(self):
        @registry.test_class(serial=True)
        class Flow:
            @registry.test()
            @registry.parametrize("locale", ["en", "de"])
            def test_a(self, locale):
                pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertIsNotNone(item.serial_group)

    def test_method_retries_inside_serial_class_raises(self):
        with self.assertRaises(ValueError) as ctx:

            @registry.test_class(serial=True)
            class Bad:
                @registry.test(retries=1)
                def test_a(self):
                    pass

        self.assertIn("serial", str(ctx.exception))

    def test_serial_and_fully_parallel_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):

            @registry.test_class(serial=True, fully_parallel=True)
            class Bad:
                @registry.test()
                def test_a(self):
                    pass

    def test_non_serial_class_leaves_serial_fields_at_defaults(self):
        @registry.test_class()
        class Plain:
            @registry.test()
            def test_a(self):
                pass

        item = registry.get_tests()[0]
        self.assertIsNone(item.serial_group)
        self.assertEqual(item.serial_retries, 0)


class TestClassFullyParallelTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_fully_parallel_true_is_stamped(self):
        @registry.test_class(fully_parallel=True)
        class Par:
            @registry.test()
            def test_a(self):
                pass

        self.assertTrue(registry.get_tests()[0].fully_parallel)

    def test_fully_parallel_false_is_stamped_distinct_from_unset(self):
        # tri-state: an explicit False must survive so a class can opt
        # OUT of a fully-parallel project; unset stays None (inherit).
        @registry.test_class(fully_parallel=False)
        class Grouped:
            @registry.test()
            def test_a(self):
                pass

        self.assertIs(registry.get_tests()[0].fully_parallel, False)

    def test_unset_fully_parallel_stays_none(self):
        @registry.test_class()
        class Plain:
            @registry.test()
            def test_a(self):
                pass

        self.assertIsNone(registry.get_tests()[0].fully_parallel)


class ParamHelperTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_plain_tuples_and_scalars_still_work_unchanged(self):
        @registry.test()
        @registry.parametrize("a, b", [(1, 2), (3, 4)])
        def sample(a, b):
            pass

        @registry.test()
        @registry.parametrize("x", [1, 2])
        def scalar(x):
            pass

        ids = [i.id for i in registry.get_tests()]
        self.assertTrue(any(i.endswith("::sample[1-2]") for i in ids))
        self.assertTrue(any(i.endswith("::sample[3-4]") for i in ids))
        self.assertTrue(any(i.endswith("::scalar[1]") for i in ids))

    def test_param_custom_id_becomes_the_suffix(self):
        @registry.test()
        @registry.parametrize("a, b", [registry.param(1, 2, id="us_entity"), (3, 4)])
        def sample(a, b):
            pass

        ids = sorted(i.id for i in registry.get_tests())
        self.assertTrue(any(i.endswith("::sample[us_entity]") for i in ids))
        self.assertTrue(any(i.endswith("::sample[3-4]") for i in ids))

    def test_param_case_id_sets_test_item_case_id(self):
        @registry.test()
        @registry.parametrize("x", [registry.param(1, case_id="7184475"), 2])
        def sample(x):
            pass

        by_suffix = {i.id.split("[")[-1]: i for i in registry.get_tests()}
        self.assertEqual(by_suffix["1]"].case_id, "7184475")
        self.assertIsNone(by_suffix["2]"].case_id)

    def test_param_case_id_overrides_decorator_template(self):
        @registry.test(case_id="TC-{x}")
        @registry.parametrize("x", [registry.param(1, case_id="7184475"), 2])
        def sample(x):
            pass

        case_ids = {i.case_id for i in registry.get_tests()}
        self.assertEqual(case_ids, {"7184475", "TC-2"})

    def test_param_case_id_supports_templates_too(self):
        @registry.test()
        @registry.parametrize("x", [registry.param(1, case_id="TC-{x}")])
        def sample(x):
            pass

        self.assertEqual(registry.get_tests()[0].case_id, "TC-1")

    def test_param_tags_union_with_decorator_tags(self):
        @registry.test(tags={"smoke"})
        @registry.parametrize("x", [registry.param(1, tags={"slow_combo"}), 2])
        def sample(x):
            pass

        by_suffix = {i.id.split("[")[-1]: i for i in registry.get_tests()}
        self.assertEqual(by_suffix["1]"].tags, {"smoke", "slow_combo"})
        self.assertEqual(by_suffix["2]"].tags, {"smoke"})

    def test_param_xfail_and_skip_populate_test_item_fields(self):
        @registry.test()
        @registry.parametrize(
            "x",
            [
                registry.param(1, xfail="[Bug 7438797] widget absent", xfail_strict=True),
                registry.param(2, xfail=True, xfail_strict=False),
                registry.param(3, skip="not in this env"),
                registry.param(4, skip=True),
                5,
            ],
        )
        def sample(x):
            pass

        by_suffix = {i.id.split("[")[-1]: i for i in registry.get_tests()}
        self.assertEqual(
            by_suffix["1]"].expected_failure,
            {"description": "[Bug 7438797] widget absent", "strict": True},
        )
        self.assertEqual(by_suffix["2]"].expected_failure, {"description": None, "strict": False})
        self.assertIsNone(by_suffix["2]"].skip_marker)
        self.assertEqual(by_suffix["3]"].skip_marker, {"description": "not in this env"})
        self.assertEqual(by_suffix["4]"].skip_marker, {"description": None})
        self.assertIsNone(by_suffix["5]"].expected_failure)
        self.assertIsNone(by_suffix["5]"].skip_marker)

    def test_mixed_param_and_plain_values_bind_correctly(self):
        @registry.test()
        @registry.parametrize("x", [registry.param(1, id="one"), (2,), 3])
        def sample(x):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 3)
        self.assertEqual({i.param_values["x"] for i in items}, {1, 2, 3})

    def test_stacked_parametrize_with_case_id_on_both_levels_raises(self):
        with self.assertRaises(ValueError):

            @registry.test()
            @registry.parametrize("b", [registry.param(1, case_id="B-1")])
            @registry.parametrize("a", [registry.param("x", case_id="A-1")])
            def sample(a, b):
                pass

    def test_stacked_parametrize_merges_ids_and_metadata(self):
        @registry.test()
        @registry.parametrize("b", [registry.param(1, id="one", tags={"t2"})])
        @registry.parametrize("a", [registry.param("x", id="ex", tags={"t1"}, xfail="bug")])
        def sample(a, b):
            pass

        item = registry.get_tests()[0]
        self.assertTrue(item.id.endswith("::sample[ex-one]"))
        self.assertEqual(item.tags, {"t1", "t2"})
        self.assertEqual(item.expected_failure, {"description": "bug", "strict": True})

    def test_stacked_parametrize_derives_missing_id_part_from_values(self):
        @registry.test()
        @registry.parametrize("b", [registry.param(1, id="one")])
        @registry.parametrize("a", ["x"])
        def sample(a, b):
            pass

        item = registry.get_tests()[0]
        self.assertTrue(item.id.endswith("::sample[x-one]"))

    def test_duplicate_explicit_param_ids_raise(self):
        with self.assertRaises(ValueError):

            @registry.test()
            @registry.parametrize("x", [registry.param(1, id="same"), registry.param(2, id="same")])
            def sample(x):
                pass

    def test_param_case_id_is_selectable(self):
        from ctrlrunner.core.selection import select_tests

        @registry.test()
        @registry.parametrize("x", [registry.param(1, case_id="7184475"), 2])
        def sample(x):
            pass

        selected = select_tests(registry.get_tests(), case_ids=["7184475"])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].param_values["x"], 1)

    def test_param_id_combined_with_fixture_parametrization(self):
        @registry.fixture(params=["chromium", "firefox"])
        def browser_type(request):
            return request.param

        @registry.test()
        @registry.parametrize("x", [registry.param(1, id="one")])
        def sample(x, browser_type):
            pass

        suffixes = sorted(i.id.split("[")[-1].rstrip("]") for i in registry.get_tests())
        self.assertEqual(suffixes, ["one-chromium", "one-firefox"])

    def test_parametrize_accepts_tuple_argnames(self):
        @registry.test()
        @registry.parametrize(("a", "b"), [(1, 2), registry.param(3, 4, id="pair")])
        def sample(a, b):
            pass

        items = registry.get_tests()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].param_values, {"a": 1, "b": 2})
        self.assertTrue(items[1].id.endswith("[pair]"))

    def test_param_is_exported_from_package_root(self):
        import ctrlrunner

        self.assertIs(ctrlrunner.param, registry.param)


if __name__ == "__main__":
    unittest.main()
