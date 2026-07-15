"""
Pass 2 of the migration: the libcst rewrite of one file.

What gets converted automatically:

    @pytest.fixture(...)                -> @fixture(...) (scope/autouse/params kept,
                                           scope="class"->"module", "package"->"session")
    def test_*(...)                     -> @test(...) added (outermost)
    @pytest.mark.parametrize(a, v)      -> @parametrize(a, v) (below @test;
                                           pytest.param(x, y) -> (x, y);
                                           pytest.param(x, id=..., marks=[...])
                                           -> param(x, id=..., case_id=...,
                                           xfail=..., skip=..., tags={...}))
    @pytest.mark.parametrize(..., indirect=True)
                                        -> params=[...] on the target fixture
                                           (cross-file, via the scanner index)
    @pytest.mark.skip/skipif            -> skip(...) call at the top of the body
    @pytest.mark.xfail                  -> fail(..., strict=...) call at the top
    @pytest.mark.timeout(N)             -> @test(timeout=N)
    @pytest.mark.flaky(reruns=N)        -> @test(retries=N)
    @pytest.mark.usefixtures("a")       -> 'a' appended to the function signature
    @pytest.mark.<case-id-marker>("X")  -> @test(case_id="X") (marker name is
                                           --case-id-marker, default test_case_id)
    request.node.add_marker(pytest.mark.<case-id-marker>(x))
                                        -> record_property("<case-id-marker>", x)
                                           (reported, but not --case-id selectable)
    @pytest.mark.<custom>               -> @test(tags={"<custom>"})
    class TestX: (no bases)             -> @test_class(...) + methods via @test
    pytest.skip(msg) call               -> skip(description=msg)
    pytest.fail(msg) call               -> raise AssertionError(msg)
    pytest.xfail(msg) call              -> fail(description=msg) + raise
    pytest-playwright page/context/browser
                                        -> from ctrlrunner.playwright.playwright_fixtures import ...

Everything else gets '# TODO(ctrlrunner-migrate): ...' at the exact spot
and an entry in the report: pytest.raises/approx/warns, monkeypatch/
tmp_path/capsys/... builtin fixtures, request.* beyond request.param,
unittest.TestCase classes, pytest_* hooks, async tests, fixture
ids=/name=, xfail(raises=...), string skipif conditions.
"""

from collections.abc import Sequence
from typing import cast

import libcst as cst
import libcst.matchers as m
from libcst.metadata import CodeRange, PositionProvider

from .report import FileReport
from .scanner import ProjectIndex

TODO_PREFIX = "# TODO(ctrlrunner-migrate): "

CTRLRUNNER_NAMES = (
    "test",
    "fixture",
    "parametrize",
    "param",
    "test_class",
    "skip",
    "fixme",
    "fail",
    "slow",
    "record_property",
)

# Default pytest marker whose string argument maps onto @test(case_id=...).
DEFAULT_CASE_ID_MARKER = "test_case_id"

# pytest builtin fixtures with no ctrlrunner equivalent.
UNSUPPORTED_FIXTURES = {
    "tmp_path",
    "tmpdir",
    "tmp_path_factory",
    "tmpdir_factory",
    "monkeypatch",
    "capsys",
    "capfd",
    "capsysbinary",
    "capfdbinary",
    "caplog",
    "recwarn",
    "pytestconfig",
    "cache",
    "doctest_namespace",
    "mocker",
}

# pytest metadata fixtures with direct ctrlrunner equivalents -- runtime
# imports, not fixtures: the parameter disappears from the signature and
# the call keeps working as a plain imported function (the testsuite
# variant is also RENAMED at its call sites, pytest name -> ctrlrunner
# name).
PROPERTY_FIXTURES = {
    "record_property": "record_property",
    "record_testsuite_property": "record_suite_property",
}

# pytest-playwright fixtures that map 1:1 onto ctrlrunner.playwright.playwright_fixtures.
PLAYWRIGHT_MAPPED = {"page", "context", "browser"}
# pytest-playwright fixtures that don't.
PLAYWRIGHT_UNMAPPED = {
    "playwright",
    "browser_name",
    "browser_channel",
    "browser_type",
    "browser_context_args",
    "browser_type_launch_args",
    "new_context",
    "is_chromium",
    "is_firefox",
    "is_webkit",
}

# pytest module attributes that always need manual attention when used.
MANUAL_PYTEST_ATTRS = {
    "raises": "pytest.raises has no ctrlrunner equivalent -- rewrite as "
    "try/except + assert (or plain 'with' helper of your own)",
    "warns": "pytest.warns has no ctrlrunner equivalent -- use warnings.catch_warnings",
    "approx": "pytest.approx has no ctrlrunner equivalent -- use math.isclose / abs(a-b) < eps",
    "importorskip": "pytest.importorskip -- use importlib + skip(...) manually",
    "deprecated_call": "pytest.deprecated_call -- use warnings.catch_warnings",
    "param": "pytest.param outside @parametrize values",
    "exit": "pytest.exit has no ctrlrunner equivalent",
    "main": "pytest.main -- run 'python -m ctrlrunner' instead",
    "fixture": "dynamic pytest.fixture usage",
    "mark": "dynamic pytest.mark usage",
}

_SCOPE_MAP = {"function": None, "module": "module", "session": "session"}


def _code(node: cst.CSTNode) -> str:
    return cst.Module(body=[]).code_for_node(node).strip()


def _todo_line(msg: str) -> cst.EmptyLine:
    return cst.EmptyLine(comment=cst.Comment(TODO_PREFIX + msg))


def _has_todo(leading_lines, msg: str) -> bool:
    """True if this exact TODO comment is already attached -- keeps
    re-running the migration idempotent."""
    return any(
        line.comment is not None and line.comment.value == TODO_PREFIX + msg
        for line in leading_lines
    )


