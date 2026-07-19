import tempfile
import unittest
import warnings

from ctrlrunner.core.hookcompat import (
    CallInfo,
    CompatibilityError,
    Config,
    ExceptionInfo,
    ExitCode,
    Item,
    Marker,
    Session,
    TestReport,
    bind_hook_args,
    hookimpl,
    is_hookwrapper,
    run_makereport_hook,
    sort_hooks,
)
from ctrlrunner.core.options import set_options
from ctrlrunner.reporting.reporter import Result


class ItemTests(unittest.TestCase):
    def _item(self, **kwargs):
        defaults = dict(
            test_id="suite.test_demo::test_a",
            attempt=1,
            tags={"mac_only", "smoke"},
            properties={"owner": "sdet"},
            func=None,
        )
        defaults.update(kwargs)
        return Item(**defaults)

    def test_nodeid_and_name(self):
        item = self._item()
        self.assertEqual(item.nodeid, "suite.test_demo::test_a")
        self.assertEqual(item.name, "test_a")

    def test_get_closest_marker_returns_marker_for_a_tag(self):
        item = self._item()
        marker = item.get_closest_marker("mac_only")
        self.assertIsInstance(marker, Marker)
        self.assertEqual(marker.name, "mac_only")

    def test_get_closest_marker_returns_default_for_unknown_name(self):
        item = self._item()
        self.assertIsNone(item.get_closest_marker("windows_only"))
        sentinel = object()
        self.assertIs(item.get_closest_marker("windows_only", sentinel), sentinel)

    def test_location_from_func_code(self):
        def sample():
            pass

        item = self._item(func=sample)
        filename, lineno, name = item.location
        self.assertIn("test_hookcompat.py", filename)
        self.assertIsInstance(lineno, int)
        self.assertEqual(name, "test_a")

    def test_location_without_func(self):
        self.assertEqual(self._item().location, (None, None, "test_a"))


class TestReportTests(unittest.TestCase):
    def test_passed_outcome(self):
        r = TestReport("m::t", 1, "passed", None)
        self.assertEqual(r.outcome, "passed")
        self.assertTrue(r.passed)
        self.assertFalse(r.failed)
        self.assertFalse(r.skipped)
        self.assertEqual(r.when, "call")
        self.assertEqual(r.nodeid, "m::t")

    def test_failed_outcome_carries_longrepr(self):
        r = TestReport("m::t", 2, "failed", "AssertionError: boom")
        self.assertEqual(r.outcome, "failed")
        self.assertTrue(r.failed)
        self.assertEqual(r.longrepr, "AssertionError: boom")
        self.assertEqual(r.attempt, 2)

    def test_skipped_and_fixme_map_to_skipped(self):
        self.assertTrue(TestReport("m::t", 1, "skipped", None).skipped)
        self.assertTrue(TestReport("m::t", 1, "fixme", None).skipped)

    def test_expected_failure_maps_to_skipped_with_wasxfail(self):
        r = TestReport("m::t", 1, "expected_failure", "known broken")
        self.assertTrue(r.skipped)
        self.assertEqual(r.wasxfail, "known broken")
        self.assertEqual(r.ctrlrunner_outcome, "expected_failure")


class SessionTests(unittest.TestCase):
    def test_counts_and_fields(self):
        results = [
            Result(test_id="m::a", outcome="passed", error=None, duration=0.1),
            Result(test_id="m::b", outcome="failed", error="boom", duration=0.1),
        ]
        s = Session(results, duration=1.5, exitstatus=1)
        self.assertEqual(s.testscollected, 2)
        self.assertEqual(s.testsfailed, 1)
        self.assertEqual(s.exitstatus, 1)
        self.assertEqual(s.duration, 1.5)
        self.assertIs(s.results, results)


