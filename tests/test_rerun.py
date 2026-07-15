import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pyrunner.core.registry import TestItem
from pyrunner.execution.rerun import (
    RerunError,
    expand_serial_groups,
    load_failed_test_ids,
    match_changed_files_to_test_ids,
    match_rerun_ids,
    resolve_changed_files,
    resolve_repo_root,
)


def _item(id_, source_path=None):
    return TestItem(
        id=id_, func=lambda: None, params=[], source_path=Path(source_path) if source_path else None
    )


class LoadFailedTestIdsTests(unittest.TestCase):
    def test_missing_file_raises_rerun_error(self):
        with self.assertRaises(RerunError):
            load_failed_test_ids(Path("/nonexistent/results.json"))

    def test_malformed_json_raises_rerun_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text("not valid json{{{")
            with self.assertRaises(RerunError):
                load_failed_test_ids(path)

    def test_returns_only_failed_test_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(
                json.dumps(
                    {
                        "tests": [
                            {"id": "mod::a", "outcome": "passed"},
                            {"id": "mod::b", "outcome": "failed"},
                            {"id": "mod::c", "outcome": "skipped"},
                            {"id": "mod::d", "outcome": "failed"},
                        ]
                    }
                )
            )
            ids = load_failed_test_ids(path)
            self.assertEqual(ids, ["mod::b", "mod::d"])

    def test_failed_entry_missing_id_raises_rerun_error_not_keyerror(self):
        # The module's contract is "bad input -> RerunError, always" (see
        # the missing-file and malformed-json paths above); a failed test
        # entry without an "id" key is the same class of malformed report
        # and must not leak a raw KeyError to the CLI.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(
                json.dumps(
                    {
                        "tests": [
                            {"id": "mod::a", "outcome": "failed"},
                            {"outcome": "failed"},  # no "id"
                        ]
                    }
                )
            )
            with self.assertRaises(RerunError):
                load_failed_test_ids(path)

    def test_no_failed_tests_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(json.dumps({"tests": [{"id": "mod::a", "outcome": "passed"}]}))
            self.assertEqual(load_failed_test_ids(path), [])


class ResolveChangedFilesTests(unittest.TestCase):
    def _init_repo(self, tmp):
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=tmp, check=True)
        (Path(tmp) / "test_a.py").write_text("# original\n")
        subprocess.run(["git", "add", "."], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp, check=True)

    def test_returns_changed_files_since_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            (Path(tmp) / "test_a.py").write_text("# changed\n")
            changed = resolve_changed_files("HEAD", cwd=tmp)
            self.assertEqual(changed, ["test_a.py"])

    def test_no_changes_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            changed = resolve_changed_files("HEAD", cwd=tmp)
            self.assertEqual(changed, [])

    def test_invalid_ref_raises_rerun_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            with self.assertRaises(RerunError):
                resolve_changed_files("not-a-real-ref-xyz", cwd=tmp)

    def test_git_not_available_raises_rerun_error(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RerunError):
            resolve_changed_files("HEAD", cwd=tmp)  # not a git repo at all -> git itself errors

    def test_ref_starting_with_dash_raises_rerun_error(self):
        # M1 (OWASP A03): a ref beginning with '-' would be parsed by git
        # as an option (argument injection) -- must be rejected outright,
        # before any subprocess runs.
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            with self.assertRaises(RerunError):
                resolve_changed_files("--output=/tmp/x", cwd=tmp)

    def test_normal_ref_still_resolves_after_validation(self):
        # The validation guard must not break the ordinary happy path.
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            (Path(tmp) / "test_a.py").write_text("# changed\n")
            changed = resolve_changed_files("HEAD", cwd=tmp)
            self.assertEqual(changed, ["test_a.py"])

    def test_changed_path_with_spaces_matches_exactly(self):
        # `git diff --name-only` prints a space-containing path raw (no
        # quoting) -- the splitlines() parse must hand it back verbatim,
        # or a changed file silently drops out of --changed-since
        # selection.
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            spaced = Path(tmp) / "test dir with spaces"
            spaced.mkdir()
            (spaced / "test_b.py").write_text("# original\n")
            subprocess.run(["git", "add", "."], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "add spaced"], cwd=tmp, check=True)
            (spaced / "test_b.py").write_text("# changed\n")
            changed = resolve_changed_files("HEAD", cwd=tmp)
            self.assertEqual(changed, ["test dir with spaces/test_b.py"])

    def test_untracked_new_file_is_included(self):
        # A brand-new, not-yet-`git add`ed test file must not be
        # invisible to --changed-since -- the plan guarantees "never
        # under-select".
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            (Path(tmp) / "test_brand_new.py").write_text("# new, untracked\n")
            changed = resolve_changed_files("HEAD", cwd=tmp)
            self.assertIn("test_brand_new.py", changed)

    def test_git_ls_files_not_available_raises_rerun_error(self):
        # Asymmetry fix: ensure the second subprocess call (git ls-files)
        # also raises RerunError (not raw FileNotFoundError) when git is unavailable.
        # Use mock to make only the second call fail, isolating that code path.
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            original_run = subprocess.run
            call_count = [0]

            def mock_run(*args, **kwargs):
                call_count[0] += 1
                # Let the first call (git diff) succeed, but make the second call
                # (git ls-files) raise FileNotFoundError
                if call_count[0] == 1:
                    return original_run(*args, **kwargs)
                elif call_count[0] == 2:
                    raise FileNotFoundError("git not found")
                return original_run(*args, **kwargs)

            with (
                mock.patch("subprocess.run", side_effect=mock_run),
                self.assertRaises(RerunError),
            ):
                resolve_changed_files("HEAD", cwd=tmp)


