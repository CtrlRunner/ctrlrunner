"""
Dedicated backward-compatibility suite. This is the single most
important test category in the whole roadmap, and scattering its
assertions across every feature's own test file makes it too easy to
miss a regression. This file is where every "absent config -> zero
behavior change" and "single/no-project run stays exactly like
before" guarantee lives, consolidated, so a future contributor
checking backward compatibility has exactly one file to read instead
of eight.

Each test below either duplicates (grouping's, since it's foundational
to that file's own other tests too) or was moved wholesale from
(tag_registry, projects, quarantine) the feature's own test file.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ctrlrunner.cli import main
from ctrlrunner.config.config import load_config
from ctrlrunner.config.projects import ProjectConfig, load_projects, run_projects
from ctrlrunner.config.tag_registry import load_tag_registry
from ctrlrunner.core import registry
from ctrlrunner.execution.orchestrator import Orchestrator
from ctrlrunner.execution.quarantine import resolve_quarantine_config
from ctrlrunner.reporting.grouping import DEFAULT_DIMENSIONS, load_grouping_dimensions


class AbsentConfigDefaultsToOffTests(unittest.TestCase):
    """Every opt-in [ctrlrunner.*] section, when absent entirely, must
    resolve to its pre-feature default: None/{}/DEFAULT_DIMENSIONS,
    never a new required key, never a behavior change."""

    def test_grouping_absent_returns_module_only_default(self):
        self.assertEqual(load_grouping_dimensions({}), DEFAULT_DIMENSIONS)

    def test_registered_tags_absent_returns_none(self):
        self.assertIsNone(load_tag_registry({}))

    def test_projects_absent_returns_empty_dict(self):
        self.assertEqual(load_projects({}), {})

    def test_quarantine_absent_returns_none(self):
        self.assertIsNone(resolve_quarantine_config({}))


class SingleProjectRunUnchangedTests(unittest.TestCase):
    """A single-project or no-project run must keep today's exact
    unprefixed test_id / single-<testsuite> JUnit shape -- the
    multi-project prefixing/wrapping introduced in section 4.4 only
    ever applies when 2+ projects are genuinely active in one
    invocation."""

    def setUp(self):
        registry.reset()

    def _make_layout(self, tmp):
        web = Path(tmp) / "tests" / "web"
        web.mkdir(parents=True)
        (web / "test_backcompat_web.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_login():\n    pass\n"
        )
        return web

    def test_run_projects_with_a_single_project_keeps_ids_unprefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = self._make_layout(tmp)
            projects = {"smoke": ProjectConfig(name="smoke", tests_dir=[str(web)])}
            combined, multi = run_projects(
                ["smoke"],
                projects,
                base_root="tests",
                base_num_workers=1,
                base_timeout=30.0,
            )
            self.assertFalse(multi)
            ids = [r.test_id for r in combined.results]
            self.assertTrue(all(not i.startswith("[") for i in ids))
            self.assertTrue(all(r.project == "smoke" for r in combined.results))


class NoHistoryStoreRoundRobinUnchangedTests(unittest.TestCase):
    """Orchestrator without a history_store still runs every test to
    completion -- duration-weighted packing is opt-in via history_store
    being non-None; without it all units get equal fallback weights
    (round-robin over units, which are whole files by default)."""

    def setUp(self):
        registry.reset()

    def test_orchestrator_without_history_store_behaves_like_round_robin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backcompat_sharding_unaffected_suite"
            root.mkdir()
            tests_src = "\n\n".join(f"@test()\ndef test_{i}():\n    pass" for i in range(6))
            (root / "test_backcompat_shard.py").write_text(
                "from ctrlrunner import test\n\n" + tests_src + "\n"
            )

            orch = Orchestrator(str(root), 3, 10.0)  # history_store=None
            reporter = orch.run()
            self.assertEqual(len(reporter.results), 6)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))


class ConfigNestingGotchaTests(unittest.TestCase):
    """Regression test for a real gotcha hit during manual verification:
    a bare `[grouping]` header in ctrlrunner.toml is a sibling TOML table,
    NOT nested under `[ctrlrunner]` -- load_config() would silently drop
    it. `[ctrlrunner.grouping]` is the correct nesting."""

    def test_correct_nesting_is_picked_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ctrlrunner.toml"
            path.write_text(
                "[ctrlrunner.grouping]\n"
                "dimensions = [\n"
                '  { name = "team", strategy = "tag_prefix", prefix = "team_" },\n'
                "]\n"
            )
            config = load_config(str(path))
            dims = load_grouping_dimensions(config)
            # "module" is force-added (prepended) since the user's
            # custom dimension list omitted it -- it's always present
            # for backward compatibility.
            self.assertEqual([d.name for d in dims], ["module", "team"])

    def test_bare_grouping_header_is_silently_a_sibling_table_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
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


class CliEndToEndBackwardCompatibilityTests(unittest.TestCase):
    """Same guarantees as SingleProjectRunUnchangedTests, verified
    through the real CLI entry point end to end (report files on disk),
    not just the Python-level run_projects() return value."""

    def setUp(self):
        registry.reset()
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)

    def _run_cli(self, argv):
        with patch.object(sys, "argv", ["ctrlrunner"] + argv), self.assertRaises(SystemExit):
            main()

    def test_no_project_flag_produces_todays_exact_single_testsuite_shape(self):
        import json
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_backcompat_cli_shape.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            os.chdir(tmp)
            self._run_cli(["--reporter", "json"])
            data = json.loads(Path("reports/html-report/results.json").read_text())
            root_el = ET.parse("reports/html-report/report.xml").getroot()

        self.assertEqual(root_el.tag, "testsuite")
        self.assertEqual(data["projects"], [])
        self.assertEqual(data["tests"][0]["id"], "tests.test_backcompat_cli_shape::test_x")


if __name__ == "__main__":
    unittest.main()