class ConfigTests(unittest.TestCase):
    def tearDown(self):
        set_options(None)

    def test_mapping_access_over_raw_toml_dict(self):
        c = Config({"timeout": 30, "root": "tests"})
        self.assertEqual(c["timeout"], 30)
        self.assertEqual(sorted(c.keys()), ["root", "timeout"])
        self.assertEqual(len(c), 2)
        self.assertEqual(c.get("nope", "dflt"), "dflt")

    def test_getoption_reads_the_options_store(self):
        set_options({"env": "staging"})
        c = Config({})
        self.assertEqual(c.getoption("env"), "staging")
        self.assertEqual(c.getoption("--env"), "staging")
        self.assertEqual(c.getoption("missing", "fallback"), "fallback")

    def test_getini_reads_the_raw_config(self):
        c = Config({"markers": ["slow"]})
        self.assertEqual(c.getini("markers"), ["slow"])
        self.assertIsNone(c.getini("nope"))

    def test_addinivalue_line_registers_marker_into_existing_tag_registry(self):
        raw = {"registered_tags": ["smoke"]}
        c = Config(raw)
        c.addinivalue_line("markers", "slow: marks slow tests")
        # The nested list is shared with the caller's dict (shallow copy),
        # so the registration is visible to load_tag_registry afterward.
        self.assertIn("slow", raw["registered_tags"])
        c.addinivalue_line("markers", "slow: duplicate is not re-added")
        self.assertEqual(raw["registered_tags"].count("slow"), 1)

    def test_addinivalue_line_is_a_silent_noop_without_a_tag_registry(self):
        raw = {}
        c = Config(raw)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            c.addinivalue_line("markers", "slow: marks slow tests")
        self.assertNotIn("registered_tags", raw)

    def test_cache_get_set_roundtrip_and_mkdir(self):
        import os

        cwd = os.getcwd()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            os.chdir(tmp)
            try:
                c = Config({})
                self.assertEqual(c.cache.get("demo/key", "fallback"), "fallback")
                c.cache.set("demo/key", {"failed": ["a", "b"]})
                self.assertEqual(c.cache.get("demo/key", None), {"failed": ["a", "b"]})
                d = c.cache.mkdir("mydir")
                self.assertTrue(d.is_dir())
                self.assertIn(".ctrlrunner_cache", str(d))
            finally:
                os.chdir(cwd)

    def test_pluginmanager_gives_truthful_no_plugin_answers(self):
        pm = Config({}).pluginmanager
        self.assertFalse(pm.hasplugin("xdist"))
        self.assertIsNone(pm.getplugin("xdist"))
        self.assertEqual(pm.list_name_plugin(), [])
        self.assertIsNone(pm.register(object()))  # accepted, ignored


class CompatErrorTests(unittest.TestCase):
    """Attributes the compat layer doesn't model FAIL LOUDLY: a
    CompatibilityError (an AttributeError subclass) whose message
    carries a concrete recommendation for the ctrlrunner way to achieve
    the same goal -- never a silent placeholder, never a silent no-op."""

    def _item(self):
        return Item("suite.test_demo::test_a", 1, tags={"smoke"})

    def test_curated_attribute_raises_with_specific_recommendation(self):
        item = self._item()
        with self.assertRaises(CompatibilityError) as ctx:
            _ = item.parent
        message = str(ctx.exception)
        self.assertIn("Item.parent", message)
        self.assertIn("collection tree", message)
        self.assertIn("item.module", message)  # the recommended alternative

    def test_unknown_attribute_raises_with_generic_guidance(self):
        item = self._item()
        with self.assertRaises(CompatibilityError) as ctx:
            _ = item.workflowsession_thing
        message = str(ctx.exception)
        self.assertIn("Item.workflowsession_thing", message)
        self.assertIn("docs/hooks.md", message)

    def test_compatibility_error_is_an_attribute_error(self):
        # hasattr()/getattr(default) probes in migrated bodies keep
        # working -- CompatibilityError subclasses AttributeError.
        item = self._item()
        self.assertFalse(hasattr(item, "parent"))
        self.assertIsNone(getattr(item, "listchain", None))

    def test_config_and_report_curated_attributes_raise_too(self):
        with self.assertRaises(CompatibilityError) as ctx:
            _ = Config({}).hook
        self.assertIn("Config.hook", str(ctx.exception))
        with self.assertRaises(CompatibilityError):
            _ = TestReport("m::t", 1, "passed", None).result

    def test_dunder_probes_raise_plain_attribute_error(self):
        # Pickle/copy protocol probes must not get compat errors back.
        item = self._item()
        probe = "__getstate__x__"
        with self.assertRaises(AttributeError):
            getattr(item, probe)


