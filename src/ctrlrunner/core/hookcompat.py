"""
Pytest-compatible shim objects handed to conftest hooks (docs/hooks.md)
-- Item/TestReport/Session/Config mirror the attribute surface a
migrated pytest hook body touches (item.get_closest_marker,
item.module/.cls/.funcargs, report.outcome/.sections, session.results,
config.getoption/.option), so `pytest_runtest_setup(item)` bodies keep
working after the rename to `ctrlrunner_runtest_setup(item)` without a
rewrite.

Attributes with a real ctrlrunner meaning are implemented for real --
including config.cache (a JSON-backed store under .ctrlrunner_cache/,
pytest's Cache API) and config.pluginmanager (truthful answers for a
runner with no plugin system: hasplugin() is False, getplugin() is
None, register() accepts and ignores). Anything not modeled FAILS
LOUDLY: CompatibilityError (an AttributeError subclass, so hasattr/
getattr probes keep their pytest behavior) whose message carries a
concrete recommendation for the ctrlrunner way to achieve the same
goal -- curated per-attribute text in ATTRIBUTE_RECOMMENDATIONS, generic
docs pointer otherwise. Dunder lookups raise plain AttributeError so
pickle/copy protocol probes behave normally.

bind_hook_args() is the pluggy-style caller both cli.py and worker.py
use: hooks receive exactly the NAMED subset of the hookspec's arguments
they declare (`def ctrlrunner_collection_modifyitems(items)` legally
skips session/config, same as pytest), and an unknown parameter name
fails loudly with the available names listed.
"""

import enum
import inspect
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

_MISSING = object()


class ExitCode(enum.IntEnum):
    """ctrlrunner's real exit codes -- pytest's ExitCode enum has 6
    members (OK/TESTS_FAILED/INTERRUPTED/INTERNAL_ERROR/USAGE_ERROR/
    NO_TESTS_COLLECTED=5); ctrlrunner has 3, and NO_TESTS_COLLECTED is
    4, not 5 -- a real behavioral difference, not a naming one, so
    don't assume numeric equality with pytest's enum when porting code
    that branches on the raw int."""

    OK = 0
    TESTS_FAILED = 1
    NO_TESTS_COLLECTED = 4


class ExceptionInfo:
    """The live-exception half of CallInfo.excinfo -- pytest's
    ExceptionInfo's most-used surface: .type/.value/.tb, .typename,
    .exconly() (short "Type: message" form)."""

    def __init__(self, exc: BaseException):
        self.value = exc
        self.type = type(exc)
        self.tb = exc.__traceback__
        self.typename = type(exc).__name__

    def exconly(self, tryshort: bool = False) -> str:
        return f"{self.typename}: {self.value}"

    def __str__(self) -> str:
        return self.exconly()

    def __repr__(self) -> str:
        return f"<ExceptionInfo {self.exconly()}>"


def bind_hook_args(hook, available: dict) -> dict:
    """pluggy-style call-by-parameter-NAME: returns the kwargs for
    `hook(**bound)` -- exactly the named subset of `available` the hook
    declares, so `def ctrlrunner_collection_modifyitems(items)` legally
    skips the leading session/config parameters just like it does in
    pytest. A declared name the hookspec doesn't provide fails loudly
    (pluggy errors on unknown parameters too), as does `*args` (pluggy
    requires named parameters)."""
    try:
        params = list(inspect.signature(hook).parameters.values())
    except (TypeError, ValueError):
        return dict(available)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return dict(available)
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
        raise CompatibilityError(
            f"{getattr(hook, '__name__', hook)}: hooks must declare named "
            f"parameters, not *args -- available: {', '.join(available)}"
        )
    bound = {}
    for p in params:
        if p.name in available:
            bound[p.name] = available[p.name]
        elif p.default is inspect.Parameter.empty:
            raise CompatibilityError(
                f"{getattr(hook, '__name__', hook)}: unknown hook parameter "
                f"{p.name!r} -- this hook receives: {', '.join(available)} "
                f"(hooks bind arguments by parameter name, exactly like pytest)"
            )
    return bound


class CompatibilityError(AttributeError):
    """A migrated hook touched something ctrlrunner doesn't model. The
    message always carries a concrete recommendation for achieving the
    same goal the ctrlrunner way -- fail loudly and helpfully, never
    silently misbehave. Subclasses AttributeError so hasattr()/getattr()
    probes in migrated bodies keep their pytest behavior."""


