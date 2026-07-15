"""
Pass 1 of the migration: cheap ast-based scan over every file, building
the project-wide context the libcst transformer (pass 2) needs:

    - fixture index: which fixture names are defined where (so we know
      whether a `page` parameter is the user's own fixture or
      pytest-playwright's, and where to inject params=[...]);
    - indirect-parametrize collection: every
      @pytest.mark.parametrize("fx", values, indirect=True) is recorded
      against the fixture it targets, so pass 2 can move the values onto
      the fixture definition (possibly in another file, e.g. conftest.py)
      and drop the decorator from the test.
"""

import ast
import contextlib
from dataclasses import dataclass, field
from pathlib import Path

TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
CONFTEST = "conftest.py"


@dataclass
class FixtureInfo:
    name: str
    path: Path
    lineno: int
    has_request: bool
    has_params: bool  # already parametrized at definition site


@dataclass
class IndirectInjection:
    """One indirect parametrize found on a test, targeting one fixture."""

    fixture_name: str
    values_source: str  # source text of the argvalues expression
    test_path: Path
    test_lineno: int


@dataclass
class ProjectIndex:
    files: list[Path] = field(default_factory=list)
    fixtures: dict[str, list[FixtureInfo]] = field(default_factory=dict)
    injections: dict[str, list[IndirectInjection]] = field(default_factory=dict)

    def fixture_defined(self, name: str) -> bool:
        return name in self.fixtures

    def params_for(self, fixture_name: str) -> str | None:
        """Values source to inject into the fixture definition, or None
        if migration of this indirect parametrize is not safe:
        conflicting value sets, several fixture definitions with the
        same name, or the fixture is already parametrized."""
        injections = self.injections.get(fixture_name)
        if not injections:
            return None
        sources = {i.values_source for i in injections}
        if len(sources) != 1:
            return None
        defs = self.fixtures.get(fixture_name, [])
        if len(defs) != 1 or defs[0].has_params:
            return None
        return injections[0].values_source


def discover_files(paths) -> list[Path]:
    """Every test file, conftest.py, plus any explicitly named .py file."""
    found = []
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py":
            found.append(p)
        elif p.is_dir():
            for pattern in TEST_FILE_PATTERNS + (CONFTEST,):
                found.extend(sorted(p.rglob(pattern)))
    seen, unique = set(), []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def _decorator_dotted_name(node: ast.expr) -> str:
    """'pytest.mark.parametrize' for both plain and called decorators."""
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_fixture_decorator(dec: ast.expr) -> bool:
    return _decorator_dotted_name(dec) in ("pytest.fixture", "fixture")


def _scan_file(path: Path, source: str, index: ProjectIndex):
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = [a.arg for a in node.args.args + node.args.kwonlyargs]

        for dec in node.decorator_list:
            if _is_fixture_decorator(dec):
                has_params = False
                if isinstance(dec, ast.Call):
                    has_params = any(kw.arg == "params" for kw in dec.keywords)
                index.fixtures.setdefault(node.name, []).append(
                    FixtureInfo(
                        name=node.name,
                        path=path,
                        lineno=node.lineno,
                        has_request="request" in arg_names,
                        has_params=has_params,
                    )
                )
                continue

            if _decorator_dotted_name(dec) not in ("pytest.mark.parametrize", "mark.parametrize"):
                continue
            if not isinstance(dec, ast.Call) or len(dec.args) < 2:
                continue
            indirect = next((kw.value for kw in dec.keywords if kw.arg == "indirect"), None)
            if indirect is None:
                continue
            argnames_node = dec.args[0]
            if not (
                isinstance(argnames_node, ast.Constant) and isinstance(argnames_node.value, str)
            ):
                continue
            names = [n.strip() for n in argnames_node.value.split(",")]
            # Only the fully-automatable shape: a single argname with
            # indirect=True or indirect=["that_name"]. Anything else is
            # left for the transformer to TODO-annotate.
            full = isinstance(indirect, ast.Constant) and indirect.value is True
            listed = (
                isinstance(indirect, (ast.List, ast.Tuple))
                and [getattr(e, "value", None) for e in indirect.elts] == names
            )
            if len(names) == 1 and (full or listed):
                values_src = ast.get_source_segment(source, dec.args[1]) or ""
                if values_src:
                    index.injections.setdefault(names[0], []).append(
                        IndirectInjection(
                            fixture_name=names[0],
                            values_source=values_src,
                            test_path=path,
                            test_lineno=node.lineno,
                        )
                    )


def scan(paths) -> ProjectIndex:
    index = ProjectIndex(files=discover_files(paths))
    for path in index.files:
        with contextlib.suppress(SyntaxError):  # pass 2 reports the parse error per file
            _scan_file(path, path.read_text(encoding="utf-8"), index)
    return index