class ItemWideSurfaceTests(unittest.TestCase):
    def _item(self, **kwargs):
        def sample():
            pass

        defaults = dict(
            test_id="suite.test_demo::test_a[en-US]",
            attempt=1,
            tags={"smoke", "mac_only"},
            properties={"owner": "sdet"},
            func=sample,
        )
        defaults.update(kwargs)
        return Item(**defaults)

    def test_module_resolves_from_func(self):
        item = self._item()
        self.assertEqual(item.module.__name__, "tests.test_hookcompat")

    def test_cls_resolves_from_module_by_name(self):
        item = self._item(cls_name="ItemWideSurfaceTests")
        # sample() is defined in THIS module, so the lookup finds this class.
        self.assertIs(item.cls, ItemWideSurfaceTests)

    def test_cls_is_none_without_class_name(self):
        self.assertIsNone(self._item().cls)

    def test_keywords_contains_name_and_tags(self):
        item = self._item()
        self.assertTrue(item.keywords["smoke"])
        self.assertTrue(item.keywords[item.name])

    def test_iter_markers_and_own_markers(self):
        item = self._item()
        names = sorted(m.name for m in item.iter_markers())
        self.assertEqual(names, ["mac_only", "smoke"])
        self.assertEqual(sorted(m.name for m in item.own_markers), ["mac_only", "smoke"])
        self.assertEqual([m.name for m in item.iter_markers(name="smoke")], ["smoke"])

    def test_add_marker_makes_get_closest_marker_find_it(self):
        item = self._item()
        item.add_marker("added_later")
        self.assertIsNotNone(item.get_closest_marker("added_later"))
        item.add_marker(Marker("as_object"))
        self.assertIsNotNone(item.get_closest_marker("as_object"))

    def test_funcargs_defaults_empty_and_is_assignable(self):
        item = self._item()
        self.assertEqual(item.funcargs, {})
        item.funcargs = {"page": object()}
        self.assertIn("page", item.funcargs)

    def test_originalname_strips_param_suffix(self):
        self.assertEqual(self._item().originalname, "test_a")

    def test_user_properties_from_properties(self):
        self.assertIn(("owner", "sdet"), self._item().user_properties)

    def test_path_and_fspath_from_func(self):
        item = self._item()
        self.assertTrue(str(item.path).endswith("test_hookcompat.py"))
        self.assertEqual(str(item.fspath), str(item.path))

    def test_config_and_session_attach_points(self):
        cfg = Config({"timeout": 30})
        session = Session(config=cfg)
        item = self._item(config=cfg, session=session)
        self.assertEqual(item.config.getini("timeout"), 30)
        self.assertIs(item.session, session)
        self.assertIs(item.session.config, cfg)


class TestReportWideSurfaceTests(unittest.TestCase):
    def test_sections_capstdout_capstderr(self):
        r = TestReport(
            "m::t",
            1,
            "failed",
            "boom",
            sections=[
                ("Captured stdout call", "hello out"),
                ("Captured stderr call", "hello err"),
            ],
        )
        self.assertEqual(len(r.sections), 2)
        self.assertEqual(r.capstdout, "hello out")
        self.assertEqual(r.capstderr, "hello err")

    def test_sections_default_empty(self):
        r = TestReport("m::t", 1, "passed", None)
        self.assertEqual(r.sections, [])
        self.assertEqual(r.capstdout, "")
        self.assertEqual(r.capstderr, "")

    def test_longreprtext_and_head_line(self):
        r = TestReport("m::t", 1, "failed", "AssertionError: x")
        self.assertEqual(r.longreprtext, "AssertionError: x")
        self.assertEqual(TestReport("m::t", 1, "passed", None).longreprtext, "")
        self.assertEqual(r.head_line, "m::t")

    def test_duration_and_location(self):
        r = TestReport("m::t", 1, "passed", None, duration=1.25, location=("f.py", 3, "t"))
        self.assertEqual(r.duration, 1.25)
        self.assertEqual(r.location, ("f.py", 3, "t"))


