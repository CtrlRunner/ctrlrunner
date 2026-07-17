"""
Test/fixture registration. This replaces pytest's collection machinery.
No file-name/function-name magic: registration happens explicitly via decorators.

Test Case ID model (replaces the pytest_collection_modifyitems hack):
    - `case_id` on @test is a plain string, or a "{param}"-style template
      when the test is parametrized (resolved per parameter set at
      registration time, e.g. "TC-100-chromium", "TC-100-firefox").
    - `tags` and `properties` are arbitrary metadata, analogous to
      Playwright TS's test.info().annotations, and get written into the
      JUnit <properties> block by the reporter so downstream tooling
      (Teams pipeline, TestRail/Jira sync, etc.) can read them without
      parsing test names.
    - Selecting tests by case_id/tag is a pure function over this
      registry (see selection.py) -- no collection hook required.

Fixture model:
    - scope: "function" | "module" (per test module, per worker) |
      "session" (per worker process, i.e. per batch of tests it runs).
    - autouse=True fixtures are resolved for every test in the run even
      if the test doesn't list them as a parameter (side-effect only).
    - params=[...] parametrizes the FIXTURE itself (like pytest's
      indirect parametrization): the fixture function must accept a
      `request` parameter and read `request.param`. Any test that
      (transitively) depends on a parametrized fixture is automatically
      multiplied, one TestItem per fixture param value, combined via
      cartesian product with any @parametrize on the test itself.
"""

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_fixtures: dict[str, "Fixture"] = {}
_tests: list["TestItem"] = []
_test_ids: set[str] = set()


@dataclass
class Fixture:
    name: str
    func: Callable
    scope: str = "function"  # "function" | "module" | "session"
    params: list = field(default_factory=list)  # dependency fixture names
    on_failure: Callable | None = None
    param_values: list[Any] | None = None  # fixture-level parametrize values
    wants_request: bool = False
    autouse: bool = False
    always_capture: bool = False


@dataclass
class TestItem:
    id: str
    func: Callable
    params: list
    timeout: float | None = None
    tags: set[str] = field(default_factory=set)
    case_id: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    param_values: dict[str, Any] = field(default_factory=dict)
    retries: int | None = None
    fixture_param_overrides: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    class_name: str | None = None
    project: str | None = None
    risk_flag: bool = False
    workers: int | None = None
    workers_mode: str | None = None  # "cap" | "dedicated" (only when workers set)
    serial_group: str | None = None  # "module::ClassName" when @test_class(serial=True)
    serial_retries: int = 0  # group retry budget (serial classes only)
    fully_parallel: bool | None = None  # tri-state: None = inherit run default
    expected_failure: dict | None = (
        None  # {"description": str|None, "strict": bool} from param(xfail=...)
    )
    skip_marker: dict | None = None  # {"description": str|None} from param(skip=...)


class param:
    """One @parametrize entry with per-entry metadata -- ctrlrunner's
    equivalent of pytest.param(..., id=..., marks=[...]), expressed as
    flat keyword arguments instead of marker objects:

        @parametrize("entity_id, label", [
            param(US_ENTITY_ID, "US", id="us_entity", case_id="7184475",
                  xfail="[Bug 7438797] audit widget absent", xfail_strict=True),
            param(NON_US_ENTITY_ID, "Non-US", id="non_us_entity", case_id="7184476"),
            ("PLAIN", "still-works"),   # plain tuples mix freely
        ])

    - `id`: custom test-id suffix for this combination (pytest.param's id=).
    - `case_id`: per-combination case id; overrides the @test decorator's
      case_id (including a "{name}" template) for this entry. "{name}"
      placeholders are supported here too.
    - `tags`: extra tags for this combination, unioned with @test's tags.
    - `xfail`: True or a reason string -- this combination is expected to
      fail (pytest.mark.xfail equivalent, applied via the runtime fail()
      pipeline). `xfail_strict` matches fail()'s default (True), NOT
      pytest's (False).
    - `skip`: True or a reason string -- this combination is skipped
      without resolving fixtures.
    """

    def __init__(
        self,
        *values: Any,
        id: str | None = None,
        case_id: str | None = None,
        tags: set[str] | None = None,
        xfail: bool | str = False,
        xfail_strict: bool = True,
        skip: bool | str = False,
    ):
        self.values = values
        self.id = id
        self.case_id = case_id
        self.tags = set(tags or set())
        self.xfail = xfail is True or isinstance(xfail, str)
        self.xfail_reason = xfail if isinstance(xfail, str) else None
        self.xfail_strict = xfail_strict
        self.skip = skip is True or isinstance(skip, str)
        self.skip_reason = skip if isinstance(skip, str) else None


