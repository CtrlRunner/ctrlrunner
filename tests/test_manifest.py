import json
import tempfile
import unittest
from pathlib import Path

from pyrunner.reporting.manifest import build_manifest, write_manifest


class BuildManifestTests(unittest.TestCase):
    def _kwargs(self, **overrides):
        base = dict(
            argv=["--reporter", "dots"],
            root="tests",
            num_workers=4,
            timeout=30.0,
            import_timeout=60.0,
            order="declared",
            seed=None,
            total_tests=10,
            failed_test_ids=["m::a", "m::b"],
        )
        base.update(overrides)
        return base

    def test_includes_versions_and_argv(self):
        manifest = build_manifest(**self._kwargs())
        self.assertIn("pyrunnerVersion", manifest)
        self.assertIn("pythonVersion", manifest)
        self.assertIn("platform", manifest)
        self.assertEqual(manifest["argv"], ["--reporter", "dots"])

    def test_includes_resolved_run_config(self):
        manifest = build_manifest(**self._kwargs())
        self.assertEqual(manifest["root"], "tests")
        self.assertEqual(manifest["numWorkers"], 4)
        self.assertEqual(manifest["timeout"], 30.0)
        self.assertEqual(manifest["importTimeout"], 60.0)
        self.assertEqual(manifest["order"], "declared")
        self.assertIsNone(manifest["seed"])

    def test_includes_totals_and_failed_ids(self):
        manifest = build_manifest(**self._kwargs())
        self.assertEqual(manifest["totalTests"], 10)
        self.assertEqual(manifest["failedTestIds"], ["m::a", "m::b"])

    def test_git_sha_is_none_outside_a_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_manifest(**self._kwargs(), cwd=tmp)
        self.assertIsNone(manifest["gitSha"])

    def test_git_sha_present_inside_a_repo(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=tmp, check=True)
            (Path(tmp) / "f.txt").write_text("x")
            subprocess.run(["git", "add", "."], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)
            manifest = build_manifest(**self._kwargs(), cwd=tmp)
        self.assertIsNotNone(manifest["gitSha"])
        self.assertEqual(len(manifest["gitSha"]), 40)


class WriteManifestTests(unittest.TestCase):
    def test_writes_valid_json_to_the_given_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "run-manifest.json")
            write_manifest(path, {"a": 1})
            data = json.loads(Path(path).read_text())
        self.assertEqual(data, {"a": 1})

    def test_write_is_atomic_and_never_leaves_a_partial_file(self):
        # Same contract as JsonReporter: a crash mid-write must never
        # leave a truncated file at the final path.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "run-manifest.json")
            write_manifest(path, {"a": 1})
            before = Path(path).read_text()
            write_manifest(path, {"a": 2})
            after = Path(path).read_text()
        self.assertNotEqual(before, after)
        self.assertEqual(json.loads(after), {"a": 2})


if __name__ == "__main__":
    unittest.main()
