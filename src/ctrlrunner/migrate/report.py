"""Migration report model + rendering (console and markdown)."""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileReport:
    path: Path
    changed: bool = False
    error: str = ""
    conversions: Counter = field(default_factory=Counter)
    # (approximate original line number or 0, message)
    todos: list[tuple[int, str]] = field(default_factory=list)

    def add(self, category: str, n: int = 1):
        self.conversions[category] += n

    def todo(self, line: int, message: str):
        self.todos.append((line, message))


CATEGORY_LABELS = {
    "tests": "test functions -> @test",
    "fixtures": "@pytest.fixture -> @fixture",
    "parametrize": "@pytest.mark.parametrize -> @parametrize",
    "markers": "markers converted (skip/skipif/xfail/timeout/flaky/usefixtures/tags)",
    "case_id": "test-case-id markers -> case_id / record_property",
    "params": "pytest.param(id=/marks=) -> param(...)",
    "runtime_calls": "pytest.skip()/fail()/xfail()/getoption() calls rewritten",
    "addoption": "pytest_addoption -> ctrlrunner_addoption",
    "test_classes": "test classes -> @test_class",
    "indirect": "indirect parametrize -> @parametrize(..., indirect=...)",
    "playwright": "pytest-playwright fixtures -> ctrlrunner.playwright.playwright_fixtures",
    "imports": "import lines added/removed",
    "config": "pyproject.toml options -> ctrlrunner.toml",
}


@dataclass
class MigrationReport:
    files: list[FileReport] = field(default_factory=list)

    @property
    def changed_files(self) -> list[FileReport]:
        return [f for f in self.files if f.changed]

    @property
    def total_todos(self) -> int:
        return sum(len(f.todos) for f in self.files)

    def totals(self) -> Counter:
        total = Counter()
        for f in self.files:
            total.update(f.conversions)
        return total

    def render_console(self, wrote: bool) -> str:
        lines = []
        totals = self.totals()
        lines.append("=" * 70)
        lines.append(
            "pytest -> ctrlrunner migration "
            + ("(APPLIED)" if wrote else "(dry-run, use --write to apply)")
        )
        lines.append("=" * 70)
        lines.append(f"files scanned : {len(self.files)}")
        lines.append(f"files changed : {len(self.changed_files)}")
        for key, label in CATEGORY_LABELS.items():
            if totals.get(key):
                lines.append(f"  {totals[key]:>4}  {label}")
        errors = [f for f in self.files if f.error]
        if errors:
            lines.append("")
            lines.append(f"ERRORS ({len(errors)}):")
            for f in errors:
                lines.append(f"  {f.path}: {f.error}")
        if self.total_todos:
            lines.append("")
            lines.append(
                f"MANUAL WORK REMAINING ({self.total_todos} item(s)) -- "
                f"marked with '# TODO(ctrlrunner-migrate)' in the code:"
            )
            for f in self.files:
                for line, msg in f.todos:
                    where = f"{f.path}:{line}" if line else str(f.path)
                    lines.append(f"  {where}: {msg}")
        else:
            lines.append("")
            lines.append("No manual work detected -- review the diff and run the suite.")
        return "\n".join(lines)

    def render_markdown(self, wrote: bool) -> str:
        totals = self.totals()
        lines = ["# pytest -> ctrlrunner migration report", ""]
        lines.append(f"Mode: {'applied (--write)' if wrote else 'dry-run'}")
        lines.append(f"Files scanned: {len(self.files)}; changed: {len(self.changed_files)}")
        lines.append("")
        lines.append("## Automatic conversions")
        lines.append("")
        lines.append("| count | conversion |")
        lines.append("|---|---|")
        for key, label in CATEGORY_LABELS.items():
            if totals.get(key):
                lines.append(f"| {totals[key]} | {label} |")
        lines.append("")
        if self.total_todos:
            lines.append(f"## Manual work remaining ({self.total_todos})")
            lines.append("")
            for f in self.files:
                for line, msg in f.todos:
                    where = f"`{f.path}:{line}`" if line else f"`{f.path}`"
                    lines.append(f"- {where} — {msg}")
        else:
            lines.append("## Manual work remaining")
            lines.append("")
            lines.append("None detected.")
        errors = [f for f in self.files if f.error]
        if errors:
            lines.append("")
            lines.append("## Errors")
            lines.append("")
            for f in errors:
                lines.append(f"- `{f.path}` — {f.error}")
        lines.append("")
        return "\n".join(lines)