@dataclass
class _ParamSet:
    """One fully-merged parametrize combination attached to a function as
    func._param_sets (consumed only by @test's expansion below)."""

    values: dict[str, Any] = field(default_factory=dict)
    # Names in `values` whose value goes to that FIXTURE's request.param
    # (pytest's indirect parametrize) instead of being bound as a test
    # kwarg. The values themselves stay in `values` -- this set only
    # changes routing at @test expansion time, so ids/case_id templates
    # see indirect values exactly like direct ones.
    indirect_names: set[str] = field(default_factory=set)
    id: str | None = None
    case_id: str | None = None
    tags: set[str] = field(default_factory=set)
    xfail: bool = False
    xfail_reason: str | None = None
    xfail_strict: bool = True
    skip: bool = False
    skip_reason: str | None = None


def fixture(
    scope: str = "function",
    on_failure: Callable | None = None,
    params: list[Any] | None = None,
    autouse: bool = False,
    always_capture: bool = False,
):
    """Decorator to register a fixture. Supports plain-return and
    generator (yield-based, for teardown) fixtures, same as pytest.

    `on_failure(value, path_prefix) -> Optional[str]` is called by the
    worker when a test using this fixture fails, letting a fixture
    capture artifacts (Playwright screenshot/trace) tied to that
    specific failure. It must return the artifact's final path (or None)
    and must never raise -- capture errors are swallowed so they can't
    mask the real test failure.

    `always_capture=True` calls that same `on_failure` callback after
    EVERY test (pass or fail), not just failures -- e.g. saving a trace
    for every run so it's viewable in UI Mode / the HTML report
    regardless of outcome, matching Playwright TS's "trace: on" mode.

    `params=[...]` parametrizes the fixture itself; the fixture function
    must accept a `request` argument and read `request.param`.

    `autouse=True` resolves this fixture for every test in the run
    (setup/teardown only run; the value is never injected as a kwarg
    unless the test also explicitly names it as a parameter).
    """

    def decorator(func):
        raw_params = list(inspect.signature(func).parameters.keys())
        wants_request = "request" in raw_params
        dep_params = [p for p in raw_params if p != "request"]

        if params is not None and not wants_request:
            raise ValueError(
                f"@fixture(params=...) on '{func.__name__}' requires the fixture function "
                f"to accept a 'request' parameter and read request.param, e.g.:\n\n"
                f"    @fixture(params=[...])\n"
                f"    def {func.__name__}(request):\n"
                f"        return request.param"
            )

        _fixtures[func.__name__] = Fixture(
            name=func.__name__,
            func=func,
            scope=scope,
            params=dep_params,
            on_failure=on_failure,
            param_values=params,
            wants_request=wants_request,
            autouse=autouse,
            always_capture=always_capture,
        )
        return func

    return decorator