class SessionAndConfigWideSurfaceTests(unittest.TestCase):
    def tearDown(self):
        set_options(None)

    def test_session_items_alias_and_config(self):
        results = [Result(test_id="m::a", outcome="passed", error=None, duration=0.1)]
        cfg = Config({"root": "tests"})
        s = Session(results, duration=1.0, exitstatus=0, config=cfg)
        self.assertIs(s.items, s.results)
        self.assertIs(s.config, cfg)

    def test_session_defaults_are_safe_for_worker_side_use(self):
        s = Session()
        self.assertEqual(s.results, [])
        self.assertEqual(s.testscollected, 0)
        self.assertIsInstance(s.config, Config)

    def test_config_option_namespace_reads_store_then_raw(self):
        set_options({"env": "staging"})
        c = Config({"timeout": 30})
        self.assertEqual(c.option.env, "staging")
        self.assertEqual(c.option.timeout, 30)
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # unknown reads silently as None
            self.assertIsNone(c.option.totally_unknown)

    def test_config_rootpath_and_args(self):
        c = Config({}, args=["tests", "--env", "qa"])
        self.assertTrue(c.rootpath.is_absolute())
        self.assertEqual(c.args, ["tests", "--env", "qa"])
        self.assertEqual(Config({}).args, [])


class ExceptionInfoTests(unittest.TestCase):
    def test_carries_the_live_exception(self):
        exc = ValueError("boom")
        try:
            raise exc
        except ValueError as e:
            info = ExceptionInfo(e)
        self.assertIs(info.value, exc)
        self.assertEqual(info.type, ValueError)
        self.assertIsNotNone(info.tb)
        self.assertEqual(info.typename, "ValueError")
        self.assertEqual(info.exconly(), "ValueError: boom")
        self.assertEqual(str(info), "ValueError: boom")


