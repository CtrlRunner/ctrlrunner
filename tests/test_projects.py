import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ctrlrunner.config.projects import (
    ProjectConfig,
    load_projects,
    resolve_project_names,
    run_projects,
)


class LoadProjectsTests(unittest.TestCase):
    def test_parses_single_project(self):
        projects = load_projects(
            {
                "projects": {
                    "smoke": {
                        "tests_dir": ["tests/web", "tests/e2e"],
                        "tags": ["smoke"],
                        "timeout": 15,
                    }
                }
            }
        )
        self.assertEqual(set(projects), {"smoke"})
        p = projects["smoke"]
        self.assertEqual(p.name, "smoke")
        self.assertEqual(p.tests_dir, ["tests/web", "tests/e2e"])
        self.assertEqual(p.tags, ["smoke"])
        self.assertEqual(p.timeout, 15)
        self.assertIsNone(p.num_workers)

    def test_string_tests_dir_is_normalized_to_a_list(self):
        projects = load_projects({"projects": {"smoke": {"tests_dir": "tests/web"}}})
        self.assertEqual(projects["smoke"].tests_dir, ["tests/web"])

    def test_missing_tests_dir_raises(self):
        with self.assertRaises(ValueError):
            load_projects({"projects": {"smoke": {"tags": ["smoke"]}}})

    def test_multiple_projects_parsed_independently(self):
        projects = load_projects(
            {
                "projects": {
                    "smoke": {"tests_dir": ["tests/web"], "timeout": 15},
                    "regression": {"tests_dir": ["tests/web"], "timeout": 30},
                }
            }
        )
        self.assertEqual(set(projects), {"smoke", "regression"})
        self.assertEqual(projects["smoke"].timeout, 15)
        self.assertEqual(projects["regression"].timeout, 30)

    def test_defaults_when_optional_fields_absent(self):
        projects = load_projects({"projects": {"smoke": {"tests_dir": ["tests"]}}})
        p = projects["smoke"]
        self.assertEqual(p.tags, [])
        self.assertIsNone(p.timeout)
        self.assertIsNone(p.num_workers)
        self.assertIsNone(p.fully_parallel)

    def test_num_workers_auto_and_percent_load_as_raw_spellings(self):
        # raw spec is stored (resolution happens at run time on the
        # machine that runs it), but validated at load so a typo fails
        # fast
        projects = load_projects(
            {
                "projects": {
                    "a": {"tests_dir": ["ta"], "num_workers": "auto"},
                    "b": {"tests_dir": ["tb"], "num_workers": "50%"},
                }
            }
        )
        self.assertEqual(projects["a"].num_workers, "auto")
        self.assertEqual(projects["b"].num_workers, "50%")

    def test_invalid_num_workers_raises_with_project_name(self):
        with self.assertRaises(ValueError) as ctx:
            load_projects({"projects": {"smoke": {"tests_dir": ["t"], "num_workers": "fast"}}})
        self.assertIn("smoke", str(ctx.exception))

    def test_invalid_timeout_raises_with_project_name(self):
        # load_projects' documented contract is "fail fast, before any
        # test runs" -- a string timeout passing load-time validation
        # only to explode mid-run inside the Orchestrator breaks it.
        with self.assertRaises(ValueError) as ctx:
            load_projects({"projects": {"smoke": {"tests_dir": ["t"], "timeout": "fast"}}})
        self.assertIn("smoke", str(ctx.exception))
        self.assertIn("timeout", str(ctx.exception))

    def test_valid_numeric_timeouts_accepted(self):
        projects = load_projects(
            {
                "projects": {
                    "ints": {"tests_dir": ["t"], "timeout": 30},
                    "floats": {"tests_dir": ["t"], "timeout": 12.5},
                    "absent": {"tests_dir": ["t"]},
                }
            }
        )
        self.assertEqual(projects["ints"].timeout, 30)
        self.assertEqual(projects["floats"].timeout, 12.5)
        self.assertIsNone(projects["absent"].timeout)

    def test_fully_parallel_parsed_and_validated(self):
        projects = load_projects(
            {"projects": {"smoke": {"tests_dir": ["t"], "fully_parallel": True}}}
        )
        self.assertIs(projects["smoke"].fully_parallel, True)

        with self.assertRaises(ValueError) as ctx:
            load_projects({"projects": {"smoke": {"tests_dir": ["t"], "fully_parallel": "yes"}}})
        self.assertIn("smoke", str(ctx.exception))