# Curated recommendations for pytest-only attributes a migrated hook is
# likely to touch, keyed by "<ShimClass>.<attribute>". Everything NOT in
# this table gets a generic CompatibilityError pointing at docs/hooks.md.
ATTRIBUTE_RECOMMENDATIONS = {
    "Item.parent": (
        "pytest's collection tree -- ctrlrunner has no collection tree. Use "
        "item.module (the module object), item.cls (the test class), or "
        "item.nodeid instead."
    ),
    "Item.listchain": (
        "pytest's collection-tree ancestry -- ctrlrunner has no collection "
        "tree. Derive grouping from item.nodeid / item.module / item.cls."
    ),
    "Item.instance": (
        "pytest's bound test-class instance -- ctrlrunner calls @test_class "
        "methods without a persistent instance. Keep shared state in "
        "class-level attributes (read via item.cls) or fixtures."
    ),
    "Item.callspec": (
        "only present on parametrized tests -- this item isn't parametrized. "
        "Guard with hasattr(item, 'callspec') first, exactly like pytest."
    ),
    "Config.hook": (
        "calling hooks from hooks is pytest plugin-manager machinery -- "
        "ctrlrunner hooks are plain functions; call your helper directly."
    ),
    "FixtureRequest.node": (
        "the requesting Item isn't threaded through the fixture resolver -- "
        "use request.fixturename/.scope, or read state from the fixture's "
        "own closure/module instead."
    ),
    "Session.perform_collect": (
        "collection is the runner's job in ctrlrunner -- tests are already "
        "collected when hooks run; read session.items instead."
    ),
    "TestReport.result": (
        "CollectReport.result is collection-phase machinery -- for test "
        "outcomes read report.outcome / report.passed / report.failed."
    ),
}


# The conftest hook names ctrlrunner dispatches today.
SUPPORTED_HOOKS = frozenset(
    {
        "ctrlrunner_addoption",
        "ctrlrunner_configure",
        "ctrlrunner_sessionstart",
        "ctrlrunner_sessionfinish",
        "ctrlrunner_unconfigure",
        "ctrlrunner_report_header",
        "ctrlrunner_terminal_summary",
        "ctrlrunner_ignore_collect",
        "ctrlrunner_itemcollected",
        "ctrlrunner_collection_modifyitems",
        "ctrlrunner_collection_finish",
        "ctrlrunner_deselected",
        "ctrlrunner_runtest_logstart",
        "ctrlrunner_runtest_setup",
        "ctrlrunner_runtest_call",
        "ctrlrunner_runtest_makereport",
        "ctrlrunner_exception_interact",
        "ctrlrunner_runtest_teardown",
        "ctrlrunner_runtest_logreport",
        "ctrlrunner_runtest_logfinish",
        "ctrlrunner_warning_recorded",
        "ctrlrunner_assertrepr_compare",
        "ctrlrunner_report_teststatus",
        "ctrlrunner_make_parametrize_id",
        "ctrlrunner_fixture_setup",
        "ctrlrunner_fixture_post_finalizer",
        "ctrlrunner_generate_tests",
    }
)

# pytest hooks with a ctrlrunner equivalent under the renamed name --
# the single source of truth the migrate tool and the startup unknown-
# hook detector both read.
PYTEST_HOOK_EQUIVALENTS = {
    "pytest_addoption": "ctrlrunner_addoption",
    "pytest_configure": "ctrlrunner_configure",
    "pytest_sessionstart": "ctrlrunner_sessionstart",
    "pytest_sessionfinish": "ctrlrunner_sessionfinish",
    "pytest_unconfigure": "ctrlrunner_unconfigure",
    "pytest_report_header": "ctrlrunner_report_header",
    "pytest_terminal_summary": "ctrlrunner_terminal_summary",
    "pytest_ignore_collect": "ctrlrunner_ignore_collect",
    "pytest_itemcollected": "ctrlrunner_itemcollected",
    "pytest_collection_modifyitems": "ctrlrunner_collection_modifyitems",
    "pytest_collection_finish": "ctrlrunner_collection_finish",
    "pytest_deselected": "ctrlrunner_deselected",
    "pytest_runtest_logstart": "ctrlrunner_runtest_logstart",
    "pytest_runtest_setup": "ctrlrunner_runtest_setup",
    "pytest_runtest_call": "ctrlrunner_runtest_call",
    "pytest_runtest_makereport": "ctrlrunner_runtest_makereport",
    "pytest_exception_interact": "ctrlrunner_exception_interact",
    "pytest_runtest_teardown": "ctrlrunner_runtest_teardown",
    "pytest_runtest_logreport": "ctrlrunner_runtest_logreport",
    "pytest_runtest_logfinish": "ctrlrunner_runtest_logfinish",
    "pytest_warning_recorded": "ctrlrunner_warning_recorded",
    "pytest_assertrepr_compare": "ctrlrunner_assertrepr_compare",
    "pytest_report_teststatus": "ctrlrunner_report_teststatus",
    "pytest_make_parametrize_id": "ctrlrunner_make_parametrize_id",
    "pytest_fixture_setup": "ctrlrunner_fixture_setup",
    "pytest_fixture_post_finalizer": "ctrlrunner_fixture_post_finalizer",
    "pytest_generate_tests": "ctrlrunner_generate_tests",
}