def parametrize(
    arg_names: str | tuple[str, ...] | list[str],
    arg_values: list[Any],
    indirect: bool | list[str] | tuple[str, ...] = False,
):
    """Stacks parametrization metadata onto the function; @test expands it
    into one TestItem per combination when it registers the test.
    Stacking multiple @parametrize decorators produces the cartesian
    product, same as pytest.

    `arg_names` is a comma-separated string ("a, b") or, pytest-style, a
    tuple/list of names (("a", "b")) -- migrated suites commonly use the
    latter form.

    `indirect` (pytest-compatible): True marks EVERY name as indirect; a
    list/tuple marks that subset. An indirect name must be a FIXTURE
    (used by this test directly in its signature, transitively via
    another fixture, or autouse) whose function accepts `request` --
    the per-combination value is delivered to that fixture as
    `request.param` instead of being passed to the test as a kwarg,
    and it REPLACES the fixture's own static params=[...] (if any) for
    this test, exactly like pytest's indirect parametrize. The test
    still receives the fixture's resolved VALUE for names in its
    signature.

    Decorator order matters: @parametrize must sit closer to the function
    than @test (i.e. @test on top, @parametrize directly above def),
    because decorators apply bottom-up and @test needs _param_sets to
    already be attached when it runs.
    """
    if isinstance(arg_names, (tuple, list)):
        names = [str(n).strip() for n in arg_names]
    else:
        names = [n.strip() for n in arg_names.split(",")]

    if indirect is True:
        indirect_names = set(names)
    elif not indirect:
        indirect_names = set()
    else:
        indirect_names = {str(n).strip() for n in indirect}
        unknown = indirect_names - set(names)
        if unknown:
            raise ValueError(
                f"@parametrize indirect={sorted(unknown)}: these names are not in "
                f"arg_names {names} -- indirect entries must be a subset of the "
                f"names being parametrized."
            )

    def decorator(func):
        if getattr(func, "_ctrlrunner_registered", False):
            raise TypeError(
                f"@parametrize on '{func.__name__}' was applied after @test already "
                f"registered it. Decorators apply bottom-up, so the correct order is:\n\n"
                f"    @test(...)\n"
                f"    @parametrize(...)\n"
                f"    def {func.__name__}(...):\n\n"
                f"(@test must be on top / outermost, @parametrize directly above the function)"
            )
        existing = getattr(func, "_param_sets", None) or [_ParamSet()]
        combined = []
        for base in existing:
            # Stacked decorators re-parametrizing the same name already
            # silently last-wins on the VALUE -- but the name's ROLE
            # (direct kwarg vs indirect fixture param) flipping between
            # levels would silently mis-route values, so that's an error.
            role_conflicts = {
                n
                for n in set(base.values) & set(names)
                if (n in base.indirect_names) != (n in indirect_names)
            }
            if role_conflicts:
                raise ValueError(
                    f"@parametrize on '{func.__name__}': {sorted(role_conflicts)} "
                    f"appear(s) in stacked @parametrize decorators with conflicting "
                    f"direct/indirect roles -- a name must be consistently direct or "
                    f"consistently indirect across every level."
                )
            for values in arg_values:
                if isinstance(values, param):
                    entry = values
                    values_tuple = entry.values
                elif len(names) == 1:
                    # Single argname: the row IS the value, even when
                    # it's a tuple -- pytest semantics
                    # (@parametrize("x", [(1, 2)]) gives x=(1, 2), it
                    # doesn't unpack). Unconditional tuple-unpacking
                    # here used to crash on this shape with an opaque
                    # zip() ValueError; tuple values are the norm for
                    # indirect fixture params (e.g. (persona, flags)).
                    entry = None
                    values_tuple = (values,)
                else:
                    entry = None
                    values_tuple = values if isinstance(values, tuple) else (values,)
                combo = dict(zip(names, values_tuple, strict=True))

                entry_case_id = entry.case_id if entry else None
                if base.case_id and entry_case_id:
                    raise ValueError(
                        f"param(case_id=...) on '{func.__name__}': stacked @parametrize "
                        f"decorators both set a case_id for the same combination "
                        f"('{base.case_id}' and '{entry_case_id}') -- a test item can "
                        f"only have one case_id, so this is ambiguous. Set case_id on "
                        f"a single @parametrize level (or on @test as a template)."
                    )

                entry_id = entry.id if entry else None
                if base.id is None and entry_id is None:
                    merged_id = None
                else:
                    # One level has an explicit id, the other may not:
                    # derive the anonymous level's part from its values so
                    # combinations stay distinguishable (index-based
                    # fallback mirrors _stable_param_str's contract).
                    idx = len(combined)
                    base_part = base.id or "-".join(
                        _stable_param_str(v, idx) for v in base.values.values()
                    )
                    entry_part = entry_id or "-".join(
                        _stable_param_str(v, idx) for v in combo.values()
                    )
                    merged_id = "-".join(p for p in (base_part, entry_part) if p)

                merged = _ParamSet(
                    values={**base.values, **combo},
                    indirect_names=base.indirect_names | indirect_names,
                    id=merged_id,
                    case_id=base.case_id or entry_case_id,
                    tags=base.tags | (entry.tags if entry else set()),
                    xfail=base.xfail or (entry.xfail if entry else False),
                    xfail_reason=base.xfail_reason or (entry.xfail_reason if entry else None),
                    xfail_strict=(
                        base.xfail_strict if base.xfail else (entry.xfail_strict if entry else True)
                    ),
                    skip=base.skip or (entry.skip if entry else False),
                    skip_reason=base.skip_reason or (entry.skip_reason if entry else None),
                )
                combined.append(merged)
        func._param_sets = combined
        return func

    return decorator


