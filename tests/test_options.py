import argparse
import tempfile
import unittest
from pathlib import Path

from ctrlrunner.config.addoption import AddoptionError, OptionParser, collect_declarations
from ctrlrunner.core.options import get_option, get_options, set_options


class OptionsStoreTests(unittest.TestCase):
    def tearDown(self):
        set_options(None)

    def test_normalization_treats_flag_and_dest_forms_the_same(self):
        set_options({"env": "staging"})
        self.assertEqual(get_option("env"), "staging")
        self.assertEqual(get_option("--env"), "staging")
        self.assertEqual(get_option("-env"), "staging")

    def test_dashes_in_name_become_underscores(self):
        set_options({"my_opt": "x"})
        self.assertEqual(get_option("--my-opt"), "x")
        self.assertEqual(get_option("my-opt"), "x")

    def test_default_only_applies_when_key_absent(self):
        set_options({"env": None})
        # a declared option resolved to None IS present -- dict
        # semantics, matching pytestconfig.getoption.
        self.assertIsNone(get_option("env", "fallback"))
        self.assertEqual(get_option("nope", "fallback"), "fallback")

    def test_get_options_returns_a_copy(self):
        set_options({"env": "qa"})
        snap = get_options()
        snap["env"] = "mutated"
        self.assertEqual(get_option("env"), "qa")

    def test_set_options_none_clears_the_store(self):
        set_options({"env": "qa"})
        set_options(None)
        self.assertEqual(get_options(), {})

    def test_set_options_copies_the_input_dict(self):
        source = {"env": "qa"}
        set_options(source)
        source["env"] = "mutated"
        self.assertEqual(get_option("env"), "qa")


class OptionParserShimTests(unittest.TestCase):
    def _parser(self, source="conftest.py"):
        shim = OptionParser()
        shim._source = source
        return shim

    def test_addoption_type_and_default(self):
        shim = self._parser()
        shim.addoption("--retries", type=int, default=2)
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        args = parser.parse_args([])
        self.assertEqual(shim.resolve({}, args), {"retries": 2})
        args = parser.parse_args(["--retries", "5"])
        self.assertEqual(shim.resolve({}, args), {"retries": 5})

    def test_addoption_choices_validated_by_argparse(self):
        shim = self._parser()
        shim.addoption("--env", choices=["qa", "staging"], default="qa")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--env", "bogus"])

    def test_store_true_default_false_when_unset(self):
        shim = self._parser()
        shim.addoption("--flag", action="store_true")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        self.assertEqual(shim.resolve({}, parser.parse_args([])), {"flag": False})
        self.assertEqual(shim.resolve({}, parser.parse_args(["--flag"])), {"flag": True})

    def test_append_action(self):
        shim = self._parser()
        shim.addoption("--tag", action="append", default=[])
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        args = parser.parse_args(["--tag", "a", "--tag", "b"])
        self.assertEqual(shim.resolve({}, args), {"tag": ["a", "b"]})

    def test_required_option_enforced(self):
        shim = self._parser()
        shim.addoption("--must-have", required=True)
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_duplicate_declaration_names_both_conftest_paths(self):
        shim = self._parser("conftest.py")
        shim.addoption("--env", default="qa")
        shim._source = "spec/web/conftest.py"
        with self.assertRaises(AddoptionError) as ctx:
            shim.addoption("--env", default="staging")
        self.assertIn("conftest.py", str(ctx.exception))
        self.assertIn("spec/web/conftest.py", str(ctx.exception))

    def test_getgroup_delegates_to_same_shim(self):
        shim = self._parser()
        group = shim.getgroup("myproject")
        group.addoption("--env", default="qa")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        self.assertEqual(shim.resolve({}, parser.parse_args([])), {"env": "qa"})

    def test_addini_warns_and_does_not_raise(self):
        import io
        import sys

        shim = self._parser()
        stderr = io.StringIO()
        old = sys.stderr
        sys.stderr = stderr
        try:
            shim.addini("some_setting", default="x")
        finally:
            sys.stderr = old
        self.assertIn("addini", stderr.getvalue())
        self.assertIn("[ctrlrunner.options]", stderr.getvalue())

    def test_declaring_a_builtin_flag_name_raises(self):
        shim = self._parser()
        shim.addoption("--timeout", type=float, default=5.0)
        parser = argparse.ArgumentParser()
        parser.add_argument("--timeout", type=float, default=30.0)
        with self.assertRaises(AddoptionError):
            shim.apply_to(parser)

    def test_dest_collision_with_builtin_raises(self):
        shim = self._parser()
        # --time-out normally derives dest "time_out", not colliding --
        # but an explicit dest= can still collide with a built-in.
        shim.addoption("--time-out", dest="timeout", type=float)
        parser = argparse.ArgumentParser()
        parser.add_argument("--timeout", type=float, default=30.0)
        with self.assertRaises(AddoptionError):
            shim.apply_to(parser)

    def test_option_name_must_start_with_dash(self):
        shim = self._parser()
        with self.assertRaises(AddoptionError):
            shim.addoption("env")

    def test_resolve_precedence_cli_over_toml_over_default(self):
        shim = self._parser()
        shim.addoption("--env", default="qa")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)

        # default only
        self.assertEqual(shim.resolve({}, parser.parse_args([])), {"env": "qa"})
        # toml overrides default
        self.assertEqual(
            shim.resolve({"env": "staging"}, parser.parse_args([])), {"env": "staging"}
        )
        # CLI overrides toml
        self.assertEqual(
            shim.resolve({"env": "staging"}, parser.parse_args(["--env", "prod"])),
            {"env": "prod"},
        )

    def test_resolve_toml_value_validated_against_declared_choices(self):
        shim = self._parser()
        shim.addoption("--env", choices=["qa", "staging"], default="qa")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        with self.assertRaises(AddoptionError):
            shim.base_values({"env": "bogus"})

    def test_undeclared_toml_keys_pass_through(self):
        shim = self._parser()
        shim.addoption("--env", default="qa")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        values = shim.base_values({"env": "qa", "free_form_key": 42})
        self.assertEqual(values["free_form_key"], 42)

    def test_cli_values_only_explicitly_typed(self):
        shim = self._parser()
        shim.addoption("--env", default="qa")
        shim.addoption("--persona", default="US")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        args = parser.parse_args(["--env", "staging"])
        self.assertEqual(shim.cli_values(args), {"env": "staging"})

    def test_help_text_includes_default_since_suppress_hides_percent_default(self):
        shim = self._parser()
        shim.addoption("--env", default="qa", help="target env")
        parser = argparse.ArgumentParser()
        shim.apply_to(parser)
        help_text = parser.format_help()
        self.assertIn("target env", help_text)
        self.assertIn("[default: qa]", help_text)