# Recommendations for pytest hooks WITHOUT a ctrlrunner equivalent --
# used by the startup unknown-hook detector and the migrate tool's TODO
# messages. Keyed by pytest name.
HOOK_RECOMMENDATIONS = {
    # --- refused: no analogue by architecture
    "pytest_cmdline_preparse": (
        "bootstrapping hooks never fired for conftest.py even in pytest -- "
        "wrap the CLI with a driver script calling python -m ctrlrunner."
    ),
    "pytest_cmdline_parse": (
        "bootstrapping hooks never fired for conftest.py even in pytest -- "
        "wrap the CLI with a driver script calling python -m ctrlrunner."
    ),
    "pytest_cmdline_main": (
        "bootstrapping hooks never fired for conftest.py even in pytest -- "
        "wrap the CLI with a driver script calling python -m ctrlrunner."
    ),
    "pytest_load_initial_conftests": (
        "bootstrapping hooks never fired for conftest.py even in pytest -- "
        "wrap the CLI with a driver script calling python -m ctrlrunner."
    ),
    "pytest_addhooks": (
        "ctrlrunner has no plugin manager to extend -- cross-cutting behavior "
        "lives in conftest hooks and custom --reporter classes."
    ),
    "pytest_plugin_registered": ("ctrlrunner has no plugin manager -- nothing is ever registered."),
    "pytest_collection": (
        "replacing the collection loop is the runner's job -- read "
        "session.items in ctrlrunner_sessionfinish, or drive Orchestrator "
        "from Python for full control."
    ),
    "pytest_runtestloop": (
        "replacing the run loop is the runner's job -- retries are built in "
        "(@test(retries=N)); scheduling via [ctrlrunner.workers]/--order."
    ),
    "pytest_runtest_protocol": (
        "replacing the per-test protocol is the runner's job -- retries are "
        "built in (@test(retries=N)); use the ctrlrunner_runtest_* hooks for "
        "per-phase behavior."
    ),
    "pytest_collect_file": (
        "ctrlrunner collects test_*.py via @test registration only (no "
        "collector tree) -- for non-Python test sources, generate @test "
        "functions at conftest import time."
    ),
    "pytest_pycollect_makemodule": (
        "no collector tree -- ctrlrunner imports test modules directly."
    ),
    "pytest_pycollect_makeitem": (
        "no collector tree -- tests are declared with @test, not discovered from arbitrary objects."
    ),
    "pytest_collectstart": "no collector tree -- see docs/hooks.md.",
    "pytest_make_collect_report": "no collector tree -- see docs/hooks.md.",
    "pytest_collectreport": "no collector tree -- see docs/hooks.md.",
    "pytest_report_collectionfinish": (
        "no collector tree -- the collection summary line is fixed; extra "
        "run-header lines are planned via ctrlrunner_report_header (Phase 1)."
    ),
    "pytest_report_to_serializable": (
        "xdist wire-format internals -- consume results via the JSON report or an EventSubscriber."
    ),
    "pytest_report_from_serializable": (
        "xdist wire-format internals -- consume results via the JSON report or an EventSubscriber."
    ),
    "pytest_markeval_namespace": (
        "ctrlrunner's skip()/fail() take real Python booleans, not string "
        "conditions -- evaluate the expression directly at the call site."
    ),
    "pytest_assertion_pass": (
        "not supported (pytest itself gates it behind an off-by-default ini) "
        "-- use step() blocks for pass-path tracing."
    ),
    "pytest_enter_pdb": (
        "no pdb integration (tests run in worker processes) -- debug with "
        "--num-workers 1 and breakpoint() in the test body."
    ),
    "pytest_leave_pdb": (
        "no pdb integration (tests run in worker processes) -- debug with "
        "--num-workers 1 and breakpoint() in the test body."
    ),
    "pytest_internalerror": (
        "runner-internal failure handling is not hookable -- observe run "
        "termination via ctrlrunner_sessionfinish or an EventSubscriber."
    ),
    "pytest_keyboard_interrupt": (
        "runner-internal failure handling is not hookable -- observe run "
        "termination via ctrlrunner_sessionfinish or an EventSubscriber."
    ),
}