def _collect_parametrized_fixtures(names, fixtures, seen=None):
    """BFS over the fixture dependency graph reachable from `names`,
    returning {fixture_name: [values...]} for every (transitively)
    required fixture that declares params=[...]."""
    if seen is None:
        seen = set()
    found = {}
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        fx = fixtures.get(name)
        if fx is None:
            continue
        if fx.param_values is not None:
            found[name] = fx.param_values
        found.update(_collect_parametrized_fixtures(fx.params, fixtures, seen))
    return found


def _fixture_closure(names, fixtures) -> set:
    """The set of fixture names reachable from `names` (a test's
    signature params) through the fixture dependency graph, plus every
    autouse fixture and ITS dependencies -- the worker resolves autouse
    fixtures for every test (worker.py builds names_to_resolve as
    item.params + autouse names), so an autouse fixture is just as
    legitimate an indirect-parametrize target as one named in the
    signature."""
    queue = list(names) + [n for n, fx in fixtures.items() if fx.autouse]
    reachable = set()
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        fx = fixtures.get(name)
        if fx is None:
            continue
        reachable.add(name)
        queue.extend(fx.params)
    return reachable


def _cartesian(mapping: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not mapping:
        return [{}]
    result = [{}]
    for name, values in mapping.items():
        result = [{**combo, name: value} for combo in result for value in values]
    return result


def _stable_param_str(value: Any, index: int) -> str:
    """Renders one parametrize value for the test id suffix. Plain str/
    int/bool/etc values render via str(value) as before -- human
    readable and already stable. But a plain object with no __str__/
    __repr__ override falls back to Python's default
    `<module.Class object at 0x104ab3d90>` repr, which embeds the
    live memory address -- different every process start, so it never
    matches across runs and silently breaks history/sharding/
    --last-failed/quarantine id lookups. Detect that specific fallback
    (both __str__ and __repr__ are the untouched `object` defaults) and
    use a deterministic index-based label instead: f"{ClassName}{index}",
    where `index` is this value's parametrize-combination's position
    among all combinations produced for the @test call -- simple and
    stable across runs (position in a fixed, code-defined list, not a
    memory address)."""
    cls = type(value)
    if cls.__str__ is object.__str__ and cls.__repr__ is object.__repr__:
        return f"{cls.__name__}{index}"
    return str(value)


def _register_item(item: "TestItem"):
    """Appends `item` to the registry, raising loudly on a duplicate test
    id instead of letting the later registration silently clobber the
    earlier one (the earlier item then never gets selected/run at all
    while the duplicate id runs twice under its neighbor's name).
    Two known collision shapes:

      (a) `@test` methods with the same name in two different
          UNDECORATED classes in one module -- both register as
          `module::method_name` (wrapping the classes in `@test_class`
          disambiguates via the class-name-qualified id rewrite, which
          always runs -- and completes -- before the next class's
          methods register, so it never trips this check).
      (b) `@parametrize` id suffixes collide because the join separator
          appears inside a value itself, e.g. ("a-b", "c") and
          ("a", "b-c") both produce the suffix "[a-b-c]".
    """
    if item.id in _test_ids:
        raise ValueError(
            f"Duplicate test id '{item.id}' -- test ids must be unique. This "
            f"usually means either (a) two undecorated classes in the same "
            f"module define a method with the same name (wrap each class in "
            f"@test_class so ids get qualified with the class name), or (b) "
            f"two @parametrize value combinations produce the same id suffix "
            f'once joined with \'-\' (e.g. ("a-b", "c") and ("a", "b-c") '
            f"both join to '[a-b-c]'), or two param(id=...) entries use the "
            f"same explicit id -- use param values/ids that don't collide, "
            f"or make them distinguishable another way."
        )
    _test_ids.add(item.id)
    _tests.append(item)


def _stamp_item(func, item):
    """Records every TestItem produced from this function (one, unless
    @parametrize expanded it into several) so a later @test_class can
    find and merge into all of them -- see test_class() below."""
    items = getattr(func, "_ctrlrunner_items", None)
    if items is None:
        items = []
        func._ctrlrunner_items = items
    items.append(item)


def test(
    timeout: float | None = None,
    tags: set[str] | None = None,
    case_id: str | None = None,
    properties: dict[str, str] | None = None,
    retries: int | None = None,
):
    """Decorator to register a test.

    `timeout` is per-test, in seconds, enforced by the orchestrator's
    watchdog (hard-kill via Job Object), not by pytest-timeout's
    thread-based interrupt. If not given here, it resolves to an
    enclosing @test_class's timeout, or the run's global --timeout
    default, in that order (see test_class() below) -- unset is
    represented as None, not a baked-in 30.0, specifically so that
    resolution chain can tell "not specified" apart from "explicitly
    set to the same value as the default."

    `case_id` may contain "{name}" placeholders resolved from either
    @parametrize arguments or fixture-parametrize values (fixture name
    as the key) -- each combination gets its own resolved case_id.

    `retries` is the number of *additional* attempts after an initial
    failure (assertion/exception), executed in-process by the worker.
    It does NOT apply to hangs -- a timed-out test is hard-killed and its
    batch is requeued, which is a different failure mode handled by the
    orchestrator, not retried in place. Same None-means-unset resolution
    chain as `timeout`.
    """

    def decorator(func):
        if getattr(func, "_ctrlrunner_registered", False):
            raise TypeError(
                f"@test applied twice to '{func.__name__}' (or applied to a function "
                f"that some other @test-registered function was reassigned to). "
                f"Applying @test more than once to the same function registers a "
                f"duplicate TestItem with no error -- give the function a single "
                f"@test decorator."
            )

        raw_sig_params = list(inspect.signature(func).parameters.keys())
        # A method written the natural way inside a @test_class body
        # (`def test_x(self, page): ...`) still has a literal leading
        # 'self' -- strip it from fixture resolution and bind it to None
        # at call time. None (not a real instance) is deliberate: it
        # means `self.whatever = ...` fails loudly with AttributeError
        # instead of silently working, actively enforcing "classes are
        # metadata containers, not instance-state containers" rather
        # than just documenting it as a convention.
        has_self = bool(raw_sig_params) and raw_sig_params[0] == "self"
        sig_params = raw_sig_params[1:] if has_self else raw_sig_params
        call_target = (lambda *a, **kw: func(None, *a, **kw)) if has_self else func

        explicit_param_sets = getattr(func, "_param_sets", None) or [_ParamSet()]
        base_properties = properties or {}
        base_tags = tags or set()
        source_path = Path(inspect.getsourcefile(func) or func.__code__.co_filename)

        # Indirect parametrize validation happens at registration, not
        # first resolve -- same import-order stance as fixture params=
        # discovery below: the fixture must already exist (be defined
        # above/earlier than) when @test runs.
        all_indirect = set().union(*(ps.indirect_names for ps in explicit_param_sets))
        fixtures_now = get_fixtures()
        if all_indirect:
            reachable = _fixture_closure(sig_params, fixtures_now)
            for name in sorted(all_indirect):
                fx = fixtures_now.get(name)
                if fx is None:
                    raise ValueError(
                        f"@parametrize(..., indirect=...) on '{func.__name__}': no "
                        f"fixture named '{name}' is registered. If it exists, it is "
                        f"probably defined AFTER this test in module import order -- "
                        f"@test looks the fixture up at decoration time, so move the "
                        f"@fixture definition for '{name}' above (earlier than) this "
                        f"test."
                    )
                if not fx.wants_request:
                    raise ValueError(
                        f"@parametrize(..., indirect=...) on '{func.__name__}': "
                        f"fixture '{name}' takes no 'request' parameter, so it has "
                        f"no way to receive the indirect value. Add `request` to its "
                        f"signature and read request.param."
                    )
                if name not in reachable:
                    raise ValueError(
                        f"@parametrize(..., indirect=...) on '{func.__name__}': "
                        f"fixture '{name}' is not used by this test -- it is neither "
                        f"in the test's signature, nor a transitive dependency of its "
                        f"fixtures, nor autouse. An indirect value for a fixture that "
                        f"never gets resolved would be silently ignored."
                    )

        fixture_param_map = _collect_parametrized_fixtures(sig_params, fixtures_now)
        # A test's indirect params REPLACE the target fixture's own
        # static params=[...] for that test (pytest semantics) -- drop
        # such fixtures from the map BEFORE the cartesian product, or
        # each test would multiply by both value sets.
        fixture_param_map = {k: v for k, v in fixture_param_map.items() if k not in all_indirect}
        fixture_param_sets = _cartesian(fixture_param_map)

        func._ctrlrunner_registered = True

        is_parametrized = not (
            len(explicit_param_sets) == 1
            and not explicit_param_sets[0].values
            and len(fixture_param_sets) == 1
            and fixture_param_sets[0] == {}
        )

        if case_id and "{" in case_id and not is_parametrized:
            raise ValueError(
                f"@test on '{func.__name__}' has a template case_id ('{case_id}') "
                f"but no parametrization (test-level or fixture-level) was found. "
                f"Either add @parametrize directly above the function (below @test), "
                f"depend on a fixture with params=[...], or use a plain case_id string."
            )

        if not is_parametrized:
            test_id = f"{func.__module__}::{func.__name__}"
            item = TestItem(
                id=test_id,
                func=call_target,
                params=sig_params,
                timeout=timeout,
                tags=set(base_tags),
                case_id=case_id,
                properties=dict(base_properties),
                retries=retries,
                source_path=source_path,
            )
            _register_item(item)
            _stamp_item(func, item)
            return func

        combo_index = 0
        for explicit_pset in explicit_param_sets:
            for fixture_pset in fixture_param_sets:
                combined = {**fixture_pset, **explicit_pset.values}
                # `combo_index` (this combination's position among all
                # combinations produced for this @test call) is what
                # makes the index-based fallback in _stable_param_str
                # unique per test item, not just per value-within-combo
                # (two objects with no custom repr in the SAME position
                # across different combos must not render identically).
                if explicit_pset.id is not None:
                    parts = [explicit_pset.id] + [
                        _stable_param_str(v, combo_index) for v in fixture_pset.values()
                    ]
                    suffix = "-".join(parts)
                else:
                    suffix = "-".join(_stable_param_str(v, combo_index) for v in combined.values())
                combo_index += 1
                test_id = f"{func.__module__}::{func.__name__}[{suffix}]"
                # A per-entry param(case_id=...) overrides the decorator's
                # case_id (template or plain) for that combination; both
                # forms support "{name}" placeholders.
                effective_case_id = explicit_pset.case_id or case_id
                resolved_case_id = (
                    effective_case_id.format(**combined) if effective_case_id else None
                )
                # Direct values bind into the function as kwargs;
                # indirect values route to their fixture's request.param
                # via fixture_param_overrides below. An indirect name in
                # the test signature deliberately stays in
                # remaining_params, so the resolver injects the FIXTURE's
                # resolved value as the kwarg (the test receives the
                # fixture instance, never the raw param) -- pytest
                # semantics. Getting this split backwards would silently
                # pass the raw param value as the kwarg.
                direct_values = {
                    k: v
                    for k, v in explicit_pset.values.items()
                    if k not in explicit_pset.indirect_names
                }
                indirect_values = {
                    k: v
                    for k, v in explicit_pset.values.items()
                    if k in explicit_pset.indirect_names
                }
                bound_func = (
                    functools.partial(call_target, **direct_values)
                    if direct_values
                    else call_target
                )
                remaining_params = [p for p in sig_params if p not in direct_values]
                item = TestItem(
                    id=test_id,
                    func=bound_func,
                    params=remaining_params,
                    timeout=timeout,
                    tags=set(base_tags) | explicit_pset.tags,
                    case_id=resolved_case_id,
                    properties=dict(base_properties),
                    param_values=combined,
                    retries=retries,
                    # No key overlap: indirect names were excluded from
                    # fixture_param_map before _cartesian above.
                    fixture_param_overrides={**fixture_pset, **indirect_values},
                    source_path=source_path,
                    expected_failure=(
                        {
                            "description": explicit_pset.xfail_reason,
                            "strict": explicit_pset.xfail_strict,
                        }
                        if explicit_pset.xfail
                        else None
                    ),
                    skip_marker=(
                        {"description": explicit_pset.skip_reason} if explicit_pset.skip else None
                    ),
                )
                _register_item(item)
                _stamp_item(func, item)
        return func

    return decorator


def test_class(
    tags: set[str] | None = None,
    properties: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int | None = None,
    workers: int | None = None,
    workers_mode: str | None = None,
    serial: bool = False,
    fully_parallel: bool | None = None,
):
    """Class decorator: applies default tags/properties/timeout/retries
    to every @test-decorated method inside the class, and rewrites each
    method's test id to `module::ClassName.method_name[...]`.

    Must be the outermost decorator on the class (Python always runs
    class decorators after the class body has fully executed, so every
    @test inside has already registered its TestItem(s) via
    _stamp_item() by the time this runs -- no special import-order
    handling needed):

        @test_class(tags={"smoke"}, timeout=30)
        class LoginTests:
            @test(case_id="TC-1")
            def test_valid_login(self, page): ...

    Classes are pure metadata containers, not instance-state containers.
    Methods are written the natural way, with a leading `self`:

        @test_class(tags={"smoke"}, timeout=30)
        class LoginTests:
            @test(case_id="TC-1")
            def test_valid_login(self, page): ...

    but `self` is always bound to `None` at call time, never a real
    instance -- no class is ever instantiated. This is deliberate, not
    an oversight: it means `self.whatever = ...` fails loudly with
    `AttributeError` instead of silently working, actively enforcing
    "no shared state between test methods" rather than merely
    documenting it as a convention (the pytest class-instance-per-test
    model this project has avoided everywhere else).

    Merge rules:
        - tags: UNION of class tags and method tags (more tags surfacing
          a test for discovery is never wrong the way silently
          overriding would be).
        - properties: dict merge, method-level key wins on conflict.
        - timeout / retries: method-level wins if the method explicitly
          set it; else this class's value; else left unset (None),
          which the orchestrator/worker already resolve to the run's
          global default the same way a plain top-level test would.
        - workers / workers_mode / serial / fully_parallel: class-level
          only -- @test deliberately has no equivalent kwargs, because
          worker scheduling below class/file granularity has no meaning
          (a single test always occupies exactly one worker).
          `workers=N` caps how many workers may run this class's tests
          concurrently (workers_mode="dedicated" reserves them instead);
          `serial=True` makes the class an atomic group: definition
          order, one worker, a failure skips the rest of the group, and
          retries= becomes the GROUP retry budget (the whole group
          restarts from its first test; retries= on individual methods
          inside a serial class is an error); `fully_parallel=True`
          lets this class's tests scatter across workers individually
          even when the run default is file-grouped scheduling.

    Validation:
        - a class with zero @test-decorated methods is almost certainly
          a mistake (decorator on the wrong class, or methods below it
          that forgot @test) -- raises ValueError.
        - applying @test_class twice, or to a subclass of an
          already-@test_class-decorated class, raises TypeError.
          Real class-inheritance semantics for test metadata isn't
          supported in v1 -- not worth the complexity budget without a
          concrete need.
    """

    def decorator(cls):
        if getattr(cls, "_ctrlrunner_test_class", False):
            raise TypeError(
                f"@test_class applied to '{cls.__name__}', which already carries "
                f"@test_class metadata (directly, or inherited from a base class). "
                f"Stacking/inheriting @test_class isn't supported -- give each "
                f"test class its own single @test_class decorator."
            )

        if serial and fully_parallel:
            raise ValueError(
                f"@test_class on '{cls.__name__}' sets both serial=True and "
                f"fully_parallel=True -- a serial group runs its tests in order "
                f"in one worker, which is the opposite of fully parallel. Pick one."
            )
        if workers is not None and (
            isinstance(workers, bool) or not isinstance(workers, int) or workers < 1
        ):
            raise ValueError(
                f"@test_class on '{cls.__name__}': workers must be an integer >= 1, got {workers!r}"
            )
        if workers_mode is not None:
            if workers is None:
                raise ValueError(
                    f"@test_class on '{cls.__name__}': workers_mode requires workers=N"
                )
            if workers_mode not in ("cap", "dedicated"):
                raise ValueError(
                    f"@test_class on '{cls.__name__}': workers_mode must be 'cap' or "
                    f"'dedicated', got {workers_mode!r}"
                )
        if (
            serial
            and retries is not None
            and (isinstance(retries, bool) or not isinstance(retries, int) or retries < 0)
        ):
            raise ValueError(
                f"@test_class on '{cls.__name__}': serial retries must be an "
                f"integer >= 0, got {retries!r}"
            )

        nested_classes = [name for name, attr in cls.__dict__.items() if isinstance(attr, type)]
        if nested_classes:
            raise TypeError(
                f"@test_class on '{cls.__name__}' found a nested class "
                f"({', '.join(nested_classes)}) defined inside its body. Nested "
                f"classes are not supported -- give '{nested_classes[0]}' its own "
                f"top-level @test_class decorator instead."
            )

        class_tags = set(tags or set())
        class_properties = dict(properties or {})
        found_any = False

        for attr_name, attr in cls.__dict__.items():
            if isinstance(attr, staticmethod):
                # @test stamps _ctrlrunner_items on the plain function it
                # wraps; a staticmethod object doesn't forward arbitrary
                # attribute lookups to that function, so
                # getattr(attr, "_ctrlrunner_items", None) below would
                # just silently return None and this method would drop
                # out of the class merge with no error at all.
                # Staticmethods also can't receive this framework's
                # None-bound `self` -- there's no self parameter to
                # bind -- so it's a real usage error, not just a
                # detection gap.
                underlying = attr.__func__
                if getattr(underlying, "_ctrlrunner_items", None):
                    raise TypeError(
                        f"@test_class on '{cls.__name__}' found '{attr_name}' decorated "
                        f"with both @staticmethod and @test. Staticmethods can't receive "
                        f"the self-binding this framework relies on (every test method's "
                        f"self is bound to None, never a real instance) -- remove "
                        f"@staticmethod from '{attr_name}' and write it as a normal method."
                    )
                continue

            items = getattr(attr, "_ctrlrunner_items", None)
            if not items:
                continue
            found_any = True
            for item in items:
                if serial and item.retries is not None:
                    # Must be checked BEFORE _merge_class_metadata, which
                    # would stamp class retries into item.retries and make
                    # a genuine method-level retries= indistinguishable.
                    raise ValueError(
                        f"retries= on @test method '{item.id}' inside serial class "
                        f"'{cls.__name__}' -- serial groups are retried together; "
                        f"use @test_class(serial=True, retries=N) for group retries."
                    )
                _merge_class_metadata(
                    item,
                    cls.__name__,
                    class_tags,
                    class_properties,
                    timeout,
                    # Serial members' per-test retry loop must stay
                    # single-attempt; the group loop owns all retrying.
                    None if serial else retries,
                )
                if serial:
                    module = item.id.split("::")[0]
                    item.serial_group = f"{module}::{cls.__name__}"
                    item.serial_retries = retries or 0
                item.workers = workers
                item.workers_mode = (workers_mode or "cap") if workers is not None else None
                item.fully_parallel = fully_parallel

        if not found_any:
            raise ValueError(
                f"@test_class on '{cls.__name__}' found no @test-decorated methods "
                f"inside it. Did you forget @test on its methods, or apply "
                f"@test_class to the wrong class?"
            )

        cls._ctrlrunner_test_class = True
        return cls

    return decorator


def _merge_class_metadata(
    item: "TestItem",
    class_name: str,
    class_tags: set[str],
    class_properties: dict[str, str],
    class_timeout: float | None,
    class_retries: int | None,
):
    item.class_name = class_name

    module, sep, rest = item.id.partition("::")
    if sep:  # defensive; every TestItem id always has "::" today
        old_id = item.id
        item.id = f"{module}::{class_name}.{rest}"
        # Keep the duplicate-id tracking set in sync with the rewrite --
        # otherwise the vacated pre-rewrite id (e.g. "module::test_a")
        # stays "reserved" forever and would wrongly block a later,
        # genuinely-unrelated registration that happens to produce that
        # same id string.
        _test_ids.discard(old_id)
        _test_ids.add(item.id)

    item.tags = set(item.tags) | class_tags
    item.properties = {**class_properties, **item.properties}

    if item.timeout is None:
        item.timeout = class_timeout
    if item.retries is None:
        item.retries = class_retries


def get_fixtures():
    return _fixtures


def get_tests():
    return _tests


def clear_tests():
    _tests.clear()
    _test_ids.clear()


def clear_fixtures():
    _fixtures.clear()


def reset():
    """Clears both registries. Intended for unit tests, so each test case
    starts from a clean slate instead of accumulating state across the
    whole test run (the registries are module-level by design, since
    real usage only ever imports test modules once per worker process)."""
    _tests.clear()
    _test_ids.clear()
    _fixtures.clear()