class CallInfoTests(unittest.TestCase):
    def test_passed_call_has_no_excinfo(self):
        call = CallInfo(when="call", excinfo=None, start=1.0, stop=1.5, duration=0.5)
        self.assertIsNone(call.excinfo)
        self.assertEqual(call.when, "call")
        self.assertEqual(call.duration, 0.5)
        self.assertIsNone(call.result)

    def test_failed_call_result_reraises_the_live_exception(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError as e:
            info = ExceptionInfo(e)
        call = CallInfo(when="call", excinfo=info)
        with self.assertRaises(RuntimeError):
            _ = call.result


class StashTests(unittest.TestCase):
    def test_item_stash_is_a_real_mutable_mapping(self):
        item = Item("suite.test_demo::test_a", 1, tags={"smoke"})
        item.stash["key"] = "value"
        self.assertEqual(item.stash["key"], "value")
        self.assertIn("key", item.stash)

    def test_config_stash_is_independent_of_item_stash(self):
        item = Item("suite.test_demo::test_a", 1)
        config = Config({})
        item.config = config
        config.stash["shared"] = 1
        item.stash["shared"] = 2
        self.assertEqual(config.stash["shared"], 1)
        self.assertEqual(item.stash["shared"], 2)


class InvocationParamsTests(unittest.TestCase):
    def test_config_invocation_params_carries_args_and_dir(self):
        c = Config({}, args=["tests", "--env", "qa"])
        self.assertEqual(c.invocation_params.args, ["tests", "--env", "qa"])
        self.assertTrue(c.invocation_params.dir.is_absolute())


class AddReportSectionTests(unittest.TestCase):
    def test_add_report_section_matches_pytest_title_convention(self):
        item = Item("suite.test_demo::test_a", 1)
        item.add_report_section("call", "log", "line one\n")
        self.assertEqual(item._report_sections, [("call", "log", "line one\n")])


class CallspecTests(unittest.TestCase):
    def test_parametrized_item_exposes_callspec(self):
        item = Item(
            "suite.test_demo::test_a[en-US]", 1, param_values={"locale": "en-US"}, param_id="en-US"
        )
        self.assertEqual(item.callspec.params, {"locale": "en-US"})
        self.assertEqual(item.callspec.id, "en-US")

    def test_non_parametrized_item_has_no_callspec(self):
        item = Item("suite.test_demo::test_a", 1)
        self.assertFalse(hasattr(item, "callspec"))
        with self.assertRaises(CompatibilityError):
            _ = item.callspec


class ExitCodeTests(unittest.TestCase):
    def test_values_match_ctrlrunners_real_exit_codes(self):
        self.assertEqual(ExitCode.OK, 0)
        self.assertEqual(ExitCode.TESTS_FAILED, 1)
        self.assertEqual(ExitCode.NO_TESTS_COLLECTED, 4)


class HookimplTopLevelExportTests(unittest.TestCase):
    def test_hookimpl_is_importable_from_the_top_level_package(self):
        # conftest.py authors write `from ctrlrunner import hookimpl`,
        # same as every other decorator (fixture/test/parametrize) --
        # not the internal `ctrlrunner.core.hookcompat` path.
        import ctrlrunner

        self.assertIs(ctrlrunner.hookimpl, hookimpl)


class HookimplOrderingTests(unittest.TestCase):
    """@ctrlrunner.hookimpl(tryfirst=/trylast=) -- pluggy's ordering
    hints, applied by sort_hooks() wherever a hook list is dispatched."""

    def test_tryfirst_runs_before_plain_hooks(self):
        @hookimpl(tryfirst=True)
        def first():
            pass

        def plain():
            pass

        ordered = sort_hooks([plain, first])
        self.assertEqual(ordered, [first, plain])

    def test_trylast_runs_after_plain_hooks(self):
        @hookimpl(trylast=True)
        def last():
            pass

        def plain():
            pass

        ordered = sort_hooks([last, plain])
        self.assertEqual(ordered, [plain, last])

    def test_relative_order_preserved_within_each_group(self):
        @hookimpl(tryfirst=True)
        def first_a():
            pass

        @hookimpl(tryfirst=True)
        def first_b():
            pass

        def plain_a():
            pass

        def plain_b():
            pass

        ordered = sort_hooks([plain_a, first_a, plain_b, first_b])
        self.assertEqual(ordered, [first_a, first_b, plain_a, plain_b])

    def test_hookimpl_is_transparent_when_unused(self):
        # A plain function (never decorated) sorts as neither first nor last.
        def plain():
            pass

        self.assertEqual(sort_hooks([plain]), [plain])


class HookwrapperMakereportTests(unittest.TestCase):
    """@ctrlrunner.hookimpl(hookwrapper=True) on
    ctrlrunner_runtest_makereport -- pluggy's yield protocol:
    `outcome = yield`, then outcome.get_result()/.force_result(...)."""

    def test_hookwrapper_generator_can_force_a_new_result(self):
        @hookimpl(hookwrapper=True)
        def wrapper(item, call):
            outcome = yield
            report = outcome.get_result()
            outcome.force_result(f"wrapped:{report}")

        result = run_makereport_hook(wrapper, {"item": "i", "call": "c"}, current_result="orig")
        self.assertEqual(result, "wrapped:orig")

    def test_hookwrapper_generator_that_does_not_force_keeps_result(self):
        @hookimpl(hookwrapper=True)
        def wrapper(item, call):
            yield

        result = run_makereport_hook(wrapper, {"item": "i", "call": "c"}, current_result="orig")
        self.assertEqual(result, "orig")

    def test_plain_generator_without_hookimpl_is_not_treated_as_wrapper(self):
        # A generator function that never opted into hookwrapper=True
        # must not be silently treated as one.
        self.assertFalse(is_hookwrapper(lambda item, call: None))


class BindHookArgsTests(unittest.TestCase):
    """pluggy-style call-by-parameter-NAME: each hook impl receives
    exactly the named subset of the hookspec's arguments it declares --
    order and position don't matter, names do. Unknown names fail
    loudly (pluggy errors on them too)."""

    AVAILABLE = {"session": "S", "config": "C", "items": "I"}

    def test_full_signature_binds_everything(self):
        def hook(session, config, items):
            pass

        self.assertEqual(
            bind_hook_args(hook, self.AVAILABLE), {"session": "S", "config": "C", "items": "I"}
        )

    def test_non_prefix_subset_binds_by_name(self):
        # THE case positional prefix-trimming got wrong:
        # def pytest_collection_modifyitems(items) skips the first TWO params.
        def hook(items):
            pass

        self.assertEqual(bind_hook_args(hook, self.AVAILABLE), {"items": "I"})

    def test_reordered_params_bind_by_name_not_position(self):
        def hook(items, session):
            pass

        self.assertEqual(bind_hook_args(hook, self.AVAILABLE), {"items": "I", "session": "S"})

    def test_unknown_parameter_name_raises_with_available_names(self):
        def hook(item):  # typo: the spec provides "items"
            pass

        with self.assertRaises(CompatibilityError) as ctx:
            bind_hook_args(hook, self.AVAILABLE)
        message = str(ctx.exception)
        self.assertIn("item", message)
        self.assertIn("items", message)  # the available names are listed

    def test_var_positional_rejected_like_pluggy(self):
        def hook(*args):
            pass

        with self.assertRaises(CompatibilityError):
            bind_hook_args(hook, self.AVAILABLE)


if __name__ == "__main__":
    unittest.main()
