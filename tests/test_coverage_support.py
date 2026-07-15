import os
import shutil
import tempfile
import unittest

import coverage as coverage_pkg

from ctrlrunner.execution.coverage_support import (
    CoverageConfig,
    CoverageSummary,
    finalize_coverage,
    prepare_data_dir,
    resolve_coverage_config,
)


class ResolveCoverageConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        result = resolve_coverage_config(
            {},
            cli_enabled=False,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertIsNone(result)

    def test_cli_flag_enables(self):
        result = resolve_coverage_config(
            {},
            cli_enabled=True,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.enabled)
        self.assertEqual(result.data_dir, os.path.join("/tmp/x", ".coverage-data"))
        self.assertIsNone(result.html_dir)
        self.assertIsNone(result.fail_under)
        self.assertTrue(result.fail_under_enforced)
        self.assertFalse(result.contexts)
        self.assertEqual(result.hard_kills, 0)

    def test_toml_enabled_flag(self):
        result = resolve_coverage_config(
            {"coverage": {"enabled": True}},
            cli_enabled=False,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.enabled)

    def test_fail_under_and_contexts_from_toml(self):
        result = resolve_coverage_config(
            {"coverage": {"fail_under": 85, "contexts": True}},
            cli_enabled=True,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertEqual(result.fail_under, 85.0)
        self.assertTrue(result.contexts)

    def test_fail_under_not_enforced_when_selection_filtered(self):
        result = resolve_coverage_config(
            {"coverage": {"fail_under": 85}},
            cli_enabled=True,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=True,
        )
        self.assertFalse(result.fail_under_enforced)

    def test_cli_html_dir_wins_over_toml(self):
        result = resolve_coverage_config(
            {"coverage": {"html_dir": "/from/toml"}},
            cli_enabled=True,
            cli_html_dir="/from/cli",
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertEqual(result.html_dir, "/from/cli")

    def test_toml_html_dir_used_when_no_cli_flag(self):
        result = resolve_coverage_config(
            {"coverage": {"html_dir": "/from/toml"}},
            cli_enabled=True,
            cli_html_dir=None,
            report_dir="/tmp/x",
            selection_filtered=False,
        )
        self.assertEqual(result.html_dir, "/from/toml")

    def test_invalid_fail_under_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_coverage_config(
                {"coverage": {"fail_under": "not-a-number"}},
                cli_enabled=True,
                cli_html_dir=None,
                report_dir="/tmp/x",
                selection_filtered=False,
            )
        self.assertIn("[ctrlrunner.coverage].fail_under", str(ctx.exception))

    def test_fail_under_bool_raises(self):
        # bool is an int subclass, so isinstance(True, (int, float)) is
        # True -- without an explicit bool guard, fail_under=True would
        # silently become 1.0 instead of raising.
        with self.assertRaises(ValueError) as ctx:
            resolve_coverage_config(
                {"coverage": {"fail_under": True}},
                cli_enabled=True,
                cli_html_dir=None,
                report_dir="/tmp/x",
                selection_filtered=False,
            )
        self.assertIn("[ctrlrunner.coverage].fail_under", str(ctx.exception))

    def test_invalid_source_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_coverage_config(
                {"coverage": {"source": "not-a-list"}},
                cli_enabled=True,
                cli_html_dir=None,
                report_dir="/tmp/x",
                selection_filtered=False,
            )
        self.assertIn("[ctrlrunner.coverage].source", str(ctx.exception))


class PrepareDataDirTests(unittest.TestCase):
    def test_creates_missing_dir(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=None,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
            )
            prepare_data_dir(cfg)
            self.assertTrue(os.path.isdir(data_dir))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_refuses_to_purge_filesystem_root(self):
        # The containment guard is the only thing between a misconfigured
        # data_dir and a recursive delete of "/" -- it must trip BEFORE
        # any rmtree happens. (rmtree here uses ignore_errors=True, so
        # without the guard this wouldn't even error loudly.)
        cfg = CoverageConfig(
            enabled=True,
            data_dir="/",
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )
        with self.assertRaises(ValueError) as ctx:
            prepare_data_dir(cfg)
        self.assertIn("Refusing to purge unsafe coverage data_dir", str(ctx.exception))

    def test_root_reached_via_dotdot_also_refused(self):
        # Same guard, but for a data_dir that only *resolves* to the root
        # (e.g. "/tmp/../.." from a sloppy config template).
        cfg = CoverageConfig(
            enabled=True,
            data_dir="/tmp/../..",
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )
        with self.assertRaises(ValueError):
            prepare_data_dir(cfg)

    def test_purges_stale_files(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            os.makedirs(data_dir)
            stale = os.path.join(data_dir, ".coverage.stale-leftover")
            with open(stale, "w") as f:
                f.write("junk")
            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=None,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
            )
            prepare_data_dir(cfg)
            self.assertFalse(os.path.exists(stale))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FinalizeCoverageTests(unittest.TestCase):
    def _write_instrumented_data(self, data_dir, module_path):
        """Runs real coverage.py instrumentation against a scratch module,
        saving a data file into data_dir -- mirrors what worker.py's
        run_worker() will do in Task 3, without needing a real subprocess."""
        cov = coverage_pkg.Coverage(data_file=os.path.join(data_dir, ".coverage"), data_suffix=True)
        cov.start()
        namespace = {}
        with open(module_path) as f:
            exec(compile(f.read(), module_path, "exec"), namespace)
        cov.stop()
        cov.save()

    def test_combine_and_report(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            os.makedirs(data_dir)
            module_path = os.path.join(tmp, "scratch_mod.py")
            with open(module_path, "w") as f:
                f.write("def covered():\n    return 1\n\ncovered()\n")
            self._write_instrumented_data(data_dir, module_path)

            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=None,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
            )
            summary = finalize_coverage(cfg)

            self.assertIsInstance(summary, CoverageSummary)
            self.assertGreaterEqual(summary.percent, 0.0)
            self.assertLessEqual(summary.percent, 100.0)
            self.assertIsNone(summary.html_dir)
            self.assertEqual(summary.hard_kills, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_html_report_generated_when_html_dir_set(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            html_dir = os.path.join(tmp, "coverage-html")
            os.makedirs(data_dir)
            module_path = os.path.join(tmp, "scratch_mod2.py")
            with open(module_path, "w") as f:
                f.write("def covered():\n    return 1\n\ncovered()\n")
            self._write_instrumented_data(data_dir, module_path)

            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=html_dir,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
            )
            summary = finalize_coverage(cfg)

            self.assertTrue(os.path.isfile(os.path.join(html_dir, "index.html")))
            self.assertEqual(summary.html_dir, html_dir)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hard_kills_passed_through(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            os.makedirs(data_dir)
            module_path = os.path.join(tmp, "scratch_mod3.py")
            with open(module_path, "w") as f:
                f.write("x = 1\n")
            self._write_instrumented_data(data_dir, module_path)

            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=None,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
                hard_kills=2,
            )
            summary = finalize_coverage(cfg)
            self.assertEqual(summary.hard_kills, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_data_dir_does_not_raise(self):
        tmp = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(tmp, ".coverage-data")
            os.makedirs(data_dir)
            cfg = CoverageConfig(
                enabled=True,
                data_dir=data_dir,
                html_dir=None,
                source=None,
                fail_under=None,
                fail_under_enforced=True,
                contexts=False,
            )
            summary = finalize_coverage(cfg)
            self.assertEqual(summary.percent, 0.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