class ResolveRepoRootTests(unittest.TestCase):
    def _init_repo(self, tmp):
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=tmp, check=True)
        (Path(tmp) / "test_a.py").write_text("# original\n")
        subprocess.run(["git", "add", "."], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp, check=True)

    def test_resolves_the_real_repo_root_from_a_subdirectory(self):
        # --changed-since must resolve paths against the actual
        # git repo root, not the process's cwd -- running pyrunner from
        # a subdirectory previously made every comparison miss.
        with tempfile.TemporaryDirectory() as tmp:
            self._init_repo(tmp)
            subdir = Path(tmp) / "tests"
            subdir.mkdir()

            root = resolve_repo_root(cwd=str(subdir))
            self.assertEqual(Path(root).resolve(), Path(tmp).resolve())

    def test_not_a_git_repo_raises_rerun_error(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RerunError):
            resolve_repo_root(cwd=tmp)


class MatchChangedFilesToTestIdsTests(unittest.TestCase):
    def test_matches_tests_whose_source_file_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_a.py").touch()
            (Path(tmp) / "test_b.py").touch()
            all_tests = [
                _item("mod::test_x", source_path=str(Path(tmp) / "test_a.py")),
                _item("mod::test_y", source_path=str(Path(tmp) / "test_b.py")),
            ]
            matched = match_changed_files_to_test_ids(["test_a.py"], all_tests, tmp)
            self.assertEqual(matched, ["mod::test_x"])

    def test_multiple_tests_in_same_changed_file_all_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_a.py").touch()
            all_tests = [
                _item("mod::test_x", source_path=str(Path(tmp) / "test_a.py")),
                _item("mod::test_y", source_path=str(Path(tmp) / "test_a.py")),
            ]
            matched = match_changed_files_to_test_ids(["test_a.py"], all_tests, tmp)
            self.assertEqual(set(matched), {"mod::test_x", "mod::test_y"})

    def test_no_source_path_never_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            all_tests = [_item("mod::test_x", source_path=None)]
            matched = match_changed_files_to_test_ids(["test_a.py"], all_tests, tmp)
            self.assertEqual(matched, [])

    def test_unrelated_changed_file_matches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_a.py").touch()
            all_tests = [_item("mod::test_x", source_path=str(Path(tmp) / "test_a.py"))]
            matched = match_changed_files_to_test_ids(["unrelated_file.py"], all_tests, tmp)
            self.assertEqual(matched, [])


class MatchRerunIdsTests(unittest.TestCase):
    def test_exact_match_passes_through(self):
        result = match_rerun_ids(["mod::a"], ["mod::a", "mod::b"])
        self.assertEqual(result, ["mod::a"])

    def test_missing_parametrized_id_falls_back_to_base_variants(self):
        current = ["mod::test_x[en-US]", "mod::test_x[uk-UA]", "mod::test_y"]
        # the stored id's exact bracket suffix no longer exists among
        # current tests (param set changed) -- must fall back to ALL
        # current variants of the base id, not silently drop it
        result = match_rerun_ids(["mod::test_x[fr-FR]"], current)
        self.assertEqual(set(result), {"mod::test_x[en-US]", "mod::test_x[uk-UA]"})

    def test_unparametrized_missing_id_matches_nothing(self):
        result = match_rerun_ids(["mod::gone"], ["mod::a", "mod::b"])
        self.assertEqual(result, [])

    def test_deduplicates_while_preserving_order(self):
        current = ["mod::a", "mod::b"]
        result = match_rerun_ids(["mod::a", "mod::a", "mod::b"], current)
        self.assertEqual(result, ["mod::a", "mod::b"])

    def test_mixed_exact_and_fallback_matches(self):
        current = ["mod::a", "mod::test_x[en-US]", "mod::test_x[uk-UA]"]
        result = match_rerun_ids(["mod::a", "mod::test_x[fr-FR]"], current)
        self.assertEqual(result, ["mod::a", "mod::test_x[en-US]", "mod::test_x[uk-UA]"])


class ExpandSerialGroupsTests(unittest.TestCase):
    """A serial class is an atomic unit -- a rerun selection
    that picks only its failed members would execute a partial group, so
    any touched serial group expands to its full membership."""

    def _serial_item(self, id_, group):
        item = _item(id_)
        item.serial_group = group
        return item

    def test_partial_serial_selection_pulls_whole_group_in_registry_order(self):
        items = [
            self._serial_item("m::C.a", "m::C"),
            self._serial_item("m::C.b", "m::C"),
            self._serial_item("m::C.c", "m::C"),
            _item("m::free"),
        ]
        expanded = expand_serial_groups(["m::C.b"], items)
        self.assertEqual(expanded, ["m::C.b", "m::C.a", "m::C.c"])

    def test_non_serial_ids_pass_through_unchanged(self):
        items = [_item("m::x"), _item("m::y")]
        self.assertEqual(expand_serial_groups(["m::y"], items), ["m::y"])

    def test_untouched_serial_groups_not_pulled_in(self):
        items = [
            self._serial_item("m::C.a", "m::C"),
            self._serial_item("m::D.a", "m::D"),
            self._serial_item("m::D.b", "m::D"),
        ]
        expanded = expand_serial_groups(["m::C.a"], items)
        self.assertEqual(expanded, ["m::C.a"])

    def test_no_duplicates_when_whole_group_already_selected(self):
        items = [
            self._serial_item("m::C.a", "m::C"),
            self._serial_item("m::C.b", "m::C"),
        ]
        expanded = expand_serial_groups(["m::C.a", "m::C.b"], items)
        self.assertEqual(expanded, ["m::C.a", "m::C.b"])

    def test_empty_selection_stays_empty(self):
        items = [self._serial_item("m::C.a", "m::C")]
        self.assertEqual(expand_serial_groups([], items), [])


if __name__ == "__main__":
    unittest.main()
