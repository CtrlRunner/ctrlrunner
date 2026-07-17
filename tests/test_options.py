import argparse
import unittest

from ctrlrunner.config.addoption import AddoptionError, OptionParser
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


if __name__ == "__main__":
    unittest.main()
