import tempfile
import unittest
from pathlib import Path

try:
    import libcst  # noqa: F401

    HAS_LIBCST = True
except ImportError:
    HAS_LIBCST = False

if HAS_LIBCST:
    from ctrlrunner.migrate import migrate_paths


def _write_tree(root: Path, files: dict):
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


@unittest.skipUnless(HAS_LIBCST, "libcst not installed")
class MigrateTestCase(unittest.TestCase):
    def migrate(self, files: dict, write: bool = False, **kwargs):
        """Returns (report, {relative_name: new_source})."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        _write_tree(root, files)
        report, changes = migrate_paths([str(root)], write=write, **kwargs)
        migrated = {str(path.relative_to(root)).replace("\\", "/"): new for path, _, new in changes}
        return report, migrated


class FixtureConversionTests(MigrateTestCase):
    def test_basic_fixture(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.fixture(scope="session", autouse=True)\n'
                    "def env():\n"
                    "    yield 1\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('@fixture(scope="session", autouse=True)', code)
        self.assertIn("from ctrlrunner import fixture", code)
        self.assertNotIn("import pytest", code)

    def test_function_scope_is_default_and_dropped(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    'import pytest\n\n@pytest.fixture(scope="function")\ndef env():\n    return 1\n'
                )
            }
        )
        self.assertIn("@fixture()", out["test_a.py"])

    def test_class_scope_downgraded_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    'import pytest\n\n@pytest.fixture(scope="class")\ndef env():\n    return 1\n'
                )
            }
        )
        self.assertIn('@fixture(scope="module")', out["test_a.py"])
        self.assertTrue(any("class" in msg for f in report.files for _, msg in f.todos))

    def test_fixture_params_forces_request_param(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.fixture(params=[1, 2])\n"
                    "def num(request):\n"
                    "    return request.param\n"
                )
            }
        )
        self.assertIn("@fixture(params=[1, 2])", out["test_a.py"])


class TestFunctionConversionTests(MigrateTestCase):
    def test_plain_test_gets_test_decorator(self):
        report, out = self.migrate({"test_a.py": ("def test_one():\n    assert True\n")})
        self.assertIn("@test()\ndef test_one():", out["test_a.py"])
        self.assertIn("from ctrlrunner import test", out["test_a.py"])
        self.assertEqual(report.totals()["tests"], 1)

    def test_timeout_flaky_and_custom_marker(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.mark.smoke\n"
                    "@pytest.mark.timeout(45)\n"
                    "@pytest.mark.flaky(reruns=3)\n"
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        self.assertIn("@test(timeout=45, retries=3, tags={'smoke'})", out["test_a.py"])

    def test_bare_flaky_marker_kept_with_todo_not_silently_dropped(self):
        # @pytest.mark.flaky (no args) doesn't match the recognized
        # `reruns=N` shape -- must not just vanish with no TODO/report
        # entry, unlike every other unrecognized marker case.
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n@pytest.mark.flaky\ndef test_one():\n    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@pytest.mark.flaky", code)
        self.assertIn("import pytest", code)
        self.assertTrue(any("flaky" in msg for f in report.files for _, msg in f.todos))

    def test_flaky_max_runs_kwarg_kept_with_todo_not_silently_dropped(self):
        # @pytest.mark.flaky(max_runs=3) is the actual `flaky` package's
        # API, not ctrlrunner's `reruns=` shape -- must be flagged, not
        # dropped.
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.mark.flaky(max_runs=3)\n"
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@pytest.mark.flaky(max_runs=3)", code)
        self.assertTrue(any("flaky" in msg for f in report.files for _, msg in f.todos))

    def test_timeout_with_unrecognized_kwarg_kept_with_todo_not_silently_dropped(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.timeout(method="thread")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('@pytest.mark.timeout(method="thread")', code)
        self.assertTrue(any("timeout" in msg for f in report.files for _, msg in f.todos))

    def test_parametrize_order_and_pytest_param(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [1, pytest.param(2, id="two")])\n'
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        # @test outermost, @parametrize directly above def -- required order.
        self.assertLess(code.index("@test("), code.index("@parametrize("))
        # pytest.param with kwargs is converted to ctrlrunner's param()
        # (id preserved), not stripped down to the bare value anymore.
        self.assertIn('parametrize("x", [1, param(2, id="two")])', code)
        self.assertIn("from ctrlrunner import param, parametrize, test", code)

    def test_skipif_and_xfail_inserted_after_docstring(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import sys\n"
                    "import pytest\n\n"
                    '@pytest.mark.skipif(sys.platform == "win32", reason="posix")\n'
                    '@pytest.mark.xfail(reason="bug", strict=True)\n'
                    "def test_one():\n"
                    '    """Doc."""\n'
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        doc = code.index('"""Doc."""')
        skip_call = code.index('skip(sys.platform == "win32", "posix")')
        fail_call = code.index('fail(description="bug", strict=True)')
        body = code.index("assert True")
        self.assertTrue(doc < skip_call < fail_call < body)

    def test_xfail_strict_defaults_to_false(self):
        # pytest xfail default is strict=False; ctrlrunner fail() defaults to
        # strict=True -- the migration must pin it explicitly.
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n@pytest.mark.xfail\ndef test_one():\n    assert False\n"
                )
            }
        )
        self.assertIn("fail(strict=False)", out["test_a.py"])

    def test_usefixtures_appended_to_signature(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.fixture\n"
                    "def db():\n"
                    "    return 1\n\n"
                    '@pytest.mark.usefixtures("db")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        self.assertIn("def test_one(db):", out["test_a.py"])


class TestClassConversionTests(MigrateTestCase):
    def test_plain_test_class(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.mark.smoke\n"
                    "@pytest.mark.timeout(30)\n"
                    "class TestLogin:\n"
                    "    def test_ok(self):\n"
                    "        assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@test_class(timeout=30, tags={'smoke'})", code)
        self.assertIn("@test()\n    def test_ok(self):", code)
        self.assertEqual(report.totals()["test_classes"], 1)

    def test_class_level_bare_flaky_marker_kept_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.mark.flaky\n"
                    "class TestLogin:\n"
                    "    def test_ok(self):\n"
                    "        assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@pytest.mark.flaky", code)
        self.assertTrue(any("flaky" in msg for f in report.files for _, msg in f.todos))

    def test_unittest_class_left_alone_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import unittest\n\n"
                    "class TestOld(unittest.TestCase):\n"
                    "    def test_ok(self):\n"
                    "        self.assertTrue(True)\n"
                )
            }
        )
        code = out.get("test_a.py", "")
        self.assertNotIn("@test_class", code)
        self.assertNotIn("@test()", code)
        self.assertTrue(any("base classes" in msg for f in report.files for _, msg in f.todos))


class RuntimeCallTests(MigrateTestCase):
    def test_skip_fail_xfail_calls(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one():\n"
                    '    pytest.skip("nope")\n\n'
                    "def test_two():\n"
                    '    pytest.fail("boom")\n\n'
                    "def test_three():\n"
                    '    pytest.xfail("later")\n'
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('skip(description="nope")', code)
        self.assertIn('raise AssertionError("boom")', code)
        self.assertIn('fail(description="later")', code)
        self.assertIn('raise AssertionError("later")', code)
        self.assertNotIn("import pytest", code)

    def test_pytest_raises_gets_todo_and_import_kept(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one():\n"
                    "    with pytest.raises(ValueError):\n"
                    '        int("x")\n'
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("TODO(ctrlrunner-migrate): pytest.raises", code)
        self.assertIn("import pytest", code)
        self.assertIn("with pytest.raises(ValueError):", code)  # untouched
        self.assertTrue(any("pytest.raises" in msg for f in report.files for _, msg in f.todos))

    def test_module_level_skip_allow_module_level_left_as_is_with_inline_todo(self):
        # ctrlrunner's skip() raises at IMPORT TIME, unlike pytest's
        # module-level skip semantics -- auto-converting this breaks
        # collection of the whole module. Must be left untouched with
        # an inline TODO comment at the exact call site.
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    'pytest.skip("unsupported on this platform", allow_module_level=True)\n\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('pytest.skip("unsupported on this platform", allow_module_level=True)', code)
        self.assertIn("TODO(ctrlrunner-migrate)", code)
        self.assertIn("allow_module_level", code.split("TODO(ctrlrunner-migrate):", 1)[1][:200])
        self.assertTrue(
            any("allow_module_level" in msg for f in report.files for _, msg in f.todos)
        )


class IndirectParametrizeTests(MigrateTestCase):
    FILES = {
        "conftest.py": (
            "import pytest\n\n@pytest.fixture\ndef user(request):\n    return request.param\n"
        ),
        "test_a.py": (
            "import pytest\n\n"
            '@pytest.mark.parametrize("user", [1, 2], indirect=True)\n'
            "def test_one(user):\n"
            "    assert user\n"
        ),
    }

    def test_values_move_to_fixture_definition(self):
        report, out = self.migrate(dict(self.FILES))
        self.assertIn("@fixture(params=[1, 2])", out["conftest.py"])
        self.assertNotIn("parametrize", out["test_a.py"])
        self.assertIn("@test()", out["test_a.py"])
        self.assertEqual(report.totals()["indirect"], 1)

    def test_conflicting_value_sets_fall_back_to_todo(self):
        files = dict(self.FILES)
        files["test_b.py"] = (
            "import pytest\n\n"
            '@pytest.mark.parametrize("user", [3], indirect=True)\n'
            "def test_two(user):\n"
            "    assert user\n"
        )
        report, out = self.migrate(files)
        self.assertNotIn("params=", out.get("conftest.py", "params= absent"))
        self.assertTrue(
            any("indirect parametrize" in msg for f in report.files for _, msg in f.todos)
        )

    def test_explicit_indirect_false_is_treated_as_not_indirect(self):
        # indirect=False is semantically identical to omitting indirect
        # entirely -- a normal, convertible parametrize case. Treating
        # it as truthy leaves a valid case unconverted
        # with a misleading "could not be auto-migrated" TODO.
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [1, 2], indirect=False)\n'
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@parametrize", code)
        self.assertIn("@test()", code)
        self.assertFalse(
            any("indirect parametrize" in msg for f in report.files for _, msg in f.todos)
        )


class PlaywrightAndImportTests(MigrateTestCase):
    def test_playwright_fixture_import_added(self):
        _, out = self.migrate({"test_a.py": ('def test_one(page):\n    page.goto("https://x")\n')})
        self.assertIn(
            "from ctrlrunner.playwright.playwright_fixtures import page", out["test_a.py"]
        )

    def test_own_page_fixture_wins_over_playwright_import(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.fixture\n"
                    "def page():\n"
                    "    return object()\n\n"
                    "def test_one(page):\n"
                    "    assert page\n"
                )
            }
        )
        self.assertNotIn("playwright_fixtures", out["test_a.py"])

    def test_unsupported_builtin_fixture_todo(self):
        report, _ = self.migrate(
            {"test_a.py": ("def test_one(tmp_path, monkeypatch):\n    assert True\n")}
        )
        msgs = [msg for f in report.files for _, msg in f.todos]
        self.assertTrue(any("tmp_path" in m for m in msgs))
        self.assertTrue(any("monkeypatch" in m for m in msgs))

    def test_star_import_does_not_abort_the_whole_migration(self):
        # migrate_paths catches ParserSyntaxError/RecursionError per file,
        # but "from pytest import *" used to trip a bare assert in
        # fix_imports -- an AssertionError that aborted the ENTIRE run,
        # other files included. It must be handled like any other
        # can't-rewrite case: keep the line, flag a TODO, move on.
        report, out = self.migrate(
            {
                "test_star.py": (
                    "from pytest import *\n\n"
                    "@fixture\n"
                    "def db():\n"
                    "    return 1\n\n"
                    "def test_one(db):\n"
                    "    assert db\n"
                ),
                "test_ok.py": (
                    "import pytest\n\n"
                    "@pytest.fixture\n"
                    "def env():\n"
                    "    return 1\n\n"
                    "def test_two(env):\n"
                    "    assert env\n"
                ),
            }
        )
        # the other file still migrated
        self.assertIn("from ctrlrunner import fixture", out["test_ok.py"])
        # the star-import file is flagged, not crashed on: its pytest
        # import survives and a human-facing note exists
        star_reports = [f for f in report.files if str(f.path).endswith("test_star.py")]
        self.assertEqual(len(star_reports), 1)
        star = star_reports[0]
        msgs = [msg for _, msg in star.todos]
        self.assertTrue(
            star.error or any("pytest" in m for m in msgs),
            f"star-import file neither errored nor flagged: todos={msgs}",
        )

    def test_from_pytest_import_names_replaced(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "from pytest import fixture, mark\n\n"
                    "@fixture\n"
                    "def db():\n"
                    "    return 1\n\n"
                    "@mark.smoke\n"
                    "def test_one(db):\n"
                    "    assert db\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertNotIn("from pytest import", code)
        self.assertIn("from ctrlrunner import fixture, test", code)
        self.assertIn("@test(tags={'smoke'})", code)


class DryRunWriteAndIdempotencyTests(MigrateTestCase):
    SOURCE = "import pytest\n\n@pytest.mark.timeout(5)\ndef test_one():\n    assert True\n"

    def test_dry_run_does_not_touch_files(self):
        self.migrate({"test_a.py": self.SOURCE}, write=False)
        on_disk = (Path(self.tmp.name) / "test_a.py").read_text(encoding="utf-8")
        self.assertEqual(on_disk, self.SOURCE)

    def test_write_applies_and_second_run_is_noop(self):
        report1, _ = self.migrate({"test_a.py": self.SOURCE}, write=True)
        self.assertEqual(len(report1.changed_files), 1)
        report2, changes2 = migrate_paths([self.tmp.name], write=False)
        self.assertEqual(changes2, [])
        self.assertEqual(len(report2.changed_files), 0)

    def test_second_run_with_remaining_pytest_is_still_noop(self):
        # Files that keep pytest.raises (TODO + kept import) must not
        # accumulate duplicate TODO comments on re-runs.
        source = (
            "import pytest\n\n"
            "def test_one():\n"
            "    with pytest.raises(ValueError):\n"
            '        int("x")\n'
        )
        self.migrate({"test_a.py": source}, write=True)
        _, changes2 = migrate_paths([self.tmp.name], write=False)
        self.assertEqual(changes2, [])


class HookAndAsyncTests(MigrateTestCase):
    def test_pytest_hook_reported(self):
        report, _ = self.migrate(
            {"conftest.py": ("def pytest_collection_modifyitems(items):\n    pass\n")}
        )
        self.assertTrue(any("pytest hook" in msg for f in report.files for _, msg in f.todos))

    def test_async_test_left_with_todo(self):
        report, out = self.migrate({"test_a.py": ("async def test_one():\n    assert True\n")})
        self.assertNotIn("@test()", out.get("test_a.py", ""))
        self.assertTrue(any("sync" in msg for f in report.files for _, msg in f.todos))

    def test_async_test_bailout_does_not_inflate_report_or_add_unused_import(self):
        # The async bail-out used to run AFTER parametrize's plan side
        # effects (report count + `from ctrlrunner import parametrize`)
        # already happened -- inflating report counts for a decorator
        # that never actually got applied, and leaving a dangling
        # unused import in a file where nothing was converted.
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [1, 2])\n'
                    "async def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out.get("test_a.py", "")
        self.assertNotIn("from ctrlrunner import parametrize", code)
        self.assertEqual(report.totals()["parametrize"], 0)


class RecordPropertyMigrationTests(MigrateTestCase):
    """pytest's record_property/record_testsuite_property fixtures now
    have direct ctrlrunner equivalents (runtime imports, not fixtures):
    the parameter disappears from the signature and the call becomes a
    plain imported function -- no TODO needed."""

    def test_record_property_param_becomes_import(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    'def test_one(record_property):\n    record_property("testrail", "C123")\n'
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("def test_one():", code)
        self.assertIn("from ctrlrunner import record_property, test", code)
        self.assertIn('record_property("testrail", "C123")', code)
        self.assertNotIn("TODO(ctrlrunner-migrate): builtin fixture 'record_property'", code)

    def test_record_testsuite_property_param_and_call_renamed(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "def test_one(record_testsuite_property):\n"
                    '    record_testsuite_property("environment", "staging")\n'
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("def test_one():", code)
        self.assertIn('record_suite_property("environment", "staging")', code)
        self.assertNotIn("record_testsuite_property", code)
        self.assertIn("record_suite_property", code)
        self.assertIn("from ctrlrunner import record_suite_property, test", code)

    def test_other_params_survive_removal_without_trailing_comma(self):
        _, out = self.migrate(
            {"test_a.py": ('def test_one(page, record_property):\n    record_property("k", "v")\n')}
        )
        self.assertIn("def test_one(page):", out["test_a.py"])

    def test_user_defined_fixture_with_same_name_left_alone(self):
        _, out = self.migrate(
            {
                "conftest.py": (
                    "import pytest\n\n"
                    "@pytest.fixture\n"
                    "def record_property():\n"
                    "    return lambda k, v: None\n"
                ),
                "test_a.py": ('def test_one(record_property):\n    record_property("k", "v")\n'),
            }
        )
        # the user's own fixture wins: param stays, no ctrlrunner import
        self.assertIn("def test_one(record_property):", out["test_a.py"])
        self.assertNotIn("from ctrlrunner import record_property", out["test_a.py"])


class CaseIdMarkerTests(MigrateTestCase):
    def test_basic_marker_becomes_case_id(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.test_case_id("7412675")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('@test(case_id="7412675")', code)
        self.assertNotIn("test_case_id", code.replace('case_id="7412675"', ""))
        self.assertNotIn("import pytest", code)
        self.assertEqual(report.totals()["case_id"], 1)

    def test_coexists_with_other_custom_markers(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "@pytest.mark.smoke\n"
                    '@pytest.mark.test_case_id("7412675")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('case_id="7412675"', code)
        self.assertIn("tags={'smoke'}", code)
        self.assertNotIn("'test_case_id'", code)

    def test_variable_argument_passes_through_verbatim(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    'TEST_ID = "7392947"\n\n'
                    "@pytest.mark.test_case_id(TEST_ID)\n"
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        self.assertIn("@test(case_id=TEST_ID)", out["test_a.py"])

    def test_bare_marker_is_kept_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n@pytest.mark.test_case_id\ndef test_one():\n    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("@pytest.mark.test_case_id", code)
        self.assertIn("@test()", code)  # no case_id= landed on @test
        self.assertTrue(any("test_case_id" in msg for f in report.files for _, msg in f.todos))

    def test_class_level_marker_kept_with_todo_not_a_tag(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.test_case_id("100")\n'
                    "class TestThing:\n"
                    "    def test_one(self):\n"
                    "        assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('@pytest.mark.test_case_id("100")', code)
        self.assertNotIn("'test_case_id'", code)  # must not degrade to a tag
        self.assertTrue(any("per-method" in msg for f in report.files for _, msg in f.todos))

    def test_custom_marker_name_option(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.testrail_id("42")\n'
                    '@pytest.mark.test_case_id("7412675")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            },
            case_id_marker="testrail_id",
        )
        code = out["test_a.py"]
        self.assertIn('case_id="42"', code)
        # the default name is now just a custom marker -> tag
        self.assertIn("tags={'test_case_id'}", code)

    def test_second_case_id_marker_kept_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.test_case_id("1")\n'
                    '@pytest.mark.test_case_id("2")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertEqual(code.count("case_id="), 1)
        self.assertIn("@pytest.mark.test_case_id", code)
        self.assertTrue(any("single case_id" in msg for f in report.files for _, msg in f.todos))

    def test_idempotent_second_run(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.test_case_id("7412675")\n'
                    "def test_one():\n"
                    "    assert True\n"
                )
            }
        )
        _, out2 = self.migrate({"test_a.py": out["test_a.py"]})
        self.assertEqual(out2, {})  # no further changes


class AddMarkerTests(MigrateTestCase):
    def test_literal_add_marker_becomes_record_property(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one(request):\n"
                    '    request.node.add_marker(pytest.mark.test_case_id("7392947"))\n'
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("record_property('test_case_id', \"7392947\")", code)
        self.assertIn("from ctrlrunner import", code)
        self.assertIn("record_property", code.split("\n")[0] + code)
        # request no longer used -> parameter dropped
        self.assertIn("def test_one():", code)
        self.assertNotIn("import pytest", code)
        self.assertTrue(
            any(
                "not selectable via --case-id" in msg.lower() or "--case-id" in msg
                for f in report.files
                for _, msg in f.todos
            )
        )

    def test_dynamic_argument_converted_verbatim(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one(request):\n"
                    "    test_id = compute()\n"
                    "    request.node.add_marker(pytest.mark.test_case_id(test_id))\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("record_property('test_case_id', test_id)", code)
        self.assertIn("def test_one():", code)

    def test_subscript_argument_converted_verbatim(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "IDS = {'a': '1'}\n\n"
                    "def test_one(request):\n"
                    "    request.node.add_marker(pytest.mark.test_case_id(IDS['a']))\n"
                    "    assert True\n"
                )
            }
        )
        self.assertIn("record_property('test_case_id', IDS['a'])", out["test_a.py"])

    def test_other_marker_via_add_marker_gets_todo_only(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one(request):\n"
                    "    request.node.add_marker(pytest.mark.slow)\n"
                    "    assert True\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("request.node.add_marker(pytest.mark.slow)", code)
        self.assertIn("def test_one(request):", code)  # request stays
        self.assertTrue(
            any(
                "add_marker has no ctrlrunner equivalent" in msg
                for f in report.files
                for _, msg in f.todos
            )
        )

    def test_mixed_request_usage_keeps_the_parameter(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one(request):\n"
                    '    request.node.add_marker(pytest.mark.test_case_id("1"))\n'
                    "    name = request.config.getoption('--env')\n"
                    "    assert name\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("record_property('test_case_id', \"1\")", code)
        self.assertIn("def test_one(request):", code)  # still used -> kept
        self.assertTrue(any("request.config" in msg for f in report.files for _, msg in f.todos))

    def test_add_marker_idempotent_second_run(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    "def test_one(request):\n"
                    '    request.node.add_marker(pytest.mark.test_case_id("7392947"))\n'
                    "    assert True\n"
                )
            }
        )
        _, out2 = self.migrate({"test_a.py": out["test_a.py"]})
        self.assertEqual(out2, {})


class PytestParamConversionTests(MigrateTestCase):
    def test_param_without_kwargs_still_stripped_to_tuple(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("a, b", [pytest.param(1, 2), (3, 4)])\n'
                    "def test_one(a, b):\n"
                    "    assert a and b\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('parametrize("a, b", [(1, 2), (3, 4)])', code)
        self.assertNotIn("param(", code.replace("parametrize(", ""))

    def test_param_with_case_id_mark_and_id(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x, y", [\n'
                    '    pytest.param(1, "Entity", marks=pytest.mark.test_case_id("7279719"),'
                    ' id="GEPM-Entity"),\n'
                    "])\n"
                    "def test_one(x, y):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn('param(1, "Entity", id="GEPM-Entity", case_id="7279719")', code)
        self.assertIn("from ctrlrunner import param", code)
        self.assertEqual(report.totals()["params"], 1)

    def test_param_with_marks_list_case_id_and_xfail(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [\n'
                    "    pytest.param(\n"
                    "        1,\n"
                    "        marks=[\n"
                    '            pytest.mark.test_case_id("7184475"),\n'
                    '            pytest.mark.xfail(strict=True, reason="[Bug 7438797] widget absent"),\n'
                    "        ],\n"
                    '        id="us_entity",\n'
                    "    ),\n"
                    "])\n"
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn(
            'param(1, id="us_entity", case_id="7184475", '
            'xfail="[Bug 7438797] widget absent", xfail_strict=True)',
            code,
        )

    def test_xfail_without_strict_gets_explicit_pytest_default(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [\n'
                    '    pytest.param(1, marks=pytest.mark.xfail(reason="bug")),\n'
                    "])\n"
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        # pytest's xfail default is strict=False; param()'s is True --
        # the migrator must always write it explicitly.
        self.assertIn('param(1, xfail="bug", xfail_strict=False)', out["test_a.py"])

    def test_skip_mark_and_plain_marker_tags(self):
        _, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [\n'
                    '    pytest.param(1, marks=[pytest.mark.skip(reason="nope"), pytest.mark.slow]),\n'
                    "])\n"
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        self.assertIn("param(1, tags={'slow'}, skip=\"nope\")", out["test_a.py"])

    def test_unconvertible_marks_leave_pytest_param_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n"
                    "import sys\n\n"
                    '@pytest.mark.parametrize("x", [\n'
                    '    pytest.param(1, marks=pytest.mark.skipif(sys.platform == "win32",'
                    ' reason="posix")),\n'
                    "])\n"
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("pytest.param(1, marks=pytest.mark.skipif", code)
        self.assertTrue(
            any("could not be fully converted" in msg for f in report.files for _, msg in f.todos)
        )

    def test_unknown_mark_with_args_becomes_tag_with_todo(self):
        report, out = self.migrate(
            {
                "test_a.py": (
                    "import pytest\n\n"
                    '@pytest.mark.parametrize("x", [\n'
                    '    pytest.param(1, marks=pytest.mark.dependency(name="a")),\n'
                    "])\n"
                    "def test_one(x):\n"
                    "    assert x\n"
                )
            }
        )
        code = out["test_a.py"]
        self.assertIn("param(1, tags={'dependency'})", code)
        self.assertTrue(any("arguments dropped" in msg for f in report.files for _, msg in f.todos))


PYPROJECT_EXAMPLE = """\
[project]
name = "legacy"

