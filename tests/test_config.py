import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ctrlrunner.config.config import load_config
from ctrlrunner.reporting.grouping import load_grouping_dimensions


class ConfigTests(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(load_config("/nonexistent/ctrlrunner.toml"), {})

    def test_toml_syntax_error_raises_clear_error_naming_the_file(self):
        # A typo'd ctrlrunner.toml previously leaked a raw TOMLDecodeError
        # with no filename; the module's posture is careful messaging
        # (warn on unknown keys, explain missing tomllib) -- a syntax
        # error deserves the same: a ValueError that says which file.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text('[ctrlrunner]\nroot = "unterminated\n')
            with self.assertRaises(ValueError) as ctx:
                load_config(str(path))
            self.assertIn("ctrlrunner.toml", str(ctx.exception))

    def test_parses_ctrlrunner_table(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(
                "[ctrlrunner]\n"
                'root = "tests"\n'
                "num_workers = 8\n"
                "timeout = 45.0\n"
                'reporter = ["dots", "json"]\n'
            )
            config = load_config(str(path))
            self.assertEqual(config["root"], "tests")
            self.assertEqual(config["num_workers"], 8)
            self.assertEqual(config["timeout"], 45.0)
            self.assertEqual(config["reporter"], ["dots", "json"])

    def test_missing_ctrlrunner_table_returns_empty_dict(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text("[other_tool]\nfoo = 1\n")
            self.assertEqual(load_config(str(path)), {})

    def test_workers_table_round_trips_through_load_config(self):
        from ctrlrunner.execution.worker_budget import load_worker_constraints

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(
                "[ctrlrunner]\n"
                'num_workers = "auto"\n'
                "\n"
                "[ctrlrunner.workers]\n"
                '"tests/test_a.py" = 1\n'
                '"tests/test_b.py::Login" = { count = 2, mode = "dedicated" }\n'
            )
            config = load_config(str(path))
            self.assertEqual(config["num_workers"], "auto")
            specs = load_worker_constraints(config)
            self.assertEqual(len(specs), 2)
            self.assertEqual(specs[1].class_name, "Login")
            self.assertEqual(specs[1].mode, "dedicated")


class NestedGroupingTableTests(unittest.TestCase):
    """Regression test for a real gotcha hit during manual verification:
    a bare `[grouping]` header in ctrlrunner.toml is a sibling TOML table,
    NOT nested under `[ctrlrunner]` -- load_config() would silently drop
    it (since it only returns data["ctrlrunner"]), and grouping would
    silently fall back to the default "module"-only dimension with no
    error at all. `[ctrlrunner.grouping]` is the correct nesting. This
    test locks in the correct behavior against a real file on disk, not
    just the in-memory dict load_grouping_dimensions() already covers
    elsewhere."""

    def test_correct_nesting_is_picked_up(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(
                "[ctrlrunner.grouping]\n"
                "dimensions = [\n"
                '  { name = "team", strategy = "tag_prefix", prefix = "team_" },\n'
                "]\n"
            )
            config = load_config(str(path))
            dims = load_grouping_dimensions(config)
            # module is always force-included for backward compatibility
            # even though this config's dimensions list only names "team" -- this test's
            # actual subject (correct [ctrlrunner.grouping] nesting parse)
            # is proven by "team" being present at all.
            self.assertEqual([d.name for d in dims], ["module", "team"])

    def test_bare_grouping_header_is_silently_a_sibling_table_not_nested(self):
        # documents the gotcha itself: this is what NOT to write. A bare
        # [grouping] table is a sibling of [ctrlrunner], not nested in it,
        # so load_config() (which only returns data["ctrlrunner"]) never
        # sees it -- grouping silently falls back to the default.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(
                "[ctrlrunner]\n"
                "[grouping]\n"
                "dimensions = [\n"
                '  { name = "team", strategy = "tag_prefix", prefix = "team_" },\n'
                "]\n"
            )
            config = load_config(str(path))
            dims = load_grouping_dimensions(config)
            self.assertEqual([d.name for d in dims], ["module"])  # silently the default, not "team"


class ConfigValidationTests(unittest.TestCase):
    """A typo'd key or mis-nested table used to be silently
    ignored -- the run proceeded with defaults and nobody noticed. The
    loader now warns (never errors -- unknown keys stay forward- and
    backward-compatible)."""

    def _load(self, toml_text):
        seen = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(toml_text)
            cfg = load_config(str(path), warn=seen.append)
        return cfg, seen

    def test_unknown_key_warns_but_still_loads(self):
        cfg, warns = self._load("[ctrlrunner]\nnum_wokers = 8\n")
        self.assertEqual(cfg, {"num_wokers": 8})
        self.assertTrue(any("num_wokers" in w for w in warns), warns)

    def test_misnested_known_table_warns_with_hint(self):
        _, warns = self._load('[ctrlrunner]\nroot = "tests"\n[workers]\n"a.py" = 1\n')
        self.assertTrue(any("[ctrlrunner.workers]" in w for w in warns), warns)

    def test_unknown_top_level_table_warns(self):
        _, warns = self._load('[ctrlrunner]\nroot = "tests"\n[banana]\nx = 1\n')
        self.assertTrue(any("banana" in w for w in warns), warns)

    def test_clean_config_produces_no_warnings(self):
        _, warns = self._load(
            "[ctrlrunner]\n"
            "num_workers = 4\n"
            "fully_parallel = false\n"
            "[ctrlrunner.workers]\n"
            '"a.py" = 1\n'
            "[ctrlrunner.projects.web]\n"
            'root = "tests"\n'
        )
        self.assertEqual(warns, [])

    def test_import_timeout_is_a_known_key(self):
        # Regression guard: a valid import_timeout
        # in ctrlrunner.toml must not trigger the "typo?" warning.
        cfg, warns = self._load("[ctrlrunner]\nimport_timeout = 120.0\n")
        self.assertEqual(cfg, {"import_timeout": 120.0})
        self.assertEqual(warns, [])

    def test_default_warn_goes_to_stderr(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text("[ctrlrunner]\nbanana = 1\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                load_config(str(path))
        self.assertIn("banana", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
