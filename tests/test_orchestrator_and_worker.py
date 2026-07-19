import contextlib
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from ctrlrunner.config.projects import ProjectConfig, run_projects
from ctrlrunner.core import registry
from ctrlrunner.core.registry import Fixture
from ctrlrunner.execution.coverage_support import CoverageConfig, finalize_coverage
from ctrlrunner.execution.orchestrator import (
    Orchestrator,
    _chunk,
    discover_and_import,
    discover_conftests,
    discover_modules,
)
from ctrlrunner.execution.worker import (
    _call_on_failure,
    _extract_aria_snapshot,
    _safe_test_dir,
    _trim_aria_snapshot_from_steps,
    capture_artifacts,
)
from ctrlrunner.reporting.reporter import Result


class NearTimeoutBadgeTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_a_test_finishing_close_to_its_timeout_is_flagged_near_timeout(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "near_timeout_suite"
            root.mkdir()
            # timeout=2 / sleep=1.8 = 90% of the timeout, comfortably
            # above the 80% threshold with 0.2s of absolute slack so a
            # slow runner can't hard-kill it, yet test_fast (a no-op)
            # stays far below.
            (root / "test_a.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=2)\ndef test_close():\n    time.sleep(1.8)\n\n"
                "@test(timeout=2)\ndef test_fast():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 2.0)
            reporter = orch.run()

        by_name = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertTrue(by_name["test_close"].near_timeout)
        self.assertFalse(by_name["test_fast"].near_timeout)


class ParamMetadataExecutionTests(unittest.TestCase):
    """param(xfail=/skip=) must ride the existing runtime fail()/SkipTest
    pipelines in the worker -- per-combination outcomes, not per-test."""

    def setUp(self):
        registry.reset()

    def test_per_param_xfail_and_skip_outcomes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "param_meta_suite"
            root.mkdir()
            (root / "test_params.py").write_text(
                "from ctrlrunner import test, parametrize, param\n\n"
                "@test(timeout=10)\n"
                "@parametrize('x', [\n"
                "    param(1, id='plain'),\n"
                "    param(2, id='xfail_fails', xfail='bug 7438797'),\n"
                "    param(3, id='xfail_passes_strict', xfail='bug', xfail_strict=True),\n"
                "    param(4, id='xfail_passes_nonstrict', xfail=True, xfail_strict=False),\n"
                "    param(5, id='skipped_combo', skip='not in this env'),\n"
                "])\n"
                "def test_p(x):\n"
                "    assert x != 2\n"
            )
            orch = Orchestrator(str(root), 1, 30.0)
            reporter = orch.run()
        by_id = {r.test_id.split("[")[-1].rstrip("]"): r for r in reporter.results}

        self.assertEqual(by_id["plain"].outcome, "passed")
        self.assertEqual(by_id["xfail_fails"].outcome, "expected_failure")
        # strict xfail that unexpectedly passes -> failed
        self.assertEqual(by_id["xfail_passes_strict"].outcome, "failed")
        self.assertIn("Unexpected pass", by_id["xfail_passes_strict"].error or "")
        # non-strict xfail that passes -> passed, flagged via property
        self.assertEqual(by_id["xfail_passes_nonstrict"].outcome, "passed")
        self.assertEqual(by_id["xfail_passes_nonstrict"].properties.get("unexpected_pass"), "true")
        self.assertEqual(by_id["skipped_combo"].outcome, "skipped")
        self.assertEqual(by_id["skipped_combo"].error, "not in this env")

    def test_expected_failure_is_not_retried(self):
        # An xfail test fails *by design* -- re-running it for every
        # configured retry burns attempts on an outcome that cannot
        # improve (pytest-rerunfailures and Playwright both treat
        # expected failures as final). The retry loop must break on
        # 'expected_failure' the same way it breaks on skipped/fixme.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "xfail_retry_suite"
            root.mkdir()
            (root / "test_xr.py").write_text(
                "_state = {'n': 0}\n"
                "from ctrlrunner import test, parametrize, param\n\n"
                "@test(retries=2)\n"
                # xfail=True (no description) so the reported error is the
                # traceback itself, which carries the body's run counter
                "@parametrize('x', [param(1, id='xf', xfail=True)])\n"
                "def test_xfails(x):\n"
                "    _state['n'] += 1\n"
                "    assert False, f\"ran {_state['n']} times\"\n"
            )
            orch = Orchestrator(str(root), 1, 30.0)
            reporter = orch.run()
        r = reporter.results[0]
        self.assertEqual(r.outcome, "expected_failure")
        self.assertEqual(r.attempts, 1)
        # the error text carries the body's own run counter -- proves the
        # body itself only executed once, not just that attempts said so
        self.assertIn("ran 1 times", r.error or "")

    def test_param_skip_never_resolves_fixtures(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "param_skip_suite"
            root.mkdir()
            (root / "test_skip.py").write_text(
                "from ctrlrunner import fixture, test, parametrize, param\n\n"
                "@fixture()\n"
                "def exploding():\n"
                "    raise RuntimeError('fixture must not be resolved for skipped combo')\n\n"
                "@test(timeout=10)\n"
                "@parametrize('x', [param(1, id='sk', skip='env')])\n"
                "def test_s(x, exploding):\n"
                "    pass\n"
            )
            orch = Orchestrator(str(root), 1, 30.0)
            reporter = orch.run()
        result = reporter.results[0]
        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(result.error, "env")


class ChunkTests(unittest.TestCase):
    def test_chunk_distributes_round_robin(self):
        result = _chunk(["a", "b", "c", "d", "e"], 2)
        self.assertEqual(result, [["a", "c", "e"], ["b", "d"]])

    def test_chunk_drops_empty_buckets_when_fewer_items_than_workers(self):
        result = _chunk(["a"], 4)
        self.assertEqual(result, [["a"]])

    def test_chunk_empty_input(self):
        self.assertEqual(_chunk([], 3), [])


class DiscoverModulesTests(unittest.TestCase):
    def test_finds_test_files_as_dotted_module_names(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            (root / "sub").mkdir(parents=True)
            (root / "test_one.py").write_text("")
            (root / "sub" / "test_two.py").write_text("")
            (root / "not_a_test.py").write_text("")

            modules = discover_modules(str(root))
            resolved = [m.resolve() for m in modules]
            self.assertIn((root / "test_one.py").resolve(), resolved)
            self.assertIn((root / "sub" / "test_two.py").resolve(), resolved)
            self.assertFalse(any("not_a_test" in str(m) for m in modules))

    def test_file_path_root_returns_just_that_file(self):
        # Regression: `ctrlrunner suite/test_one.py` (pytest-style single-file
        # selection) used to silently collect 0 tests -- rglob() on a file
        # path (not a directory) always returns empty, no error raised.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_one.py").write_text("")
            (root / "test_two.py").write_text("")

            modules = discover_modules(str(root / "test_one.py"))

            self.assertEqual([m.resolve() for m in modules], [(root / "test_one.py").resolve()])


class DiscoverConftestsTests(unittest.TestCase):
    def test_finds_conftest_files_shallowest_first(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            (root / "sub").mkdir(parents=True)
            (root / "conftest.py").write_text("")
            (root / "sub" / "conftest.py").write_text("")

            modules = discover_conftests(str(root))
            self.assertEqual(len(modules), 2)
            self.assertEqual(modules[0].resolve(), (root / "conftest.py").resolve())
            self.assertEqual(modules[1].resolve(), (root / "sub" / "conftest.py").resolve())

    def test_no_conftest_returns_empty_list(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_one.py").write_text("")
            self.assertEqual(discover_conftests(str(root)), [])

    def test_file_path_root_finds_sibling_conftest(self):
        # A single-file root must still pick up the conftest.py that would
        # have been found had the containing directory been passed instead.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text("")
            (root / "test_one.py").write_text("")

            modules = discover_conftests(str(root / "test_one.py"))

            self.assertEqual([m.resolve() for m in modules], [(root / "conftest.py").resolve()])

    def test_ancestor_conftests_discovered_up_to_git_boundary(self):
        # A run scoped to a deep subdirectory must still pick up conftest.py
        # files defined at ancestor levels (project root, intermediate
        # dirs) -- previously only descendants of `root` were found at
        # all, so shared setup registered above a scoped run's root was
        # silently skipped.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "conftest.py").write_text("")
            mid = project_root / "spec" / "web"
            mid.mkdir(parents=True)
            (mid / "conftest.py").write_text("")
            sub = mid / "gepm_dataset"
            sub.mkdir()
            (sub / "conftest.py").write_text("")

            modules = [m.resolve() for m in discover_conftests(str(sub))]

            self.assertEqual(
                modules,
                [
                    (project_root / "conftest.py").resolve(),
                    (mid / "conftest.py").resolve(),
                    (sub / "conftest.py").resolve(),
                ],
            )

    def test_ancestor_walk_stops_at_git_boundary_not_further(self):
        # A conftest.py above the .git boundary must NOT be picked up --
        # the walk stops there, same convention as
        # migrate/config_migrator.py's find_pyproject.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            outer = Path(tmp) / "outer"
            outer.mkdir()
            (outer / "conftest.py").write_text("")  # outside the repo -- must be ignored
            project_root = outer / "project"
            (project_root / ".git").mkdir(parents=True)
            sub = project_root / "sub"
            sub.mkdir()

            modules = [m.resolve() for m in discover_conftests(str(sub))]

            self.assertEqual(modules, [])

    def test_project_root_promoted_to_front_even_if_already_on_sys_path(self):
        # A dev/editable install (`uv run`, `pip install -e .`) can
        # already have the project root on sys.path via a .pth file or
        # similar -- just far down the list, after site-packages/.venv
        # entries. A naive "insert only if not already present" guard
        # would see it there and leave it in that low-priority spot,
        # silently defeating the ancestor-priority ordering below it
        # (this is exactly what a real uv-run environment hit: the
        # project root's conftest.py lost to a closer, unrelated one
        # even after the ordering direction itself was fixed).
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "conftest.py").write_text("")
            mid = project_root / "spec" / "web"
            mid.mkdir(parents=True)
            (mid / "conftest.py").write_text("")
            sub = mid / "gepm_dataset"
            sub.mkdir()
            (sub / "conftest.py").write_text("")

            original_sys_path = list(sys.path)
            try:
                # Simulate the polluted environment: project root already
                # on sys.path, buried at the end -- as a venv/editable
                # install would leave it, not freshly inserted at the front.
                sys.path.append(str(project_root))

                discover_conftests(str(sub))

                self.assertEqual(Path(sys.path[0]).resolve(), project_root.resolve())
            finally:
                sys.path[:] = original_sys_path


class AncestorConftestImportResolutionTests(unittest.TestCase):
    """End-to-end regression: a bare `from conftest import x` in a test
    file scoped several directories below the project root must resolve
    to the project-root conftest.py, not silently pick up whichever
    same-named conftest.py Python's own import machinery happens to find
    first."""

    def test_bare_conftest_import_reaches_the_project_root_definition(self):
        from ctrlrunner.execution.worker import module_name_for_path

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "conftest.py").write_text(
                "def shared_guard(value):\n    return ('root-guard', value)\n"
            )
            sub = project_root / "spec" / "web" / "gepm_dataset"
            sub.mkdir(parents=True)
            # A DIFFERENT, unrelated conftest.py at the scoped level --
            # must not shadow the root one for the bare import below.
            (sub / "conftest.py").write_text("LOCAL_ONLY = True\n")
            (sub / "test_x.py").write_text(
                "from conftest import shared_guard\n\nRESULT = shared_guard(42)\n"
            )

            discover_and_import(str(sub), force_reload=True)

            mod = sys.modules[module_name_for_path(sub / "test_x.py")]
            self.assertEqual(mod.RESULT, ("root-guard", 42))

    def test_bare_conftest_import_reaches_root_even_with_an_intervening_ancestor_conftest(self):
        # Regression for the actual reported failure: when the scoped run
        # root is a directory BELOW one that itself has its own unrelated
        # conftest.py (so the ancestor walk collects TWO+ conftest.py
        # files, not one), sys.path insertion order must still put the
        # project root ahead of the intervening one. A prior version of
        # discover_conftests' insertion loop reversed that order, so the
        # nearer, unrelated conftest.py won the bare `from conftest
        # import x` lookup instead -- this only surfaces with 2+
        # ancestors, which test_bare_conftest_import_reaches_the_
        # project_root_definition above (a single ancestor) can't catch.
        from ctrlrunner.execution.worker import module_name_for_path

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_root = Path(tmp) / "project"
            (project_root / ".git").mkdir(parents=True)
            (project_root / "conftest.py").write_text(
                "def shared_guard(value):\n    return ('root-guard', value)\n"
            )
            gepm_dataset = project_root / "spec" / "web" / "gepm_dataset"
            gepm_dataset.mkdir(parents=True)
            # An intervening ancestor conftest.py, closer to the test file
            # than the project root, that does NOT define shared_guard --
            # must not shadow the root one for the bare import below.
            (gepm_dataset / "conftest.py").write_text("LOCAL_ONLY = True\n")
            tabs = gepm_dataset / "gepm_dashboard_tabs"
            tabs.mkdir()
            (tabs / "test_x.py").write_text(
                "from conftest import shared_guard\n\nRESULT = shared_guard(42)\n"
            )

            discover_and_import(str(tabs), force_reload=True)

            mod = sys.modules[module_name_for_path(tabs / "test_x.py")]
            self.assertEqual(mod.RESULT, ("root-guard", 42))


class FilePathRootOrchestratorTests(unittest.TestCase):
    """End-to-end regression for the CLI bug: `ctrlrunner suite/test_one.py`
    (a single file, pytest-style) must actually run that file's tests
    instead of silently selecting zero."""

    def setUp(self):
        registry.reset()

    def test_orchestrator_runs_a_single_file_root(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_one.py").write_text(
                "from ctrlrunner import test\n\n@test(timeout=10)\ndef test_a():\n    pass\n"
            )
            (root / "test_two.py").write_text(
                "from ctrlrunner import test\n\n@test(timeout=10)\ndef test_b():\n    pass\n"
            )
            orch = Orchestrator(str(root / "test_one.py"), 1, 30.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertTrue(reporter.results[0].test_id.endswith("test_a"))


class IndirectParametrizeEndToEndTests(unittest.TestCase):
    """@parametrize(..., indirect=...) through the real worker path:
    a stateful generator fixture (setup + teardown, request.param-driven
    -- the migrated-Playwright-mock shape) receives a different value
    from each test, teardown runs per test, and a single parametrized
    variant is selectable by its full bracketed id."""

    def setUp(self):
        registry.reset()

    SUITE = (
        "from ctrlrunner import fixture, parametrize, test\n\n"
        "import json, os\n\n"
        "LOG = os.environ['INDIRECT_E2E_LOG']\n\n"
        "def _log(event):\n"
        "    with open(LOG, 'a') as f:\n"
        "        f.write(json.dumps(event) + '\\n')\n\n"
        "@fixture()\n"
        "def features_enabled(request):\n"
        "    _log({'setup': request.param})\n"
        "    yield request.param\n"
        "    _log({'teardown': request.param})\n\n"
        "@test(timeout=10)\n"
        "@parametrize('features_enabled', ['flag-a'], indirect=True)\n"
        "def test_one(features_enabled):\n"
        "    assert features_enabled == 'flag-a'\n\n"
        "@test(timeout=10)\n"
        "@parametrize('features_enabled', ['flag-b'], indirect=True)\n"
        "def test_two(features_enabled):\n"
        "    assert features_enabled == 'flag-b'\n"
    )

    def test_each_test_feeds_its_own_value_and_teardown_runs(self):
        import json

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "events.jsonl"
            (root / "test_indirect.py").write_text(self.SUITE)
            with mock.patch.dict(os.environ, {"INDIRECT_E2E_LOG": str(log_path)}):
                orch = Orchestrator(str(root), 1, 30.0)
                reporter = orch.run()

            self.assertEqual(len(reporter.results), 2)
            self.assertEqual({r.outcome for r in reporter.results}, {"passed"})
            self.assertEqual(
                sorted(r.test_id.split("[")[-1].rstrip("]") for r in reporter.results),
                ["flag-a", "flag-b"],
            )
            events = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertIn({"setup": "flag-a"}, events)
            self.assertIn({"teardown": "flag-a"}, events)
            self.assertIn({"setup": "flag-b"}, events)
            self.assertIn({"teardown": "flag-b"}, events)

    def test_single_variant_selectable_by_full_bracketed_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "events.jsonl"
            (root / "test_indirect.py").write_text(self.SUITE)
            with mock.patch.dict(os.environ, {"INDIRECT_E2E_LOG": str(log_path)}):
                orch = Orchestrator(
                    str(root), 1, 30.0, test_ids=["suite.test_indirect::test_two[flag-b]"]
                )
                reporter = orch.run()

            self.assertEqual(len(reporter.results), 1)
            self.assertEqual(reporter.results[0].outcome, "passed")
            self.assertTrue(reporter.results[0].test_id.endswith("[flag-b]"))


class CustomOptionsEndToEndTests(unittest.TestCase):
    """The options dict passed to Orchestrator reaches get_option() in
    a spawned worker, both at module level and inside a fixture --
    mirrors the playwright_config plumbing this feature clones."""

    def setUp(self):
        registry.reset()

    def test_options_reach_module_level_and_fixture_in_worker(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_options.py").write_text(
                "from ctrlrunner import fixture, get_option, test\n\n"
                "MODULE_ENV = get_option('env')\n\n"
                "@fixture()\n"
                "def env_fixture():\n"
                "    return get_option('env')\n\n"
                "@test(timeout=10)\n"
                "def test_module_level(env_fixture):\n"
                "    assert MODULE_ENV == 'staging'\n"
                "    assert env_fixture == 'staging'\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, options={"env": "staging"})
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "passed")

    def test_no_options_means_get_option_returns_default(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_options.py").write_text(
                "from ctrlrunner import get_option, test\n\n"
                "@test(timeout=10)\n"
                "def test_default():\n"
                "    assert get_option('env', 'fallback') == 'fallback'\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")


class AlwaysCaptureOrderingRegressionTests(unittest.TestCase):
    """Regression test: always_capture=True must fire BEFORE fixture
    teardown closes the underlying resource (e.g. a Playwright context),
    not after -- calling on_failure on an already-torn-down resource
    used to silently fail (exception swallowed) and produce no artifact
    at all for a *passing* test."""

    def setUp(self):
        registry.reset()

    def test_always_capture_runs_before_resource_is_torn_down(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_ordering.py").write_text(
                "from ctrlrunner import fixture, test\n\n"
                "class Resource:\n"
                "    def __init__(self):\n"
                "        self.closed = False\n\n"
                "def _capture(value, prefix):\n"
                "    if value.closed:\n"
                "        raise RuntimeError('resource already closed -- ordering bug!')\n"
                "    path = prefix + '.txt'\n"
                "    with open(path, 'w') as f:\n"
                "        f.write('ok')\n"
                "    return path\n\n"
                "@fixture(scope='function', on_failure=_capture, always_capture=True)\n"
                "def resource():\n"
                "    r = Resource()\n"
                "    yield r\n"
                "    r.closed = True\n\n"
                "@test(timeout=10)\n"
                "def test_passes(resource):\n"
                "    assert True\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            self.assertEqual(reporter.results[0].outcome, "passed")
            self.assertEqual(len(reporter.results[0].artifacts), 1)
            self.assertTrue(reporter.results[0].artifacts[0].endswith("resource.txt"))


class CollectionHooksTests(unittest.TestCase):
    """ctrlrunner_itemcollected / ctrlrunner_collection_modifyitems /
    ctrlrunner_collection_finish / ctrlrunner_deselected /
    ctrlrunner_ignore_collect -- pytest's collection-phase hooks, fired
    in the main process around select_tests()."""

    def setUp(self):
        registry.reset()

    def test_modifyitems_reorders_and_removes_and_adds_markers(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def _write(line):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(line + '\\n')\n\n"
                "def ctrlrunner_itemcollected(item):\n"
                "    _write(f'collected:{item.name}')\n\n"
                "def ctrlrunner_collection_modifyitems(items):\n"
                "    items.reverse()\n"
                "    items[:] = [i for i in items if i.name != 'test_dropped']\n"
                "    for i in items:\n"
                "        i.add_marker('touched')\n\n"
                "def ctrlrunner_collection_finish(session):\n"
                "    _write(f'finish:{session.testscollected}')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_one():\n    pass\n\n"
                "@test()\ndef test_dropped():\n    pass\n\n"
                "@test()\ndef test_two():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        executed = [r.test_id.split("::")[-1] for r in reporter.results]
        self.assertEqual(executed, ["test_two", "test_one"])  # reversed, dropped removed
        self.assertTrue(all("touched" in r.tags for r in reporter.results))
        self.assertEqual(
            [line for line in lines if line.startswith("collected:")],
            ["collected:test_one", "collected:test_dropped", "collected:test_two"],
        )
        self.assertIn("finish:3", lines)

    def test_deselected_fires_with_filtered_out_items(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_deselected(items):\n"
                "    with open(LOG, 'a') as f:\n"
                "        for i in items:\n"
                "            f.write(f'deselected:{i.name}\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'smoke'})\ndef test_kept():\n    pass\n\n"
                "@test()\ndef test_filtered():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, tags=["smoke"])
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(lines, ["deselected:test_filtered"])

    def test_ignore_collect_excludes_a_file_before_import(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_ignore_collect(collection_path, config):\n"
                "    if collection_path.name == 'test_skipme.py':\n"
                "        return True\n"
                "    return None\n"
            )
            (root / "test_kept.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            (root / "test_skipme.py").write_text("raise RuntimeError('must never be imported')\n")
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "passed")


class CallPhaseHooksTests(unittest.TestCase):
    """ctrlrunner_runtest_call / ctrlrunner_runtest_makereport /
    ctrlrunner_exception_interact / ctrlrunner_runtest_logfinish --
    Phase 2 of the pytest hook parity plan."""

    def setUp(self):
        registry.reset()

    def test_runtest_call_fires_before_test_body_and_its_exception_fails_the_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_runtest_call(item):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(f'call:{item.nodeid}\\n')\n"
                "    raise RuntimeError('boom from runtest_call')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n"
                "    raise AssertionError('should never execute')\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertIn("boom from runtest_call", result.error)
        self.assertNotIn("should never execute", result.error)  # test body never ran
        self.assertEqual(lines, [f"call:{result.test_id}"])

    def test_makereport_return_value_replaces_the_report_logreport_receives(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_runtest_makereport(item, call):\n"
                "    item.rep_call = 'custom-marker'\n"  # classic pytest pattern
                "    call.report_overridden = True\n"
                "    return call\n\n"  # anything truthy-non-None overrides
                "def ctrlrunner_runtest_logreport(report):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(f'logreport-saw-override:{getattr(report, \"report_overridden\", False)}\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertEqual(lines, ["logreport-saw-override:True"])

    def test_exception_interact_fires_on_failure_with_live_exception_object(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_exception_interact(node, call, report):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(\n"
                "            f'interact:{node.nodeid}:{type(call.excinfo.value).__name__}:'\n"
                "            f'{call.excinfo.value.args[0]}\\n'\n"
                "        )\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    raise ValueError('specific failure text')\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(lines, [f"interact:{result.test_id}:ValueError:specific failure text"])

    def test_exception_interact_does_not_fire_for_a_passing_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_exception_interact(node, call, report):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write('should never fire\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertFalse(log_path.exists())

    def test_logfinish_fires_after_logreport_with_the_same_location(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def _write(line):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(line + '\\n')\n\n"
                "def ctrlrunner_runtest_logreport(report):\n"
                "    _write(f'logreport:{report.nodeid}')\n\n"
                "def ctrlrunner_runtest_logfinish(nodeid, location):\n"
                "    _write(f'logfinish:{nodeid}')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        test_id = reporter.results[0].test_id
        self.assertEqual(lines, [f"logreport:{test_id}", f"logfinish:{test_id}"])


class Phase3HookTests(unittest.TestCase):
    """ctrlrunner_warning_recorded / ctrlrunner_assertrepr_compare /
    ctrlrunner_make_parametrize_id / ctrlrunner_fixture_setup /
    ctrlrunner_fixture_post_finalizer / ctrlrunner_generate_tests --
    Phase 3 of the pytest hook parity plan."""

    def setUp(self):
        registry.reset()

    def test_warning_recorded_fires_for_each_captured_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_warning_recorded(warning_message, when, nodeid, location):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(f'{when}:{nodeid}:{warning_message}\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "import warnings\n"
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n"
                "    warnings.warn('be careful', UserWarning)\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertEqual(len(lines), 1)
        self.assertIn("runtest", lines[0])
        self.assertIn("be careful", lines[0])

    def test_warning_message_is_the_real_warningmessage_object_with_category(self):
        # pytest's hookspec passes the full warnings.WarningMessage
        # instance (.category/.filename/.lineno/.message), not just the
        # bare warning -- a migrated hook reading warning_message.category
        # must not break.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_warning_recorded(warning_message, when, nodeid, location):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(warning_message.category.__name__ + '\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "import warnings\n"
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n"
                "    warnings.warn('be careful', UserWarning)\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertEqual(lines, ["UserWarning"])

    def test_assertrepr_compare_augments_assertion_failure_message(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_assertrepr_compare(config, op, left, right):\n"
                "    if op == '==' and isinstance(left, str) and isinstance(right, str):\n"
                "        return [f'custom string diff: {left!r} != {right!r}']\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    assert 'foo' == 'bar'\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "failed")
        self.assertIn("custom string diff: 'foo' != 'bar'", reporter.results[0].error)

    def test_make_parametrize_id_used_for_the_test_id_suffix(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_make_parametrize_id(config, val, argname):\n"
                "    if argname == 'n':\n"
                "        return f'custom{val}'\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test, parametrize\n\n"
                "@test()\n@parametrize('n', [1, 2])\n"
                "def test_a(n):\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        ids = sorted(r.test_id for r in reporter.results)
        self.assertTrue(any("custom1" in i for i in ids))
        self.assertTrue(any("custom2" in i for i in ids))

    def test_fixture_setup_and_post_finalizer_fire_around_a_fixture(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def _write(line):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(line + '\\n')\n\n"
                "def ctrlrunner_fixture_setup(fixturedef, request):\n"
                "    _write(f'setup:{fixturedef.argname}:{fixturedef.scope}')\n\n"
                "def ctrlrunner_fixture_post_finalizer(fixturedef, request):\n"
                "    _write(f'finalizer:{fixturedef.argname}')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import fixture, test\n\n"
                "@fixture()\ndef resource():\n    yield object()\n\n"
                "@test()\ndef test_a(resource):\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertIn("setup:resource:function", lines)
        self.assertIn("finalizer:resource", lines)
        self.assertLess(lines.index("setup:resource:function"), lines.index("finalizer:resource"))

    def test_session_shouldstop_set_from_a_hook_cancels_the_rest_of_the_run(self):
        # One worker so tests run strictly in sequence -- shouldstop set
        # during test_a's teardown must cancel test_b/test_c before they
        # get a chance to run (they end up "not_run"), the same
        # observable shape as a fail-policy cancel.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_runtest_teardown(item):\n"
                "    if item.name == 'test_a':\n"
                "        item.session.shouldstop = 'stopping after test_a'\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    pass\n\n"
                "@test()\ndef test_b():\n    pass\n\n"
                "@test()\ndef test_c():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 3)
        by_name = {r.test_id.split("::")[-1]: r.outcome for r in reporter.results}
        self.assertEqual(by_name["test_a"], "passed")
        self.assertEqual(by_name["test_b"], "not_run")
        self.assertEqual(by_name["test_c"], "not_run")

    def test_generate_tests_dynamically_parametrizes_a_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_generate_tests(metafunc):\n"
                "    if 'env' in metafunc.fixturenames:\n"
                "        metafunc.parametrize('env', ['qa', 'staging'])\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a(env):\n    assert env\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 2)
        self.assertTrue(all(r.outcome == "passed" for r in reporter.results))
        suffixes = sorted(r.test_id.split("[")[-1].rstrip("]") for r in reporter.results)
        self.assertEqual(suffixes, ["qa", "staging"])


class CaptureSuppressionTests(unittest.TestCase):
    def test_passed_test_output_does_not_leak_and_failed_test_output_is_attached(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_quiet_pass():\n"
                "    print('should not leak')\n\n"
                "@test()\ndef test_noisy_fail():\n"
                "    print('should be attached to failure')\n"
                "    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertIsNone(by_id["test_quiet_pass"].console_captured)
        self.assertIn("should be attached to failure", by_id["test_noisy_fail"].console_captured)


class RuntestHooksTests(unittest.TestCase):
    """ctrlrunner_runtest_logstart/setup/teardown/logreport: conftest-
    discovered per-test hooks, fired once per attempt inside the
    worker process that runs the test, with pytest-shaped arguments
    (item / report objects -- see core/hookcompat.py) so migrated
    pytest hook bodies keep working."""

    def setUp(self):
        registry.reset()

    def _write_conftest(self, root, log_path, extra_setup="", extra_teardown=""):
        (root / "conftest.py").write_text(
            f"LOG = {str(log_path)!r}\n\n"
            "def _write(line):\n"
            "    with open(LOG, 'a') as f:\n"
            "        f.write(line + '\\n')\n\n"
            "def ctrlrunner_runtest_logstart(nodeid, location):\n"
            "    _write(f'logstart:{nodeid}')\n\n"
            "def ctrlrunner_runtest_setup(item):\n"
            "    _write(f'setup:{item.nodeid}:{item.attempt}')\n"
            f"    {extra_setup}\n\n"
            "def ctrlrunner_runtest_teardown(item, nextitem):\n"
            "    _write(f'teardown:{item.nodeid}:{item.attempt}')\n"
            f"    {extra_teardown}\n\n"
            "def ctrlrunner_runtest_logreport(report):\n"
            "    _write(f'logreport:{report.nodeid}:{report.attempt}:{report.outcome}')\n"
        )

    def test_all_four_hooks_fire_in_order_for_a_passing_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            self._write_conftest(root, log_path)
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertEqual(
            lines,
            [
                "logstart:suite.test_demo::test_a",
                "setup:suite.test_demo::test_a:1",
                "teardown:suite.test_demo::test_a:1",
                "logreport:suite.test_demo::test_a:1:passed",
            ],
        )

    def test_hooks_fire_once_per_attempt_for_a_retried_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            self._write_conftest(root, log_path)
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "attempts = {'n': 0}\n\n"
                "@test(retries=1)\n"
                "def test_flaky():\n"
                "    attempts['n'] += 1\n"
                "    assert attempts['n'] >= 2\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertEqual(
            [line for line in lines if line.startswith("logreport")],
            [
                "logreport:suite.test_demo::test_flaky:1:failed",
                "logreport:suite.test_demo::test_flaky:2:passed",
            ],
        )

    def test_broken_setup_hook_does_not_fail_the_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            self._write_conftest(root, log_path, extra_setup="raise RuntimeError('setup boom')")
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        warning_messages = " ".join(w["message"] for w in (reporter.results[0].warnings or []))
        self.assertIn("setup boom", warning_messages)

    def test_broken_teardown_hook_does_not_fail_the_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            self._write_conftest(
                root, log_path, extra_teardown="raise RuntimeError('teardown boom')"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        warning_messages = " ".join(w["message"] for w in (reporter.results[0].warnings or []))
        self.assertIn("teardown boom", warning_messages)

    def test_skip_from_setup_hook_via_marker_skips_the_test(self):
        # The pytest pattern that motivated the compat layer:
        #   if item.get_closest_marker("mac_only"): pytest.skip(...)
        # written with ctrlrunner's skip() -- must control the outcome,
        # not be swallowed by broken-hook isolation.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "from ctrlrunner import skip\n\n"
                "def ctrlrunner_runtest_setup(item):\n"
                "    if item.get_closest_marker('mac_only'):\n"
                "        skip(True, 'this test only runs on macOS')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'mac_only'})\n"
                "def test_tagged():\n"
                "    assert False, 'must never run'\n\n"
                "@test()\n"
                "def test_untagged():\n"
                "    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id: r for r in reporter.results}
        self.assertEqual(by_id["suite.test_demo::test_tagged"].outcome, "skipped")
        self.assertIn("macOS", by_id["suite.test_demo::test_tagged"].error)
        self.assertEqual(by_id["suite.test_demo::test_untagged"].outcome, "passed")

    def test_fixme_from_setup_hook_reports_fixme(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "from ctrlrunner import fixme\n\n"
                "def ctrlrunner_runtest_setup(item):\n"
                "    fixme(True, 'JIRA-1: known broken environment')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "fixme")
        self.assertIn("JIRA-1", reporter.results[0].error)

    def test_fail_from_setup_hook_marks_expected_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "from ctrlrunner import fail\n\n"
                "def ctrlrunner_runtest_setup(item):\n"
                "    fail(True, 'JIRA-2: expected broken', strict=True)\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "expected_failure")

    def test_full_pytest_surface_in_hooks_without_warnings(self):
        # A hook body leaning on the wider pytest object surface --
        # item.session/.config/.module/.cls/.funcargs, report.sections,
        # config.pluginmanager -- must work (or degrade silently) with
        # ZERO warnings on the result: the compat layer's contract.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def _write(line):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(line + '\\n')\n\n"
                "def ctrlrunner_runtest_setup(item):\n"
                "    _write(f'timeout={item.config.getini(\"timeout\")}')\n"
                "    _write(f'module={item.module.__name__}')\n"
                "    _write(f'cls={item.cls}')\n"
                "    _write(f'xdist={item.session.config.pluginmanager.hasplugin(\"xdist\")}')\n"
                "    _write(f'collected={item.session.testscollected}')\n\n"
                "def ctrlrunner_runtest_teardown(item, nextitem):\n"
                "    _write(f'funcargs={sorted(item.funcargs.keys())}')\n\n"
                "def ctrlrunner_runtest_logreport(report):\n"
                "    _write(f'duration_is_number={isinstance(report.duration, float)}')\n"
                "    _write(f'sections={report.sections}')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import fixture, test\n\n"
                "@fixture()\n"
                "def resource():\n"
                "    return object()\n\n"
                "@test()\n"
                "def test_a(resource):\n"
                "    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, raw_config={"timeout": 30})
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "passed")
        self.assertFalse(result.warnings)  # the whole point: silence
        self.assertIn("timeout=30", lines)
        self.assertIn("module=suite.test_demo", lines)
        self.assertIn("cls=None", lines)
        self.assertIn("xdist=False", lines)
        self.assertIn("collected=1", lines)
        self.assertIn("funcargs=['resource']", lines)
        self.assertIn("duration_is_number=True", lines)
        self.assertIn("sections=[]", lines)

    def test_unported_pytest_attribute_fails_the_test_with_recommendation(self):
        # Fail-loudly policy: a hook touching pytest-only machinery
        # (item.parent -- the collection tree) fails the test with the
        # CompatibilityError recommendation in the error text, instead
        # of degrading to a warning or a silent placeholder.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "conftest.py").write_text(
                "def ctrlrunner_runtest_setup(item):\n    if item.parent:\n        pass\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertIn("Item.parent", result.error)
        self.assertIn("collection tree", result.error)
        self.assertIn("item.module", result.error)

    def test_teardown_nextitem_is_the_next_test_in_the_worker_batch(self):
        # pytest(-xdist) semantics: nextitem is the next item in THIS
        # worker's queue, or None for the last one -- a real Item shim,
        # not a permanent None.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n\n"
                "def ctrlrunner_runtest_teardown(item, nextitem):\n"
                "    nxt = nextitem.name if nextitem else None\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(f'{item.name}->{nxt}\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_first():\n    pass\n\n"
                "@test()\ndef test_second():\n    pass\n\n"
                "@test()\ndef test_third():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(len(reporter.results), 3)
        self.assertEqual(
            lines,
            [
                "test_first->test_second",
                "test_second->test_third",
                "test_third->None",
            ],
        )

    def test_teardown_hook_fires_even_for_a_skipped_test(self):
        # pytest calls pytest_runtest_teardown for skipped items too.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            log_path = Path(tmp) / "log.txt"
            (root / "conftest.py").write_text(
                f"LOG = {str(log_path)!r}\n"
                "from ctrlrunner import skip\n\n"
                "def ctrlrunner_runtest_setup(item):\n"
                "    skip(True, 'always skipped')\n\n"
                "def ctrlrunner_runtest_teardown(item, nextitem):\n"
                "    with open(LOG, 'a') as f:\n"
                "        f.write(f'teardown:{item.nodeid}\\n')\n"
            )
            (root / "test_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            lines = log_path.read_text().splitlines()

        self.assertEqual(reporter.results[0].outcome, "skipped")
        self.assertEqual(lines, ["teardown:suite.test_demo::test_a"])


class WallClockParallelismTests(unittest.TestCase):
    """The assertion class the suite lacked (and why sequential batch
    execution went unnoticed for a while): every functional
    behavior -- results, timeouts, requeue -- is identical whether
    workers run concurrently or one-after-another; only wall time
    differs, and nothing measured it. This is the permanent regression
    guard for scheduler concurrency."""

    def setUp(self):
        registry.reset()

    def _make_sleep_suite(self, tmp, seconds, count, suite_name):
        # One FILE per sleep test: under the file-grouped default a
        # single file's tests share one worker in order, so wall-clock
        # concurrency across workers is only observable across files.
        root = Path(tmp) / suite_name
        root.mkdir()
        for i in range(count):
            # Unique module filename per suite: a repeated name would
            # already sit in sys.modules from a previous test in this
            # class, making re-import a no-op after registry.reset()
            # (zero tests collected).
            (root / f"test_{suite_name}_{i}.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                f"@test(timeout=30)\ndef test_sleep_{i}():\n    time.sleep({seconds})\n"
            )
        return root

    def test_two_workers_run_two_slow_tests_concurrently(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_sleep_suite(tmp, seconds=2, count=2, suite_name="par2w")
            orch = Orchestrator(str(root), 2, 30.0)

            start = time.time()
            reporter = orch.run()
            elapsed = time.time() - start

            self.assertEqual(len(reporter.results), 2)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))
            # Sequential execution would need >= 4s of sleeping alone
            # (2s + 2s) plus 2x interpreter spawn. Concurrent execution
            # sleeps for ~max(2, 2) = 2s total. The 4s bound holds even
            # accounting for one spawn's overhead, and fails decisively
            # (>5s) if the scheduler regresses to sequential.
            self.assertLess(
                elapsed,
                4.0,
                f"two 2s tests on -n 2 took {elapsed:.2f}s -- workers are not running concurrently",
            )

    def test_single_worker_still_runs_sequentially(self):
        # Sanity check of the measurement itself: with -n 1 the same two
        # tests MUST take >= 4s, proving the concurrent case above isn't
        # passing because the sleeps somehow didn't happen.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_sleep_suite(tmp, seconds=2, count=2, suite_name="par1w")
            orch = Orchestrator(str(root), 1, 30.0)

            start = time.time()
            reporter = orch.run()
            elapsed = time.time() - start

            self.assertEqual(len(reporter.results), 2)
            self.assertGreaterEqual(elapsed, 4.0)


class SchedulingUnitsTests(unittest.TestCase):
    """The file-grouped default and the cap-mode worker constraints:
    a file's tests share one worker in definition order unless
    fully_parallel opts them out, and workers=1 on a class serializes
    it even when the rest of the run is fully parallel."""

    def setUp(self):
        registry.reset()

    def test_same_file_tests_share_one_worker_by_default(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "filegroup_suite"
            root.mkdir()
            tests_src = "\n\n".join(f"@test()\ndef test_{i}():\n    pass" for i in range(4))
            (root / "test_grouped.py").write_text(
                "from ctrlrunner import test\n\n" + tests_src + "\n"
            )

            orch = Orchestrator(str(root), 4, 10.0)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 4)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertEqual(
                len(worker_ids),
                1,
                f"same-file tests scattered across workers {worker_ids} under the "
                f"file-grouped default",
            )

    def test_fully_parallel_scatters_same_file_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "fullypar_suite"
            root.mkdir()
            tests_src = "\n\n".join(f"@test()\ndef test_{i}():\n    pass" for i in range(4))
            (root / "test_scattered.py").write_text(
                "from ctrlrunner import test\n\n" + tests_src + "\n"
            )

            orch = Orchestrator(str(root), 4, 10.0, fully_parallel=True)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 4)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertGreater(
                len(worker_ids), 1, "fully_parallel=True did not scatter same-file tests"
            )

    def test_class_fully_parallel_scatters_only_that_class(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "classpar_suite"
            root.mkdir()
            (root / "test_classpar.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(fully_parallel=True)\n"
                "class Par:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 2)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertEqual(len(worker_ids), 2, "@test_class(fully_parallel=True) did not scatter")

    def test_workers_cap_one_serializes_the_class_onto_one_worker(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "capone_suite"
            root.mkdir()
            (root / "test_capped.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(workers=1, fully_parallel=True)\n"
                "class Capped:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 4, 10.0)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 3)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertEqual(
                len(worker_ids),
                1,
                f"workers=1 class ran on {len(worker_ids)} workers -- cap not enforced",
            )

    def test_dedicated_class_runs_alongside_pool_without_deadlock(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "dedicated_suite"
            root.mkdir()
            (root / "test_dedicated.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(workers=1, workers_mode='dedicated')\n"
                "class Reserved:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        pass\n"
            )
            (root / "test_pool.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_c():\n    pass\n\n"
                "@test()\ndef test_d():\n    pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 4)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))
            reserved = [r for r in reporter.results if "Reserved" in r.test_id]
            self.assertEqual(len({r.worker_id for r in reserved}), 1)

    def test_config_worker_constraint_caps_a_file(self):
        from ctrlrunner.execution.worker_budget import WorkerConstraintSpec

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "configcap_suite"
            root.mkdir()
            tests_src = "\n\n".join(f"@test()\ndef test_{i}():\n    pass" for i in range(4))
            (root / "test_configcapped.py").write_text(
                "from ctrlrunner import test\n\n" + tests_src + "\n"
            )

            spec = WorkerConstraintSpec(
                path_pattern=(root / "test_configcapped.py").resolve().as_posix(),
                class_name=None,
                count=1,
                mode="cap",
                order=0,
            )
            orch = Orchestrator(str(root), 4, 10.0, fully_parallel=True, worker_constraints=[spec])
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 4)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertEqual(len(worker_ids), 1, "config file cap not enforced")


class TagRegistryOrchestratorIntegrationTests(unittest.TestCase):
    """Verifies validation actually happens where the plan specifies:
    immediately after discovery, before any test runs -- through the
    real Orchestrator, not just the pure tag_registry functions."""

    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp, suite_name):
        root = Path(tmp) / suite_name
        root.mkdir()
        (root / f"test_{suite_name}.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test(tags={'smoke'})\n"
            "def test_a():\n    pass\n\n"
            "@test(tags={'typo_tag'})\n"
            "def test_b():\n    assert False\n"
        )
        return root

    def test_strict_mode_runs_zero_tests_and_raises(self):
        from ctrlrunner.config.tag_registry import TagRegistry, TagValidationError

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "strict_tags_suite")
            reg = TagRegistry(entries=["smoke"], strict=True)
            orch = Orchestrator(str(root), 1, 10.0, tag_registry=reg)
            with self.assertRaises(TagValidationError):
                orch.run()
            # zero tests must have run -- the reporter never got a chance
            # to record anything
            self.assertEqual(orch.reporter.results, [])

    def test_warning_mode_still_runs_all_tests(self):
        from ctrlrunner.config.tag_registry import TagRegistry

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "warn_tags_suite")
            reg = TagRegistry(entries=["smoke"], strict=False)
            orch = Orchestrator(str(root), 1, 10.0, tag_registry=reg)
            reporter = orch.run()  # must not raise
            self.assertEqual(len(reporter.results), 2)

    def test_no_registry_is_fully_unaffected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "no_registry_suite")
            orch = Orchestrator(str(root), 1, 10.0)  # tag_registry=None default
            reporter = orch.run()
            self.assertEqual(len(reporter.results), 2)


class EventEnvelopeIntegrationTests(unittest.TestCase):
    """Verifies the two-tier design through a real Orchestrator.run():
    EventSubscribers receive envelopes, ConsoleReporters keep receiving
    their unchanged simple calls, and both happen from the same run
    without one depending on the other."""

    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp, suite_name):
        root = Path(tmp) / suite_name
        root.mkdir()
        (root / f"test_{suite_name}.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\n"
            "def test_a():\n    pass\n\n"
            "@test()\n"
            "def test_b():\n    assert False\n"
        )
        return root

    def test_subscriber_receives_full_lifecycle_in_order(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "event_lifecycle_suite")
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        types = [e.type for e in received]
        self.assertEqual(types[0], "run_start")
        self.assertEqual(types[-1], "run_end")
        self.assertIn("worker_spawned", types)
        self.assertEqual(types.count("test_start"), 2)
        self.assertEqual(types.count("test_end"), 2)
        # every envelope is schema-versioned and JSON-serializable
        from ctrlrunner.reporting.events import SCHEMA_VERSION

        for e in received:
            self.assertEqual(e.schema_version, SCHEMA_VERSION)
            json.dumps(e.to_dict())

    def test_test_end_payload_matches_the_actual_result(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "event_payload_suite")
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[RecordingSubscriber()])
            reporter = orch.run()

        by_id = {e.payload["id"]: e.payload for e in received}
        for result in reporter.results:
            payload = by_id[result.test_id]
            self.assertEqual(payload["outcome"], result.outcome)
            self.assertEqual(payload["duration"], round(result.duration, 3))
            self.assertEqual(payload["attempts"], result.attempts)

    def test_restart_overhead_is_included_in_the_test_end_event_payload(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "restart_overhead_event_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\ndef test_hangs():\n    time.sleep(30)\n\n"
                "@test()\ndef test_after_hang():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 30.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        by_id = {p["id"]: p for p in received}
        self.assertIn(
            "workerRestartOverhead", by_id["restart_overhead_event_suite.test_hang::test_hangs"]
        )
        overhead = by_id["restart_overhead_event_suite.test_hang::test_after_hang"][
            "workerRestartOverhead"
        ]
        self.assertIsNotNone(overhead)
        self.assertGreaterEqual(overhead, 0.0)

    def test_console_reporter_is_completely_unaffected_by_event_subscribers(self):
        # the core promise of the two-tier design: adding subscribers
        # must not change what a plain ConsoleReporter sees or how.
        from ctrlrunner.reporting.events import EventSubscriber
        from ctrlrunner.reporting.reporters import ConsoleReporter

        cr_calls = []

        class RecordingConsoleReporter(ConsoleReporter):
            def on_run_start(self, total):
                cr_calls.append(("on_run_start", total))

            def on_test_start(self, test_id):
                cr_calls.append(("on_test_start", test_id))

            def on_test_end(self, result):
                cr_calls.append(("on_test_end", result))

            def on_run_end(self, results, duration):
                cr_calls.append(("on_run_end", len(results)))

        class NoOpSubscriber(EventSubscriber):
            def on_event(self, event):
                pass

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "event_isolation_suite")
            orch = Orchestrator(
                str(root),
                1,
                10.0,
                console_reporters=[RecordingConsoleReporter()],
                event_subscribers=[NoOpSubscriber()],
            )
            orch.run()

        kinds = [c[0] for c in cr_calls]
        self.assertEqual(kinds[0], "on_run_start")
        self.assertEqual(kinds[-1], "on_run_end")
        self.assertEqual(kinds.count("on_test_end"), 2)
        # on_test_end must still receive the real Result object, not a dict
        test_end_result = next(c[1] for c in cr_calls if c[0] == "on_test_end")
        self.assertTrue(hasattr(test_end_result, "outcome"))

    def test_no_subscribers_means_zero_envelope_construction_overhead(self):
        # _emit() should short-circuit before building anything if
        # nobody's listening -- not load-bearing behavior, but worth
        # locking in given the hot-loop concern noted in the plan.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "event_no_subscribers_suite")
            orch = Orchestrator(str(root), 1, 10.0)  # no event_subscribers
            reporter = orch.run()  # must not raise
            self.assertEqual(len(reporter.results), 2)

    def test_unknown_event_type_style_subscriber_does_not_break_anything(self):
        # a subscriber that only handles known types today must not
        # break when it silently ignores ones it doesn't recognize --
        # this is what makes future event types additive, not breaking.
        from ctrlrunner.reporting.events import EventSubscriber

        class PickySubscriber(EventSubscriber):
            def __init__(self):
                self.seen_test_end = 0

            def on_event(self, event):
                if event.type == "test_end":
                    self.seen_test_end += 1
                # everything else silently ignored

        sub = PickySubscriber()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "event_unknown_type_suite")
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[sub])
            orch.run()
        self.assertEqual(sub.seen_test_end, 2)

    def test_worker_terminated_emitted_on_timeout_kill(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "worker_terminated":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "hang_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            orch = Orchestrator(str(root), 1, 1.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["reason"], "timeout")

    def test_worker_terminated_emitted_on_cancellation(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "worker_terminated":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "cancel_event_suite"
            root.mkdir()
            (root / "test_cancel.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=30)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            cancel_event = threading.Event()
            orch = Orchestrator(
                str(root),
                1,
                30.0,
                cancel_event=cancel_event,
                event_subscribers=[RecordingSubscriber()],
            )

            def cancel_soon():
                time.sleep(0.5)
                cancel_event.set()

            threading.Thread(target=cancel_soon, daemon=True).start()
            orch.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["reason"], "cancelled")

    def test_test_end_is_emitted_for_a_timeout_killed_test(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "test_end_timeout_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            orch = Orchestrator(str(root), 1, 1.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["outcome"], "failed")

    def test_test_end_is_emitted_for_a_cancelled_test(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "test_end_cancel_suite"
            root.mkdir()
            (root / "test_cancel.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=30)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            cancel_event = threading.Event()
            orch = Orchestrator(
                str(root),
                1,
                30.0,
                cancel_event=cancel_event,
                event_subscribers=[RecordingSubscriber()],
            )

            def cancel_soon():
                time.sleep(0.5)
                cancel_event.set()

            threading.Thread(target=cancel_soon, daemon=True).start()
            orch.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["outcome"], "cancelled")

    def test_test_end_is_emitted_for_a_worker_crash(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "test_end_crash_suite"
            root.mkdir()
            (root / "test_crash.py").write_text(
                "import os, sys\nfrom ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    os._exit(1)\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["outcome"], "failed")


class GroupingIntegrationTests(unittest.TestCase):
    """Verifies grouping is computed through a real Orchestrator.run(),
    not just the pure grouping.py functions -- and that Result.groups
    reaches both the reporter and the event payload."""

    def setUp(self):
        registry.reset()

    def test_default_no_config_groups_by_file_only(self):
        from ctrlrunner.reporting.grouping import DEFAULT_DIMENSIONS

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "default_grouping_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)  # grouping_dimensions=None -> default
            self.assertEqual(orch.grouping_dimensions, DEFAULT_DIMENSIONS)
            reporter = orch.run()
            result = reporter.results[0]
            self.assertIn("file", result.groups)
            self.assertTrue(result.groups["file"].endswith("test_a.py"))

    def test_custom_dimensions_computed_and_attached_to_results(self):
        from ctrlrunner.reporting.grouping import GroupingDimension

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "custom_grouping_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test(tags={'team_backend'}, properties={'owner': 'alice'})\n"
                "def test_x():\n    pass\n"
            )
            dims = [
                GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"}),
                GroupingDimension(name="owner", strategy="property", options={"key": "owner"}),
            ]
            orch = Orchestrator(str(root), 1, 10.0, grouping_dimensions=dims)
            reporter = orch.run()
            result = reporter.results[0]
            self.assertEqual(result.groups, {"team": "backend", "owner": "alice"})
            self.assertNotIn("file", result.groups)  # not force-injected

    def test_groups_present_on_cancelled_results_too(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "cancel_grouping_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=30)\ndef test_hangs():\n    time.sleep(30)\n"
            )
            cancel_event = threading.Event()
            orch = Orchestrator(str(root), 1, 30.0, cancel_event=cancel_event)

            def cancel_soon():
                time.sleep(0.5)
                cancel_event.set()

            threading.Thread(target=cancel_soon, daemon=True).start()
            reporter = orch.run()

            self.assertEqual(reporter.results[0].outcome, "cancelled")
            self.assertIn("file", reporter.results[0].groups)

    def test_groups_included_in_event_envelope_payload(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                if event.type == "test_end":
                    received.append(event.payload)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "event_grouping_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        self.assertIn("groups", received[0])
        self.assertIn("file", received[0]["groups"])


class RunProjectsIntegrationTests(unittest.TestCase):
    """Real end-to-end verification via actual Orchestrator.run() calls
    -- this is where the trickiest part of section 4.4 lives (registry
    reset + forced re-import across a tests_dir shared by two
    projects), so it needs real subprocess execution, not a mock."""

    def setUp(self):
        registry.reset()

    def _make_layout(self, tmp):
        web = Path(tmp) / "tests" / "web"
        e2e = Path(tmp) / "tests" / "e2e"
        web.mkdir(parents=True)
        e2e.mkdir(parents=True)
        (web / "test_web.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test(tags={'smoke'})\ndef test_login():\n    pass\n\n"
            "@test(tags={'regression'})\ndef test_checkout():\n    assert False\n"
        )
        (e2e / "test_e2e.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_full_flow():\n    pass\n"
        )
        return web, e2e

    def test_single_project_keeps_id_unprefixed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, _ = self._make_layout(tmp)
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

    def test_two_projects_with_overlapping_tests_dir_both_see_their_own_selection(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, e2e = self._make_layout(tmp)
            projects = {
                "smoke": ProjectConfig(
                    name="smoke", tests_dir=[str(web), str(e2e)], tags=["smoke"]
                ),
                "regression": ProjectConfig(name="regression", tests_dir=[str(web)]),
            }
            combined, multi = run_projects(
                ["smoke", "regression"],
                projects,
                base_root="tests",
                base_num_workers=2,
                base_timeout=30.0,
            )
            self.assertTrue(multi)
            by_project = {}
            for r in combined.results:
                by_project.setdefault(r.project, []).append(r.test_id)

            # smoke: only the smoke-tagged test, from its own tag filter
            # identity is the RAW test_id (no "[project] " prefix
            # baked in) -- project is the sole disambiguator, which is
            # exactly why by_project is keyed on r.project above.
            self.assertEqual(len(by_project["smoke"]), 1)
            self.assertFalse(by_project["smoke"][0].startswith("["))
            self.assertIn("test_login", by_project["smoke"][0])

            # regression: both of web's tests (no tag filter), NOT e2e's
            # (not in this project's tests_dir at all)
            self.assertEqual(len(by_project["regression"]), 2)
            self.assertTrue(all(not i.startswith("[") for i in by_project["regression"]))

    def test_cli_tag_overrides_project_tags_filter(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, _ = self._make_layout(tmp)
            projects = {"smoke": ProjectConfig(name="smoke", tests_dir=[str(web)], tags=["smoke"])}
            # CLI --tag regression should override the project's own
            # tags=["smoke"] filter entirely
            combined, multi = run_projects(
                ["smoke"],
                projects,
                base_root="tests",
                base_num_workers=1,
                base_timeout=30.0,
                cli_tags=["regression"],
            )
            ids = [r.test_id for r in combined.results]
            self.assertEqual(len(ids), 1)
            self.assertIn("test_checkout", ids[0])

    def test_project_timeout_and_num_workers_used_when_cli_not_given(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, _ = self._make_layout(tmp)
            projects = {
                "smoke": ProjectConfig(name="smoke", tests_dir=[str(web)], timeout=1, num_workers=1)
            }
            # base_timeout=30 would never trigger a hard-kill; the
            # project's own timeout=1 should be what's actually used
            root = Path(tmp) / "tests" / "web"
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test()\ndef test_hangs():\n    time.sleep(30)\n"
            )
            combined, multi = run_projects(
                ["smoke"],
                projects,
                base_root="tests",
                base_num_workers=4,
                base_timeout=30.0,
            )
            hang_result = next(r for r in combined.results if "test_hangs" in r.test_id)
            self.assertEqual(hang_result.outcome, "failed")
            self.assertIn("timeout", hang_result.error.lower())

    def test_cli_num_workers_overrides_project_num_workers(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, _ = self._make_layout(tmp)
            projects = {"smoke": ProjectConfig(name="smoke", tests_dir=[str(web)], num_workers=1)}
            # cli_num_workers explicitly given should win over the
            # project's num_workers=1
            combined, multi = run_projects(
                ["smoke"],
                projects,
                base_root="tests",
                base_num_workers=4,
                base_timeout=30.0,
                cli_num_workers=2,
            )
            self.assertEqual(len(combined.results), 2)  # both web tests ran regardless

    def test_event_envelopes_carry_the_project_name(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            web, _ = self._make_layout(tmp)
            projects = {"smoke": ProjectConfig(name="smoke", tests_dir=[str(web)])}
            run_projects(
                ["smoke"],
                projects,
                base_root="tests",
                base_num_workers=1,
                base_timeout=30.0,
                event_subscribers=[RecordingSubscriber()],
            )
        self.assertTrue(received)
        self.assertTrue(all(e.project == "smoke" for e in received))


class FailPolicyIntegrationTests(unittest.TestCase):
    """Real Orchestrator.run() verification -- this is where the
    trickiest bug in this whole feature lived (a scheduler
    responsiveness gap that let a burst of already-queued 'finished'
    messages blow straight past --max-failures before the cancellation
    check ever ran), so pure FailPolicyState unit tests alone would
    never have caught it."""

    def setUp(self):
        registry.reset()

    def _make_failing_suite(self, tmp, count, suite_name="fail_suite"):
        root = Path(tmp) / suite_name
        root.mkdir()
        tests_src = "\n\n".join(
            f"@test()\ndef test_fail_{i}():\n    assert False" for i in range(count)
        )
        (root / f"test_{suite_name}.py").write_text(
            "from ctrlrunner import test\n\n" + tests_src + "\n"
        )
        return root

    def test_max_failures_stops_after_threshold_marks_rest_not_run(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_failing_suite(tmp, 5, suite_name="maxfail5")
            fp = FailPolicyState(max_failures=2)
            orch = Orchestrator(str(root), 1, 10.0, fail_policy=fp)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 5)
            outcomes = [r.outcome for r in reporter.results]
            self.assertEqual(outcomes.count("failed"), 2)
            self.assertEqual(outcomes.count("not_run"), 3)
            self.assertEqual(fp.cancel_reason, "max_failures")

    def test_max_failures_zero_means_unlimited(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_failing_suite(tmp, 4, suite_name="maxfailunlimited")
            fp = FailPolicyState(max_failures=0)
            orch = Orchestrator(str(root), 1, 10.0, fail_policy=fp)
            reporter = orch.run()
            self.assertEqual(len(reporter.results), 4)
            self.assertTrue(all(r.outcome == "failed" for r in reporter.results))
            self.assertIsNone(fp.cancel_reason)

    def test_no_fail_policy_at_all_is_unaffected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_failing_suite(tmp, 3, suite_name="nopolicy")
            orch = Orchestrator(str(root), 1, 10.0)  # fail_policy=None
            reporter = orch.run()
            self.assertEqual(len(reporter.results), 3)
            self.assertTrue(all(r.outcome == "failed" for r in reporter.results))

    def test_max_timeouts_stops_after_first_timeout_kill(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "hang_suite"
            root.mkdir()
            (root / "test_hangs.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\ndef test_hang_a():\n    time.sleep(30)\n\n"
                "@test(timeout=1)\ndef test_hang_b():\n    time.sleep(30)\n\n"
                "@test()\ndef test_c():\n    pass\n"
            )
            fp = FailPolicyState(max_timeouts=1)
            orch = Orchestrator(str(root), 2, 30.0, fail_policy=fp)
            reporter = orch.run()

            by_id = {r.test_id: r.outcome for r in reporter.results}
            self.assertEqual(by_id["hang_suite.test_hangs::test_hang_a"], "failed")
            self.assertEqual(fp.cancel_reason, "max_timeouts")
            self.assertEqual(fp.timeout_count, 1)
            # whatever didn't get to run must be not_run, not silently missing
            self.assertEqual(len(reporter.results), 3)

    def test_stop_on_worker_crash_detects_real_crash_and_cancels(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "crash_suite"
            root.mkdir()
            (root / "test_crash.py").write_text(
                "import os, time\nfrom ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    pass\n\n"
                # sleep first so test_a's own "finished" message has time
                # to actually flush through the queue before the abrupt
                # exit -- os._exit() skips normal interpreter cleanup, so
                # a multiprocessing.Queue message still in its internal
                # feeder thread's buffer can be lost if the process dies
                # before that thread flushes it.
                "@test()\ndef test_crashes():\n    time.sleep(0.3)\n    os._exit(1)\n"
            )
            fp = FailPolicyState(stop_on_worker_crash=True)
            orch = Orchestrator(str(root), 1, 10.0, fail_policy=fp)
            reporter = orch.run()

            by_id = {r.test_id: r for r in reporter.results}
            self.assertEqual(by_id["crash_suite.test_crash::test_a"].outcome, "passed")
            self.assertEqual(by_id["crash_suite.test_crash::test_crashes"].outcome, "failed")
            self.assertIn("crashed", by_id["crash_suite.test_crash::test_crashes"].error)
            self.assertEqual(fp.cancel_reason, "stop_on_worker_crash")

    def test_worker_crash_without_stop_on_worker_crash_does_not_cancel(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "crash_suite2"
            root.mkdir()
            (root / "test_crash.py").write_text(
                "import os\nfrom ctrlrunner import test\n\n"
                "@test()\ndef test_crashes():\n    os._exit(1)\n"
            )
            (root / "test_unrelated.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_fine():\n    pass\n"
            )
            fp = FailPolicyState(stop_on_worker_crash=False)
            orch = Orchestrator(str(root), 2, 10.0, fail_policy=fp)
            reporter = orch.run()
            # the crash is still detected/reported, just doesn't cancel
            # anything else -- test_fine (a separate worker) still runs
            by_id = {r.test_id: r.outcome for r in reporter.results}
            self.assertEqual(by_id["crash_suite2.test_unrelated::test_fine"], "passed")
            self.assertIsNone(fp.cancel_reason)

    def test_retry_then_pass_does_not_count_toward_max_failures(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "flaky_suite"
            root.mkdir()
            (root / "test_flaky.py").write_text(
                "_state = {'n': 0}\n"
                "from ctrlrunner import test\n\n"
                "@test(retries=1)\n"
                "def test_flaky():\n"
                "    _state['n'] += 1\n"
                "    assert _state['n'] >= 2\n"
            )
            fp = FailPolicyState(max_failures=1)
            orch = Orchestrator(str(root), 1, 10.0, fail_policy=fp)
            reporter = orch.run()
            self.assertEqual(reporter.results[0].outcome, "passed")
            self.assertEqual(fp.failure_count, 0)  # retried-then-passed never counted
            self.assertIsNone(fp.cancel_reason)


class ShardingIntegrationTests(unittest.TestCase):
    """Real Orchestrator.run() verification with a genuinely seeded
    HistoryStore -- proves the wiring (history lookup -> lpt_shard ->
    actual worker assignment) works end-to-end, not just that
    lpt_shard() itself is correct in isolation (already covered by
    tests/test_sharding.py)."""

    def setUp(self):
        registry.reset()

    def test_no_history_store_behaves_exactly_like_round_robin(self):
        # Orchestrator without a history_store still runs everything
        # correctly (batching is file-grouped by default now; with a
        # single file this is one batch on one worker).

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "sharding_unaffected_suite"
            root.mkdir()
            tests_src = "\n\n".join(f"@test()\ndef test_{i}():\n    pass" for i in range(6))
            (root / "test_x.py").write_text("from ctrlrunner import test\n\n" + tests_src + "\n")

            orch = Orchestrator(str(root), 3, 10.0)  # history_store=None
            reporter = orch.run()
            self.assertEqual(len(reporter.results), 6)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))

    def test_seeded_history_isolates_slow_tests_across_workers(self):
        # per-test LPT is specifically what fully_parallel=True buys, so
        # this test opts in -- under the file-grouped default all 8
        # tests share one file and would serialize onto one worker.
        from ctrlrunner.reporting.history import HistoryStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "sharding_seeded_suite"
            root.mkdir()
            tests_src = (
                "\n\n".join(f"@test()\ndef test_slow_{i}():\n    time.sleep(1.0)" for i in range(2))
                + "\n\n"
                + "\n\n".join(f"@test()\ndef test_fast_{i}():\n    pass" for i in range(6))
            )
            (root / "test_mixed.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n" + tests_src + "\n"
            )

            db_path = str(Path(tmp) / "history.db")
            module_prefix = "sharding_seeded_suite.test_mixed"
            with HistoryStore(db_path) as store:
                for i in range(2):
                    store.record_run(
                        [
                            Result(
                                test_id=f"{module_prefix}::test_slow_{i}",
                                outcome="passed",
                                error=None,
                                duration=2.0,
                            )
                        ]
                    )
                for i in range(6):
                    store.record_run(
                        [
                            Result(
                                test_id=f"{module_prefix}::test_fast_{i}",
                                outcome="passed",
                                error=None,
                                duration=0.01,
                            )
                        ]
                    )

            with HistoryStore(db_path) as store:
                orch = Orchestrator(str(root), 2, 10.0, history_store=store, fully_parallel=True)
                start = time.time()
                reporter = orch.run()
                elapsed = time.time() - start

            self.assertEqual(len(reporter.results), 8)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))
            # if both 1.0s-sleep tests had landed on the same worker,
            # this would take >= ~2.0s of sleep alone; isolated onto
            # separate workers, wall time should stay well under that.
            self.assertLess(elapsed, 2.0, "seeded history did not isolate the slow tests")

    def test_seeded_history_weighs_whole_files_under_grouped_default(self):
        # the file-grouped analogue: two slow FILES with seeded history
        # must land on different workers (unit weight = sum of member
        # durations), keeping wall time near one file's sleep total.
        from ctrlrunner.reporting.history import HistoryStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "sharding_filegroup_suite"
            root.mkdir()
            for name in ("alpha", "beta"):
                (root / f"test_{name}.py").write_text(
                    "import time\nfrom ctrlrunner import test\n\n"
                    f"@test()\ndef test_slow_{name}():\n    time.sleep(0.5)\n"
                )

            db_path = str(Path(tmp) / "history.db")
            with HistoryStore(db_path) as store:
                for name in ("alpha", "beta"):
                    store.record_run(
                        [
                            Result(
                                test_id=f"sharding_filegroup_suite.test_{name}::test_slow_{name}",
                                outcome="passed",
                                error=None,
                                duration=2.0,
                            )
                        ]
                    )

            with HistoryStore(db_path) as store:
                orch = Orchestrator(str(root), 2, 10.0, history_store=store)
                reporter = orch.run()

            self.assertEqual(len(reporter.results), 2)
            worker_ids = {r.worker_id for r in reporter.results}
            self.assertEqual(len(worker_ids), 2, "slow files were not isolated across workers")


class ProfilingIntegrationTests(unittest.TestCase):
    """Real Orchestrator.run() verification for section 4.12 -- retry
    accumulation across attempts, test-body/capture step wrapping, and
    worker_restart_overhead, all through the actual worker subprocess
    pipeline, not just steps.py/di.py in isolation."""

    def setUp(self):
        registry.reset()

    def test_no_retries_keeps_flat_step_tree_no_attempt_wrapper(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "profiling_flat_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            names = [s["name"] for s in reporter.results[0].steps]
            self.assertEqual(names, ["test body"])

    def test_retries_accumulate_all_attempts_under_numbered_parents(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "profiling_retry_suite"
            root.mkdir()
            (root / "test_flaky.py").write_text(
                "from ctrlrunner import test\n\n"
                "_state = {'n': 0}\n\n"
                "@test(retries=2)\n"
                "def test_flaky():\n"
                "    _state['n'] += 1\n"
                "    assert _state['n'] >= 3\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            result = reporter.results[0]
            self.assertEqual(result.outcome, "passed")
            self.assertEqual(result.attempts, 3)
            top_level_names = [s["name"] for s in result.steps]
            self.assertEqual(top_level_names, ["attempt 1", "attempt 2", "attempt 3"])
            # first two attempts failed, third passed -- visible per-attempt
            self.assertEqual(result.steps[0]["children"][0]["outcome"], "failed")
            self.assertEqual(result.steps[1]["children"][0]["outcome"], "failed")
            self.assertEqual(result.steps[2]["children"][0]["outcome"], "passed")

    def test_capture_step_appears_alongside_fixture_setup_teardown_on_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "profiling_capture_suite"
            root.mkdir()
            (root / "test_capture.py").write_text(
                "from ctrlrunner import test, fixture\n\n"
                "def _capture(value, prefix):\n"
                "    path = prefix + '.txt'\n"
                "    open(path, 'w').write('x')\n"
                "    return path\n\n"
                "@fixture(scope='function', on_failure=_capture)\n"
                "def resource():\n"
                "    yield 'r'\n\n"
                "@test()\n"
                "def test_x(resource):\n"
                "    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            names = [s["name"] for s in reporter.results[0].steps]
            self.assertEqual(
                names,
                [
                    "fixture:resource:setup",
                    "test body",
                    "capture:resource",
                    "fixture:resource:teardown",
                ],
            )

    def test_worker_restart_overhead_measured_on_requeued_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "profiling_restart_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\ndef test_hangs():\n    time.sleep(30)\n\n"
                "@test()\ndef test_after_hang():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 30.0)
            reporter = orch.run()
            by_id = {r.test_id: r for r in reporter.results}
            self.assertIsNone(
                by_id["profiling_restart_suite.test_hang::test_hangs"].worker_restart_overhead
            )
            overhead = by_id[
                "profiling_restart_suite.test_hang::test_after_hang"
            ].worker_restart_overhead
            self.assertIsNotNone(overhead)
            self.assertGreaterEqual(overhead, 0.0)
            self.assertLess(overhead, 10.0)  # sanity bound, not a tight timing assertion

    def test_report_timeout_kill_passes_through_pending_restart_overhead(self):
        # Isolated unit test (per the task brief's stability preference)
        # for the requeue-then-timed-out-again scenario: a test that was
        # requeued onto a fresh worker after a first timeout-kill, and
        # then hangs again and gets hard-killed a second time, must not
        # silently drop the overhead measured on the requeued attempt.
        # Exercising this via two real hanging worker subprocesses is
        # timing-fragile, so this drives _report_timeout_kill directly
        # with self._restart_overhead_for_result pre-populated, exactly
        # as the "finished" branch's own pop() already does.
        orch = Orchestrator(root="unused", num_workers=1, default_timeout=10.0)
        orch.items_by_id = {}
        orch.groups_by_id = {}
        orch._restart_overhead_for_result["mod::stuck"] = 4.56

        orch._report_timeout_kill("mod::stuck", {"mod::stuck": 1}, worker_id=0)

        result = orch.reporter.results[0]
        self.assertEqual(result.worker_restart_overhead, 4.56)
        # and it's consumed -- not left around to leak onto some later result
        self.assertNotIn("mod::stuck", orch._restart_overhead_for_result)

    def test_no_restart_means_overhead_stays_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "profiling_no_restart_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()
            self.assertIsNone(reporter.results[0].worker_restart_overhead)


class QuarantineIntegrationTests(unittest.TestCase):
    """Real Orchestrator.run() verification for section 4.9's
    quarantine mechanism -- the outcome transform, the fail-policy
    exclusion (derived purely from the outcome string, no special-casing
    needed in fail_policy.py itself), and the always-visible quarantined
    flag regardless of pass/fail."""

    def setUp(self):
        registry.reset()

    def test_quarantined_failure_gets_distinct_outcome_and_reason(self):
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_basic_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_flaky():\n    assert False\n"
            )
            qc = QuarantineConfig(
                test_ids={"quarantine_basic_suite.test_x::test_flaky"}, reason="JIRA-999"
            )
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc)
            reporter = orch.run()
            r = reporter.results[0]
            self.assertEqual(r.outcome, "quarantined_failure")
            self.assertTrue(r.quarantined)
            self.assertEqual(r.quarantine_reason, "JIRA-999")

    def test_quarantined_pass_stays_passed_but_flagged(self):
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_pass_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_ok():\n    pass\n"
            )
            qc = QuarantineConfig(test_ids={"quarantine_pass_suite.test_x::test_ok"})
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc)
            reporter = orch.run()
            r = reporter.results[0]
            self.assertEqual(r.outcome, "passed")
            self.assertTrue(r.quarantined)

    def test_unquarantined_test_unaffected(self):
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_unaffected_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    assert False\n"
            )
            qc = QuarantineConfig(test_ids={"some.other.test::not_this_one"})
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc)
            reporter = orch.run()
            r = reporter.results[0]
            self.assertEqual(r.outcome, "failed")
            self.assertFalse(r.quarantined)

    def test_quarantined_failure_does_not_count_toward_max_failures(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_failpolicy_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_quarantined():\n    assert False\n\n"
                "@test()\ndef test_real_failure():\n    assert False\n\n"
                "@test()\ndef test_ok():\n    pass\n"
            )
            qc = QuarantineConfig(test_ids={"quarantine_failpolicy_suite.test_x::test_quarantined"})
            fp = FailPolicyState(max_failures=1)
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc, fail_policy=fp)
            reporter = orch.run()

            by_id = {r.test_id: r for r in reporter.results}
            self.assertEqual(
                by_id["quarantine_failpolicy_suite.test_x::test_quarantined"].outcome,
                "quarantined_failure",
            )
            # only the REAL failure counted -- the quarantined one didn't
            self.assertEqual(fp.failure_count, 1)
            self.assertEqual(fp.cancel_reason, "max_failures")

    def test_no_quarantine_config_is_fully_unaffected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_none_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    assert False\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)  # quarantine=None
            reporter = orch.run()
            r = reporter.results[0]
            self.assertEqual(r.outcome, "failed")
            self.assertFalse(r.quarantined)

    def test_quarantined_timeout_does_not_count_toward_max_timeouts(self):
        # A hard-kill timeout is reported orchestrator-side
        # (_report_timeout_kill), on a different code path from a worker-
        # reported failure -- the quarantine transform must reach it too,
        # or a quarantined hanging test aborts the whole run through
        # --max-timeouts despite being quarantined.
        from ctrlrunner.execution.fail_policy import FailPolicyState
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_timeout_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\ndef test_hangs():\n    time.sleep(30)\n\n"
                "@test()\ndef test_ok():\n    pass\n"
            )
            qc = QuarantineConfig(test_ids={"quarantine_timeout_suite.test_x::test_hangs"})
            fp = FailPolicyState(max_timeouts=1)
            orch = Orchestrator(str(root), 1, 30.0, quarantine=qc, fail_policy=fp)
            reporter = orch.run()

            by_id = {r.test_id: r for r in reporter.results}
            hung = by_id["quarantine_timeout_suite.test_x::test_hangs"]
            self.assertEqual(hung.outcome, "quarantined_failure")
            self.assertTrue(hung.quarantined)
            # neither policy counter saw the quarantined kill...
            self.assertEqual(fp.timeout_count, 0)
            self.assertEqual(fp.failure_count, 0)
            self.assertIsNone(fp.cancel_reason)
            # ...so the rest of the suite still ran instead of not_run
            self.assertEqual(by_id["quarantine_timeout_suite.test_x::test_ok"].outcome, "passed")

    def test_quarantined_flaky_test_recovers_via_retries(self):
        # Quarantine must not interfere with retries: a quarantined test
        # that fails once and passes on retry ends up 'passed' (quarantine
        # only ever rewrites 'failed'), still flagged, with both attempts
        # counted.
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_flaky_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "_state = {'n': 0}\n"
                "from ctrlrunner import test\n\n"
                "@test(retries=1)\n"
                "def test_flaky():\n"
                "    _state['n'] += 1\n"
                "    assert _state['n'] >= 2\n"
            )
            qc = QuarantineConfig(test_ids={"quarantine_flaky_suite.test_x::test_flaky"})
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc)
            reporter = orch.run()
            r = reporter.results[0]
            self.assertEqual(r.outcome, "passed")
            self.assertTrue(r.quarantined)
            self.assertEqual(r.attempts, 2)

    def test_quarantined_serial_member_still_skips_subsequent_members(self):
        # The quarantine transform is orchestrator-side; inside the worker
        # a quarantined member's failure is a raw 'failed', so serial
        # skip-on-fail still protects the rest of the group. Pins that
        # interaction: quarantining a member doesn't un-skip its
        # dependents.
        from ctrlrunner.execution.quarantine import QuarantineConfig

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "quarantine_serial_suite"
            root.mkdir()
            (root / "test_serial_q.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        assert False, 'boom'\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )
            qc = QuarantineConfig(test_ids={"quarantine_serial_suite.test_serial_q::Flow.test_b"})
            orch = Orchestrator(str(root), 1, 10.0, quarantine=qc)
            reporter = orch.run()

            by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
            self.assertEqual(by_name["test_a"].outcome, "passed")
            self.assertEqual(by_name["test_b"].outcome, "quarantined_failure")
            self.assertTrue(by_name["test_b"].quarantined)
            self.assertEqual(by_name["test_c"].outcome, "skipped")


class CancellationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def test_run_stops_promptly_and_marks_remaining_as_cancelled(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "cancel_suite"
            root.mkdir()
            (root / "test_slow.py").write_text(
                "import time\n"
                "from ctrlrunner import test\n\n"
                "@test(timeout=30)\n"
                "def test_a():\n    pass\n\n"
                "@test(timeout=30)\n"
                "def test_b():\n    time.sleep(10)\n\n"
                "@test(timeout=30)\n"
                "def test_c():\n    pass\n"
            )
            cancel_event = threading.Event()
            orch = Orchestrator(str(root), 1, 30.0, cancel_event=cancel_event)

            def cancel_soon():
                time.sleep(0.5)
                cancel_event.set()

            threading.Thread(target=cancel_soon, daemon=True).start()

            start = time.time()
            reporter = orch.run()
            elapsed = time.time() - start

            self.assertLess(elapsed, 5.0)  # must not wait out test_b's sleep(10)
            outcomes = {r.outcome for r in reporter.results}
            self.assertIn("cancelled", outcomes)
            self.assertNotIn("failed", outcomes)


class WorkerIdOnResultTests(unittest.TestCase):
    """Result.worker_id should be populated from the slot that
    produced it on every result-producing path except the
    never-started cancelled-pending-batch path (which never had a
    slot assigned)."""

    def setUp(self):
        registry.reset()

    def test_finished_result_carries_worker_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_finished_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_x():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].worker_id, 1)

    def test_timeout_kill_result_carries_worker_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_timeout_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            orch = Orchestrator(str(root), 1, 1.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "failed")
        self.assertEqual(reporter.results[0].worker_id, 1)

    def test_worker_crash_result_carries_worker_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_crash_suite"
            root.mkdir()
            (root / "test_crash.py").write_text(
                "import os\nfrom ctrlrunner import test\n\n@test()\ndef test_a():\n    os._exit(1)\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "failed")
        self.assertEqual(reporter.results[0].worker_id, 1)

    def test_cancelled_pending_batch_has_no_worker_id(self):
        # A batch that was still pending (never assigned a slot) when
        # cancellation hits must NOT be attributed to any worker.
        # Drive _run_scheduler directly with num_workers=1 and two
        # batches so the second batch never gets a slot before the
        # cancel_event fires mid-first-batch.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_cancel_suite"
            root.mkdir()
            (root / "test_slow.py").write_text(
                "import time\n"
                "from ctrlrunner import test\n\n"
                "@test(timeout=30)\n"
                "def test_a():\n    time.sleep(10)\n\n"
                "@test(timeout=30)\n"
                "def test_b():\n    pass\n"
            )
            cancel_event = threading.Event()
            orch = Orchestrator(str(root), 1, 30.0, cancel_event=cancel_event)

            from ctrlrunner.core.registry import get_tests
            from ctrlrunner.execution.orchestrator import discover_and_import
            from ctrlrunner.reporting.grouping import compute_groups

            modules = discover_and_import(str(root))
            all_tests = get_tests()
            orch.items_by_id = {t.id: t for t in all_tests}
            orch.groups_by_id = {
                t.id: compute_groups(t, orch.grouping_dimensions, str(root)) for t in all_tests
            }
            test_ids = [t.id for t in all_tests]
            timeouts = {tid: 30.0 for tid in test_ids}
            # Two separate single-test batches -- the second is still
            # sitting in `pending` (no slot ever assigned to it) when
            # cancellation fires.
            from ctrlrunner.execution.worker_budget import Batch, ExecUnit

            pending = [
                Batch(units=[ExecUnit(key=tid, kind="single", test_ids=(tid,))]) for tid in test_ids
            ]

            def cancel_soon():
                time.sleep(0.5)
                cancel_event.set()

            threading.Thread(target=cancel_soon, daemon=True).start()

            orch._run_scheduler(pending, modules, timeouts)
            reporter = orch.reporter

        cancelled = [r for r in reporter.results if r.outcome == "cancelled"]
        self.assertEqual(len(cancelled), 2)
        self.assertTrue(all(r.worker_id is None for r in cancelled))

    def test_worker_id_stays_bounded_by_num_workers_across_sequential_batches(self):
        # Timeline report: worker_id is the row a test lands on in the
        # HTML report's Gantt chart, which pre-seeds exactly num_workers
        # rows. With num_workers=2 and 5 single-test batches, at least
        # one slot must be reused after freeing up -- worker_id must
        # never exceed num_workers even though more than num_workers
        # batches were spawned over the run's lifetime.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_bounded_suite"
            root.mkdir()
            body = "from ctrlrunner import test\n\n" + "\n".join(
                f"@test()\ndef test_{i}():\n    pass\n" for i in range(5)
            )
            (root / "test_many.py").write_text(body)
            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 5)
        worker_ids = {r.worker_id for r in reporter.results}
        self.assertTrue(worker_ids.issubset({1, 2}))

    def test_timeout_kill_result_carries_real_started_at(self):
        # The stuck test's worker did send a real "started" IPC message
        # before it was hard-killed -- that timestamp must survive onto
        # the synthetic result instead of defaulting to None (which
        # would otherwise drop it from the Gantt timeline as a gap).
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "worker_id_timeout_started_at_suite"
            root.mkdir()
            (root / "test_hang.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\n"
                "def test_hangs():\n    time.sleep(30)\n"
            )
            orch = Orchestrator(str(root), 1, 1.0)
            reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "failed")
        self.assertIsNotNone(reporter.results[0].started_at)


class SerialClassTests(unittest.TestCase):
    """@test_class(serial=True): definition order in one worker,
    skip-on-fail, and whole-group retries with exactly one finished
    result per test id."""

    def setUp(self):
        registry.reset()

    def test_serial_class_runs_in_definition_order_on_one_worker(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_order_suite"
            root.mkdir()
            (root / "test_serial_order.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_c_first(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_a_second(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b_third(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 4, 10.0)
            reporter = orch.run()

            self.assertEqual(len(reporter.results), 3)
            self.assertTrue(all(r.outcome == "passed" for r in reporter.results))
            self.assertEqual(len({r.worker_id for r in reporter.results}), 1)
            names = [r.test_id.rsplit(".", 1)[-1] for r in reporter.results]
            self.assertEqual(names, ["test_c_first", "test_a_second", "test_b_third"])

    def test_failure_skips_all_subsequent_group_members(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_skip_suite"
            root.mkdir()
            (root / "test_serial_skip.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        assert False, 'boom'\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
            self.assertEqual(len(reporter.results), 3)
            self.assertEqual(by_name["test_a"].outcome, "passed")
            self.assertEqual(by_name["test_b"].outcome, "failed")
            self.assertEqual(by_name["test_c"].outcome, "skipped")
            self.assertIn("serial group", by_name["test_c"].error)
            self.assertIn("test_b", by_name["test_c"].error)

    def test_group_retries_rerun_whole_group_with_one_result_per_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_retry_suite"
            root.mkdir()
            (root / "test_serial_retry.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "COUNT = {'a': 0, 'b': 0}\n\n"
                "@test_class(serial=True, retries=1)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n"
                "        COUNT['a'] += 1\n\n"
                "    @test()\n"
                "    def test_b(self):\n"
                "        COUNT['b'] += 1\n"
                "        assert COUNT['b'] >= 2, 'flaky once'\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            # exactly ONE result per test -- the failed first group
            # attempt emitted nothing
            self.assertEqual(len(reporter.results), 3)
            self.assertTrue(
                all(r.outcome == "passed" for r in reporter.results),
                [f"{r.test_id}: {r.outcome}" for r in reporter.results],
            )
            # every member reports the GROUP attempt number
            self.assertTrue(all(r.attempts == 2 for r in reporter.results))

    def test_exhausted_group_retries_report_failure_and_skips(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_exhaust_suite"
            root.mkdir()
            (root / "test_serial_exhaust.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True, retries=1)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        assert False, 'always'\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
            self.assertEqual(len(reporter.results), 3)
            self.assertEqual(by_name["test_a"].outcome, "passed")
            self.assertEqual(by_name["test_b"].outcome, "failed")
            self.assertEqual(by_name["test_b"].attempts, 2)
            self.assertEqual(by_name["test_c"].outcome, "skipped")

    def test_hard_kill_mid_group_without_budget_fails_stuck_and_skips_rest(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_kill_suite"
            root.mkdir()
            (root / "test_serial_kill.py").write_text(
                "import time\nfrom ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True, timeout=2)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n        time.sleep(60)\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 1, 2.0)
            reporter = orch.run()

            by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
            self.assertEqual(len(reporter.results), 3, sorted(by_name))
            self.assertEqual(by_name["test_a"].outcome, "passed")
            self.assertEqual(by_name["test_b"].outcome, "failed")
            self.assertIn("Hard-killed", by_name["test_b"].error)
            self.assertEqual(by_name["test_c"].outcome, "skipped")
            self.assertIn("hard-killed", by_name["test_c"].error)

    def test_hard_kill_mid_group_with_budget_requeues_whole_group_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_killretry_suite"
            root.mkdir()
            flag = (Path(tmp) / "first_attempt_done.flag").as_posix()
            (root / "test_serial_killretry.py").write_text(
                "import os\nimport time\nfrom ctrlrunner import test, test_class\n\n"
                f"FLAG = {flag!r}\n\n"
                "@test_class(serial=True, retries=1, timeout=2)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n        pass\n\n"
                "    @test()\n"
                "    def test_b(self):\n"
                "        if not os.path.exists(FLAG):\n"
                "            open(FLAG, 'w').close()\n"
                "            time.sleep(60)\n\n"
                "    @test()\n"
                "    def test_c(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 1, 2.0)
            reporter = orch.run()

            # first attempt hangs on test_b -> hard-kill consumes one
            # group attempt, nothing is reported; the WHOLE group runs
            # again on a fresh worker and passes -- exactly one result
            # per test, every member reporting group attempt 2.
            self.assertEqual(len(reporter.results), 3)
            self.assertTrue(
                all(r.outcome == "passed" for r in reporter.results),
                [f"{r.test_id}: {r.outcome}" for r in reporter.results],
            )
            self.assertTrue(all(r.attempts == 2 for r in reporter.results))
            test_ids = [r.test_id for r in reporter.results]
            self.assertEqual(len(test_ids), len(set(test_ids)), "duplicate results")

    def test_skipped_member_does_not_fail_the_group(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "serial_skipmember_suite"
            root.mkdir()
            (root / "test_serial_skipmember.py").write_text(
                "from ctrlrunner import skip, test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class Flow:\n"
                "    @test()\n"
                "    def test_a(self):\n"
                "        skip('not applicable here')\n\n"
                "    @test()\n"
                "    def test_b(self):\n        pass\n"
            )

            orch = Orchestrator(str(root), 2, 10.0)
            reporter = orch.run()

            by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
            self.assertEqual(by_name["test_a"].outcome, "skipped")
            self.assertEqual(by_name["test_b"].outcome, "passed")


class NextSpawnableIndexTests(unittest.TestCase):
    """The dedicated-mode eligibility check, in isolation: which pending
    batch may spawn given the live slots and the run's reservations."""

    def _orch(self, num_workers, reservations):
        orch = Orchestrator.__new__(Orchestrator)  # no run, no discovery
        orch.num_workers = num_workers
        orch._reservations = reservations
        return orch

    def _slot(self, group=None, dedicated=False):
        from ctrlrunner.execution.orchestrator import _WorkerSlot

        return _WorkerSlot(
            worker_id=0,
            proc=None,
            job=None,
            queue=None,
            remaining=["x"],
            deadline=0.0,
            group=group,
            dedicated=dedicated,
        )

    def _batch(self, group=None, dedicated=False):
        from ctrlrunner.execution.worker_budget import Batch, ExecUnit

        return Batch(
            units=[ExecUnit(key="k", kind="single", test_ids=("t",))],
            group=group,
            dedicated=dedicated,
        )

    def test_no_constraints_degenerates_to_fifo(self):
        orch = self._orch(4, {})
        pending = [self._batch(), self._batch()]
        self.assertEqual(orch._next_spawnable_index(pending, []), 0)

    def test_dedicated_batch_blocked_at_its_reservation(self):
        orch = self._orch(4, {"d": 1})
        pending = [self._batch(group="d", dedicated=True)]
        slots = [self._slot(group="d", dedicated=True)]
        self.assertIsNone(orch._next_spawnable_index(pending, slots))

    def test_dedicated_batch_allowed_below_its_reservation(self):
        orch = self._orch(4, {"d": 2})
        pending = [self._batch(group="d", dedicated=True)]
        slots = [self._slot(group="d", dedicated=True)]
        self.assertEqual(orch._next_spawnable_index(pending, slots), 0)

    def test_pool_batch_blocked_while_reservation_holds_slots_free(self):
        # n=2, d reserves 1 and still has pending work: the pool may
        # only use 1 slot even though 2 are physically free.
        orch = self._orch(2, {"d": 1})
        pending = [self._batch(group="d", dedicated=True), self._batch(), self._batch()]
        slots = [self._slot()]  # one live pool worker
        # index 0 (dedicated) is eligible; pool (1, 2) are not
        self.assertEqual(orch._next_spawnable_index(pending, slots), 0)
        # with the dedicated batch spawned, the next pick must be None:
        slots.append(self._slot(group="d", dedicated=True))
        self.assertIsNone(orch._next_spawnable_index(pending[1:], slots))

    def test_drained_dedicated_group_releases_its_reservation(self):
        # d has NO pending batch and NO live slot left -> its
        # reservation no longer subtracts from the pool budget.
        orch = self._orch(2, {"d": 1})
        pending = [self._batch(), self._batch()]
        slots = [self._slot()]
        self.assertEqual(orch._next_spawnable_index(pending, slots), 1 - 1)

    def test_live_dedicated_slot_keeps_reservation_active(self):
        # d's batch is live (could time out and requeue) -- the pool
        # budget stays shrunk while it runs.
        orch = self._orch(2, {"d": 1})
        pending = [self._batch()]
        slots = [self._slot(group="d", dedicated=True), self._slot()]
        self.assertIsNone(orch._next_spawnable_index(pending, slots))

    def test_skips_blocked_batch_and_returns_later_eligible_one(self):
        orch = self._orch(4, {"d": 1})
        pending = [self._batch(group="d", dedicated=True), self._batch()]
        slots = [self._slot(group="d", dedicated=True)]
        self.assertEqual(orch._next_spawnable_index(pending, slots), 1)

    def test_cap_batches_count_against_the_pool_not_reservations(self):
        # cap-labeled batches are ordinary pool citizens for slot math
        orch = self._orch(2, {})
        pending = [self._batch(group="c"), self._batch(group="c")]
        slots = [self._slot(group="c")]
        self.assertEqual(orch._next_spawnable_index(pending, slots), 0)


class CallOnFailureTests(unittest.TestCase):
    def test_calls_two_arg_callback_without_outcome(self):
        received = []

        def old_style(value, prefix):
            received.append((value, prefix))
            return "path"

        result = _call_on_failure(old_style, "val", "prefix", "failed")
        self.assertEqual(result, "path")
        self.assertEqual(received, [("val", "prefix")])

    def test_calls_three_arg_callback_with_outcome(self):
        received = []

        def new_style(value, prefix, outcome):
            received.append((value, prefix, outcome))
            return "path"

        result = _call_on_failure(new_style, "val", "prefix", "passed")
        self.assertEqual(result, "path")
        self.assertEqual(received, [("val", "prefix", "passed")])


class ArtifactCaptureTests(unittest.TestCase):
    def test_safe_test_dir_strips_special_characters(self):
        safe = _safe_test_dir("pkg.mod::test_x[en-US]")
        self.assertNotIn("::", safe)
        self.assertNotIn("[", safe)
        self.assertNotIn("]", safe)

    def test_capture_artifacts_calls_on_failure_and_returns_paths(self):
        captured_calls = []

        def on_failure(value, prefix):
            path = f"{prefix}.png"
            captured_calls.append((value, path))
            return path

        fixtures = {"page": Fixture(name="page", func=lambda: None, on_failure=on_failure)}
        resolved_all = {"page": {"url": "https://example.com"}}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            artifacts = capture_artifacts(
                "mod::test_x", 1, resolved_all, fixtures, artifacts_root=Path(tmp)
            )
            self.assertEqual(len(artifacts), 1)
            self.assertTrue(artifacts[0].endswith("page.png"))
            self.assertTrue(Path(artifacts[0]).parent.exists())

    def test_capture_artifacts_warns_when_on_failure_raises(self):
        def broken_on_failure(value, prefix):
            raise AttributeError("'dict' object has no attribute 'screenshot'")

        fixtures = {
            "custom_page": Fixture(
                name="custom_page", func=lambda: None, on_failure=broken_on_failure
            )
        }
        resolved_all = {"custom_page": {"url": "https://example.com"}}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with self.assertWarns(RuntimeWarning) as cm:
                artifacts = capture_artifacts(
                    "mod::test_x", 1, resolved_all, fixtures, artifacts_root=Path(tmp)
                )
            self.assertEqual(artifacts, [])
            message = str(cm.warning)
            self.assertIn("custom_page", message)
            self.assertIn("AttributeError", message)

    def test_extract_aria_snapshot_writes_artifact_and_trims_traceback(self):
        tb = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "AssertionError: Locator expected to contain text 'x'\n"
            "Actual value: y\n"
            "Call log:\n"
            '  - waiting for locator("h1")\n'
            "\nAria snapshot:\n"
            '- heading "Playwright enables reliable web automation" [level=1]\n'
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            trimmed, path = _extract_aria_snapshot(tb, "mod::test_x", 1, artifacts_root=Path(tmp))
            self.assertIsNotNone(path)
            self.assertTrue(path.endswith("aria-snapshot.yml"))
            content = Path(path).read_text()
            self.assertIn('- heading "Playwright enables reliable web automation"', content)
            self.assertNotIn("Aria snapshot:\n- heading", trimmed)
            self.assertIn("(Aria snapshot attached as aria-snapshot.yml)", trimmed)
            self.assertIn("Call log:", trimmed)

    def test_extract_aria_snapshot_leaves_plain_traceback_untouched(self):
        tb = "Traceback (most recent call last):\nAssertionError: nope\n"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            trimmed, path = _extract_aria_snapshot(tb, "mod::test_x", 1, artifacts_root=Path(tmp))
            self.assertIsNone(path)
            self.assertEqual(trimmed, tb)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_trim_aria_snapshot_from_steps_trims_nested_step_errors(self):
        steps = [
            {
                "name": "test body",
                "error": (
                    "AssertionError: Locator expected to contain text 'x'\n"
                    "Call log:\n  - waiting\n"
                    '\nAria snapshot:\n- heading "y" [level=1]'
                ),
                "children": [
                    {
                        "name": "inner",
                        "error": 'AssertionError: nope\nAria snapshot:\n- text "z"',
                        "children": [],
                    }
                ],
            },
            {"name": "clean", "error": None, "children": []},
        ]
        trimmed = _trim_aria_snapshot_from_steps(steps)
        self.assertNotIn("- heading", trimmed[0]["error"])
        self.assertIn("Call log:", trimmed[0]["error"])
        self.assertIn("(Aria snapshot attached as aria-snapshot.yml)", trimmed[0]["error"])
        self.assertNotIn('- text "z"', trimmed[0]["children"][0]["error"])
        self.assertIsNone(trimmed[1]["error"])

    def test_capture_artifacts_swallows_exceptions_from_on_failure(self):
        def broken_on_failure(value, prefix):
            raise RuntimeError("capture blew up")

        fixtures = {"page": Fixture(name="page", func=lambda: None, on_failure=broken_on_failure)}
        resolved_all = {"page": object()}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            artifacts = capture_artifacts(
                "mod::test_x", 1, resolved_all, fixtures, artifacts_root=Path(tmp)
            )
            self.assertEqual(artifacts, [])

    def test_capture_artifacts_skips_fixtures_without_on_failure(self):
        fixtures = {"page": Fixture(name="page", func=lambda: None, on_failure=None)}
        resolved_all = {"page": object()}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            artifacts = capture_artifacts(
                "mod::test_x", 1, resolved_all, fixtures, artifacts_root=Path(tmp)
            )
            self.assertEqual(artifacts, [])

    def test_only_always_skips_fixtures_without_always_capture(self):
        called = []

        def on_failure(value, prefix):
            called.append(value)
            return f"{prefix}.txt"

        fixtures = {
            "page": Fixture(
                name="page", func=lambda: None, on_failure=on_failure, always_capture=False
            )
        }
        resolved_all = {"page": "value"}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            artifacts = capture_artifacts(
                "mod::test_x",
                1,
                resolved_all,
                fixtures,
                artifacts_root=Path(tmp),
                only_always=True,
            )
            self.assertEqual(artifacts, [])
            self.assertEqual(called, [])

    def test_only_always_still_captures_fixtures_with_always_capture(self):
        def on_failure(value, prefix):
            path = f"{prefix}.txt"
            Path(path).write_text(value)
            return path

        fixtures = {
            "ctx": Fixture(
                name="ctx", func=lambda: None, on_failure=on_failure, always_capture=True
            )
        }
        resolved_all = {"ctx": "trace-data"}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            artifacts = capture_artifacts(
                "mod::test_x",
                1,
                resolved_all,
                fixtures,
                artifacts_root=Path(tmp),
                only_always=True,
            )
            self.assertEqual(len(artifacts), 1)
            self.assertTrue(artifacts[0].endswith("ctx.txt"))


class TimeoutSentinelResolutionTests(unittest.TestCase):
    """timeout=0 is an explicit (if unusual) user choice and must
    stay 0, not silently become the run's default_timeout -- the same
    is-None-means-unset contract retries already gets right."""

    def setUp(self):
        registry.reset()

    def test_explicit_timeout_zero_hard_kills_almost_immediately(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "zero_timeout_suite"
            root.mkdir()
            (root / "test_x.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=0)\ndef test_a():\n    time.sleep(20)\n"
            )
            start = time.time()
            orch = Orchestrator(str(root), 1, 20.0)  # default_timeout is deliberately large
            reporter = orch.run()
            elapsed = time.time() - start

        self.assertEqual(reporter.results[0].outcome, "failed")
        # WORKER_RESTART_BUFFER (5s) is the only slack; with the bug
        # (timeout=0 falling back to default_timeout=20.0) this would
        # take ~20s+ instead.
        self.assertLess(elapsed, 10.0)


class ImportPhaseTimeoutTests(unittest.TestCase):
    """Suite import time must not be charged against the first
    test's own timeout budget."""

    def setUp(self):
        registry.reset()

    def test_slow_import_does_not_false_timeout_the_first_test(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "slow_import_suite"
            root.mkdir()
            # Importing this module alone takes 0.6s -- comfortably
            # more than the first test's own 0.2s timeout (+0.1s
            # restart buffer, patched below), which is exactly the old
            # bug's trigger condition.
            (root / "test_a.py").write_text(
                "import time\ntime.sleep(0.6)\nfrom ctrlrunner import test\n\n"
                "@test()\ndef test_fast():\n    pass\n"
            )
            with (
                mock.patch("ctrlrunner.execution.orchestrator.WORKER_RESTART_BUFFER", 0.1),
                mock.patch("ctrlrunner.execution.orchestrator.IMPORT_PHASE_TIMEOUT", 5.0),
            ):
                orch = Orchestrator(str(root), 1, 0.2)
                reporter = orch.run()

        self.assertEqual(len(reporter.results), 1)
        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertNotIn("Hard-killed", reporter.results[0].error or "")


class ProcessGroupKillTests(unittest.TestCase):
    """JobObject.terminate() on POSIX must kill the whole process
    group, not just the leader's PID -- a plain os.kill only killed the
    leader, leaving any orphaned browser/node grandchild running."""

    @unittest.skipIf(sys.platform == "win32", "POSIX process-group behavior only")
    def test_terminate_kills_the_whole_process_group_not_just_the_leader(self):
        from ctrlrunner.execution.jobobject import JobObject

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pid_file = Path(tmp) / "child.pid"
            script = (
                "import os, sys, time\n"
                # Mirrors worker.run_worker()'s own os.setpgid(0, 0) --
                # a real worker sets its OWN pgid before launching any
                # browser/node helper; this script does the same so the
                # scenario matches production instead of relying on the
                # (broken) parent-side setpgid this test guards against.
                "os.setpgid(0, 0)\n"
                "pid = os.fork()\n"
                "if pid == 0:\n"
                "    time.sleep(30)\n"
                "    sys.exit(0)\n"
                "else:\n"
                "    with open(sys.argv[1], 'w') as f:\n"
                "        f.write(str(pid))\n"
                "    time.sleep(30)\n"
            )
            proc = subprocess.Popen([sys.executable, "-c", script, str(pid_file)])
            try:
                deadline = time.time() + 5
                while not pid_file.exists() and time.time() < deadline:
                    time.sleep(0.05)
                child_pid = int(pid_file.read_text())

                job = JobObject()
                job.assign(proc.pid)
                job.terminate()
                proc.wait(timeout=5)

                deadline = time.time() + 2
                child_alive = True
                while time.time() < deadline:
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        child_alive = False
                        break
                    time.sleep(0.05)
                self.assertFalse(child_alive, "grandchild process survived JobObject.terminate()")
            finally:
                with contextlib.suppress(Exception):
                    proc.kill()


class PolicyCancelDoesNotOverwriteExternalCancelTests(unittest.TestCase):
    """A policy trip must not overwrite an already-set external
    (UI/user) cancel reason -- otherwise unfinished tests get 'not_run'
    instead of 'cancelled'."""

    def test_external_cancel_reason_is_not_overwritten_by_a_later_policy_trip(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        fp = FailPolicyState(max_failures=1)
        orch = Orchestrator("unused", 1, 10.0, fail_policy=fp)
        orch.cancel_event.set()  # simulate an external cancel firing first
        orch._trigger_policy_cancel("max_failures")
        self.assertIsNone(fp.cancel_reason)
        self.assertTrue(orch.cancel_event.is_set())

    def test_policy_trip_still_sets_reason_when_nothing_cancelled_it_first(self):
        from ctrlrunner.execution.fail_policy import FailPolicyState

        fp = FailPolicyState(max_failures=1)
        orch = Orchestrator("unused", 1, 10.0, fail_policy=fp)
        orch._trigger_policy_cancel("max_failures")
        self.assertEqual(fp.cancel_reason, "max_failures")
        self.assertTrue(orch.cancel_event.is_set())


class NearTimeoutPerAttemptTests(unittest.TestCase):
    """near_timeout must compare a SINGLE attempt's own duration to
    its own per-attempt budget, not the aggregate across every retry."""

    def setUp(self):
        registry.reset()

    def test_retried_test_is_not_falsely_flagged_from_aggregate_duration(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "retry_near_timeout_suite"
            root.mkdir()
            # Two attempts of 0.5s each (50% of the 1.0s per-attempt
            # budget) sum to 1.0s aggregate -- >= 0.8 * 1.0, which is
            # exactly what the OLD (aggregate-based) code would flag as
            # near_timeout, despite neither attempt individually
            # coming close.
            (root / "test_a.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "_state = {'n': 0}\n\n"
                "@test(timeout=1.0, retries=1)\n"
                "def test_flaky_then_pass():\n"
                "    _state['n'] += 1\n"
                "    time.sleep(0.5)\n"
                "    if _state['n'] == 1:\n"
                "        assert False\n"
            )
            orch = Orchestrator(str(root), 1, 1.0)
            reporter = orch.run()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(result.attempts, 2)
        self.assertFalse(result.near_timeout)


class SchedulerCrashSafetyTests(unittest.TestCase):
    """An exception from an EventSubscriber or ConsoleReporter must
    never orphan a live worker slot -- it gets logged once and that
    specific subscriber/reporter is disabled, everything else (other
    subscribers, other reporters, the run itself) keeps working."""

    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp, name="crash_safety_suite"):
        root = Path(tmp) / name
        root.mkdir()
        (root / "test_a.py").write_text(
            "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
        )
        return root

    def test_broken_event_subscriber_does_not_crash_the_run(self):
        from ctrlrunner.reporting.events import EventSubscriber

        class BrokenSubscriber(EventSubscriber):
            def on_event(self, event):
                raise RuntimeError("boom")

        received = []

        class GoodSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event.type)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(
                str(root),
                1,
                10.0,
                event_subscribers=[BrokenSubscriber(), GoodSubscriber()],
            )
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        # the good subscriber kept receiving events despite the other one
        # raising on every single call
        self.assertIn("run_start", received)
        self.assertIn("run_end", received)

    def test_broken_console_reporter_does_not_prevent_other_reporters(self):
        from ctrlrunner.reporting.reporters import ConsoleReporter

        class BrokenReporter(ConsoleReporter):
            def on_test_end(self, result):
                raise RuntimeError("boom")

            def on_run_end(self, results, duration):
                raise RuntimeError("boom")

        seen_ends = []

        class GoodReporter(ConsoleReporter):
            def on_test_end(self, result):
                seen_ends.append(result.test_id)

            def on_run_end(self, results, duration):
                seen_ends.append("run_end")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp, "crash_safety_suite2")
            orch = Orchestrator(
                str(root), 1, 10.0, console_reporters=[BrokenReporter(), GoodReporter()]
            )
            reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        self.assertIn(reporter.results[0].test_id, seen_ends)
        self.assertIn("run_end", seen_ends)


class GuardedOnRunEndTests(unittest.TestCase):
    """A reporter whose on_run_end raises
    (e.g. a locked/corrupt history store) must not stop later
    reporters (JUnit/JSON/HTML) from getting their own on_run_end
    call."""

    def setUp(self):
        registry.reset()

    def test_reporter_raising_in_on_run_end_does_not_block_the_next_reporter(self):
        from ctrlrunner.reporting.reporters import ConsoleReporter

        class LockedHistoryReporter(ConsoleReporter):
            def on_run_end(self, results, duration):
                raise RuntimeError("database is locked")

        calls = []

        class JsonLikeReporter(ConsoleReporter):
            def on_run_end(self, results, duration):
                calls.append(len(results))

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "guarded_on_run_end_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(
                str(root),
                1,
                10.0,
                console_reporters=[LockedHistoryReporter(), JsonLikeReporter()],
            )
            orch.run()

        self.assertEqual(calls, [1])


class QueueDrainTests(unittest.TestCase):
    """B1/B2: a result already sitting in a slot's queue at the moment
    the slot is finalized (clean exit, crash, timeout, or cancellation)
    must be read and turned into a Result -- not lost, and not left to
    make an already-completed test get mislabeled not_run/crashed."""

    def setUp(self):
        registry.reset()

    def _fake_item(self, test_id):
        from ctrlrunner.core.registry import TestItem

        return TestItem(id=test_id, func=lambda: None, params=[])

    def test_finalize_slot_drains_a_trailing_finished_message_before_reporting_not_run(self):
        import multiprocessing as mp

        from ctrlrunner.execution.jobobject import JobObject
        from ctrlrunner.execution.orchestrator import Orchestrator, _WorkerSlot

        orch = Orchestrator("unused", 1, 10.0)
        orch.items_by_id = {"mod::test_a": self._fake_item("mod::test_a")}
        orch.groups_by_id = {"mod::test_a": {}}

        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        # Simulate the exact race: a real "finished" message is sitting
        # in the queue at the moment we decide to finalize the slot
        # (e.g. is_alive() just went False).
        q.put(
            (
                "finished",
                1,
                "mod::test_a",
                "passed",
                None,
                0.01,
                1,
                [],
                [],
                {},
                0.01,
                None,
                None,
                None,
                time.time(),
            )
        )
        time.sleep(0.1)  # let the feeder thread flush it into the pipe

        class DummyProc:
            def join(self, timeout=None):
                pass

            def is_alive(self):
                return False

        slot = _WorkerSlot(
            worker_id=1,
            proc=DummyProc(),
            job=JobObject(),
            queue=q,
            remaining=["mod::test_a"],
            deadline=time.time() + 10,
            killed=True,
        )

        timeouts = {"mod::test_a": 10.0}
        orch._finalize_slot(slot, timeouts)

        # The drain must have consumed the "finished" message and
        # removed the test from slot.remaining -- so a subsequent
        # not_run/timeout-kill report for this slot would no longer
        # include it.
        self.assertNotIn("mod::test_a", slot.remaining)
        self.assertEqual(len(orch.reporter.results), 1)
        self.assertEqual(orch.reporter.results[0].outcome, "passed")
        q.close()

    def test_corrupt_message_is_logged_not_silently_swallowed(self):
        from ctrlrunner.execution.jobobject import JobObject
        from ctrlrunner.execution.orchestrator import Orchestrator, _WorkerSlot

        orch = Orchestrator("unused", 1, 10.0)

        class BoomQueue:
            def get_nowait(self):
                raise RuntimeError("corrupt pickle")

            def close(self):
                pass

        class DummyProc:
            def join(self, timeout=None):
                pass

            def is_alive(self):
                return False

        slot = _WorkerSlot(
            worker_id=1,
            proc=DummyProc(),
            job=JobObject(),
            queue=BoomQueue(),
            remaining=["mod::test_a"],
            deadline=time.time() + 10,
        )

        with self.assertLogs("ctrlrunner.execution.orchestrator", level="ERROR") as ctx:
            orch._drain_queue_once(slot, {"mod::test_a": 10.0})

        self.assertTrue(any("corrupt" in msg.lower() for msg in ctx.output))


class EventPayloadFieldsTests(unittest.TestCase):
    """test_end/test_start event payloads must carry
    retriesConfigured, workerId, and nearTimeout so a consumer can
    correlate events back to worker lifecycle and retry configuration."""

    def setUp(self):
        registry.reset()

    def test_test_end_payload_includes_worker_id_retries_configured_and_near_timeout(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "event_payload_fields_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n@test(retries=2)\ndef test_a():\n    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        test_end = next(e for e in received if e.type == "test_end")
        self.assertIn("workerId", test_end.payload)
        self.assertIn("retriesConfigured", test_end.payload)
        self.assertIn("nearTimeout", test_end.payload)
        self.assertEqual(test_end.payload["retriesConfigured"], 2)

        test_start = next(e for e in received if e.type == "test_start")
        self.assertIn("workerId", test_start.payload)


class EventOrderingTests(unittest.TestCase):
    """test_end for a test a worker was killed/crashed over must
    precede that worker's worker_terminated event; every test_end has a
    preceding test_start, even for tests that were cancelled/not_run
    before a real one ever arrived."""

    def setUp(self):
        registry.reset()

    def test_test_end_precedes_worker_terminated_on_timeout_kill(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "event_ordering_timeout_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "import time\nfrom ctrlrunner import test\n\n"
                "@test(timeout=1)\ndef test_hangs():\n    time.sleep(30)\n"
            )
            orch = Orchestrator(str(root), 1, 1.0, event_subscribers=[RecordingSubscriber()])
            orch.run()

        types_with_reason = [(e.type, e.payload.get("reason")) for e in received]
        test_end_idx = next(i for i, (t, _) in enumerate(types_with_reason) if t == "test_end")
        terminated_idx = next(
            i
            for i, (t, r) in enumerate(types_with_reason)
            if t == "worker_terminated" and r == "timeout"
        )
        self.assertLess(test_end_idx, terminated_idx)

    def test_cancelled_test_end_has_a_preceding_test_start(self):
        from ctrlrunner.reporting.events import EventSubscriber

        received = []

        class RecordingSubscriber(EventSubscriber):
            def on_event(self, event):
                received.append(event)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "event_ordering_cancel_suite"
            root.mkdir()
            (root / "test_a.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\ndef test_a():\n    pass\n\n"
                "@test()\ndef test_b():\n    pass\n"
            )
            cancel_event = threading.Event()
            cancel_event.set()  # cancel before anything ever starts
            orch = Orchestrator(
                str(root),
                1,
                10.0,
                cancel_event=cancel_event,
                event_subscribers=[RecordingSubscriber()],
            )
            reporter = orch.run()

        self.assertTrue(all(r.outcome == "cancelled" for r in reporter.results))
        started_ids = {e.payload["id"] for e in received if e.type == "test_start"}
        ended_ids = {e.payload["id"] for e in received if e.type == "test_end"}
        # every test_end must have a matching test_start -- synthesized
        # for tests that never actually got a real one.
        self.assertEqual(ended_ids, started_ids)


class AssertDetailsIntegrationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp):
        root = Path(tmp) / "assert_details_suite"
        root.mkdir()
        (root / "test_assert_details.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\n"
            "def test_equality_failure():\n"
            "    left = 1\n"
            "    right = 2\n"
            "    assert left == right\n\n"
            "@test()\n"
            "def test_explicit_raise():\n"
            "    raise AssertionError('boom')\n\n"
            "@test()\n"
            "def test_passing():\n"
            "    assert 1 == 1\n"
        )
        return root

    def test_assertion_failure_populates_assert_details(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        eq_result = by_id["test_equality_failure"]
        self.assertEqual(eq_result.outcome, "failed")
        self.assertIsNotNone(eq_result.assert_details)
        self.assertEqual(eq_result.assert_details["expr"], "left == right")
        self.assertEqual(eq_result.assert_details["left"]["repr"], "1")
        self.assertEqual(eq_result.assert_details["right"]["repr"], "2")

    def test_explicit_raise_leaves_assert_details_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertIsNone(by_id["test_explicit_raise"].assert_details)

    def test_passing_test_has_no_assert_details(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertIsNone(by_id["test_passing"].assert_details)

    def test_assert_details_survives_full_chain_into_html_report(self):
        from ctrlrunner.reporting.html_report import render_html

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        out = render_html(reporter.results)
        self.assertIn("left == right", out)


class LogCaptureIntegrationTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp):
        root = Path(tmp) / "log_capture_suite"
        root.mkdir()
        (root / "test_log_capture_suite.py").write_text(
            "import logging\n"
            "from ctrlrunner import test\n\n"
            "@test()\n"
            "def test_passing_with_output():\n"
            "    print('hello from passing test')\n"
            "    logging.getLogger('demo').warning('warning from passing test')\n\n"
            "@test()\n"
            "def test_failing_with_output():\n"
            "    print('hello from failing test')\n"
            "    assert False\n"
        )
        return root

    def test_logs_off_by_default_populates_nothing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        for r in reporter.results:
            self.assertIsNone(r.logs)

    def test_logs_on_captures_both_passing_and_failing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0, logs_mode="on")
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        for name in ("test_passing_with_output", "test_failing_with_output"):
            self.assertIsNotNone(by_id[name].logs)
            self.assertEqual(len(by_id[name].logs), 1)
        self.assertIn(
            "hello from passing test", by_id["test_passing_with_output"].logs[0]["stdout"]
        )
        self.assertIn(
            "warning from passing test",
            by_id["test_passing_with_output"].logs[0]["records"][0]["message"],
        )
        self.assertIn(
            "hello from failing test", by_id["test_failing_with_output"].logs[0]["stdout"]
        )

    def test_logs_only_on_failure_keeps_failing_drops_passing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._make_suite(tmp)
            orch = Orchestrator(str(root), 1, 10.0, logs_mode="only-on-failure")
            reporter = orch.run()

        by_id = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertIsNone(by_id["test_passing_with_output"].logs)
        self.assertIsNotNone(by_id["test_failing_with_output"].logs)
        self.assertIn(
            "hello from failing test", by_id["test_failing_with_output"].logs[0]["stdout"]
        )


class CoverageIntegrationTests(unittest.TestCase):
    """Spawns a real worker process with coverage enabled and checks a
    data file lands in the configured data_dir -- mirrors the existing
    AssertDetailsIntegrationTests/LogCaptureIntegrationTests pattern of
    running Orchestrator.run() end-to-end rather than calling run_worker()
    directly, since it must exercise the real spawn/import/exit path."""

    def setUp(self):
        registry.reset()
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def test_worker_writes_coverage_data_file(self):
        test_dir = os.path.join(self.tmp_dir, "tests")
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "test_cov_demo.py"), "w") as f:
            f.write(
                "from ctrlrunner import test\n\n@test()\ndef test_one():\n    assert 1 + 1 == 2\n"
            )

        data_dir = os.path.join(self.tmp_dir, ".coverage-data")
        os.makedirs(data_dir)
        coverage_config = CoverageConfig(
            enabled=True,
            data_dir=data_dir,
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )

        orch = Orchestrator(
            test_dir,
            num_workers=1,
            default_timeout=10.0,
            coverage_config=coverage_config,
        )
        reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")
        data_files = glob.glob(os.path.join(data_dir, ".coverage.*"))
        self.assertTrue(data_files, f"expected a .coverage.* file in {data_dir}")
        self.assertIsInstance(orch.run_duration, float)
        self.assertGreaterEqual(orch.run_duration, 0.0)

    def test_hard_kill_increments_coverage_config(self):
        """A worker that never finishes its batch (timeout) is
        hard-killed via JobObject.terminate() before it can reach its own
        cov.stop()/cov.save() -- coverage_config.hard_kills must reflect
        that, so the run can warn about incomplete coverage data."""
        test_dir = os.path.join(self.tmp_dir, "tests3")
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "test_cov_hang.py"), "w") as f:
            f.write(
                "import time\n"
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_hangs():\n"
                "    time.sleep(30)\n"
            )

        data_dir = os.path.join(self.tmp_dir, ".coverage-data-3")
        os.makedirs(data_dir)
        coverage_config = CoverageConfig(
            enabled=True,
            data_dir=data_dir,
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )

        orch = Orchestrator(
            test_dir,
            num_workers=1,
            default_timeout=0.5,
            coverage_config=coverage_config,
        )
        orch.run()

        self.assertEqual(coverage_config.hard_kills, 1)

    def test_contexts_enabled_switches_per_test(self):
        test_dir = os.path.join(self.tmp_dir, "tests4")
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "test_cov_ctx.py"), "w") as f:
            f.write(
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_a():\n"
                "    assert 1 == 1\n\n"
                "@test()\n"
                "def test_b():\n"
                "    assert 2 == 2\n"
            )

        data_dir = os.path.join(self.tmp_dir, ".coverage-data-4")
        os.makedirs(data_dir)
        coverage_config = CoverageConfig(
            enabled=True,
            data_dir=data_dir,
            html_dir=None,
            source=None,
            fail_under=None,
            fail_under_enforced=True,
            contexts=True,
        )

        orch = Orchestrator(
            test_dir,
            num_workers=1,
            default_timeout=10.0,
            coverage_config=coverage_config,
        )
        reporter = orch.run()

        self.assertEqual(len(reporter.results), 2)
        for r in reporter.results:
            self.assertEqual(r.outcome, "passed")
        data_files = glob.glob(os.path.join(data_dir, ".coverage.*"))
        self.assertTrue(data_files)

    def test_module_level_code_is_covered(self):
        """Regression test: coverage.start() used to run AFTER the worker's import loop, so
        every module-level statement (imports, def/class statements,
        decorators, module-level constants computed via a function call)
        in the code under test was invisible to coverage.py -- only
        function bodies actually called during the test loop got
        recorded. A module with true near-100% coverage was reported as
        ~25% under the old ordering. This fixture module deliberately
        exercises module-level code (a top-level function called to
        compute a module-level constant, and a top-level class) so that
        a wrong-but-in-range percentage (which the old, weaker assertions
        in this class would have let through) can't silently pass."""
        test_dir = os.path.join(self.tmp_dir, "tests5")
        os.makedirs(test_dir)
        with open(os.path.join(test_dir, "test_cov_module_level.py"), "w") as f:
            f.write(
                "from ctrlrunner import test\n\n"
                "def multiply(x, y):\n"
                "    return x * y\n\n"
                "class Calculator:\n"
                "    def add(self, a, b):\n"
                "        return a + b\n\n"
                "CONSTANT = multiply(6, 7)\n\n"
                "@test()\n"
                "def test_module_level_code():\n"
                "    assert CONSTANT == 42\n"
                "    calc = Calculator()\n"
                "    assert calc.add(2, 3) == 5\n"
            )

        data_dir = os.path.join(self.tmp_dir, ".coverage-data-5")
        os.makedirs(data_dir)
        coverage_config = CoverageConfig(
            # source is scoped to just the fixture module's own directory
            # (as a real user's [ctrlrunner.coverage].source config would
            # be) so the reported percentage measures only the code under
            # test, not incidental ctrlrunner-internal code that also runs
            # in the worker process after cov.start().
            enabled=True,
            data_dir=data_dir,
            html_dir=None,
            source=[test_dir],
            fail_under=None,
            fail_under_enforced=True,
            contexts=False,
        )

        orch = Orchestrator(
            test_dir,
            num_workers=1,
            default_timeout=10.0,
            coverage_config=coverage_config,
        )
        reporter = orch.run()

        self.assertEqual(reporter.results[0].outcome, "passed")

        summary = finalize_coverage(coverage_config)
        # Before the fix, the module-level function/class/import/constant
        # statements above (only ever executed at import time, before
        # cov.start() ran) were invisible to coverage.py and this same
        # fixture reported roughly a third of its statements covered.
        # With the fix, essentially the whole small, fully-exercised
        # module is covered.
        self.assertGreaterEqual(
            summary.percent,
            80.0,
            f"expected high coverage with module-level code counted, got {summary.percent}",
        )


class RecordPropertyE2ETests(unittest.TestCase):
    """Runtime record_property()/record_suite_property() flow
    from a worker process into Result.properties and
    reporter.suite_properties respectively."""

    def setUp(self):
        registry.reset()

    def test_record_property_and_suite_property_reach_the_report(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "recprop_suite"
            root.mkdir()
            (root / "test_props.py").write_text(
                "from ctrlrunner import record_property, record_suite_property, test\n\n"
                "@test()\n"
                "def test_records():\n"
                '    record_property("testrail", "C123")\n'
                '    record_suite_property("environment", "staging")\n'
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(result.properties.get("testrail"), "C123")
        self.assertEqual(reporter.suite_properties, {"environment": "staging"})


class TeardownErrorSurfacingTests(unittest.TestCase):
    """A passing test whose fixture teardown raised used
    to stay silently 'passed' -- a false-pass. Default (strict_teardown)
    now fails it; strict_teardown=False keeps the old outcome but flags
    it via a teardown_failed property."""

    SUITE = (
        "from ctrlrunner import fixture, test\n\n"
        "@fixture(scope='function')\n"
        "def broken():\n"
        "    yield 'value'\n"
        "    raise RuntimeError('teardown boom')\n\n"
        "@test()\n"
        "def test_uses_broken(broken):\n"
        "    assert broken == 'value'\n"
    )

    def setUp(self):
        registry.reset()

    def _run(self, suite_src, **orch_kwargs):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "td_suite"
            root.mkdir()
            (root / "test_td.py").write_text(suite_src)
            orch = Orchestrator(str(root), 1, 10.0, **orch_kwargs)
            return orch.run()

    def test_strict_default_fails_a_passing_test_with_broken_teardown(self):
        reporter = self._run(self.SUITE)
        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertIn("teardown failed", result.error)
        self.assertIn("RuntimeError: teardown boom", result.error)
        self.assertEqual(result.properties.get("teardown_failed"), "true")

    def test_non_strict_keeps_passed_but_flags_property(self):
        reporter = self._run(self.SUITE, strict_teardown=False)
        result = reporter.results[0]
        self.assertEqual(result.outcome, "passed")
        self.assertEqual(result.properties.get("teardown_failed"), "true")

    def test_failed_test_gets_teardown_error_appended(self):
        suite = self.SUITE.replace(
            "    assert broken == 'value'\n",
            "    raise AssertionError('test itself failed')\n",
        )
        reporter = self._run(suite)
        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertIn("test itself failed", result.error)
        self.assertIn("Additionally, fixture teardown failed", result.error)

    def test_session_scope_teardown_error_lands_in_suite_properties(self):
        suite = (
            "from ctrlrunner import fixture, test\n\n"
            "@fixture(scope='session')\n"
            "def sess_broken():\n"
            "    yield 'value'\n"
            "    raise RuntimeError('session teardown boom')\n\n"
            "@test()\n"
            "def test_uses(sess_broken):\n"
            "    pass\n"
        )
        reporter = self._run(suite)
        result = reporter.results[0]
        # the test itself finished before session teardown ran
        self.assertEqual(result.outcome, "passed")
        keys = [k for k in reporter.suite_properties if k.startswith("teardown_error:")]
        self.assertEqual(keys, ["teardown_error:sess_broken"])
        self.assertIn("session teardown boom", reporter.suite_properties[keys[0]])


class FilteredTracebackE2ETests(unittest.TestCase):
    """A real failed run's error text starts at user code --
    no ctrlrunner/execution/worker.py dispatch frames."""

    def setUp(self):
        registry.reset()

    def test_failure_traceback_has_no_runner_frames(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "tb_suite"
            root.mkdir()
            (root / "test_tb.py").write_text(
                "from ctrlrunner import test\n\n"
                "@test()\n"
                "def test_fails():\n"
                "    raise AssertionError('user boom')\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        result = reporter.results[0]
        self.assertEqual(result.outcome, "failed")
        self.assertIn("user boom", result.error)
        self.assertIn("test_tb.py", result.error)
        self.assertNotIn("ctrlrunner/execution/worker.py", result.error)


class ReconciliationInvariantTests(unittest.TestCase):
    """Safety belt for the exactly-once result contract:
    a selected test that somehow produced no Result gets a synthesized
    failure instead of silently vanishing from the report."""

    def setUp(self):
        registry.reset()

    def _make_suite(self, tmp):
        root = Path(tmp) / "recon_suite"
        root.mkdir()
        (root / "test_recon.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\ndef test_one():\n    pass\n\n"
            "@test()\ndef test_two():\n    pass\n"
        )
        return root

    def test_normal_run_is_a_noop(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            orch = Orchestrator(str(self._make_suite(tmp)), 1, 10.0)
            reporter = orch.run()
        outcomes = {r.test_id.split("::")[-1]: r.outcome for r in reporter.results}
        self.assertEqual(outcomes, {"test_one": "passed", "test_two": "passed"})

    def test_dropped_result_is_synthesized_as_failed(self):
        # Simulate a bookkeeping regression: the reporter silently drops
        # one specific test's real result.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            orch = Orchestrator(str(self._make_suite(tmp)), 1, 10.0)
            real_add = orch.reporter.add_result
            dropped = []

            def dropping_add(test_id, outcome, error, duration, **kwargs):
                if test_id.endswith("test_two") and not dropped:
                    dropped.append(test_id)
                    # swallow the genuine result once
                    return Result(test_id=test_id, outcome=outcome, error=error, duration=duration)
                return real_add(test_id, outcome, error, duration, **kwargs)

            orch.reporter.add_result = dropping_add
            reporter = orch.run()

        self.assertEqual(dropped, ["recon_suite.test_recon::test_two"])
        by_name = {r.test_id.split("::")[-1]: r for r in reporter.results}
        self.assertEqual(by_name["test_one"].outcome, "passed")
        self.assertEqual(by_name["test_two"].outcome, "failed")
        self.assertIn("produced no result", by_name["test_two"].error)


class WarningsCaptureTests(unittest.TestCase):
    """Python warnings raised during a test are captured
    per-test into Result.warnings (JSON `warnings`, console summary)."""

    def setUp(self):
        registry.reset()

    def test_deprecation_warning_captured_on_result(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "warn_suite"
            root.mkdir()
            (root / "test_warns.py").write_text(
                "import warnings\nfrom ctrlrunner import test\n\n"
                "@test()\n"
                "def test_warns():\n"
                "    warnings.warn('legacy api', DeprecationWarning)\n\n"
                "@test()\n"
                "def test_clean():\n"
                "    pass\n"
            )
            orch = Orchestrator(str(root), 1, 10.0)
            reporter = orch.run()

        by_name = {r.test_id.split("::")[-1]: r for r in reporter.results}
        warns = by_name["test_warns"].warnings
        self.assertIsNotNone(warns)
        self.assertEqual(warns[0]["category"], "DeprecationWarning")
        self.assertIn("legacy api", warns[0]["message"])
        self.assertEqual(warns[0]["attempt"], 1)
        self.assertIn("test_warns.py", warns[0]["filename"])
        self.assertIsNone(by_name["test_clean"].warnings)


class DottedNameAliasTests(unittest.TestCase):
    """The runner imports test files under a hash-of-path
    sys.modules key. Without also aliasing the dotted name,
    user code doing `import tests_pkg.test_mod` re-executes the file into
    a SECOND module object with divergent globals -- the classic
    importlib-mode double-import."""

    def _cleanup(self, tmp_dir, keys):
        if tmp_dir in sys.path:
            sys.path.remove(tmp_dir)
        for k in keys:
            sys.modules.pop(k, None)

    def test_dotted_import_returns_the_runner_module_object(self):
        import importlib

        from ctrlrunner.execution.worker import import_module_by_path, module_name_for_path

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pkg = Path(tmp) / "alias_demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "test_aliased.py").write_text("SENTINEL = []\n")
            sys.path.insert(0, tmp)
            keys = [
                module_name_for_path(pkg / "test_aliased.py"),
                "alias_demo_pkg.test_aliased",
                "alias_demo_pkg",
            ]
            self.addCleanup(self._cleanup, tmp, keys)

            key = import_module_by_path(pkg / "test_aliased.py", "alias_demo_pkg.test_aliased")
            runner_mod = sys.modules[key]
            runner_mod.SENTINEL.append("set-by-runner")

            user_mod = importlib.import_module("alias_demo_pkg.test_aliased")
            self.assertIs(user_mod, runner_mod)
            self.assertEqual(user_mod.SENTINEL, ["set-by-runner"])

    def test_alias_never_clobbers_an_existing_dotted_module(self):
        # Regression guard: two files producing the SAME dotted name
        # (two roots with identical relative layout) each keep their own
        # hash key; the alias stays pointing at whoever came first.
        from ctrlrunner.execution.worker import import_module_by_path, module_name_for_path

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            for root in (a, b):
                root.mkdir()
                (root / "test_same.py").write_text(f"WHO = {str(root.name)!r}\n")
            keys = [
                module_name_for_path(a / "test_same.py"),
                module_name_for_path(b / "test_same.py"),
                "test_same",
            ]
            self.addCleanup(self._cleanup, tmp, keys)

            key_a = import_module_by_path(a / "test_same.py", "test_same")
            key_b = import_module_by_path(b / "test_same.py", "test_same")
            self.assertNotEqual(key_a, key_b)
            self.assertEqual(sys.modules[key_a].WHO, "a")
            self.assertEqual(sys.modules[key_b].WHO, "b")
            # alias belongs to the first file and was not stolen
            self.assertIs(sys.modules["test_same"], sys.modules[key_a])


class StartedAtThreadingTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def tearDown(self):
        registry.reset()

    def test_result_started_at_is_set_from_a_real_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_started_at_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            before = time.time()
            orch = Orchestrator(str(root), num_workers=1, default_timeout=30.0)
            reporter = orch.run()
            after = time.time()

        [result] = reporter.results
        self.assertIsNotNone(result.started_at)
        self.assertGreaterEqual(result.started_at, before)
        self.assertLessEqual(result.started_at, after)

    def test_serial_group_skip_on_fail_member_gets_started_at(self):
        # Exercises _run_serial_group's synthetic "finished" tuple for a
        # skipped member -- it must carry the SAME started_at as the
        # "started" message put right before it (worker.py:431), not None.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_serial_skip_demo.py").write_text(
                "from ctrlrunner import test, test_class\n\n"
                "@test_class(serial=True)\n"
                "class SerialDemo:\n"
                "    @test()\n"
                "    def test_first_fails(self):\n"
                "        assert False\n\n"
                "    @test()\n"
                "    def test_second_never_runs(self):\n"
                "        pass\n"
            )
            before = time.time()
            orch = Orchestrator(str(root), num_workers=1, default_timeout=30.0)
            reporter = orch.run()
            after = time.time()

        by_name = {r.test_id.rsplit(".", 1)[-1]: r for r in reporter.results}
        skipped = by_name["test_second_never_runs"]
        self.assertEqual(skipped.outcome, "skipped")
        self.assertIsNotNone(skipped.started_at)
        self.assertGreaterEqual(skipped.started_at, before)
        self.assertLessEqual(skipped.started_at, after)

    def test_orchestrator_exposes_run_start(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_run_start_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            before = time.time()
            orch = Orchestrator(str(root), num_workers=1, default_timeout=30.0)
            orch.run()
            after = time.time()

        self.assertGreaterEqual(orch.run_start, before)
        self.assertLessEqual(orch.run_start, after)


class CollectionSummaryPrintTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def tearDown(self):
        registry.reset()

    def test_run_prints_collection_summary_before_scheduling(self):
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "tests"
            root.mkdir()
            (root / "test_collection_summary_demo.py").write_text(
                "from ctrlrunner import test\n\n@test()\ndef test_a():\n    pass\n"
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                Orchestrator(str(root), num_workers=1, default_timeout=30.0).run()
        self.assertIn("Collected 1 test across 1 file", buf.getvalue())


class GrepFilterOrchestratorTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def tearDown(self):
        registry.reset()

    def _write_suite(self, tmp):
        root = Path(tmp) / "tests"
        root.mkdir()
        (root / "test_grep_demo.py").write_text(
            "from ctrlrunner import test\n\n"
            "@test()\ndef test_login():\n    pass\n\n"
            "@test()\ndef test_logout():\n    pass\n\n"
            "@test()\ndef test_signup():\n    pass\n"
        )

    def test_grep_selects_matching_tests_only(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self._write_suite(tmp)
            orch = Orchestrator(
                str(Path(tmp) / "tests"), num_workers=1, default_timeout=30.0, grep="log"
            )
            reporter = orch.run()
        ids = {r.test_id.rsplit("::", 1)[-1] for r in reporter.results}
        self.assertEqual(ids, {"test_login", "test_logout"})

    def test_grep_not_excludes_matching_tests(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            self._write_suite(tmp)
            orch = Orchestrator(
                str(Path(tmp) / "tests"), num_workers=1, default_timeout=30.0, grep_not="log"
            )
            reporter = orch.run()
        ids = {r.test_id.rsplit("::", 1)[-1] for r in reporter.results}
        self.assertEqual(ids, {"test_signup"})


class OrderSeedOrchestratorTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def tearDown(self):
        registry.reset()

    def _write_suite(self, tmp):
        root = Path(tmp) / "tests"
        root.mkdir()
        for name in ("a", "b", "c"):
            (root / f"test_order_{name}.py").write_text(
                f"from ctrlrunner import test\n\n@test()\ndef test_{name}():\n    pass\n"
            )
        return str(root)

    def test_default_order_stamps_no_suite_properties(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._write_suite(tmp)
            orch = Orchestrator(root, num_workers=1, default_timeout=30.0)
            orch.run()
        self.assertNotIn("order", orch.reporter.suite_properties)
        self.assertNotIn("seed", orch.reporter.suite_properties)

    def test_random_order_stamps_order_and_seed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._write_suite(tmp)
            orch = Orchestrator(root, num_workers=1, default_timeout=30.0, order="random", seed=7)
            orch.run()
        self.assertEqual(orch.reporter.suite_properties["order"], "random")
        self.assertEqual(orch.reporter.suite_properties["seed"], "7")

    def test_alpha_order_stamps_order_without_seed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._write_suite(tmp)
            orch = Orchestrator(root, num_workers=1, default_timeout=30.0, order="alpha")
            orch.run()
        self.assertEqual(orch.reporter.suite_properties["order"], "alpha")
        self.assertNotIn("seed", orch.reporter.suite_properties)

    def test_all_tests_still_run_under_random_order(self):
        # Reordering units must never drop or duplicate a test.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = self._write_suite(tmp)
            orch = Orchestrator(root, num_workers=2, default_timeout=30.0, order="random", seed=3)
            reporter = orch.run()
        ids = {r.test_id for r in reporter.results}
        self.assertEqual(len(ids), 3)
        self.assertEqual({r.outcome for r in reporter.results}, {"passed"})


class ImportTimeoutConfigTests(unittest.TestCase):
    def test_orchestrator_defaults_to_module_constant(self):
        from ctrlrunner.execution.orchestrator import IMPORT_PHASE_TIMEOUT

        orch = Orchestrator("tests", num_workers=1, default_timeout=30.0)
        self.assertEqual(orch.import_timeout, IMPORT_PHASE_TIMEOUT)

    def test_import_phase_kill_message_uses_configured_budget(self):
        orch = Orchestrator("tests", num_workers=1, default_timeout=30.0, import_timeout=123.0)
        orch.items_by_id = {}
        orch.groups_by_id = {}
        orch._report_timeout_kill("m::t", {"m::t": 30.0}, worker_id=1, importing=True)

        [result] = orch.reporter.results
        self.assertIn("123.0s", result.error)
        self.assertEqual(result.duration, 123.0)


class FlakyFlagTests(unittest.TestCase):
    def setUp(self):
        registry.reset()

    def _make_orchestrator(self):
        orch = Orchestrator("tests", num_workers=1, default_timeout=30.0)
        orch.items_by_id = {}
        orch.groups_by_id = {}
        return orch

    def _finished_msg(self, test_id, outcome, attempts):
        return (
            "finished",
            1,
            test_id,
            outcome,
            None,
            0.1,
            attempts,
            [],
            [],
            {},
            0.1,
            None,
            None,
            None,
            time.time(),
        )

    def test_passed_after_retry_is_flagged_flaky(self):
        orch = self._make_orchestrator()
        slot = mock.Mock(worker_id=1, remaining=["m::t"], units=[])
        orch._handle_message(slot, self._finished_msg("m::t", "passed", 2), {"m::t": 30.0})
        self.assertTrue(orch.reporter.results[0].flaky)

    def test_passed_on_first_attempt_is_not_flaky(self):
        orch = self._make_orchestrator()
        slot = mock.Mock(worker_id=1, remaining=["m::t"], units=[])
        orch._handle_message(slot, self._finished_msg("m::t", "passed", 1), {"m::t": 30.0})
        self.assertFalse(orch.reporter.results[0].flaky)

    def test_failed_after_retries_is_not_flaky(self):
        orch = self._make_orchestrator()
        slot = mock.Mock(worker_id=1, remaining=["m::t"], units=[])
        orch._handle_message(slot, self._finished_msg("m::t", "failed", 3), {"m::t": 30.0})
        self.assertFalse(orch.reporter.results[0].flaky)


if __name__ == "__main__":
    unittest.main()