def _str_arg(
    args: Sequence[cst.Arg], position: int | None, keyword: str
) -> cst.BaseExpression | None:
    """Value of a positional-or-keyword argument, or None."""
    positional = [a for a in args if a.keyword is None]
    for a in args:
        if a.keyword is not None and a.keyword.value == keyword:
            return a.value
    if position is not None and len(positional) > position:
        return positional[position].value
    return None


class _PytestParamConverter(cst.CSTTransformer):
    """pytest.param(...) inside argvalues:

    - no keywords          -> bare value / (a, b) tuple, as before
    - id=/marks=[...]      -> ctrlrunner param(a, b, id=..., case_id=...,
                              xfail=..., xfail_strict=..., skip=..., tags={...})
    - anything unconvertible (skipif/raises/conditions/non-mark exprs)
      -> the pytest.param call is left untouched + a TODO.
    """

    def __init__(self, canonical, case_id_marker: str):
        self.canonical = canonical
        self.case_id_marker = case_id_marker
        self.changed = False
        self.used_param = False
        self.converted_params = 0
        self.todos: list[str] = []

    def leave_Call(self, original_node, updated_node):
        name = _dotted(updated_node.func)
        if name is None or self.canonical(name) != "pytest.param":
            return updated_node
        positional = [a for a in updated_node.args if a.keyword is None]
        keywords = [a for a in updated_node.args if a.keyword is not None]
        if not keywords:
            self.changed = True
            if len(positional) == 1:
                return positional[0].value
            return cst.Tuple(elements=[cst.Element(value=a.value) for a in positional])

        kwargs: dict[str, str] = {}
        tags: set[str] = set()
        for arg in keywords:
            assert arg.keyword is not None
            key = arg.keyword.value
            if key == "id":
                kwargs["id"] = _code(arg.value)
            elif key == "marks":
                if not self._convert_marks(arg.value, kwargs, tags):
                    self.todos.append(
                        f"pytest.param marks= could not be fully converted "
                        f"({_code(original_node)}) -- left as pytest.param; "
                        f"convert to param(...) manually"
                    )
                    return updated_node
            else:
                self.todos.append(
                    f"pytest.param keyword '{key}=' has no param() equivalent "
                    f"({_code(original_node)}) -- left as pytest.param"
                )
                return updated_node

        if tags:
            kwargs["tags"] = "{{{}}}".format(", ".join(repr(t) for t in sorted(tags)))
        parts = [_code(a.value) for a in positional]
        for key in ("id", "case_id", "tags", "xfail", "xfail_strict", "skip"):
            if key in kwargs:
                parts.append(f"{key}={kwargs[key]}")
        self.changed = True
        self.used_param = True
        self.converted_params += 1
        return cst.parse_expression(f"param({', '.join(parts)})")

    def _convert_marks(self, value: cst.BaseExpression, kwargs: dict, tags: set) -> bool:
        """Fills kwargs/tags from a marks= expression; False -> bail out
        and leave the whole pytest.param untouched."""
        if isinstance(value, (cst.List, cst.Tuple)):
            elements = [el.value for el in value.elements]
        else:
            elements = [value]

        for expr in elements:
            call_args: list[cst.Arg] = []
            if isinstance(expr, cst.Call):
                mark_name = _dotted(expr.func)
                call_args = list(expr.args)
            else:
                mark_name = _dotted(expr)
            canonical = self.canonical(mark_name) if mark_name else None
            if canonical is None or not canonical.startswith("pytest.mark."):
                return False  # non-mark expression (variable, helper call, ...)
            marker = canonical[len("pytest.mark.") :]

            if self.case_id_marker and marker == self.case_id_marker:
                if "case_id" in kwargs or len(call_args) != 1 or call_args[0].keyword:
                    return False
                kwargs["case_id"] = _code(call_args[0].value)
            elif marker == "xfail":
                if "xfail" in kwargs:
                    return False
                reason = None
                strict = None
                for a in call_args:
                    key = a.keyword.value if a.keyword else None
                    if key == "reason" or (key is None and m.matches(a.value, m.SimpleString())):
                        reason = _code(a.value)
                    elif key == "strict":
                        strict = _code(a.value)
                    else:
                        # condition expression / raises= / anything else:
                        # param(xfail=...) is unconditional and untyped.
                        return False
                kwargs["xfail"] = reason if reason is not None else "True"
                # pytest's xfail default is strict=False; param()'s is
                # strict=True -- always written explicitly so migrated
                # behavior matches pytest either way.
                kwargs["xfail_strict"] = strict if strict is not None else "False"
            elif marker == "skip":
                if "skip" in kwargs:
                    return False
                reason = _str_arg(call_args, 0, "reason")
                kwargs["skip"] = _code(reason) if reason is not None else "True"
            elif marker in ("skipif", "usefixtures", "parametrize"):
                return False
            else:
                tags.add(marker)
                if call_args:
                    self.todos.append(
                        f"marks=pytest.mark.{marker}(...) arguments dropped "
                        f"(kept as tag '{marker}') -- re-check"
                    )
        return True


def _asname_str(alias: "cst.ImportAlias") -> str | None:
    """String value of an import alias's `as` target, if present --
    always a plain Name for the import lists this module deals with."""
    if alias.asname is None:
        return None
    target = alias.asname.name
    assert isinstance(target, cst.Name)
    return target.value


def _dotted(node: cst.BaseExpression) -> str | None:
    parts = []
    while isinstance(node, cst.Attribute):
        parts.append(node.attr.value)
        node = node.value
    if isinstance(node, cst.Name):
        parts.append(node.value)
        return ".".join(reversed(parts))
    return None


