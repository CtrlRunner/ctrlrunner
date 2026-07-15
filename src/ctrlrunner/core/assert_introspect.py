"""
Runtime introspection for a failed `assert` statement, deliberately NOT
an import-time AST rewrite (pytest's `_pytest.assertion.rewrite`
installs a MetaPathFinder that rewrites every test module's `assert`
statements at import time -- permanent, global machinery baked into
every worker's import path). Instead this parses only the ONE source
file containing the failing assert, at the moment it fails, and
resolves ONLY side-effect-free sub-expressions.

Never executes user code: operand resolution is restricted to
Constant, Name (dict lookup only), static Attribute access (via
inspect.getattr_static, with an explicit refusal to report values
found behind a descriptor -- covers @property and ORM-style lazy
attributes), and Subscript on plain dict/list/tuple/str. Anything else
(Call, Await, Yield, comprehensions, lambda, walrus) is left
unresolved rather than risk a side effect or a hang in a process that
must stay instantly killable.

Never raises: build_assert_details() must always return either a
partial-or-full details dict or None. A bug here must never change a
test's outcome or crash the worker.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import os
import reprlib
from typing import Any

# Bounded, not a strict LRU: oldest-inserted entry is evicted first
# once the cache is full. Good enough to avoid re-parsing the same
# file for every assertion failure in a large run without adding a
# real LRU dependency for a cache this small.
_CACHE_MAX = 64
_ast_cache: dict[str, tuple[float, str, ast.Module]] = {}

_MAX_NAMES = 10
_MAX_DIFF_ELEMENTS = 10_000
_MAX_DIFF_LEN = 10_000

_SAFE_SUBSCRIPT_TYPES = (dict, list, tuple, str)
_SAFE_KEY_TYPES = (int, float, str, bool, type(None))


class _SafeRepr(reprlib.Repr):
    """reprlib.Repr's own repr_dict formats a dict by iterating its keys
    and then doing a FRESH `x[key]` lookup per key to fetch the value --
    not by using `.items()`. For a dict whose keys have a custom
    __hash__/__eq__, that lookup re-invokes them a second time, purely
    as a side effect of trying to DISPLAY the dict -- the same class of
    bug just closed in _diff() and _resolve(), but reachable through
    reprlib's internals instead of this module's own code, and at ANY
    nesting depth (a hostile dict nested inside a list/tuple would hit
    this too, since reprlib recurses back through self.repr_dict for
    every nested dict it encounters). repr_set/repr_frozenset have a
    smaller version of the same risk via their sort-for-determinism
    attempt, which can invoke a custom __lt__.

    Overriding these three methods on the instance means reprlib's own
    recursive dispatch (repr1 -> getattr(self, "repr_dict", ...)) goes
    through this safety gate at every level of nesting, not just the
    top-level value being formatted -- so this is closed for arbitrary
    nesting depth, not just the direct case."""

    def repr_dict(self, x, level):
        if not all(type(k) in _SAFE_KEY_TYPES for k in x):
            return f"{{...}} ({len(x)} item(s), unsafe key type not shown)"
        return super().repr_dict(x, level)

    def repr_set(self, x, level):
        if not all(type(v) in _SAFE_KEY_TYPES for v in x):
            return f"{{...}} ({len(x)} item(s), unsafe element type not shown)"
        return super().repr_set(x, level)

    def repr_frozenset(self, x, level):
        if not all(type(v) in _SAFE_KEY_TYPES for v in x):
            return f"frozenset(...) ({len(x)} item(s), unsafe element type not shown)"
        return super().repr_frozenset(x, level)


_repr = _SafeRepr()
_repr.maxstring = 2000
_repr.maxother = 2000
_repr.maxlist = 50
_repr.maxdict = 50
_repr.maxset = 50
_repr.maxfrozenset = 50
_repr.maxtuple = 50

_FORBIDDEN_NODE_TYPES = (
    ast.Call,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.NamedExpr,
)

_COMPARE_OPS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.In: "in",
    ast.NotIn: "not in",
    ast.Is: "is",
    ast.IsNot: "is not",
}


def build_assert_details(exc: AssertionError) -> dict | None:
    """Best-effort enrichment for a failed `assert` statement. Returns
    None if introspection isn't possible or safe -- the caller must
    fall back to the plain traceback in that case. Never raises."""
    try:
        return _build(exc)
    except Exception:
        return None


def _build(exc: AssertionError) -> dict | None:
    frame, lineno = _last_frame(exc)
    if frame is None:
        return None

    filename = frame.f_code.co_filename
    cached = _parse_cached(filename)
    if cached is None:
        return None
    source, module = cached

    node, ambiguous = _find_assert_node(module, lineno)
    if node is None:
        return None

    expr_src = ast.get_source_segment(source, node.test)
    if expr_src is None:
        return None

    details: dict[str, Any] = {
        "expr": expr_src,
        "op": None,
        "left": None,
        "right": None,
        "diff": None,
        "names": None,
        "truncated": False,
    }
    if ambiguous:
        return details

    names = _collect_names(node.test, frame)
    if names:
        details["names"] = names

    test = node.test
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        op_symbol = _COMPARE_OPS.get(type(test.ops[0]))
        left_val, left_ok = _resolve(test.left, frame)
        right_val, right_ok = _resolve(test.comparators[0], frame)
        if op_symbol is not None and left_ok and right_ok:
            details["op"] = op_symbol
            details["left"] = _describe(left_val)
            details["right"] = _describe(right_val)
            if isinstance(test.ops[0], (ast.Eq, ast.NotEq)):
                diff, truncated = _diff(left_val, right_val)
                details["diff"] = diff
                details["truncated"] = truncated

    return details


def _last_frame(exc: AssertionError):
    tb = exc.__traceback__
    if tb is None:
        return None, None
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame, tb.tb_lineno


def _parse_cached(filename: str) -> tuple[str, ast.Module] | None:
    try:
        mtime = os.stat(filename).st_mtime
    except OSError:
        return None

    cached = _ast_cache.get(filename)
    if cached is not None and cached[0] == mtime:
        return cached[1], cached[2]

    try:
        with open(filename, encoding="utf-8") as f:
            source = f.read()
        module = ast.parse(source, filename=filename)
    except (OSError, SyntaxError, ValueError):
        return None

    if len(_ast_cache) >= _CACHE_MAX:
        _ast_cache.pop(next(iter(_ast_cache)))
    _ast_cache[filename] = (mtime, source, module)
    return source, module


def _find_assert_node(module: ast.Module, lineno: int) -> tuple[ast.Assert | None, bool]:
    candidates = [
        n
        for n in ast.walk(module)
        if isinstance(n, ast.Assert) and n.lineno <= lineno <= (n.end_lineno or n.lineno)
    ]
    if not candidates:
        return None, False
    candidates.sort(key=lambda n: (n.lineno, n.col_offset))
    return candidates[0], len(candidates) > 1


def _contains_forbidden(node: ast.AST) -> bool:
    return any(isinstance(n, _FORBIDDEN_NODE_TYPES) for n in ast.walk(node))


def _iter_source_order(node: ast.AST):
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _iter_source_order(child)


def _collect_names(test: ast.AST, frame) -> dict[str, str] | None:
    if _contains_forbidden(test):
        return None
    names: dict[str, str] = {}
    for n in _iter_source_order(test):
        if isinstance(n, ast.Name) and n.id not in names:
            value, ok = _resolve_name(n.id, frame)
            if ok:
                names[n.id] = _repr_safe(value)
            if len(names) >= _MAX_NAMES:
                break
    return names or None


def _resolve_name(name: str, frame) -> tuple[Any, bool]:
    if name in frame.f_locals:
        return frame.f_locals[name], True
    if name in frame.f_globals:
        return frame.f_globals[name], True
    if name in frame.f_builtins:
        return frame.f_builtins[name], True
    return None, False


def _resolve(node: ast.AST, frame) -> tuple[Any, bool]:
    if _contains_forbidden(node):
        return None, False
    if isinstance(node, ast.Constant):
        return node.value, True
    if isinstance(node, ast.Name):
        return _resolve_name(node.id, frame)
    if isinstance(node, ast.Attribute):
        base, ok = _resolve(node.value, frame)
        if not ok:
            return None, False
        sentinel = object()
        value = inspect.getattr_static(base, node.attr, sentinel)
        if value is sentinel:
            return None, False
        # getattr_static bypasses the descriptor protocol -- for any
        # attribute backed by a descriptor (property, an ORM's lazy
        # relationship, etc.) it hands back the descriptor object
        # itself, not the resolved value. Showing that would be
        # actively misleading, so detect it via the class MRO and
        # treat it as unresolved instead of displaying the wrong thing.
        for klass in type(base).__mro__:
            if node.attr in klass.__dict__:
                attr_value = klass.__dict__[node.attr]
                if any("__get__" in t.__dict__ for t in type(attr_value).__mro__):
                    return None, False
                break
        return value, True
    if isinstance(node, ast.Subscript):
        base, ok = _resolve(node.value, frame)
        if not ok or type(base) not in _SAFE_SUBSCRIPT_TYPES:
            return None, False
        key, key_ok = _resolve(node.slice, frame)
        # The base-type check above only guarantees base.__getitem__
        # itself isn't overridden -- it says nothing about the KEY. A
        # dict lookup with a key resolved from an arbitrary frame-local
        # object (via Name) would re-invoke that object's __hash__/__eq__
        # a second time during introspection if we didn't also restrict
        # the key to safe, non-overridable builtin types.
        if not key_ok or type(key) not in _SAFE_KEY_TYPES:
            return None, False
        try:
            return base[key], True
        except (KeyError, IndexError, TypeError):
            return None, False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        val, ok = _resolve(node.operand, frame)
        # Exact-type check, not isinstance: a user-defined subclass of
        # int/float/complex with an overridden __neg__ must not have
        # that operator re-invoked by introspection. type(x) is bool
        # is excluded implicitly since bool is not in this tuple.
        if ok and type(val) in (int, float, complex):
            return -val, True
        return None, False
    return None, False


def _repr_safe(value: Any) -> str:
    try:
        return _repr.repr(value)
    except Exception:
        return "<unrepresentable>"


def _describe(value: Any) -> dict:
    return {"repr": _repr_safe(value), "type": type(value).__name__}


def _diff(left: Any, right: Any) -> tuple[str | dict | None, bool]:
    # Exact-type checks throughout (not isinstance): a str/set/dict
    # SUBCLASS could override comparison-relevant dunders. And for
    # set/dict specifically, the container's own type being safe says
    # nothing about what's INSIDE it -- computing `right - left` or
    # `.keys() - .keys()` invokes __hash__/__eq__ on every element/key,
    # a second time, if any of them are user objects with custom
    # __hash__/__eq__. Both checks are required; neither alone is
    # enough to keep this side-effect-free.
    if type(left) is str and type(right) is str:
        left_lines = left.splitlines(keepends=True) or [left]
        right_lines = right.splitlines(keepends=True) or [right]
        text = "\n".join(difflib.unified_diff(left_lines, right_lines, lineterm=""))
        if not text:
            return None, False
        if len(text) > _MAX_DIFF_LEN:
            return text[:_MAX_DIFF_LEN], True
        return text, False

    if type(left) in (set, frozenset) and type(right) in (set, frozenset):
        if len(left) > _MAX_DIFF_ELEMENTS or len(right) > _MAX_DIFF_ELEMENTS:
            return None, False
        if not all(type(x) in _SAFE_KEY_TYPES for x in left) or not all(
            type(x) in _SAFE_KEY_TYPES for x in right
        ):
            return None, False
        missing = sorted(_repr_safe(x) for x in (right - left))
        extra = sorted(_repr_safe(x) for x in (left - right))
        if not missing and not extra:
            return None, False
        return {"missing": missing, "extra": extra}, False

    if type(left) is dict and type(right) is dict:
        if len(left) > _MAX_DIFF_ELEMENTS or len(right) > _MAX_DIFF_ELEMENTS:
            return None, False
        if not all(type(k) in _SAFE_KEY_TYPES for k in left) or not all(
            type(k) in _SAFE_KEY_TYPES for k in right
        ):
            return None, False
        missing = sorted(_repr_safe(k) for k in (right.keys() - left.keys()))
        extra = sorted(_repr_safe(k) for k in (left.keys() - right.keys()))
        if not missing and not extra:
            return None, False
        return {"missing": missing, "extra": extra}, False

    return None, False