def hook_name_recommendation(name: str) -> str:
    """The startup-abort / migrate-TODO guidance for a conftest function
    named like a hook ctrlrunner doesn't dispatch."""
    equivalent = PYTEST_HOOK_EQUIVALENTS.get(name)
    if equivalent is not None:
        return (
            f"supported after rename to {equivalent} -- "
            f"run `python -m ctrlrunner.migrate` (it converts this automatically)."
        )
    recommendation = HOOK_RECOMMENDATIONS.get(name)
    if recommendation is not None:
        return recommendation
    if name.startswith("ctrlrunner_"):
        supported = ", ".join(sorted(SUPPORTED_HOOKS))
        return f"not a ctrlrunner hook (typo?) -- supported hooks are: {supported}."
    return "no ctrlrunner equivalent -- see docs/hooks.md and docs/pytest-hooks-parity-plan.md."


class _CompatAttrs:
    """Mixin: unknown (non-underscore) attributes raise
    CompatibilityError with a recommendation -- curated per-attribute
    text where we know the pytest feature, generic guidance otherwise.
    Dunder lookups raise plain AttributeError so pickle/copy protocol
    probes behave normally."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        key = f"{type(self).__name__}.{name}"
        recommendation = ATTRIBUTE_RECOMMENDATIONS.get(key)
        if recommendation is None:
            recommendation = (
                "not modeled by ctrlrunner's pytest-compat layer. See "
                "docs/hooks.md#compatibility-limits for what each hook object "
                "carries, and docs/pytest-hooks-parity-plan.md for what's "
                "planned."
            )
        raise CompatibilityError(f"{key}: {recommendation}")


@dataclass(frozen=True)
class Marker(_CompatAttrs):
    """What Item.get_closest_marker returns -- pytest.Mark's shape.
    ctrlrunner tags are bare names, so args/kwargs are always empty;
    they exist so `marker.args` in a migrated body doesn't crash."""

    name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _CallSpec:
    """item.callspec -- pytest's per-parametrize-combination object.
    Only ever attached to a parametrized Item (see Item.__init__)."""

    params: dict
    id: str | None


@dataclass(frozen=True)
class _InvocationParams:
    """config.invocation_params -- pytest's raw-argv snapshot."""

    args: list
    dir: Path


class CallInfo(_CompatAttrs):
    """The object for ctrlrunner_runtest_makereport's `call` argument --
    pytest CallInfo's most-used surface. `excinfo` is None when the
    phase passed (pytest's own convention) or a real ExceptionInfo
    carrying the LIVE exception object when it raised -- not a string,
    so a hookwrapper-style consumer can re-raise, inspect .value's
    attributes, or build a custom report exactly as it would in pytest."""

    def __init__(
        self,
        when: str,
        excinfo: ExceptionInfo | None,
        start: float = 0.0,
        stop: float = 0.0,
        duration: float = 0.0,
    ):
        self.when = when
        self.excinfo = excinfo
        self.start = start
        self.stop = stop
        self.duration = duration

    @property
    def result(self):
        if self.excinfo is not None:
            raise self.excinfo.value
        return None


class _OptionNamespace:
    """config.option -- pytest's parsed-args namespace, answered from
    the ctrlrunner_addoption options store first, then the raw toml
    dict. Unknown names silently read as None (pytest would raise; the
    compat layer's contract is to never crash -- or warn from -- a hook)."""

    def __init__(self, raw: dict):
        self._raw = raw

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        from .options import get_option

        value = get_option(name, _MISSING)
        if value is not _MISSING:
            return value
        return self._raw.get(name)