[tool.pytest.ini_options]
pythonpath = [".", "src/helper"]
testpaths = ["spec"]
addopts = "-v --tb=short --strict-markers -n 4 --dist=loadscope"
timeout = 300
filterwarnings = ["ignore::DeprecationWarning:openpyxl.packaging.core"]
markers = [
    "health_check: Minimal happy path tests",
    "smoke: Smoke tests",
    "test_case_id: Azure DevOps Test Plans test case ID",
    "team_1: Team 1 specific tests",
    "team_2: Team 2 specific tests",
    "team_3: Team 3 specific tests",
    "timeout: pytest-timeout marker",
]
"""


class ConfigMigrationTests(MigrateTestCase):
    def _migrate_tree(self, extra_files=None, write=False, **kwargs):
        files = {
            "pyproject.toml": PYPROJECT_EXAMPLE,
            "spec/test_a.py": "def test_one():\n    assert True\n",
        }
        files.update(extra_files or {})
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        _write_tree(root, files)
        report, changes = migrate_paths([str(root / "spec")], write=write, **kwargs)
        return root, report, changes

    def _config_text(self, changes, root) -> str:
        target = (root / "ctrlrunner.toml").resolve()
        for path, _, new in changes:
            if path.resolve() == target:
                return new
        raise AssertionError("no ctrlrunner.toml in changes")

    def test_full_mapping_from_pyproject(self):
        root, report, changes = self._migrate_tree()
        text = self._config_text(changes, root)
        self.assertIn('root = "spec"', text)
        self.assertIn("timeout = 300", text)
        self.assertIn("num_workers = 4", text)
        self.assertIn("strict_tags = true", text)
        self.assertIn('"smoke"', text)
        self.assertIn('"team_1"', text)
        # excluded: the case-id marker and converted-away markers
        self.assertNotIn("test_case_id", text)
        self.assertNotIn('"timeout"', text)
        # unmappable options become commented TODO lines
        self.assertIn("# TODO(ctrlrunner-migrate): addopts '--dist=loadscope'", text)
        self.assertIn("filterwarnings", text)
        self.assertIn("pythonpath", text)
        # >=3 team_* tags -> prefix-pattern tip
        self.assertIn("team_*", text)
        self.assertGreater(report.totals()["config"], 0)

    def test_generated_toml_parses_and_loads_without_warnings(self):
        import tomllib

        from ctrlrunner.config.config import load_config

        root, _, changes = self._migrate_tree()
        text = self._config_text(changes, root)
        parsed = tomllib.loads(text)
        self.assertIn("ctrlrunner", parsed)
        config_path = root / "generated_ctrlrunner.toml"
        config_path.write_text(text, encoding="utf-8")
        warnings: list[str] = []
        section = load_config(str(config_path), warn=warnings.append)
        self.assertEqual(warnings, [])
        self.assertEqual(section["root"], "spec")
        self.assertEqual(section["num_workers"], 4)
        self.assertTrue(section["strict_tags"])

    def test_dry_run_writes_nothing_and_write_creates_the_file(self):
        root, _, _ = self._migrate_tree(write=False)
        self.assertFalse((root / "ctrlrunner.toml").exists())

        root2, _, _ = self._migrate_tree(write=True)
        target = root2 / "ctrlrunner.toml"
        self.assertTrue(target.exists())
        self.assertIn('root = "spec"', target.read_text(encoding="utf-8"))
        # second run: existing ctrlrunner.toml is never overwritten
        report, changes = migrate_paths([str(root2 / "spec")], write=True)
        self.assertNotIn(target.resolve(), [p.resolve() for p, _, _ in changes])
        self.assertTrue(any("already exists" in msg for f in report.files for _, msg in f.todos))

    def test_existing_ctrlrunner_toml_is_untouched(self):
        marker = "# hand-written -- do not touch\n"
        root, report, changes = self._migrate_tree(
            extra_files={"ctrlrunner.toml": marker}, write=True
        )
        self.assertEqual((root / "ctrlrunner.toml").read_text(encoding="utf-8"), marker)
        self.assertNotIn((root / "ctrlrunner.toml").resolve(), [p.resolve() for p, _, _ in changes])
        self.assertTrue(any("already exists" in msg for f in report.files for _, msg in f.todos))

    def test_no_config_flag_disables_the_pass(self):
        root, report, changes = self._migrate_tree(migrate_config_files=False)
        self.assertNotIn((root / "ctrlrunner.toml").resolve(), [p.resolve() for p, _, _ in changes])
        self.assertEqual(report.totals()["config"], 0)

    def test_pyproject_found_in_parent_of_migrated_path(self):
        # _migrate_tree already migrates root/spec while pyproject.toml
        # sits at root -- assert the upward walk found it.
        root, _, changes = self._migrate_tree()
        self.assertIn((root / "ctrlrunner.toml").resolve(), [p.resolve() for p, _, _ in changes])

    def test_addopts_num_workers_auto_and_list_form(self):
        from ctrlrunner.migrate.config_migrator import build_ctrlrunner_toml

        text, _, _ = build_ctrlrunner_toml(
            {"addopts": ["-n", "auto", "--strict-markers"]}, "test_case_id"
        )
        self.assertIn('num_workers = "auto"', text)
        self.assertIn("strict_tags = true", text)

    def test_no_pyproject_means_no_config_entry(self):
        report, _ = self.migrate({"test_a.py": "def test_one():\n    assert True\n"})
        self.assertEqual(report.totals()["config"], 0)


if __name__ == "__main__":
    unittest.main()
