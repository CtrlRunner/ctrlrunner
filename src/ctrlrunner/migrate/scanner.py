"""
Pass 1 of the migration: cheap ast-based scan over every file, building
the project-wide context the libcst transformer (pass 2) needs:

    - fixture index: which fixture names are defined where (so we know
      whether a `page` parameter is the user's own fixture or
      pytest-playwright's);
    - indirect-parametrize collection: every fixture name targeted by a
      @pytest.mark.parametrize(..., indirect=...) anywhere in the
      project is recorded, so pass 2 can add a `request` parameter to
      that fixture's definition (possibly in another file, e.g.
      conftest.py) if it lacks one. The values themselves stay on the
      tests' decorators -- ctrlrunner's @parametrize supports indirect=
      natively, so pass 2 passes them through verbatim.
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
    test_path: Path
    test_lineno: int


@dataclass
class ProjectIndex:
    files: list[Path] = field(default_factory=list)
    fixtures: dict[str, list[FixtureInfo]] = field(default_factory=dict)
    injections: dict[str, list[IndirectInjection]] = field(default_factory=dict)

    def fixture_defined(self, name: str) -> bool:
        return name in self.fixtures


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


def _record_parametrize_indirect(dec: ast.expr, lineno: int, path: Path, index: ProjectIndex):
    """Shared by both function-decorator and class-decorator scanning --
    pytest's class-level @pytest.mark.parametrize(..., indirect=...)
    applies to every method the same way a method's own does, so it
    needs the exact same recording (keyed by fixture name, agnostic to
    whether the decorator sat on a class or a function).

    Records every fixture name targeted by indirect= -- True means all
    names, a list/tuple means that subset. Only the NAMES are needed
    (to add `request` to the fixture definitions); the values stay on
    the test's decorator, passed through verbatim by pass 2."""
    if _decorator_dotted_name(dec) not in ("pytest.mark.parametrize", "mark.parametrize"):
        return
    if not isinstance(dec, ast.Call) or len(dec.args) < 2:
        return
    indirect = next((kw.value for kw in dec.keywords if kw.arg == "indirect"), None)
    if indirect is None:
        return
    argnames_node = dec.args[0]
    if not (isinstance(argnames_node, ast.Constant) and isinstance(argnames_node.value, str)):
        return
    names = [n.strip() for n in argnames_node.value.split(",")]

    if isinstance(indirect, ast.Constant):
        targeted = names if indirect.value is True else []
    elif isinstance(indirect, (ast.List, ast.Tuple)):
        listed = {e.value for e in indirect.elts if isinstance(e, ast.Constant)}
        targeted = [n for n in names if n in listed]
    else:
        return  # dynamic indirect expression -- can't resolve names statically

    for nm in targeted:
        index.injections.setdefault(nm, []).append(
            IndirectInjection(fixture_name=nm, test_path=path, test_lineno=lineno)
        )


def _scan_file(path: Path, source: str, index: ProjectIndex):
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # A class-level indirect parametrize applies to every method
            # in the class the same way a method's own would -- pass 2's
            # transformer replays it per-method, so pass 1 must be able
            # to resolve it the same way.
            for dec in node.decorator_list:
                _record_parametrize_indirect(dec, node.lineno, path, index)
            continue

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

            _record_parametrize_indirect(dec, node.lineno, path, index)


def scan(paths) -> ProjectIndex:
    index = ProjectIndex(files=discover_files(paths))
    for path in index.files:
        with contextlib.suppress(SyntaxError):  # pass 2 reports the parse error per file
            _scan_file(path, path.read_text(encoding="utf-8"), index)
    return index