class ProjectWorkerPrecedenceTests(unittest.TestCase):
    """num_workers and fully_parallel per-project precedence, observed
    through the Orchestrators run_projects actually constructs."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def _run_two_projects(self, tmp, projects_kwargs, run_kwargs):
        captured = []
        from ctrlrunner.execution.orchestrator import Orchestrator

        real_init = Orchestrator.__init__

        def spy_init(self_orch, root, num_workers, timeout, **kwargs):
            captured.append(
                {"num_workers": num_workers, "fully_parallel": kwargs.get("fully_parallel")}
            )
            return real_init(self_orch, root, num_workers, timeout, **kwargs)

        for name in ("a", "b"):
            root = Path(tmp) / f"tests_{name}"
            root.mkdir()
            (root / f"test_{name}.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )

        projects = {
            name: ProjectConfig(
                name=name,
                tests_dir=[str(Path(tmp) / f"tests_{name}")],
                **projects_kwargs.get(name, {}),
            )
            for name in ("a", "b")
        }
        with mock.patch.object(Orchestrator, "__init__", spy_init):
            run_projects(["a", "b"], projects, base_root="tests", base_timeout=30.0, **run_kwargs)
        return captured

    def test_project_num_workers_auto_resolves_to_concrete_int(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
            mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=9),
        ):
            captured = self._run_two_projects(
                tmp,
                {"a": {"num_workers": "auto"}, "b": {"num_workers": 2}},
                {"base_num_workers": 1},
            )
        self.assertEqual(captured[0]["num_workers"], 8)  # auto = 9 - 1
        self.assertEqual(captured[1]["num_workers"], 2)

    def test_cli_num_workers_auto_beats_project_int(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
            mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=5),
        ):
            captured = self._run_two_projects(
                tmp,
                {"a": {"num_workers": 2}},
                {"base_num_workers": 1, "cli_num_workers": "auto"},
            )
        self.assertEqual(captured[0]["num_workers"], 4)
        self.assertEqual(captured[1]["num_workers"], 4)

    def test_project_fully_parallel_overrides_base_in_both_directions(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            captured = self._run_two_projects(
                tmp,
                {"a": {"fully_parallel": True}},
                {"base_num_workers": 1, "base_fully_parallel": False},
            )
        self.assertIs(captured[0]["fully_parallel"], True)  # project override
        self.assertIs(captured[1]["fully_parallel"], False)  # inherits base

        from ctrlrunner.core import registry

        registry.reset()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            captured = self._run_two_projects(
                tmp,
                {"a": {"fully_parallel": False}},
                {"base_num_workers": 1, "base_fully_parallel": True},
            )
        self.assertIs(captured[0]["fully_parallel"], False)  # explicit opt-out
        self.assertIs(captured[1]["fully_parallel"], True)


class SharedFailPolicyAcrossProjectsTests(unittest.TestCase):
    """Real run_projects() verification that a FailPolicyState threshold
    crossed in one project stops a later project from ever starting --
    the whole reason fail_policy is a single object shared across every
    project's Orchestrator, not a fresh one per project."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def test_threshold_in_first_project_prevents_second_from_starting(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "sharedfp_a"
            b = Path(tmp) / "sharedfp_b"
            a.mkdir()
            b.mkdir()
            (a / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_1():\n    assert False\n\n"
                "@test()\ndef test_2():\n    assert False\n"
            )
            (b / "test_b.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_3():\n    pass\n"
            )
            projects = {
                "p1": ProjectConfig(name="p1", tests_dir=[str(a)]),
                "p2": ProjectConfig(name="p2", tests_dir=[str(b)]),
            }
            fp = FailPolicyState(max_failures=2)
            combined, multi = run_projects(
                ["p1", "p2"],
                projects,
                base_root="x",
                base_num_workers=1,
                base_timeout=10.0,
                fail_policy=fp,
            )
            self.assertEqual(fp.cancel_reason, "max_failures")
            # p2 never got to start, but its one test still gets an
            # explicit report entry (not_run) instead of vanishing --
            # the same visibility an unstarted-within-a-project test
            # already gets.
            p1_results = [r for r in combined.results if r.project == "p1"]
            p2_results = [r for r in combined.results if r.project == "p2"]
            self.assertEqual(len(p1_results), 2)
            self.assertEqual(len(p2_results), 1)
            self.assertTrue(all(r.outcome == "not_run" for r in p2_results))
            self.assertEqual(len(combined.results), 3)

    def test_without_fail_policy_both_projects_run_normally(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "nofp_a"
            b = Path(tmp) / "nofp_b"
            a.mkdir()
            b.mkdir()
            (a / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_1():\n    assert False\n"
            )
            (b / "test_b.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_2():\n    pass\n"
            )
            projects = {
                "p1": ProjectConfig(name="p1", tests_dir=[str(a)]),
                "p2": ProjectConfig(name="p2", tests_dir=[str(b)]),
            }
            combined, multi = run_projects(
                ["p1", "p2"],
                projects,
                base_root="x",
                base_num_workers=1,
                base_timeout=10.0,
            )
            self.assertEqual({r.project for r in combined.results}, {"p1", "p2"})


class ModuleCollisionAcrossProjectsTests(unittest.TestCase):
    """Two projects that each contain a same-named relative test
    file (e.g. tests/test_x.py) must not collide -- project B's
    force_reload must never end up re-running project A's module."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def test_two_projects_with_identically_named_relative_test_files_both_run_their_own(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "collision_a" / "tests"
            b = Path(tmp) / "collision_b" / "tests"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            # Same relative filename ("tests/test_x.py") under two
            # different project roots, with DIFFERENT test bodies --
            # the old dotted-name scheme made both resolve to the same
            # sys.modules key ("tests.test_x").
            (a / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_from_a():\n    pass\n"
            )
            (b / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_from_b():\n    pass\n"
            )
            projects = {
                "proj_a": ProjectConfig(name="proj_a", tests_dir=[str(a)]),
                "proj_b": ProjectConfig(name="proj_b", tests_dir=[str(b)]),
            }
            combined, multi = run_projects(
                ["proj_a", "proj_b"],
                projects,
                base_root="x",
                base_num_workers=1,
                base_timeout=10.0,
            )

        names_by_project = {}
        for r in combined.results:
            names_by_project.setdefault(r.project, set()).add(r.test_id.split("::")[-1])

        # Each project must see its OWN test -- not the other project's
        # test, and not both projects seeing the same one.
        self.assertEqual(names_by_project.get("proj_a"), {"test_from_a"})
        self.assertEqual(names_by_project.get("proj_b"), {"test_from_b"})


class FixtureRegistryClearedBetweenProjectsTests(unittest.TestCase):
    """A fixture defined only in project 1's conftest must not
    silently resolve for project 2 -- clear_tests() alone left it
    registered, so project 2 got project 1's fixture instead of an
    'Unknown fixture' error."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def test_project_2_does_not_see_project_1s_fixture(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "fixtureclear_a"
            b = Path(tmp) / "fixtureclear_b"
            a.mkdir()
            b.mkdir()
            (a / "conftest.py").write_text(
                "from ctrlrunner import fixture\n\n"
                "@fixture()\ndef only_in_a():\n    yield 'a-value'\n"
            )
            (a / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_uses_a_fixture(only_in_a):\n    assert only_in_a == 'a-value'\n"
            )
            (b / "test_b.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_uses_missing_fixture(only_in_a):\n    pass\n"
            )
            projects = {
                "p1": ProjectConfig(name="p1", tests_dir=[str(a)]),
                "p2": ProjectConfig(name="p2", tests_dir=[str(b)]),
            }
            combined, multi = run_projects(
                ["p1", "p2"],
                projects,
                base_root="x",
                base_num_workers=1,
                base_timeout=10.0,
            )

        p1_result = next(r for r in combined.results if r.project == "p1")
        p2_result = next(r for r in combined.results if r.project == "p2")
        self.assertEqual(p1_result.outcome, "passed")
        # p2's test references a fixture name that doesn't exist in ITS
        # OWN project -- it must fail loudly (Unknown fixture), never
        # silently resolve to project 1's leftover fixture.
        self.assertEqual(p2_result.outcome, "failed")
        self.assertIn("nknown fixture", p2_result.error or "")


class UpfrontStrictTagValidationTests(unittest.TestCase):
    """Strict tag validation must see every requested project's
    tests BEFORE any project starts -- otherwise project 1 runs to
    completion and only THEN does project 2's bad tag abort the whole
    invocation, discarding project 1's results."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def test_bad_tag_in_second_project_is_caught_before_first_project_runs(self):
        from ctrlrunner.config.tag_registry import TagRegistry, TagValidationError

        marker = None
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "strict_a"
            b = Path(tmp) / "strict_b"
            a.mkdir()
            b.mkdir()
            marker = Path(tmp) / "project_1_ran.marker"
            (a / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                f"@test()\ndef test_1():\n    open({str(marker)!r}, 'w').close()\n"
            )
            (b / "test_b.py").write_text(
                "from ctrlrunner import test\n\n@test(tags=['typo_tag'])\ndef test_2():\n    pass\n"
            )
            projects = {
                "p1": ProjectConfig(name="p1", tests_dir=[str(a)]),
                "p2": ProjectConfig(name="p2", tests_dir=[str(b)]),
            }
            tag_registry = TagRegistry(entries=["smoke"], strict=True)

            with self.assertRaises(TagValidationError):
                run_projects(
                    ["p1", "p2"],
                    projects,
                    base_root="x",
                    base_num_workers=1,
                    base_timeout=10.0,
                    tag_registry=tag_registry,
                )

            # project 1 must never have run at all -- the whole point
            # of catching this up front instead of mid-invocation.
            self.assertFalse(marker.exists())


class CoverageConfigThreadingTests(unittest.TestCase):
    """coverage_config must be threaded through run_projects() into every
    project's Orchestrator(...) call unchanged (the same object identity),
    the same way fail_policy/history_store already are."""

    def setUp(self):
        from ctrlrunner.core import registry

        registry.reset()

    def test_coverage_config_threaded_to_orchestrator(self):
        captured = {}

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)

            def run(self):
                return SimpleNamespace(results=[])

        # Orchestrator is imported locally inside run_projects() (`from
        # ..execution.orchestrator import Orchestrator`), so it must be
        # patched at its defining module, not at ctrlrunner.config.projects
        # (which never binds an `Orchestrator` name of its own).
        with mock.patch("ctrlrunner.execution.orchestrator.Orchestrator", FakeOrchestrator):
            coverage_config = object()  # identity check only -- must be the same object
            projects = {"proj1": ProjectConfig(name="proj1", tests_dir=["."])}
            run_projects(
                ["proj1"],
                projects,
                base_root=".",
                base_num_workers=1,
                base_timeout=1.0,
                coverage_config=coverage_config,
            )
        self.assertIs(captured["coverage_config"], coverage_config)


class ResolveProjectNamesTests(unittest.TestCase):
    def test_known_names_pass_through_unchanged(self):
        available = {"smoke": ProjectConfig(name="smoke", tests_dir=["tests"])}
        self.assertEqual(resolve_project_names(["smoke"], available), ["smoke"])

    def test_unknown_name_raises_with_available_list(self):
        available = {"smoke": ProjectConfig(name="smoke", tests_dir=["tests"])}
        with self.assertRaises(ValueError) as ctx:
            resolve_project_names(["typo"], available)
        self.assertIn("smoke", str(ctx.exception))
        self.assertIn("typo", str(ctx.exception))

    def test_no_projects_configured_at_all_message_is_clear(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_project_names(["smoke"], {})
        self.assertIn("none configured", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
