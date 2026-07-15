"""
Standalone benchmark for ctrlrunner's test discovery/import speed --
NOT part of the unittest suite (timing assertions on shared/slow CI
machines are inherently flaky; this is a measurement tool, not a gate).

Run: uv run python scripts/benchmark_discovery.py

"Discovery" here has no separate collection phase distinct from
import: it's rglob("test_*.py") + rglob("conftest.py") followed by
import_module_by_path() for each file, which is what actually
executes @test/@parametrize decorators and populates the registry.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ctrlrunner.core import registry
from ctrlrunner.execution.orchestrator import discover_and_import


def _write_suite(root: Path, num_files: int, tests_per_file: int, parametrize_values: int) -> None:
    for i in range(num_files):
        lines = ["from ctrlrunner import test, parametrize", ""]
        for j in range(tests_per_file):
            if parametrize_values > 1:
                values = ", ".join(str(v) for v in range(parametrize_values))
                lines.append(f"@test()\n@parametrize('n', [{values}])\ndef test_{j}(n):\n    pass\n")
            else:
                lines.append(f"@test()\ndef test_{j}():\n    pass\n")
        (root / f"test_file_{i}.py").write_text("\n".join(lines))


def _run_one(label: str, num_files: int, tests_per_file: int, parametrize_values: int) -> None:
    registry.reset()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "tests"
        root.mkdir()
        _write_suite(root, num_files, tests_per_file, parametrize_values)

        start = time.perf_counter()
        discover_and_import(str(root))
        elapsed = time.perf_counter() - start

    total_items = len(registry.get_tests())
    rate = total_items / elapsed if elapsed > 0 else float("inf")
    print(
        f"{label:<28} files={num_files:<4} base_tests={num_files * tests_per_file:<6} "
        f"registered_items={total_items:<7} time={elapsed:.3f}s  items/sec={rate:.0f}"
    )
    registry.reset()


def main() -> None:
    print("ctrlrunner discovery/import benchmark")
    print("-" * 90)
    _run_one("small, no parametrize", num_files=10, tests_per_file=5, parametrize_values=1)
    _run_one("medium, no parametrize", num_files=50, tests_per_file=10, parametrize_values=1)
    _run_one("medium, parametrize x5", num_files=50, tests_per_file=10, parametrize_values=5)


if __name__ == "__main__":
    main()