class _FnPlan:
    """Everything decided about one function before rebuilding it."""

    def __init__(self):
        self.is_test = False
        self.is_fixture = False
        self.is_async = False
        self.test_args: list[str] = []  # e.g. ['timeout=30', 'tags={"smoke"}']
        self.tags: set[str] = set()
        self.parametrize_srcs: list[str] = []  # 'parametrize("a", [1, 2])'
        self.body_inserts: list[str] = []  # 'skip(cond, "reason")'
        self.extra_params: list[str] = []  # usefixtures names
        self.remove_params: set[str] = set()  # params replaced by ctrlrunner imports
        self.kept_decorators: list[cst.Decorator] = []
        self.fixture_args: list[str] = []
        self.needs_request_param = False
        self.todos: list[str] = []
        self.marker_conversions = 0


class MigrationTransformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        index: ProjectIndex,
        report: FileReport,
        is_test_file: bool,
        is_conftest: bool,
        case_id_marker: str = DEFAULT_CASE_ID_MARKER,
    ):
        self.index = index
        self.report = report
        self.is_test_file = is_test_file
        self.is_conftest = is_conftest
        self.case_id_marker = case_id_marker
        self.aliases: dict[str, str] = {}  # local name -> canonical prefix
        self.needed_imports: set[str] = set()  # names from ctrlrunner
        self.playwright_imports: set[str] = set()
        self._class_stack: list[dict] = []
        self._converted_any = False

    # ---------- helpers -------------------------------------------------

    def _line(self, node) -> int:
        try:
            position = cast(CodeRange, self.metadata[PositionProvider][node])
            return position.start.line
        except KeyError:
            return 0

    def canonical(self, dotted: str) -> str:
        head, sep, rest = dotted.partition(".")
        head = self.aliases.get(head, head)
        return head + sep + rest if rest else head

    def _todo(self, node, msg: str):
        self.report.todo(self._line(node), msg)

    def _decorator_canonical(self, dec: cst.Decorator) -> str | None:
        expr = dec.decorator
        if isinstance(expr, cst.Call):
            expr = expr.func
        name = _dotted(expr)
        return self.canonical(name) if name else None

    def _decorator_args(self, dec: cst.Decorator) -> list[cst.Arg]:
        return list(dec.decorator.args) if isinstance(dec.decorator, cst.Call) else []

    # ---------- imports --------------------------------------------------

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name = _dotted(alias.name) or ""
            local = _asname_str(alias) or name.split(".")[0]
            if name.split(".")[0] in ("pytest", "ctrlrunner"):
                self.aliases[local] = name

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or isinstance(node.names, cst.ImportStar):
            return
        module = _dotted(node.module) or ""
        if module.split(".")[0] not in ("pytest", "ctrlrunner"):
            return
        for alias in node.names:
            assert isinstance(alias.name, cst.Name)
            imported = alias.name.value
            local = _asname_str(alias) or imported
            self.aliases[local] = f"{module}.{imported}"

    # ---------- classes --------------------------------------------------

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        info = {
            "name": node.name.value,
            "convertible": False,
            "converted_methods": 0,
            "is_test_class": False,
        }
        if node.name.value.startswith("Test") or self._has_pytest_marks(node.decorators):
            info["is_test_class"] = True
            bases = [b for b in node.bases if not m.matches(b.value, m.Name("object"))]
            info["convertible"] = not bases
        self._class_stack.append(info)

    def _has_pytest_marks(self, decorators) -> bool:
        return any(
            (self._decorator_canonical(d) or "").startswith("pytest.mark.") for d in decorators
        )

    def leave_ClassDef(self, original_node, updated_node):
        info = self._class_stack.pop()
        if not info["is_test_class"]:
            return updated_node
        if not info["convertible"]:
            if info["converted_methods"] or self._looks_like_test_class(original_node):
                msg = f"class {info['name']}: convert manually (has base classes)"
                self._todo(
                    original_node,
                    f"class {info['name']} has base classes "
                    f"(unittest.TestCase?) -- @test_class supports plain "
                    f"classes only; convert manually",
                )
                if _has_todo(updated_node.leading_lines, msg):
                    return updated_node
                return updated_node.with_changes(
                    leading_lines=[*updated_node.leading_lines, _todo_line(msg)]
                )
            return updated_node
        if not info["converted_methods"]:
            return updated_node

        # Class-level marks -> @test_class arguments.
        cls_args, kept, todos = [], [], []
        tags: set[str] = set()
        for dec in updated_node.decorators:
            canonical = self._decorator_canonical(dec) or ""
            if not canonical.startswith("pytest.mark."):
                kept.append(dec)
                continue
            marker = canonical[len("pytest.mark.") :]
            args = self._decorator_args(dec)
            if marker == "timeout":
                value = _str_arg(args, 0, "timeout")
                if value is not None:
                    cls_args.append(f"timeout={_code(value)}")
                    self.report.add("markers")
                else:
                    # Unrecognized arg shape -- don't silently drop it,
                    # keep the decorator and flag it, exactly
                    # like the function-level case.
                    kept.append(dec)
                    todos.append(
                        f"unrecognized @pytest.mark.timeout form ({_code(dec.decorator)}) "
                        f"on class {info['name']} -- left as-is; convert manually to "
                        f"@test_class(timeout=...)"
                    )
            elif marker == "flaky":
                value = _str_arg(args, 0, "reruns")
                if value is not None:
                    cls_args.append(f"retries={_code(value)}")
                    self.report.add("markers")
                else:
                    kept.append(dec)
                    todos.append(
                        f"unrecognized @pytest.mark.flaky form ({_code(dec.decorator)}) "
                        f"on class {info['name']} -- left as-is; convert manually to "
                        f"@test_class(retries=...)"
                    )
            elif marker in ("skip", "skipif", "xfail", "usefixtures", "parametrize"):
                todos.append(
                    f"class-level @pytest.mark.{marker} on "
                    f"{info['name']} -- apply per-method manually"
                )
                kept.append(dec)
            elif self.case_id_marker and marker == self.case_id_marker:
                # @test_class has no case_id kwarg (one case id can't
                # describe several methods) -- must not degrade to a tag.
                todos.append(
                    f"class-level @pytest.mark.{marker} on {info['name']} -- "
                    f"@test_class has no case_id; apply case_id=... per-method manually"
                )
                kept.append(dec)
            else:
                tags.add(marker)
                self.report.add("markers")
        if tags:
            cls_args.append("tags={{{}}}".format(", ".join(repr(t) for t in sorted(tags))))

        for msg in todos:
            self._todo(original_node, msg)
        self.needed_imports.add("test_class")
        self.report.add("test_classes")
        tc = cst.Decorator(decorator=cst.parse_expression(f"test_class({', '.join(cls_args)})"))
        leading = list(updated_node.leading_lines)
        leading += [_todo_line(t) for t in todos]
        return updated_node.with_changes(decorators=[tc, *kept], leading_lines=leading)

    def _looks_like_test_class(self, node: cst.ClassDef) -> bool:
        return any(
            m.matches(
                el, m.FunctionDef(name=m.Name(value=m.MatchIfTrue(lambda v: v.startswith("test"))))
            )
            for el in node.body.body
        )

    # ---------- functions --------------------------------------------------

    def leave_FunctionDef(self, original_node, updated_node):
        name = updated_node.name.value

        if name.startswith("pytest_"):
            msg = f"pytest hook '{name}' -- no ctrlrunner equivalent"
            self._todo(
                original_node,
                f"pytest hook '{name}' has no ctrlrunner equivalent "
                f"(ctrlrunner is deliberately hook-free; see docs)",
            )
            if _has_todo(updated_node.leading_lines, msg):
                return updated_node
            return updated_node.with_changes(
                leading_lines=[*updated_node.leading_lines, _todo_line(msg)]
            )

        plan = self._plan_function(original_node, updated_node)
        if plan is None:
            return updated_node

        if plan.is_async:
            msg = "async test -- ctrlrunner is sync-only"
            self._todo(
                original_node,
                f"async def {name} -- ctrlrunner runs sync tests only; "
                f"wrap the async body with asyncio.run() manually",
            )
            if _has_todo(updated_node.leading_lines, msg):
                return updated_node
            return updated_node.with_changes(
                leading_lines=[*updated_node.leading_lines, _todo_line(msg)]
            )

        return self._rebuild_function(original_node, updated_node, plan)

    def _plan_function(self, original_node, updated_node) -> _FnPlan | None:
        """Classify and collect every decision; None -> leave untouched."""
        name = updated_node.name.value
        plan = _FnPlan()
        pytest_marked = False

        for dec in updated_node.decorators:
            canonical = self._decorator_canonical(dec) or ""
            if canonical in (
                "ctrlrunner.test",
                "ctrlrunner.fixture",
                "ctrlrunner.registry.test",
                "ctrlrunner.registry.fixture",
                "ctrlrunner.core.registry.test",
                "ctrlrunner.core.registry.fixture",
            ):
                return None  # already migrated
            if canonical == "pytest.fixture":
                plan.is_fixture = True
            elif canonical.startswith("pytest.mark."):
                pytest_marked = True

        in_class = bool(self._class_stack) and self._class_stack[-1]["is_test_class"]
        if in_class and not self._class_stack[-1]["convertible"]:
            return None
        is_test_name = name.startswith("test")
        plan.is_test = (
            not plan.is_fixture
            and is_test_name
            and not self.is_conftest
            and (self.is_test_file or pytest_marked or in_class)
        )
        if not plan.is_test and not plan.is_fixture:
            return None

        # Checked BEFORE any decorator/signature side effects below
        # (report counts, needed_imports, plan.parametrize_srcs, ...) --
        # otherwise an async test with e.g. @pytest.mark.parametrize
        # would have that marker "converted" (report count bumped,
        # `from ctrlrunner import parametrize` inserted) even though the
        # function is left as pytest and the conversion never actually
        # lands in the rebuilt output.
        if updated_node.asynchronous is not None:
            plan.is_async = True
            return plan

        for dec in updated_node.decorators:
            self._plan_decorator(dec, plan, original_node)

        self._plan_signature(original_node, updated_node, plan)
        # Deliberately scans updated_node: statement-level rewrites (e.g.
        # request.node.add_marker -> record_property) have already run by
        # the time leave_FunctionDef fires, so converted uses no longer
        # count as remaining request.* usage.
        self._plan_request_usage(updated_node, plan)
        return plan

    # ----- decorators ----------

    def _plan_decorator(self, dec: cst.Decorator, plan: _FnPlan, fn_node):
        canonical = self._decorator_canonical(dec) or ""
        args = self._decorator_args(dec)

        if canonical == "pytest.fixture":
            self._plan_fixture_decorator(args, plan, fn_node)
            return
        if not canonical.startswith("pytest.mark."):
            plan.kept_decorators.append(dec)
            return

        marker = canonical[len("pytest.mark.") :]
        if self.case_id_marker and marker == self.case_id_marker:
            self._plan_case_id_marker(args, plan, dec)
            return
        handler = getattr(self, f"_mark_{marker}", None)
        if handler is not None:
            handler(args, plan, fn_node, dec)
        else:
            plan.tags.add(marker)
            plan.marker_conversions += 1
            if args:
                plan.todos.append(
                    f"marker '{marker}' had arguments ({_code(dec.decorator)}) -- "
                    f"dropped; consider properties={{...}} on @test"
                )

    def _plan_case_id_marker(self, args, plan: _FnPlan, dec: cst.Decorator):
        """@pytest.mark.<case-id-marker>("7412675") -> @test(case_id="7412675").
        The argument may be any expression (variable, dict lookup) -- it is
        carried over verbatim, since @test(case_id=<expr>) is valid too."""
        positional = [a for a in args if a.keyword is None]
        if len(positional) != 1 or len(args) != 1:
            plan.kept_decorators.append(dec)
            plan.todos.append(
                f"unrecognized @pytest.mark.{self.case_id_marker} form "
                f"({_code(dec.decorator)}) -- left as-is; add case_id=... to @test manually"
            )
            return
        if any(a.startswith("case_id=") for a in plan.test_args):
            plan.kept_decorators.append(dec)
            plan.todos.append(
                f"multiple @pytest.mark.{self.case_id_marker} markers on one test -- "
                f"@test takes a single case_id; second marker left as-is"
            )
            return
        plan.test_args.append(f"case_id={_code(positional[0].value)}")
        self.report.add("case_id")

    def _plan_fixture_decorator(self, args, plan: _FnPlan, fn_node):
        for arg in args:
            key = arg.keyword.value if arg.keyword else None
            src = _code(arg.value)
            if key == "scope" or (key is None and not plan.fixture_args):
                scope = src.strip("\"'")
                if scope in _SCOPE_MAP:
                    if _SCOPE_MAP[scope]:
                        plan.fixture_args.append(f'scope="{_SCOPE_MAP[scope]}"')
                elif scope == "class":
                    plan.fixture_args.append('scope="module"')
                    plan.todos.append(
                        'fixture scope="class" -> "module" (no class scope in ctrlrunner) -- verify'
                    )
                elif scope == "package":
                    plan.fixture_args.append('scope="session"')
                    plan.todos.append('fixture scope="package" -> "session" -- verify')
                else:
                    plan.fixture_args.append(f"scope={src}")
            elif key == "autouse":
                plan.fixture_args.append(f"autouse={src}")
            elif key == "params":
                plan.fixture_args.append(f"params={src}")
                plan.needs_request_param = True
            elif key == "ids":
                plan.todos.append(
                    "fixture ids=... not supported -- ctrlrunner "
                    "derives the id suffix from the value itself"
                )
            elif key == "name":
                plan.todos.append(
                    f"fixture name={src} alias not supported -- "
                    f"ctrlrunner registers by function name; rename "
                    f"the function or update references"
                )
            else:
                plan.todos.append(
                    f"fixture argument '{key}={src}' has no ctrlrunner equivalent -- dropped"
                )

        # Cross-file indirect parametrize -> params=[...] injection.
        fixture_name = fn_node.name.value
        injected = self.index.params_for(fixture_name)
        if injected and not any(a.startswith("params=") for a in plan.fixture_args):
            plan.fixture_args.append(f"params={injected}")
            plan.needs_request_param = True
            self.report.add("indirect")

    def _mark_parametrize(self, args, plan, fn_node, dec):
        if len(args) < 2:
            plan.kept_decorators.append(dec)
            plan.todos.append("unrecognized @parametrize form -- left as is")
            return
        argnames = _str_arg(args, 0, "argnames")
        argvalues = _str_arg(args, 1, "argvalues")
        if argnames is None or argvalues is None:
            plan.kept_decorators.append(dec)
            plan.todos.append("unrecognized @parametrize form -- left as is")
            return
        indirect = _str_arg(args, None, "indirect")
        ids = _str_arg(args, None, "ids")
        # indirect=False is semantically identical to omitting indirect
        # entirely -- only an explicit indirect=True (or a bare truthy
        # value) means the "indirect" case; treating indirect=False as
        # truthy left an otherwise-convertible parametrize case
        # unconverted with a misleading "could not be auto-migrated"
        # TODO.
        is_indirect = indirect is not None and _code(indirect).strip() != "False"

        if is_indirect:
            handled = self._plan_indirect(argnames, argvalues, plan, fn_node)
            if not handled:
                plan.kept_decorators.append(dec)
                plan.todos.append(
                    "indirect parametrize could not be auto-migrated (multi-arg "
                    "indirect, conflicting value sets across tests, fixture not "
                    "found, or fixture already parametrized) -- move the values "
                    "to @fixture(params=[...]) manually"
                )
            return
        if ids is not None:
            plan.todos.append(
                "parametrize ids=... dropped -- ctrlrunner derives the test id suffix from the values"
            )

        converter = _PytestParamConverter(self.canonical, self.case_id_marker)
        new_values = argvalues.visit(converter)
        # leave_Call() above only ever returns a BaseExpression (the
        # original call, a converted param() call, a stripped-down Tuple,
        # or a bare positional value) -- never a removal/flatten sentinel.
        assert isinstance(new_values, cst.BaseExpression)
        plan.todos.extend(converter.todos)
        if converter.used_param:
            self.needed_imports.add("param")
            self.report.add("params", converter.converted_params)
        plan.parametrize_srcs.append(f"parametrize({_code(argnames)}, {_code(new_values)})")
        plan.marker_conversions += 1
        self.report.add("parametrize")
        self.needed_imports.add("parametrize")

    def _plan_indirect(self, argnames, argvalues, plan, fn_node) -> bool:
        if not m.matches(argnames, m.SimpleString()):
            return False
        evaluated = cst.ensure_type(argnames, cst.SimpleString).evaluated_value
        if not isinstance(evaluated, str):  # bytes literal -- not a valid argnames string
            return False
        names = [n.strip() for n in evaluated.split(",")]
        if len(names) != 1:
            return False
        injected = self.index.params_for(names[0])
        if injected is None or injected != _code(argvalues).strip():
            return False
        # Values land on the fixture definition (possibly another file);
        # here the decorator is simply dropped.
        plan.marker_conversions += 1
        return True

    def _mark_skip(self, args, plan, fn_node, dec):
        reason = _str_arg(args, 0, "reason")
        plan.body_inserts.append(
            f"skip(description={_code(reason)})" if reason is not None else "skip()"
        )
        plan.marker_conversions += 1
        self.needed_imports.add("skip")

    def _mark_skipif(self, args, plan, fn_node, dec):
        condition = _str_arg(args, 0, "condition")
        reason = _str_arg(args, None, "reason")
        if condition is None or m.matches(condition, m.SimpleString()):
            plan.kept_decorators.append(dec)
            plan.todos.append(
                "skipif with a string condition (old pytest "
                "style) -- rewrite as a boolean expression"
            )
            return
        call = f"skip({_code(condition)}"
        if reason is not None:
            call += f", {_code(reason)}"
        plan.body_inserts.append(call + ")")
        plan.marker_conversions += 1
        self.needed_imports.add("skip")

    def _mark_xfail(self, args, plan, fn_node, dec):
        positional = [a for a in args if a.keyword is None]
        condition = positional[0].value if positional else None
        if condition is not None and m.matches(condition, m.SimpleString()):
            condition = None  # xfail("reason") shorthand
            reason = positional[0].value
        else:
            reason = _str_arg(args, None, "reason")
        strict = _str_arg(args, None, "strict")
        raises = _str_arg(args, None, "raises")
        if raises is not None:
            plan.todos.append(
                f"xfail(raises={_code(raises)}) -- ctrlrunner's "
                f"fail() accepts any failure; assert the "
                f"exception type manually if it matters"
            )
        parts = []
        if condition is not None:
            parts.append(_code(condition))
        if reason is not None:
            parts.append(f"description={_code(reason)}")
        # pytest xfail defaults to strict=False; ctrlrunner fail() to strict=True.
        parts.append(f"strict={_code(strict) if strict is not None else 'False'}")
        plan.body_inserts.append(f"fail({', '.join(parts)})")
        plan.marker_conversions += 1
        self.needed_imports.add("fail")

    def _mark_timeout(self, args, plan, fn_node, dec):
        value = _str_arg(args, 0, "timeout")
        if value is not None:
            plan.test_args.append(f"timeout={_code(value)}")
            plan.marker_conversions += 1
            return
        # Bare `@pytest.mark.timeout` or an arg shape we don't
        # recognize (e.g. method="thread") -- must not silently vanish
        # with no conversion and no TODO; keep the original
        # decorator and flag it like every other unrecognized marker.
        plan.kept_decorators.append(dec)
        plan.todos.append(
            f"unrecognized @pytest.mark.timeout form ({_code(dec.decorator)}) -- "
            f"left as-is; convert manually to @test(timeout=...)"
        )

    def _mark_flaky(self, args, plan, fn_node, dec):
        reruns = _str_arg(args, 0, "reruns")
        if reruns is not None:
            plan.test_args.append(f"retries={_code(reruns)}")
            plan.marker_conversions += 1
            if any(a.keyword and a.keyword.value == "reruns_delay" for a in args):
                plan.todos.append(
                    "flaky reruns_delay dropped -- ctrlrunner retries immediately, in-process"
                )
            return
        # Bare `@pytest.mark.flaky`, or the `flaky` package's own
        # max_runs=/min_passes= API -- neither matches ctrlrunner's
        # `reruns=N` shape. Must not silently vanish; keep the
        # original decorator and flag it.
        plan.kept_decorators.append(dec)
        plan.todos.append(
            f"unrecognized @pytest.mark.flaky form ({_code(dec.decorator)}) -- "
            f"left as-is; convert manually to @test(retries=...)"
        )

    def _mark_usefixtures(self, args, plan, fn_node, dec):
        for arg in args:
            if m.matches(arg.value, m.SimpleString()):
                plan.extra_params.append(
                    cst.ensure_type(arg.value, cst.SimpleString).evaluated_value
                )
                plan.marker_conversions += 1
            else:
                plan.todos.append(
                    f"usefixtures({_code(arg.value)}) with a "
                    f"non-literal name -- add to the signature "
                    f"manually"
                )

    def _mark_asyncio(self, args, plan, fn_node, dec):
        plan.todos.append(
            "@pytest.mark.asyncio -- ctrlrunner is sync-only; "
            "wrap the body with asyncio.run() manually"
        )

    # ----- signature / body analysis ----------

    def _plan_signature(self, original_node, updated_node, plan: _FnPlan):
        param_names = [p.name.value for p in updated_node.params.params]
        for pname in param_names:
            if pname in PROPERTY_FIXTURES and not self.index.fixture_defined(pname):
                # record_property / record_testsuite_property: drop the
                # param, import the ctrlrunner equivalent instead. Call
                # sites of the renamed testsuite variant are rewritten
                # in leave_Call.
                plan.remove_params.add(pname)
                self.needed_imports.add(PROPERTY_FIXTURES[pname])
            elif pname in UNSUPPORTED_FIXTURES:
                plan.todos.append(
                    f"builtin fixture '{pname}' has no ctrlrunner "
                    f"equivalent -- provide your own @fixture or "
                    f"inline the behavior"
                )
            elif pname in PLAYWRIGHT_MAPPED and not self.index.fixture_defined(pname):
                self.playwright_imports.add(pname)
            elif pname in PLAYWRIGHT_UNMAPPED and not self.index.fixture_defined(pname):
                plan.todos.append(
                    f"pytest-playwright fixture '{pname}' -- use "
                    f"ctrlrunner.playwright.playwright_fixtures.configure() / --browser CLI "
                    f"flag instead"
                )

    def _plan_request_usage(self, updated_node, plan: _FnPlan):
        attrs = set()
        for attr in m.findall(updated_node.body, m.Attribute(value=m.Name("request"))):
            name = cst.ensure_type(attr, cst.Attribute).attr.value
            if name != "param":
                attrs.add(name)
        for name in sorted(attrs):
            plan.todos.append(
                f"request.{name} is not supported (ctrlrunner's FixtureRequest only carries .param)"
            )
        # A test whose body no longer touches `request` at all (typically
        # because every request.node.add_marker(...) was rewritten to
        # record_property above) must not keep the parameter: ctrlrunner
        # would try to resolve a fixture named 'request' and fail.
        if (
            plan.is_test
            and not plan.needs_request_param
            and any(p.name.value == "request" for p in updated_node.params.params)
            and not m.findall(updated_node.body, m.Name("request"))
        ):
            plan.remove_params.add("request")

    # ----- rebuild ----------

    def _rebuild_function(self, original_node, updated_node, plan: _FnPlan):
        decorators = []
        if plan.is_test:
            if plan.tags:
                plan.test_args.append(
                    "tags={{{}}}".format(", ".join(repr(t) for t in sorted(plan.tags)))
                )
            decorators.append(
                cst.Decorator(decorator=cst.parse_expression(f"test({', '.join(plan.test_args)})"))
            )
            decorators += [
                cst.Decorator(decorator=cst.parse_expression(src)) for src in plan.parametrize_srcs
            ]
            self.needed_imports.add("test")
            self.report.add("tests")
            if self._class_stack and self._class_stack[-1]["is_test_class"]:
                self._class_stack[-1]["converted_methods"] += 1
        if plan.is_fixture:
            decorators.append(
                cst.Decorator(
                    decorator=cst.parse_expression(f"fixture({', '.join(plan.fixture_args)})")
                )
            )
            self.needed_imports.add("fixture")
            self.report.add("fixtures")
        decorators += plan.kept_decorators

        params = list(updated_node.params.params)
        if plan.remove_params:
            params = [p for p in params if p.name.value not in plan.remove_params]
            if params:
                params[-1] = params[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
        existing = {p.name.value for p in params}
        for extra in plan.extra_params:
            if extra not in existing:
                params.append(cst.Param(name=cst.Name(extra)))
        if plan.needs_request_param and "request" not in existing:
            params.append(cst.Param(name=cst.Name("request")))
        body = updated_node.body
        if plan.body_inserts:
            body = self._insert_into_body(body, plan.body_inserts)

        if plan.marker_conversions:
            self.report.add("markers", plan.marker_conversions)
        leading = list(updated_node.leading_lines)
        for msg in plan.todos:
            self._todo(original_node, msg)
            leading.append(_todo_line(msg))
        self._converted_any = True

        return updated_node.with_changes(
            decorators=decorators,
            params=updated_node.params.with_changes(params=params),
            body=body,
            leading_lines=leading,
        )

    def _insert_into_body(self, body, inserts: list[str]):
        statements = [cst.parse_statement(src) for src in inserts]
        if isinstance(body, cst.SimpleStatementSuite):  # def f(): pass
            inner = [cst.SimpleStatementLine(body=[stmt]) for stmt in body.body]
            return cst.IndentedBlock(body=statements + inner)
        docstring_offset = 0
        if body.body and m.matches(
            body.body[0],
            m.SimpleStatementLine(body=[m.Expr(value=m.SimpleString() | m.ConcatenatedString())]),
        ):
            docstring_offset = 1
        new_body = (
            list(body.body[:docstring_offset]) + statements + list(body.body[docstring_offset:])
        )
        return body.with_changes(body=new_body)

    # ---------- runtime pytest.* calls --------------------------------------

    def leave_Call(self, original_node, updated_node):
        # pytest's record_testsuite_property has a different name in
        # ctrlrunner -- rename the call itself; the signature param is
        # dropped separately in _rebuild_function. Skipped when the user
        # defined their OWN fixture of that name (then the call target
        # is their fixture's value, not pytest's builtin).
        func = updated_node.func
        if (
            isinstance(func, cst.Name)
            and func.value == "record_testsuite_property"
            and not self.index.fixture_defined("record_testsuite_property")
        ):
            return updated_node.with_changes(func=cst.Name("record_suite_property"))
        return updated_node

    def leave_SimpleStatementLine(self, original_node, updated_node):
        rewritten = self._rewrite_add_marker_statement(original_node, updated_node)
        if rewritten is not None:
            return rewritten
        rewritten = self._rewrite_call_statement(original_node, updated_node)
        if rewritten is not None:
            return rewritten
        return self._annotate_manual_pytest_use(original_node, updated_node)

    def _rewrite_add_marker_statement(self, original_node, updated_node):
        """request.node.add_marker(pytest.mark.<case-id-marker>(x)) ->
        record_property("<case-id-marker>", x).

        ctrlrunner has no runtime marker API; record_property lands the value
        in the same JUnit/JSON property channel the reporter already uses
        for case_id ("test_case_id"), so downstream report consumers keep
        working -- but it does NOT reach TestItem.case_id, i.e. the test
        stays unselectable via --case-id. Any other add_marker use gets a
        TODO and is left untouched."""
        if len(updated_node.body) != 1 or not m.matches(
            updated_node.body[0], m.Expr(value=m.Call())
        ):
            return None
        call = cst.ensure_type(cst.ensure_type(updated_node.body[0], cst.Expr).value, cst.Call)
        if _dotted(call.func) != "request.node.add_marker":
            return None

        inner = call.args[0].value if len(call.args) == 1 else None
        inner_name = _dotted(inner.func) if isinstance(inner, cst.Call) else None
        canonical = self.canonical(inner_name) if inner_name else None
        convertible = (
            self.case_id_marker
            and isinstance(inner, cst.Call)
            and canonical == f"pytest.mark.{self.case_id_marker}"
            and len(inner.args) == 1
            and inner.args[0].keyword is None
        )
        if not convertible:
            msg = (
                "request.node.add_marker has no ctrlrunner equivalent -- "
                "move the metadata to @test(...) or record_property(...) manually"
            )
            self._todo(original_node, msg)
            if _has_todo(updated_node.leading_lines, msg):
                return updated_node
            return updated_node.with_changes(
                leading_lines=[*updated_node.leading_lines, _todo_line(msg)]
            )

        assert isinstance(inner, cst.Call)
        arg_code = _code(inner.args[0].value)
        self.needed_imports.add("record_property")
        self.report.add("case_id")
        msg = (
            f"add_marker({self.case_id_marker}) -> record_property: the value is "
            f"reported (JUnit/JSON property) but NOT selectable via --case-id; "
            f"move it to @test(case_id=...) if selection matters"
        )
        self._todo(original_node, msg)
        src = f"record_property({self.case_id_marker!r}, {arg_code})"
        new_body = cst.ensure_type(cst.parse_statement(src), cst.SimpleStatementLine).body
        leading = list(updated_node.leading_lines)
        if not _has_todo(leading, msg):
            leading.append(_todo_line(msg))
        return updated_node.with_changes(body=new_body, leading_lines=leading)

    def leave_With(self, original_node, updated_node):
        return self._annotate_manual_pytest_use(original_node, updated_node)

    def _rewrite_call_statement(self, original_node, updated_node):
        """pytest.skip/fail/xfail as a standalone statement."""
        if len(updated_node.body) != 1 or not m.matches(
            updated_node.body[0], m.Expr(value=m.Call())
        ):
            return None
        expr = cst.ensure_type(updated_node.body[0], cst.Expr).value
        call = cst.ensure_type(expr, cst.Call)
        name = _dotted(call.func)
        canonical = self.canonical(name) if name else None
        if canonical not in ("pytest.skip", "pytest.fail", "pytest.xfail"):
            return None

        reason = _str_arg(call.args, 0, "reason") or _str_arg(call.args, 0, "msg")
        reason_src = _code(reason) if reason is not None else None

        if canonical == "pytest.skip":
            if any(a.keyword and a.keyword.value == "allow_module_level" for a in call.args):
                # ctrlrunner's skip() raises AT IMPORT TIME, unlike
                # pytest's module-level-skip semantics -- auto-
                # converting this breaks collection of the whole
                # module. Leave the call untouched with an inline TODO
                # at the exact spot (not just a report entry) -- this
                # needs manual handling, there's no equivalent to fall
                # back to. Not counted as a converted runtime_call
                # since nothing was actually converted.
                msg = (
                    "pytest.skip(allow_module_level=True) has no ctrlrunner equivalent "
                    "(ctrlrunner's skip() raises at import time, breaking module "
                    "collection) -- needs manual handling"
                )
                self._todo(original_node, msg)
                if _has_todo(updated_node.leading_lines, msg):
                    return updated_node
                return updated_node.with_changes(
                    leading_lines=[*updated_node.leading_lines, _todo_line(msg)]
                )
            self.report.add("runtime_calls")
            self.needed_imports.add("skip")
            src = f"skip(description={reason_src})" if reason_src else "skip()"
            return updated_node.with_changes(
                body=[cst.ensure_type(cst.parse_statement(src), cst.SimpleStatementLine).body[0]]
            )
        if canonical == "pytest.fail":
            self.report.add("runtime_calls")
            src = f"raise AssertionError({reason_src or ''})"
            return updated_node.with_changes(
                body=[cst.ensure_type(cst.parse_statement(src), cst.SimpleStatementLine).body[0]]
            )
        # pytest.xfail(msg): marks as expected-to-fail AND stops the test.
        self.report.add("runtime_calls")
        self.needed_imports.add("fail")
        mark = f"fail(description={reason_src})" if reason_src else "fail()"
        stop = f"raise AssertionError({reason_src or repr('expected failure')})"
        first = cst.ensure_type(cst.parse_statement(mark), cst.SimpleStatementLine)
        second = cst.ensure_type(cst.parse_statement(stop), cst.SimpleStatementLine)
        return cst.FlattenSentinel(
            [
                first.with_changes(leading_lines=updated_node.leading_lines),
                second,
            ]
        )

    def _annotate_manual_pytest_use(self, original_node, updated_node):
        """Attach a TODO to statements that keep using pytest.<attr>."""
        found = set()
        for attr_node in m.findall(updated_node, m.Attribute(attr=m.Name())):
            assert isinstance(attr_node, cst.BaseExpression)
            name = _dotted(attr_node)
            if not name:
                continue
            canonical = self.canonical(name)
            if canonical.startswith("pytest."):
                attr = canonical.split(".", 1)[1].split(".")[0]
                if attr in MANUAL_PYTEST_ATTRS:
                    found.add(attr)
        if not found:
            return updated_node
        leading = list(updated_node.leading_lines)
        changed = False
        for attr in sorted(found):
            msg = MANUAL_PYTEST_ATTRS[attr]
            self._todo(original_node, msg)
            if not _has_todo(leading, msg):
                leading.append(_todo_line(msg))
                changed = True
        if not changed:
            return updated_node
        return updated_node.with_changes(leading_lines=leading)