class _PluginManager:
    """config.pluginmanager -- real, truthful answers for a runner with
    no plugin system: nothing is ever registered, so hasplugin() is
    False, getplugin() is None, and register() accepts and ignores.
    These are correct statements about ctrlrunner, not placeholders."""

    def hasplugin(self, name: str) -> bool:
        return False

    has_plugin = hasplugin

    def getplugin(self, name: str):
        return None

    get_plugin = getplugin

    def list_name_plugin(self) -> list:
        return []

    def register(self, plugin, name=None):
        return None

    def unregister(self, plugin=None, name=None):
        return None

    def import_plugin(self, modname: str):
        return None


class _Cache:
    """config.cache -- pytest's Cache API, implemented for real: a
    JSON-backed store under <rootpath>/.ctrlrunner_cache/ (values under
    v/, directories under d/, exactly pytest's layout convention).
    Cross-run persistent, like pytest's .pytest_cache."""

    def __init__(self, rootpath: Path):
        self._root = rootpath / ".ctrlrunner_cache"

    def _value_path(self, key: str) -> Path:
        return self._root / "v" / Path(key)

    def get(self, key: str, default=None):
        import json

        try:
            return json.loads(self._value_path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def set(self, key: str, value) -> None:
        import json

        path = self._value_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        except (OSError, TypeError):
            pass  # an unwritable/unserializable cache must never break a hook

    def mkdir(self, name: str) -> Path:
        path = self._root / "d" / name
        path.mkdir(parents=True, exist_ok=True)
        return path


class Item(_CompatAttrs):
    """The per-test object for ctrlrunner_runtest_setup/teardown --
    pytest Item's commonly-used surface, built from the ctrlrunner
    test's own metadata (id, tags, properties, function object)."""

    def __init__(
        self,
        test_id: str,
        attempt: int,
        tags=(),
        properties=None,
        func=None,
        cls_name: str | None = None,
        config: "Config | None" = None,
        session: "Session | None" = None,
        param_values: dict | None = None,
        param_id: str | None = None,
    ):
        self.nodeid = test_id
        self.test_id = test_id  # ctrlrunner-native alias
        self.attempt = attempt
        self.name = test_id.split("::")[-1]
        self.tags: set[str] = set(tags)
        self.properties = dict(properties or {})
        self.funcargs: dict = {}  # populated by the worker after fixture resolve
        self.config = config if config is not None else Config({})
        self.session = session if session is not None else Session(config=self.config)
        self.stash: dict = {}
        self._func = func
        self._cls_name = cls_name
        self._report_sections: list = []
        # item.callspec exists ONLY for parametrized tests in pytest --
        # accessing it on a plain test raises. Matched here by simply
        # not setting the attribute at all when there's nothing to
        # report; _CompatAttrs.__getattr__ then raises CompatibilityError
        # with a hasattr()-guard recommendation, same as real pytest's
        # own AttributeError.
        if param_values:
            self.callspec = _CallSpec(dict(param_values), param_id)

    def add_report_section(self, when: str, key: str, content: str) -> None:
        """pytest's item.add_report_section -- attaches extra captured
        output to this attempt's eventual TestReport.sections, titled
        exactly like pytest's own ("Captured {key} {when}")."""
        self._report_sections.append((when, key, content))

    def get_closest_marker(self, name: str, default=None):
        """pytest's marker lookup, answered from the test's tags --
        `@test(tags={"mac_only"})` is ctrlrunner's `@pytest.mark.mac_only`."""
        if name in self.tags:
            return Marker(name)
        return default

    def iter_markers(self, name: str | None = None):
        for tag in sorted(self.tags):
            if name is None or tag == name:
                yield Marker(tag)

    @property
    def own_markers(self) -> list:
        return [Marker(tag) for tag in sorted(self.tags)]

    def add_marker(self, marker, append: bool = True) -> None:
        """Adds a tag at runtime -- visible to later get_closest_marker/
        iter_markers calls in this attempt's hooks. Selection already
        happened, so this never changes which tests run."""
        name = getattr(marker, "name", None)
        if name is None:
            name = marker if isinstance(marker, str) else str(marker)
        self.tags.add(name)

    @property
    def keywords(self) -> dict:
        return {self.name: True, **{tag: True for tag in self.tags}}

    @property
    def originalname(self) -> str:
        return self.name.split("[")[0]

    @property
    def user_properties(self) -> list:
        return list(self.properties.items())

    @property
    def module(self):
        return inspect.getmodule(self._func) if self._func is not None else None

    @property
    def cls(self):
        """The @test_class class object, resolved by name from the
        test's own module -- None for plain function tests."""
        if not self._cls_name:
            return None
        module = self.module
        return getattr(module, self._cls_name, None) if module is not None else None

    @property
    def path(self) -> Path | None:
        code = getattr(self._func, "__code__", None)
        return Path(code.co_filename) if code is not None else None

    @property
    def fspath(self) -> Path | None:
        return self.path

    @property
    def location(self) -> tuple:
        """(filename, lineno, testname) -- pytest's item.location."""
        code = getattr(self._func, "__code__", None)
        if code is None:
            return (None, None, self.name)
        return (code.co_filename, code.co_firstlineno, self.name)


class TestReport(_CompatAttrs):
    """The object for ctrlrunner_runtest_logreport -- pytest TestReport's
    commonly-used surface. `outcome` carries pytest's three-value
    vocabulary (passed/failed/skipped) so migrated
    `report.outcome == "failed"` checks keep working; the richer
    ctrlrunner outcome (fixme, expected_failure, ...) is preserved as
    `ctrlrunner_outcome`."""

    def __init__(
        self,
        test_id: str,
        attempt: int,
        outcome: str,
        error: str | None,
        duration: float = 0.0,
        location: tuple | None = None,
        sections: list | None = None,
        user_properties: list | None = None,
        keywords: dict | None = None,
    ):
        self.nodeid = test_id
        self.test_id = test_id  # ctrlrunner-native alias
        self.attempt = attempt
        self.when = "call"  # one report per attempt, not per phase
        self.ctrlrunner_outcome = outcome
        self.outcome = "skipped" if outcome in ("skipped", "fixme", "expected_failure") else outcome
        self.longrepr = error
        self.duration = duration
        self.location = location if location is not None else (None, None, test_id.split("::")[-1])
        self.sections = list(sections or [])
        self.user_properties = list(user_properties or [])
        self.keywords = dict(keywords or {})
        # pytest sets wasxfail (the reason string) on xfail reports.
        self.wasxfail = (error or "") if outcome == "expected_failure" else None

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"

    @property
    def skipped(self) -> bool:
        return self.outcome == "skipped"

    @property
    def longreprtext(self) -> str:
        return str(self.longrepr) if self.longrepr else ""

    @property
    def head_line(self) -> str:
        return self.nodeid

    def _section_text(self, needle: str) -> str:
        return "".join(text for title, text in self.sections if needle in title)

    @property
    def capstdout(self) -> str:
        return self._section_text("stdout")

    @property
    def capstderr(self) -> str:
        return self._section_text("stderr")

    @property
    def caplog(self) -> str:
        return self._section_text("log")


class FixtureDef(_CompatAttrs):
    """The object for ctrlrunner_fixture_setup/post_finalizer's
    `fixturedef` argument -- pytest FixtureDef's most-used surface.
    `cached_result` is only set for post_finalizer (the value that was
    just torn down); setup fires before the value exists."""

    def __init__(self, argname: str, scope: str, cached_result=None):
        self.argname = argname
        self.scope = scope
        self.cached_result = cached_result


class FixtureRequest(_CompatAttrs):
    """The object for ctrlrunner_fixture_setup/post_finalizer's
    `request` argument. `.node` (the requesting Item) isn't threaded
    through di.py's resolver today -- accessing it raises
    CompatibilityError rather than returning something misleading."""

    def __init__(self, fixturename: str, scope: str, config: "Config | None"):
        self.fixturename = fixturename
        self.scope = scope
        self.config = config


class Session(_CompatAttrs):
    """The object for ctrlrunner_sessionfinish (full, with results) and
    for item.session inside workers (results not final yet -- counts
    default to what the worker knows)."""

    def __init__(
        self,
        results: list | None = None,
        duration: float = 0.0,
        exitstatus: int = 0,
        config: "Config | None" = None,
        testscollected: int | None = None,
    ):
        self.results = results if results is not None else []
        self.items = self.results  # pytest's session.items, closest match
        self.duration = duration
        self.exitstatus = exitstatus
        self.config = config if config is not None else Config({})
        self.testscollected = testscollected if testscollected is not None else len(self.results)
        self.testsfailed = sum(1 for r in self.results if getattr(r, "outcome", None) == "failed")
        self.startpath = Path.cwd()
        # Real and settable: a per-test hook (logreport/teardown/...)
        # doing `item.session.shouldstop = "reason"` is picked up by
        # the worker after the current attempt and forwarded to the
        # orchestrator, which cancels the run via the same cancel_event
        # path --fail-fast/[ctrlrunner.fail_policy] already use (see
        # worker.py's per-attempt check and
        # Orchestrator._trigger_policy_cancel). shouldfail behaves the
        # same way -- ctrlrunner has no setup/call/teardown phase split
        # to distinguish "stop, current test's later phases still run"
        # (shouldstop) from "stop immediately" (shouldfail).
        self.shouldstop: bool | str = False
        self.shouldfail: bool | str = False


class Metafunc(_CompatAttrs):
    """The object for ctrlrunner_generate_tests -- pytest Metafunc's
    most-used surface. `.parametrize(...)` calls are buffered (`_calls`)
    and applied by registry.py's test() decorator after every
    ctrlrunner_generate_tests hook has run, by feeding each one through
    the exact same parametrize() machinery a static @parametrize
    decorator uses -- not a reimplementation, the real thing."""

    def __init__(self, function, fixturenames, config, cls=None, module=None):
        self.function = function
        self.fixturenames = list(fixturenames)
        self.config = config
        self.cls = cls
        self.module = module
        self.definition = function  # pytest's FunctionDefinition -- function is close enough here
        self._calls: list = []

    def parametrize(self, argnames, argvalues, indirect=False, ids=None, scope=None):
        self._calls.append((argnames, list(argvalues), indirect, list(ids) if ids else None))


class TerminalReporter(_CompatAttrs):
    """The object for ctrlrunner_terminal_summary -- pytest
    TerminalReporter's most-used surface: section()/write_sep()/
    write_line()/write() plus .stats (outcome -> list of Results)."""

    _WIDTH = 80

    def __init__(self, stats: dict | None = None, stream=None):
        self._stream = stream if stream is not None else sys.stdout
        self.stats = dict(stats or {})

    def write(self, text: str, **markup) -> None:
        print(text, end="", file=self._stream)

    def write_line(self, line: str = "", **markup) -> None:
        print(line, file=self._stream)

    line = write_line

    def write_sep(self, sep: str = "-", title: str | None = None, **markup) -> None:
        if title:
            pad = max(2, self._WIDTH - len(title) - 2)
            half = pad // 2
            print(f"{sep * half} {title} {sep * (pad - half)}", file=self._stream)
        else:
            print(sep * self._WIDTH, file=self._stream)

    def section(self, title: str, sep: str = "=", **markup) -> None:
        self.write_sep(sep, title)

    def ensure_newline(self) -> None:
        pass


class Config(_CompatAttrs, Mapping):
    """The object for ctrlrunner_configure (and item.config /
    session.config) -- a read-only Mapping over the raw ctrlrunner.toml
    dict, plus pytest Config's getoption()/getini()/option/rootpath.
    getoption() is answered from the ctrlrunner_addoption options store
    (seeded before any hook runs); getini() from the toml dict.
    addinivalue_line() has no ctrlrunner meaning -- it warns and no-ops
    rather than crashing a migrated body."""

    def __init__(self, raw: dict | None, args: list | None = None):
        self._raw = dict(raw or {})
        self.args = list(args or [])
        self.rootpath = Path.cwd()
        self.rootdir = self.rootpath
        inipath = Path("ctrlrunner.toml")
        self.inipath = inipath.resolve() if inipath.exists() else None
        self.inifile = str(self.inipath) if self.inipath else None
        self.option = _OptionNamespace(self._raw)
        self.pluginmanager = _PluginManager()
        self.cache = _Cache(self.rootpath)
        self.stash: dict = {}
        self.invocation_params = _InvocationParams(list(self.args), self.rootpath)

    def __getitem__(self, key):
        return self._raw[key]

    def __iter__(self):
        return iter(self._raw)

    def __len__(self):
        return len(self._raw)

    def getoption(self, name: str, default=None):
        from .options import get_option

        return get_option(name, default)

    getvalue = getoption  # pytest's older alias

    def getini(self, name: str):
        return self._raw.get(name)

    def addinivalue_line(self, name: str, line: str) -> None:
        """pytest's marker/ini registration, mapped for real where it
        has a ctrlrunner meaning: addinivalue_line("markers",
        "slow: desc") registers the marker name as a tag in
        registered_tags -- IF the project uses a tag registry (the key
        exists in ctrlrunner.toml); a project without one accepts every
        tag anyway, so there is nothing to register. Other list-valued
        keys get the line appended; everything else is a silent no-op.
        Only effective from ctrlrunner_configure -- the tag registry is
        built after configure hooks run, exactly so this works."""
        if name == "markers":
            tags = self._raw.get("registered_tags")
            if isinstance(tags, list):
                marker_name = line.split(":", 1)[0].strip()
                if marker_name and marker_name not in tags:
                    tags.append(marker_name)
            return
        existing = self._raw.get(name)
        if isinstance(existing, list):
            existing.append(line)


def hookimpl(func=None, *, tryfirst=False, trylast=False, hookwrapper=False, optionalhook=False):
    """pytest/pluggy's @pytest.hookimpl -- usable as `@hookimpl` or
    `@hookimpl(tryfirst=True)` etc. ctrlrunner hooks are matched by
    conftest function NAME, never registered with a plugin manager, so
    this decorator carries no registration side effect -- it only
    stamps ordering/wrapper flags onto the function for sort_hooks()/
    run_makereport_hook() to read. `optionalhook` is accepted for
    signature compatibility with migrated bodies but has no effect
    (ctrlrunner never errors on an unrecognized hook NAME the way
    pytest's hookspec validation does -- see the fail-loudly unknown-
    hook check in config/addoption.py instead)."""

    def decorate(fn):
        fn._ctrlrunner_hookimpl = {
            "tryfirst": tryfirst,
            "trylast": trylast,
            "hookwrapper": hookwrapper,
            "optionalhook": optionalhook,
        }
        return fn

    return decorate(func) if func is not None else decorate


def _hookimpl_flags(hook) -> dict:
    return getattr(hook, "_ctrlrunner_hookimpl", None) or {}


def is_hookwrapper(hook) -> bool:
    return bool(_hookimpl_flags(hook).get("hookwrapper"))


def sort_hooks(hooks: list) -> list:
    """Stable-sorts by @hookimpl ordering hint: every tryfirst hook
    before every plain hook before every trylast hook, relative
    discovery order preserved within each group (Python's sort is
    stable, so a single sort by group-rank alone is enough)."""

    def rank(hook):
        flags = _hookimpl_flags(hook)
        if flags.get("tryfirst"):
            return 0
        if flags.get("trylast"):
            return 2
        return 1

    return sorted(hooks, key=rank)


class _HookCallOutcome:
    """pluggy's yield-protocol outcome object, handed to a hookwrapper
    generator's `outcome = yield` -- get_result() returns the current
    value (or re-raises a captured exception), force_result(value)
    overrides it for whichever hook/caller consults the outcome next."""

    def __init__(self, result=None, excinfo: BaseException | None = None):
        self._result = result
        self._excinfo = excinfo

    def get_result(self):
        if self._excinfo is not None:
            raise self._excinfo
        return self._result

    def force_result(self, result) -> None:
        self._result = result
        self._excinfo = None


def run_makereport_hook(hook, available: dict, current_result):
    """Calls one ctrlrunner_runtest_makereport hook, honoring
    hookwrapper=True: a wrapper is a generator with one `yield`; it
    receives an _HookCallOutcome seeded with `current_result` (the
    report so far) at the yield point, and may call
    outcome.force_result(...) before finishing to change it. A plain
    (non-wrapper) hook is just called and its return value used as-is
    (None means "no opinion, keep current_result" -- worker.py already
    treats a None return that way)."""
    if not is_hookwrapper(hook):
        return hook(**bind_hook_args(hook, available))
    gen = hook(**bind_hook_args(hook, available))
    next(gen)  # advance to the `outcome = yield` point
    outcome = _HookCallOutcome(current_result)
    try:
        gen.send(outcome)
    except StopIteration:
        pass
    else:
        # A wrapper must have exactly one yield -- pluggy raises on a
        # second one too; keep the message actionable.
        raise CompatibilityError(
            f"{getattr(hook, '__name__', hook)}: hookwrapper generators must "
            f"yield exactly once (`outcome = yield`)."
        )
    return outcome.get_result()