class UnknownHookDetectionTests(unittest.TestCase):
    """Fail-loudly policy at startup: a conftest defining a pytest_* or
    ctrlrunner_* hook ctrlrunner doesn't support aborts collection with
    a per-hook recommendation, instead of being silently ignored.
    allow_unknown_hooks=True (ctrlrunner.toml escape hatch, for shared
    pytest+ctrlrunner conftests mid-migration) downgrades to a
    warning."""

    def _conftest(self, tmp, body):
        root = Path(tmp) / "suite"
        root.mkdir()
        (root / "conftest.py").write_text(body)
        return root

    def test_refused_pytest_hook_aborts_with_recommendation(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._conftest(tmp, "def pytest_enter_pdb(config, pdb):\n    pass\n")
            with self.assertRaises(AddoptionError) as ctx:
                collect_declarations([str(root)])
        message = str(ctx.exception)
        self.assertIn("pytest_enter_pdb", message)
        self.assertIn("breakpoint()", message)

    def test_unrenamed_supported_pytest_hook_aborts_pointing_at_migrate(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._conftest(tmp, "def pytest_runtest_setup(item):\n    pass\n")
            with self.assertRaises(AddoptionError) as ctx:
                collect_declarations([str(root)])
        message = str(ctx.exception)
        self.assertIn("ctrlrunner_runtest_setup", message)
        self.assertIn("migrate", message)

    def test_unknown_ctrlrunner_hook_aborts_listing_supported_names(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._conftest(tmp, "def ctrlrunner_runtest_setupp(item):\n    pass\n")
            with self.assertRaises(AddoptionError) as ctx:
                collect_declarations([str(root)])
        message = str(ctx.exception)
        self.assertIn("ctrlrunner_runtest_setupp", message)
        self.assertIn("ctrlrunner_runtest_setup", message)  # the supported list

    def test_allow_unknown_hooks_downgrades_to_warning(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._conftest(tmp, "def pytest_enter_pdb(config, pdb):\n    pass\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                shim = collect_declarations([str(root)], allow_unknown_hooks=True)
        self.assertIsNotNone(shim)
        self.assertIn("pytest_enter_pdb", stderr.getvalue())

    def test_supported_hooks_and_plain_helpers_pass_clean(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._conftest(
                tmp,
                "def ctrlrunner_configure(config):\n    pass\n\n"
                "def ctrlrunner_runtest_logreport(report):\n    pass\n\n"
                "def my_helper():\n    pass\n",
            )
            shim = collect_declarations([str(root)])
        self.assertEqual(len(shim.configure_hooks), 1)


class ConfigureSessionfinishCollectionTests(unittest.TestCase):
    """collect_declarations() also collects ctrlrunner_configure and
    ctrlrunner_sessionfinish from conftest.py, in the same discovery
    pass as ctrlrunner_addoption -- no extra conftest import."""

    def test_collects_configure_and_sessionfinish_hooks(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "calls = []\n\n"
                "def ctrlrunner_configure(config):\n"
                "    calls.append(('configure', config))\n\n"
                "def ctrlrunner_sessionfinish(results, duration, exitstatus):\n"
                "    calls.append(('sessionfinish', results, duration, exitstatus))\n"
            )
            shim = collect_declarations([str(root)])

        self.assertEqual(len(shim.configure_hooks), 1)
        self.assertEqual(len(shim.sessionfinish_hooks), 1)

    def test_conftest_without_hooks_collects_nothing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text("x = 1\n")
            shim = collect_declarations([str(root)])

        self.assertEqual(shim.configure_hooks, [])
        self.assertEqual(shim.sessionfinish_hooks, [])

    def test_hooks_collected_shallowest_conftest_first(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            (root / "sub").mkdir(parents=True)
            (root / "conftest.py").write_text("def ctrlrunner_configure(config):\n    pass\n")
            (root / "sub" / "conftest.py").write_text(
                "def ctrlrunner_configure(config):\n    pass\n"
            )
            shim = collect_declarations([str(root)])

        self.assertEqual(len(shim.configure_hooks), 2)
        root_hook_module = shim.configure_hooks[0].__module__
        sub_hook_module = shim.configure_hooks[1].__module__
        self.assertNotEqual(root_hook_module, sub_hook_module)


if __name__ == "__main__":
    unittest.main()
