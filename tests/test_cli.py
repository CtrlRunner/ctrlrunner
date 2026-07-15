import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from ctrlrunner.cli import main
from ctrlrunner.core import registry


class RerunCliIntegrationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def _make_suite(self, tmp, module_name="rerun_demo"):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / f"test_{module_name}.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\ndef test_a():\n    pass\n\n"
            "@test()\ndef test_b():\n    assert False\n\n"
            "@test()\ndef test_c():\n    assert False\n"
        )
        return module_name

    def test_last_failed_reruns_only_previously_failed_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self._make_suite(tmp, "last_failed_demo")
            os.chdir(tmp)
            self._run_cli(["--reporter", "dots,json"])  # full run: 1 passed, 2 failed

            registry.reset()
            self._run_cli(["--last-failed", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(ids, {f"tests.test_{mod}::test_b", f"tests.test_{mod}::test_c"})

    def test_last_failed_with_no_previous_report_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "no_report_demo")
            os.chdir(tmp)
            self._run_cli(["--last-failed"])
            self.assertFalse(Path("reports/html-report/results.json").exists())

    def test_results_json_written_even_without_json_reporter(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self._make_suite(tmp, "always_json_demo")
            os.chdir(tmp)
            self._run_cli(["--reporter", "dots"])  # no 'json' requested

            results_path = Path("reports/html-report/results.json")
            self.assertTrue(results_path.exists())

            # ...which is exactly what --last-failed needs next run:
            registry.reset()
            self._run_cli(["--last-failed", "--reporter", "dots"])
            data = json.loads(results_path.read_text())
        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(ids, {f"tests.test_{mod}::test_b", f"tests.test_{mod}::test_c"})

    def test_failed_from_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = self._make_suite(tmp, "failed_from_demo")
            os.chdir(tmp)
            self._run_cli(["--reporter", "json", "--json-output", "saved.json"])

            registry.reset()
            self._run_cli(["--failed-from", "saved.json", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(ids, {f"tests.test_{mod}::test_b", f"tests.test_{mod}::test_c"})

    def test_last_failed_after_a_clean_run_selects_zero_tests_not_all(self):
        # An empty rerun match must never fall through
        # to "run the whole suite" -- that's the exact inverted
        # semantics --test-id nonexistent correctly avoids (0 tests).
        with tempfile.TemporaryDirectory() as tmp:
            mod = self._make_suite(tmp, "last_failed_clean_demo")
            os.chdir(tmp)
            # Overwrite the demo suite so every test passes -- a clean run.
            (Path(tmp) / "tests" / f"test_{mod}.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    pass\n\n"
                "@test()\ndef test_b():\n    pass\n"
            )
            self._run_cli(["--reporter", "json"])  # full clean run: 2 passed, 0 failed

            registry.reset()
            self._run_cli(["--last-failed", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        self.assertEqual(data["stats"]["total"], 0)

    def test_changed_since_reruns_only_tests_in_changed_files(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_changedsince_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            (root / "test_changedsince_b.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_b():\n    pass\n"
            )
            os.chdir(tmp)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "a@b.c"], check=True)
            subprocess.run(["git", "config", "user.name", "test"], check=True)
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], check=True)

            (root / "test_changedsince_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n\n"
                "@test()\ndef test_a2():\n    pass\n"
            )
            self._run_cli(["--changed-since", "HEAD", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(
            ids, {"tests.test_changedsince_a::test_a", "tests.test_changedsince_a::test_a2"}
        )

    def test_explicit_test_id_with_rerun_flag_warns_that_test_id_is_discarded(self):
        # A rerun flag silently discarding an explicit --test-id
        # is a sharp edge with no plan-defined semantics -- at minimum
        # this must be a visible warning, not silent.
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "mutual_excl_demo")
            os.chdir(tmp)
            self._run_cli(["--reporter", "json"])  # seed a previous run

            registry.reset()
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                self._run_cli(
                    ["--last-failed", "--test-id", "some::explicit::id", "--reporter", "json"]
                )
        self.assertIn("--test-id", buf.getvalue())
        self.assertIn("ignored", buf.getvalue().lower())

    def test_list_after_last_failed_flag_is_documented_as_unsupported_combo(self):
        # --list short-circuits before rerun resolution (cli.py) by
        # design -- --list is a discovery-time view, rerun flags need a
        # previous run's results, which is a run-time concept. This test
        # locks in that --list --last-failed lists the FULL suite (rerun
        # flags are silently not applied to --list), matching documented
        # behavior rather than leaving it an untested implicit accident.
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "list_rerun_demo")
            os.chdir(tmp)
            self._run_cli(["--reporter", "json"])
            registry.reset()

            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self._run_cli(["--last-failed", "--list", "json"])
            data = json.loads(buf.getvalue())
        self.assertEqual(len(data["tests"]), 3)  # all 3 tests, rerun flag not applied to --list

    def test_logs_flag_populates_result_logs_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_x():\n"
                "    print('cli logs test output')\n"
            )
            os.chdir(tmp)
            self._run_cli(["--logs", "on", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())
        self.assertEqual(data["tests"][0]["logs"][0]["stdout"].strip(), "cli logs test output")


class ListProjectScopingTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def _make_project_layout(self, tmp):
        web = Path(tmp) / "tests" / "web"
        e2e = Path(tmp) / "tests" / "e2e"
        web.mkdir(parents=True)
        e2e.mkdir(parents=True)
        (web / "test_web.py").write_text(
            "from ctrlrunner import test\n\n@test(tags={'smoke'})\ndef test_login():\n    pass\n"
        )
        (e2e / "test_e2e.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_full_flow():\n    pass\n"
        )
        (Path(tmp) / "ctrlrunner.toml").write_text(
            "[ctrlrunner.projects.smoke]\n"
            'tests_dir = ["tests/web"]\n\n'
            "[ctrlrunner.projects.e2e]\n"
            'tests_dir = ["tests/e2e"]\n'
        )

    def test_list_with_project_flag_only_lists_that_projects_tests(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            self._make_project_layout(tmp)
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self._run_cli(["--project", "smoke", "--list", "json"])
            data = json.loads(buf.getvalue())
        ids = [t["id"] for t in data["tests"]]
        self.assertTrue(all("test_login" in i for i in ids))
        self.assertFalse(any("test_full_flow" in i for i in ids))

    def test_list_with_project_flag_applies_that_projects_own_tags_filter(self):
        # A real run of --project smoke would apply the project's own
        # `tags` config as a selection filter (run_projects()'s
        # effective_tags logic) -- --list is supposed to be a pure view
        # over that exact same selection pipeline, so it must
        # apply the same filter instead of listing every test in the
        # project's tests_dir regardless of tags.
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'smoke'})\ndef test_login():\n    pass\n\n"
                "@test(tags={'regression'})\ndef test_checkout():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text(
                '[ctrlrunner.projects.smoke]\ntests_dir = ["tests"]\ntags = ["smoke"]\n'
            )
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self._run_cli(["--project", "smoke", "--list", "json"])
            data = json.loads(buf.getvalue())
        ids = [t["id"] for t in data["tests"]]
        self.assertTrue(all("test_login" in i for i in ids))
        self.assertFalse(any("test_checkout" in i for i in ids))

    def test_project_tags_validated_against_tag_registry(self):
        # A typo'd tag in a project's TOML `tags` filter used to
        # silently select zero tests -- it should raise the same clear
        # "unregistered tag" error the CLI's own tag validation path
        # produces, instead of a confusing empty result.
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test(tags={'smoke'})\ndef test_login():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text(
                "[ctrlrunner]\n"
                "registered_tags = ['smoke']\n"
                "strict_tags = true\n\n"
                '[ctrlrunner.projects.typo]\ntests_dir = ["tests"]\ntags = ["smoke-typo"]\n'
            )
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                self._run_cli(["--project", "typo", "--list", "json"])
        self.assertIn("smoke-typo", buf.getvalue())
        self.assertIn("registered_tags", buf.getvalue())


class ProjectCliIntegrationTests(unittest.TestCase):
    """First CLI-level tests in this project (prior verification was all
    manual `python -m ctrlrunner ...` subprocess runs) -- added here
    specifically because the bug below was only ever caught by actually
    reading the file `cli.main()` produces, not by any unit test of
    run_projects() itself (which returns a combined Python object
    correctly; the bug was purely in how cli.py wired that object into
    the JSON reporter's file-writing side effect)."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _make_project_layout(self, tmp):
        web = Path(tmp) / "tests" / "web"
        e2e = Path(tmp) / "tests" / "e2e"
        web.mkdir(parents=True)
        e2e.mkdir(parents=True)
        (web / "test_web.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test(tags={'smoke'})\ndef test_login():\n    pass\n\n"
            "@test(tags={'regression'})\ndef test_checkout():\n    pass\n"
        )
        (e2e / "test_e2e.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_full_flow():\n    pass\n"
        )
        (Path(tmp) / "ctrlrunner.toml").write_text(
            "[ctrlrunner.projects.smoke]\n"
            'tests_dir = ["tests/web", "tests/e2e"]\n'
            'tags = ["smoke"]\n\n'
            "[ctrlrunner.projects.regression]\n"
            'tests_dir = ["tests/web"]\n'
        )

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_combined_json_includes_every_project_not_just_the_last(self):
        # Regression test: JsonReporter.on_run_end() overwrites
        # results.json on every call, and each project's own
        # Orchestrator.run() calls it once -- naively passing JsonReporter
        # through as a per-project console reporter meant the final
        # results.json only ever showed the LAST project's tests, with
        # every earlier project's data silently lost.
        with tempfile.TemporaryDirectory() as tmp:
            self._make_project_layout(tmp)
            os.chdir(tmp)
            self._run_cli(["--project", "smoke,regression", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        self.assertEqual(set(data["projects"]), {"smoke", "regression"})
        self.assertEqual(data["stats"]["total"], 3)  # smoke's 1 + regression's 2
        # test_id stays the RAW id in
        # multi-project runs -- the "project" field is the sole
        # disambiguator, since a "[project] " id prefix broke every
        # history/rerun/quarantine join that queries by raw id.
        projects_seen = {t["project"] for t in data["tests"]}
        self.assertEqual(projects_seen, {"smoke", "regression"})

    def test_junit_xml_wraps_testsuites_for_multi_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_project_layout(tmp)
            os.chdir(tmp)
            self._run_cli(["--project", "smoke,regression"])
            root = ET.parse("reports/html-report/report.xml").getroot()

        self.assertEqual(root.tag, "testsuites")
        names = {s.get("name") for s in root.findall("testsuite")}
        self.assertEqual(names, {"smoke", "regression"})

    def test_single_project_run_keeps_single_testsuite_and_unprefixed_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_project_layout(tmp)
            os.chdir(tmp)
            self._run_cli(["--project", "smoke", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())
            root = ET.parse("reports/html-report/report.xml").getroot()

        self.assertEqual(root.tag, "testsuite")  # NOT wrapped in <testsuites>
        ids = [t["id"] for t in data["tests"]]
        self.assertTrue(all(not i.startswith("[") for i in ids))

    def test_unknown_project_name_fails_fast_with_no_report_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_project_layout(tmp)
            os.chdir(tmp)
            self._run_cli(["--project", "typo-project"])
            self.assertFalse(Path("reports/html-report/report.xml").exists())

    def test_no_project_flag_is_completely_unaffected(self):
        # today's exact single-Orchestrator path, sanity-checked through
        # the real CLI entry point rather than only through Orchestrator
        # directly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            os.chdir(tmp)
            self._run_cli(["--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())
            root_el = ET.parse("reports/html-report/report.xml").getroot()

        self.assertEqual(root_el.tag, "testsuite")
        self.assertEqual(data["projects"], [])
        self.assertEqual(data["tests"][0]["id"], "tests.test_a::test_x")


class WorkerConfigCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit) as ctx:
            main()
        return ctx.exception.code

    def _make_suite(self, tmp, module_name):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / f"test_{module_name}.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
        )

    def test_dash_n_auto_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "nauto_demo")
            os.chdir(tmp)
            code = self._run_cli(["-n", "auto", "--reporter", "json"])
            self.assertEqual(code, 0)
            data = json.loads(Path("reports/html-report/results.json").read_text())
            self.assertEqual(len(data["tests"]), 1)

    def test_dash_n_percent_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "npercent_demo")
            os.chdir(tmp)
            code = self._run_cli(["-n", "50%", "--reporter", "json"])
            self.assertEqual(code, 0)

    def test_dash_n_zero_rejected_at_parse_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "nzero_demo")
            os.chdir(tmp)
            code = self._run_cli(["-n", "0"])
            self.assertEqual(code, 2)  # argparse usage error

    def test_dash_n_garbage_rejected_at_parse_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "ngarbage_demo")
            os.chdir(tmp)
            code = self._run_cli(["-n", "banana"])
            self.assertEqual(code, 2)

    def test_config_num_workers_auto_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "cfgauto_demo")
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text('[ctrlrunner]\nnum_workers = "auto"\n')
            code = self._run_cli(["--reporter", "json"])
            self.assertEqual(code, 0)

    def test_config_num_workers_percent_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "cfgpercent_demo")
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text('[ctrlrunner]\nnum_workers = "50%"\n')
            code = self._run_cli(["--reporter", "json"])
            self.assertEqual(code, 0)

    def test_invalid_config_num_workers_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "cfgbadworkers_demo")
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text('[ctrlrunner]\nnum_workers = "fast"\n')
            code = self._run_cli([])
            self.assertEqual(code, 1)
            self.assertFalse(Path("reports/html-report/results.json").exists())

    def test_invalid_workers_table_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "cfgbadtable_demo")
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text('[ctrlrunner.workers]\n"tests/test_x.py" = 0\n')
            code = self._run_cli([])
            self.assertEqual(code, 1)

    def test_invalid_fully_parallel_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, "cfgbadfp_demo")
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text('[ctrlrunner]\nfully_parallel = "yes"\n')
            code = self._run_cli([])
            self.assertEqual(code, 1)

    def test_workers_table_cap_run_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_capped_cli.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    pass\n\n"
                "@test()\ndef test_b():\n    pass\n"
            )
            os.chdir(tmp)
            Path("ctrlrunner.toml").write_text(
                "[ctrlrunner]\nfully_parallel = true\n\n"
                '[ctrlrunner.workers]\n"tests/test_capped_cli.py" = 1\n'
            )
            code = self._run_cli(["-n", "4", "--reporter", "json"])
            self.assertEqual(code, 0)
            data = json.loads(Path("reports/html-report/results.json").read_text())
            self.assertEqual(len(data["tests"]), 2)
            self.assertTrue(all(t["outcome"] == "passed" for t in data["tests"]))


class ConfigValidationCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_bad_fail_policy_config_fails_fast_with_no_report_written(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text(
                '[ctrlrunner.fail_policy]\nmax_failures = "5"\n'
            )
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                self._run_cli([])
            self.assertFalse(Path("reports/html-report/report.xml").exists())
        self.assertIn("fail_policy", buf.getvalue())

    def test_invalid_import_timeout_config_fails_fast(self):
        # import_timeout gates worker hard-kills during suite import --
        # a string/zero/negative value must die at config validation,
        # not mid-run inside the orchestrator's watchdog arithmetic.
        for bad in ('"fast"', "0", "true"):
            with self.subTest(value=bad), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "tests"
                root.mkdir()
                (root / "test_a.py").write_text(
                    "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
                )
                (Path(tmp) / "ctrlrunner.toml").write_text(
                    f"[ctrlrunner]\nimport_timeout = {bad}\n"
                )
                os.chdir(tmp)
                buf = io.StringIO()
                with (
                    contextlib.redirect_stderr(buf),
                    patch.object(sys, "argv", ["ctrlrunner"]),
                    self.assertRaises(SystemExit) as ctx,
                ):
                    main()
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn("import_timeout", buf.getvalue())
                os.chdir(self._cwd)

    def test_strict_tags_unregistered_tag_stops_collection_with_exit_1(self):
        # The CLI-level TagValidationError catch: with --strict-tags an
        # unregistered tag must abort before ANY test runs (exit 1, the
        # "collection stopped" message, no report written).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'not_registered_anywhere'})\ndef test_x():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text(
                '[ctrlrunner]\nregistered_tags = ["smoke"]\n'
            )
            os.chdir(tmp)
            buf = io.StringIO()
            with (
                contextlib.redirect_stderr(buf),
                patch.object(sys, "argv", ["ctrlrunner", "--strict-tags"]),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("collection stopped", buf.getvalue())
            # the report dir skeleton may exist (created before
            # collection), but no result artifacts were published
            self.assertEqual(list(Path().glob("reports/**/report.xml")), [])
            self.assertEqual(list(Path().glob("reports/**/results.json")), [])

    def test_unknown_config_key_warns_on_stderr_but_run_proceeds(self):
        # A typo'd key must be loud (stderr warning) but not
        # fatal -- the run still executes.
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_cfgwarn_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text("[ctrlrunner]\nnum_wokers = 2\n")
            os.chdir(tmp)
            buf = io.StringIO()
            with (
                contextlib.redirect_stderr(buf),
                patch.object(sys, "argv", ["ctrlrunner"]),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
            self.assertEqual(ctx.exception.code, 0)
        self.assertIn("num_wokers", buf.getvalue())

    def test_junit_logs_flag_embeds_captured_stdout_in_xml(self):
        # --logs on + --junit-logs system-out puts test
        # stdout into <system-out> in report.xml.
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_junitlogs_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_prints():\n"
                '    print("captured-for-junit")\n'
            )
            os.chdir(tmp)
            with (
                patch.object(
                    sys,
                    "argv",
                    ["ctrlrunner", "--logs", "on", "--junit-logs", "system-out"],
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
            self.assertEqual(ctx.exception.code, 0)
            case = ET.parse("reports/html-report/report.xml").getroot().find("testcase")
            self.assertIn("captured-for-junit", case.find("system-out").text)

    def test_failed_from_expands_partial_serial_group_to_whole_group(self):
        # Rerunning only the failed member of a serial class
        # must pull in the whole class -- a partial serial group runs
        # skip-on-fail over a subset the author never intended.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_serialrerun_demo.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_first(self):\n"
                "        pass\n\n"
                "    @test()\n"
                "    def test_second(self):\n"
                "        pass\n"
            )
            failed_json = Path(tmp) / "prev-results.json"
            failed_json.write_text(
                json.dumps(
                    {
                        "tests": [
                            {
                                "id": "tests.test_serialrerun_demo::Flow.test_second",
                                "outcome": "failed",
                            }
                        ]
                    }
                )
            )
            os.chdir(tmp)
            with (
                patch.object(
                    sys,
                    "argv",
                    ["ctrlrunner", "--failed-from", str(failed_json), "--reporter", "json"],
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
            self.assertEqual(ctx.exception.code, 0)
            data = json.loads(Path("reports/html-report/results.json").read_text())
            ran = sorted(t["id"] for t in data["tests"])
            self.assertEqual(
                ran,
                [
                    "tests.test_serialrerun_demo::Flow.test_first",
                    "tests.test_serialrerun_demo::Flow.test_second",
                ],
            )

    def test_uncreatable_report_path_fails_with_message_not_traceback(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_badpath_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            blocker = Path(tmp) / "blocker"
            blocker.write_text("")  # a FILE where a directory is needed
            os.chdir(tmp)
            buf = io.StringIO()
            with (
                contextlib.redirect_stderr(buf),
                patch.object(
                    sys, "argv", ["ctrlrunner", "--junit-xml", str(blocker / "sub" / "report.xml")]
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
            self.assertEqual(ctx.exception.code, 1)
        self.assertIn("cannot create report directory", buf.getvalue())


class HistoryDbPathDerivationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_history_db_follows_custom_reports_dir(self):
        # HistoryConfig.db_path's OLD hardcoded
        # default ("reports/.history.db") ignored a custom
        # --reports-dir entirely -- the history file must live under
        # whatever reports_dir was actually configured.
        #
        # Deliberately uses a module name distinct from other test_a.py
        # fixtures in this file (tests.test_a) -- a plain
        # importlib.import_module() no-ops on an already-cached
        # sys.modules entry, so reusing that exact module name across
        # TestCase classes (each with its own tempdir) can leave a
        # LATER test's registry empty even after registry.reset(),
        # since the module's @test() decorators never re-run.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_history_db_path_derivation.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            os.chdir(tmp)
            self._run_cli(["--reports-dir", "custom_reports"])
            self.assertTrue((Path(tmp) / "custom_reports" / ".history.db").exists())


class ListRiskFlagTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_list_json_flags_a_test_with_history_near_its_timeout(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            # timeout=2 / sleep=1.8 keeps the 90%-of-timeout ratio while
            # leaving 0.2s of absolute slack, so a slow CI runner can't
            # turn the seeding run's test_slow into an actual hard-kill.
            (root / "test_risk_flag_suite.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=2)\ndef test_slow():\n    time.sleep(1.8)\n\n"
                "@test(timeout=10)\ndef test_fast():\n    pass\n"
            )
            os.chdir(tmp)
            # seed history: test_slow ~1.8s / 2s timeout. Suppress its
            # console output so the test run stays quiet.
            with contextlib.redirect_stdout(io.StringIO()):
                self._run_cli(["--reporter", "json"])

            registry.reset()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self._run_cli(["--list", "json"])
            data = json.loads(buf.getvalue())

        by_id = {t["id"]: t for t in data["tests"]}
        slow_id = next(k for k in by_id if "test_slow" in k)
        fast_id = next(k for k in by_id if "test_fast" in k)
        self.assertTrue(by_id[slow_id]["riskFlag"])
        self.assertFalse(by_id[fast_id]["riskFlag"])


class UICliHeadedFlagOverrideTests(unittest.TestCase):
    """`--headed` used to be a store_true flag defaulting to False --
    there was no way to express "explicitly force headless" from the
    CLI when ctrlrunner.toml set `headed = true`. Exercised through
    `_ui()` with `serve_ui` mocked out so no server actually starts."""

    def _config(self, tmp, headed_value: str) -> str:
        cfg = Path(tmp) / "ctrlrunner.toml"
        cfg.write_text(f"[ctrlrunner]\nheaded = {headed_value}\n")
        return str(cfg)

    def test_no_headed_flag_forces_headless_over_truthy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = self._config(tmp, "true")
            with (
                patch("ctrlrunner.ui.ui_server.serve_ui") as mock_serve_ui,
                patch.object(
                    sys, "argv", ["ctrlrunner", "ui", "--config", cfg_path, "--no-headed"]
                ),
            ):
                from ctrlrunner.cli import _ui

                _ui(sys.argv[2:])
        kwargs = mock_serve_ui.call_args.kwargs
        self.assertTrue(kwargs["playwright_config"]["headless"])

    def test_headed_flag_still_overrides_falsy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = self._config(tmp, "false")
            with (
                patch("ctrlrunner.ui.ui_server.serve_ui") as mock_serve_ui,
                patch.object(sys, "argv", ["ctrlrunner", "ui", "--config", cfg_path, "--headed"]),
            ):
                from ctrlrunner.cli import _ui

                _ui(sys.argv[2:])
        kwargs = mock_serve_ui.call_args.kwargs
        self.assertFalse(kwargs["playwright_config"]["headless"])

    def test_absent_flag_falls_back_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = self._config(tmp, "true")
            with (
                patch("ctrlrunner.ui.ui_server.serve_ui") as mock_serve_ui,
                patch.object(sys, "argv", ["ctrlrunner", "ui", "--config", cfg_path]),
            ):
                from ctrlrunner.cli import _ui

                _ui(sys.argv[2:])
        kwargs = mock_serve_ui.call_args.kwargs
        self.assertFalse(kwargs["playwright_config"]["headless"])


class BindHostGuardCliTests(unittest.TestCase):
    """_resolve_bind_host is the only thing standing between the
    auth-light UI/report servers and a routable interface -- a
    regression here silently exposes them, so the refusal path (exit 1,
    no server call) and the explicit --allow-remote opt-in are pinned
    for both subcommands."""

    def test_show_report_refuses_non_loopback_bind_without_allow_remote(self):
        stderr = io.StringIO()
        with (
            patch("ctrlrunner.ui.show_report.serve_report") as mock_serve,
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as ctx,
        ):
            from ctrlrunner.cli import _show_report

            _show_report(["some-report.html", "--bind", "0.0.0.0"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("refusing to bind to non-loopback address", stderr.getvalue())
        mock_serve.assert_not_called()

    def test_show_report_allow_remote_passes_bind_through(self):
        with patch("ctrlrunner.ui.show_report.serve_report") as mock_serve:
            from ctrlrunner.cli import _show_report

            _show_report(["some-report.html", "--bind", "0.0.0.0", "--allow-remote"])
        self.assertEqual(mock_serve.call_args.kwargs["bind"], "0.0.0.0")

    def test_ui_refuses_non_loopback_bind_without_allow_remote(self):
        stderr = io.StringIO()
        with (
            patch("ctrlrunner.ui.ui_server.serve_ui") as mock_serve,
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as ctx,
        ):
            from ctrlrunner.cli import _ui

            _ui(["--bind", "192.168.1.10"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("refusing to bind to non-loopback address", stderr.getvalue())
        mock_serve.assert_not_called()

    def test_loopback_binds_pass_without_allow_remote(self):
        from ctrlrunner.cli import _resolve_bind_host

        for bind in ("127.0.0.1", "localhost", "::1"):
            self.assertEqual(_resolve_bind_host(bind, allow_remote=False), bind)

    def test_show_report_missing_report_exits_1(self):
        # The FileNotFoundError -> exit 1 catch in _show_report: point it
        # at an empty directory so the real serve_report raises.
        stderr = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as ctx,
        ):
            from ctrlrunner.cli import _show_report

            _show_report([tmp, "--no-browser"])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("No report found", stderr.getvalue())


class FlakyReportCliTests(unittest.TestCase):
    """The flaky-report subcommand previously had zero coverage -- exit
    codes for its refusal paths and the --output happy path."""

    def _write_config(self, tmp, body):
        cfg = Path(tmp) / "ctrlrunner.toml"
        cfg.write_text(body)
        return str(cfg)

    def _run(self, argv):
        from ctrlrunner.cli import _flaky_report

        stderr, stdout = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as ctx,
        ):
            _flaky_report(argv)
        return ctx.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_history_disabled_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, "[ctrlrunner.history]\nenabled = false\n")
            code, _, err = self._run(["--config", cfg])
        self.assertEqual(code, 1)
        self.assertIn("history] is disabled", err)

    def test_missing_history_db_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_config(tmp, f'[ctrlrunner]\nreports_dir = "{tmp}/reports"\n')
            code, _, err = self._run(["--config", cfg])
        self.assertEqual(code, 1)
        self.assertIn("no history database found", err)

    def test_output_file_written_on_success(self):
        from ctrlrunner.reporting.history import HistoryStore
        from ctrlrunner.reporting.reporter import Result

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "reports" / ".history.db")
            with HistoryStore(db_path) as store:
                store.record_run(
                    [
                        Result(
                            test_id="mod::a",
                            outcome="failed",
                            error="x",
                            duration=0.1,
                            attempts=2,
                            retries_configured=1,
                        )
                    ]
                )
            cfg = self._write_config(tmp, f'[ctrlrunner]\nreports_dir = "{tmp}/reports"\n')
            out_path = str(Path(tmp) / "flaky.json")
            code, out, _ = self._run(["--config", cfg, "--format", "json", "--output", out_path])
            self.assertEqual(code, 0)
            self.assertIn("Wrote flaky report", out)
            self.assertTrue(Path(out_path).exists())
            json.loads(Path(out_path).read_text())  # valid JSON payload


class ReportTimestampCliOverrideTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_no_report_timestamp_flag_forces_it_off_over_truthy_config(self):
        # report_timestamp=true in config used to be unforceable back to
        # off from the CLI, since --report-timestamp was a plain
        # store_true flag with no way to express "explicitly False".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text("[ctrlrunner]\nreport_timestamp = true\n")
            os.chdir(tmp)
            self._run_cli(["--no-report-timestamp", "--reporter", "json"])
            self.assertTrue(Path("reports/html-report/results.json").exists())


class MultiProjectDurationTests(unittest.TestCase):
    """The combined multi-project JSON `duration` used to be
    sum(r.duration for r in results) -- inconsistent with single-project
    mode's wall-clock semantics for the exact same field. Two projects,
    each running 2 tests in parallel (num_workers=2) that each sleep
    0.4s, gives a per-project wall time of ~0.4s (~0.8s total across
    both projects, run sequentially) but a summed test duration of
    ~1.6s -- wall clock must be well under the sum."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_combined_duration_is_wall_clock_not_sum_of_test_durations(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b"):
                root = Path(tmp) / f"tests_{name}"
                root.mkdir()
                (root / f"test_{name}.py").write_text(
                    "import time\nfrom ctrlrunner import test\n\n"
                    "@test()\ndef test_one():\n    time.sleep(0.4)\n\n"
                    "@test()\ndef test_two():\n    time.sleep(0.4)\n"
                )
            # fully_parallel: this test measures wall-clock vs summed
            # durations, which needs the two same-file tests to actually
            # run concurrently -- the file-grouped default would
            # serialize them onto one worker.
            (Path(tmp) / "ctrlrunner.toml").write_text(
                "[ctrlrunner]\nfully_parallel = true\n\n"
                '[ctrlrunner.projects.a]\ntests_dir = ["tests_a"]\nnum_workers = 2\n\n'
                '[ctrlrunner.projects.b]\ntests_dir = ["tests_b"]\nnum_workers = 2\n'
            )
            os.chdir(tmp)
            self._run_cli(["--project", "a,b", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        sum_of_test_durations = sum(t["duration"] for t in data["tests"])
        self.assertLess(data["stats"]["duration"], sum_of_test_durations - 0.3)


class MultiProjectLineReporterResetTests(unittest.TestCase):
    """LineReporter._seen accumulates unique test_ids across an
    entire multi-project invocation (the same reporter instance is
    reused for every project, since run_projects() builds console
    reporters once and passes them to each project's Orchestrator) --
    without resetting it at the top of each project's run, the second
    project's "[n/total]" progress fraction overshoots its own total
    (e.g. "[4/2]") because `n` still counts the first project's tests."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_progress_fraction_never_exceeds_its_own_projects_total(self):
        import contextlib
        import io
        import re

        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "tests_a"
            root_a.mkdir()
            (root_a / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_one():\n    pass\n\n"
                "@test()\ndef test_two():\n    pass\n\n"
                "@test()\ndef test_three():\n    pass\n"
            )
            root_b = Path(tmp) / "tests_b"
            root_b.mkdir()
            (root_b / "test_b.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_one():\n    pass\n"
            )
            (Path(tmp) / "ctrlrunner.toml").write_text(
                '[ctrlrunner.projects.a]\ntests_dir = ["tests_a"]\n\n'
                '[ctrlrunner.projects.b]\ntests_dir = ["tests_b"]\n'
            )
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self._run_cli(["--project", "a,b", "--reporter", "line"])
            output = buf.getvalue()

        fractions = [(int(n), int(t)) for n, t in re.findall(r"\[(\d+)/(\d+)\]", output)]
        self.assertTrue(fractions)
        self.assertTrue(all(n <= t for n, t in fractions))


class CoverageCliIntegrationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit) as cm:
            main()
        return cm.exception.code

    def _make_suite(self, tmp, two_tests=False):
        root = Path(tmp) / "tests"
        root.mkdir()
        if two_tests:
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_ok():\n"
                "    assert 1 == 1\n\n"
                "@test()\n"
                "def test_two():\n"
                "    assert 2 == 2\n"
            )
        else:
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_ok():\n    assert 1 == 1\n"
            )

    def test_coverage_flag_adds_percent_to_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            code = self._run_cli(["--coverage", "--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        self.assertEqual(code, 0)
        self.assertIn("coveragePercent", data["stats"])

    def test_coverage_fail_under_fails_run_when_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            (Path(tmp) / "ctrlrunner.toml").write_text("[ctrlrunner.coverage]\nfail_under = 100\n")
            os.chdir(tmp)
            code = self._run_cli(["--coverage", "--reporter", "json"])

        self.assertNotEqual(code, 0)

    def test_coverage_fail_under_not_enforced_when_test_id_filter_active(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp, two_tests=True)
            (Path(tmp) / "ctrlrunner.toml").write_text("[ctrlrunner.coverage]\nfail_under = 100\n")
            os.chdir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                code = self._run_cli(
                    [
                        "--coverage",
                        "--test-id",
                        "tests.test_demo::test_ok",
                        "--reporter",
                        "json",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("fail-under not enforced", buf.getvalue())

    def test_coverage_off_by_default_no_json_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            code = self._run_cli(["--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())

        self.assertEqual(code, 0)
        self.assertNotIn("coveragePercent", data["stats"])


class TagNotCliTests(unittest.TestCase):
    """--tag-not drops tests carrying any of the
    excluded tags, AND-ed after the include filters."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def test_tag_not_excludes_matching_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_tagnot_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'smoke'})\ndef test_fast():\n    pass\n\n"
                "@test(tags={'smoke', 'slow'})\ndef test_slow():\n    pass\n"
            )
            os.chdir(tmp)
            with (
                patch.object(
                    sys, "argv", ["ctrlrunner", "--tag-not", "slow", "--reporter", "dots"]
                ),
                self.assertRaises(SystemExit),
            ):
                main()
            data = json.loads(Path("reports/html-report/results.json").read_text())
        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(ids, {"tests.test_tagnot_demo::test_fast"})


class RunManifestCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def test_run_manifest_written_next_to_results_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_manifest_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_ok():\n    pass\n\n"
                "@test()\ndef test_bad():\n    assert False\n"
            )
            os.chdir(tmp)
            with (
                patch.object(sys, "argv", ["ctrlrunner", "--reporter", "dots"]),
                self.assertRaises(SystemExit),
            ):
                main()
            manifest = json.loads(Path("reports/html-report/run-manifest.json").read_text())

        self.assertEqual(manifest["totalTests"], 2)
        self.assertEqual(manifest["failedTestIds"], ["tests.test_manifest_demo::test_bad"])
        self.assertIn("--reporter", manifest["argv"])
        self.assertIn("ctrlrunnerVersion", manifest)


class OrderSeedCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _make_suite(self, tmp):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / "test_orderseed_demo.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
        )

    def test_random_order_seed_lands_in_junit_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            with (
                patch.object(
                    sys,
                    "argv",
                    ["ctrlrunner", "--order", "random", "--seed", "99", "--reporter", "dots"],
                ),
                self.assertRaises(SystemExit),
            ):
                main()
            tree = ET.parse("reports/html-report/report.xml")
        props = {p.get("name"): p.get("value") for p in tree.getroot().iter("property")}
        self.assertEqual(props.get("order"), "random")
        self.assertEqual(props.get("seed"), "99")

    def test_declared_order_default_has_no_order_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            with (
                patch.object(sys, "argv", ["ctrlrunner", "--reporter", "dots"]),
                self.assertRaises(SystemExit),
            ):
                main()
            tree = ET.parse("reports/html-report/report.xml")
        props = {p.get("name") for p in tree.getroot().iter("property")}
        self.assertNotIn("order", props)


class FailOnFlakyCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli_code(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit) as ctx:
            main()
        return ctx.exception.code

    def _make_flaky_suite(self, tmp):
        root = Path(tmp) / "tests"
        root.mkdir()
        # A module-level counter makes the first attempt fail and the
        # retry pass -- a deterministic flaky test, no timing/threading.
        (root / "test_flaky_demo.py").write_text(
            "from ctrlrunner import test\n\n"
            "_attempts = {'n': 0}\n\n"
            "@test(retries=1)\n"
            "def test_eventually_passes():\n"
            "    _attempts['n'] += 1\n"
            "    assert _attempts['n'] >= 2\n"
        )

    def test_fail_on_flaky_makes_a_flaky_pass_fail_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_flaky_suite(tmp)
            os.chdir(tmp)
            code = self._run_cli_code(["--fail-on-flaky", "--reporter", "dots"])
        self.assertEqual(code, 1)

    def test_without_fail_on_flaky_a_flaky_pass_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_flaky_suite(tmp)
            os.chdir(tmp)
            code = self._run_cli_code(["--reporter", "dots"])
        self.assertEqual(code, 0)


class GrepCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def _make_suite(self, tmp):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / "test_grep_cli_demo.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\ndef test_login():\n    pass\n\n"
            "@test()\ndef test_signup():\n    pass\n"
        )

    def test_grep_selects_only_matching_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            self._run_cli(["--grep", "login", "--reporter", "dots"])
            data = json.loads(Path("reports/html-report/results.json").read_text())
        ids = {t["id"] for t in data["tests"]}
        self.assertEqual(ids, {"tests.test_grep_cli_demo::test_login"})

    def test_bad_grep_regex_exits_cleanly_via_argparse(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_suite(tmp)
            os.chdir(tmp)
            with (
                patch.object(
                    sys, "argv", ["ctrlrunner", "--grep", "(unclosed", "--reporter", "dots"]
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
        self.assertEqual(ctx.exception.code, 2)


class UnknownReporterCliTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def test_unknown_reporter_exits_cleanly_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_unknown_reporter_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            os.chdir(tmp)
            with (
                patch.object(sys, "argv", ["ctrlrunner", "--reporter", "list"]),
                self.assertRaises(SystemExit) as ctx,
            ):
                main()
        self.assertEqual(ctx.exception.code, 1)


class EmptySelectionExitCodeTests(unittest.TestCase):
    """A run that selected zero tests must exit
    with code 4, not 0 -- a typo'd --tag/--test-id or a wrong root must
    never produce a green CI run that tested nothing. Rerun flags
    matching zero remain a legitimate exit-0 success."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _make_passing_suite(self, tmp, module_name):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / f"test_{module_name}.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
        )

    def _run_cli_code(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit) as ctx:
            main()
        return ctx.exception.code

    def test_no_tests_matching_tag_filter_exits_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_passing_suite(tmp, "empty_tag_demo")
            os.chdir(tmp)
            code = self._run_cli_code(["--tag", "nonexistent", "--reporter", "dots"])
        self.assertEqual(code, 4)

    def test_empty_root_with_no_filters_exits_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tests").mkdir()
            os.chdir(tmp)
            code = self._run_cli_code(["--reporter", "dots"])
        self.assertEqual(code, 4)

    def test_last_failed_matching_zero_still_exits_0(self):
        # "--last-failed matched nothing" means the previous run had no
        # failures -- a legitimate success, never exit 4.
        with tempfile.TemporaryDirectory() as tmp:
            self._make_passing_suite(tmp, "lf_zero_demo")
            os.chdir(tmp)
            self.assertEqual(self._run_cli_code(["--reporter", "dots"]), 0)
            registry.reset()
            code = self._run_cli_code(["--last-failed", "--reporter", "dots"])
        self.assertEqual(code, 0)


class HtmlReportTimelineFieldsTests(unittest.TestCase):
    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def test_html_report_embeds_run_started_at_and_num_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_timeline_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            os.chdir(tmp)
            with (
                patch.object(
                    sys,
                    "argv",
                    ["ctrlrunner", "-n", "1", "--reporter", "dots", "--html-report"],
                ),
                self.assertRaises(SystemExit),
            ):
                main()
            html = Path("reports/html-report/report.html").read_text(encoding="utf-8")

        m = re.search(r"window\.__CTRLRUNNER_REPORT__ = (.*?);</script>", html, re.DOTALL)
        data = json.loads(m.group(1))
        self.assertIsNotNone(data["runStartedAt"])
        self.assertIsNotNone(data["runDuration"])
        self.assertEqual(data["numWorkers"], 1)
        self.assertIsNotNone(data["tests"][0]["startedAt"])
        self.assertEqual(data["tests"][0]["workerId"], 1)


if __name__ == "__main__":
    unittest.main()
