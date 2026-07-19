"""
Fixture dependency resolution. Fixtures are resolved recursively by
parameter name, exactly like pytest, but scope caching is explicit:

    - "function": fresh every test call, torn down at the end of that call.
    - "module": cached per test module, torn down when the worker moves
      on to a different module (or finishes).
    - "session": cached for the whole worker process, torn down when the
      worker finishes its assigned batch.

There is no cross-process session -- each worker owns its own
session-scoped fixtures (e.g. one browser instance per worker, reused
across the tests assigned to it).
"""

import contextlib
import inspect
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from . import hookcompat
from .registry import get_fixtures
from .steps import step

# ctrlrunner_fixture_setup/ctrlrunner_fixture_post_finalizer -- set once
# per worker by worker.py's conftest discovery pass (same per-process-
# global convention as worker.py's own _hook_config/_hook_session).
_fixture_setup_hooks: list = []
_fixture_post_finalizer_hooks: list = []
_fixture_hook_config = None


def set_fixture_hooks(setup_hooks, post_finalizer_hooks, config) -> None:
    global _fixture_setup_hooks, _fixture_post_finalizer_hooks, _fixture_hook_config
    _fixture_setup_hooks = list(setup_hooks)
    _fixture_post_finalizer_hooks = list(post_finalizer_hooks)
    _fixture_hook_config = config


def _call_fixture_hooks(hooks, name: str, scope: str, cached_result=None) -> None:
    if not hooks:
        return
    fixturedef = hookcompat.FixtureDef(name, scope, cached_result=cached_result)
    request = hookcompat.FixtureRequest(name, scope, _fixture_hook_config)
    available = {"fixturedef": fixturedef, "request": request}
    # a broken fixture hook must never affect fixture resolution itself
    for hook in hookcompat.sort_hooks(hooks):
        with contextlib.suppress(Exception):
            hook(**hookcompat.bind_hook_args(hook, available))


@dataclass
class FixtureRequest:
    """Passed to fixtures that declare a `request` parameter, so a
    parametrized fixture (params=[...]) can read the value selected for
    the current test via request.param -- mirrors pytest's request.param."""

    param: Any = None


class FixtureResolver:
    def __init__(self):
        self._session_cache = {}
        self._session_stack = ExitStack()
        self._module_cache = {}
        self._module_stack = ExitStack()
        self._current_module = None
        # (fixture name, formatted traceback) per failed
        # teardown since the last drain -- stack.close() itself never
        # raises, but these no longer vanish: the worker drains after
        # each test (function scope) and after close_session()
        # (module/session scope) and surfaces them.
        self.teardown_errors: list[tuple[str, str]] = []

    def begin_module(self, module_name: str):
        """Call before running each test. Tears down module-scoped
        fixtures when the worker moves from one test module to another."""
        if module_name == self._current_module:
            return
        self._module_stack.close()
        self._module_stack = ExitStack()
        self._module_cache = {}
        self._current_module = module_name

    def resolve(self, names, function_stack: ExitStack, fixture_param_overrides=None):
        """Returns (values, resolved_all).

        `values` has one entry per name in `names` (in order requested).
        `resolved_all` includes every fixture resolved for this call,
        including transitive dependencies -- the worker uses it to look
        up on_failure capture callbacks when a test fails.
        """
        fixtures = get_fixtures()
        overrides = fixture_param_overrides or {}
        resolved_all = {}
        values = {
            name: self._resolve_one(name, fixtures, function_stack, resolved_all, overrides)
            for name in names
        }
        return values, resolved_all

    def _resolve_one(self, name, fixtures, function_stack, resolved_all, overrides):
        # Function-scope cache: `resolved_all` is shared across the whole
        # resolve() call (direct names plus every transitive dependency),
        # so checking it first here is what makes a diamond dependency
        # (e.g. test_x(page, context) where page itself depends on
        # context) build 'context' exactly once and share that single
        # instance everywhere it's needed in this call -- matching the
        # documented "function: fresh every test call" contract (one
        # instance per *call*, not one per edge in the dependency graph).
        if name in resolved_all:
            return resolved_all[name]

        if name not in fixtures:
            raise ValueError(f"Unknown fixture: '{name}'")
        fx = fixtures[name]

        has_override = name in overrides
        if fx.param_values is not None and not has_override:
            # The overwhelmingly likely cause is import order --
            # @test's decorator runs `_collect_parametrized_fixtures`
            # against whatever is in the fixture registry AT THAT
            # MOMENT. If '{name}' is @fixture(params=[...]) but
            # defined further down the module (or in a conftest
            # imported later) than the test that uses it, the
            # fixture didn't exist yet when @test looked it up, so
            # the test was registered as if it were unparametrized
            # -- no override was ever recorded for it. By the time
            # this resolve() call runs, '{name}' exists and IS
            # parametrized, so this "no value selected" branch
            # trips. Name the fixture and the fix explicitly rather
            # than blaming DI internals.
            raise ValueError(
                f"Fixture '{name}' is parametrized (params=[...]) but no value was "
                f"selected for this test run. This almost always means '{name}' is "
                f"defined AFTER the test that uses it (directly or transitively) in "
                f"module import order -- @test discovers fixture parametrization by "
                f"looking at the fixture registry at decoration time, so a fixture "
                f"defined later is invisible to it. Move the @fixture(params=[...]) "
                f"definition for '{name}' above (earlier in the module than) any test "
                f"that depends on it, then re-run."
            )
        chosen_value = overrides[name] if has_override else None
        if has_override and not fx.wants_request:
            # Registration-time validation in @test already rejects this
            # for @parametrize(..., indirect=...); this backstop protects
            # hand-built TestItems (tests/tools constructing items
            # directly) from a silently-ignored override.
            raise ValueError(
                f"Fixture '{name}' received an indirect parametrize value but its "
                f"function signature has no 'request' parameter -- add `request` "
                f"and read request.param."
            )

        # An override without static params= (indirect parametrize) is
        # parametrized too: the cache key must carry the value so two
        # tests giving a module/session fixture different values get
        # distinct instances.
        is_parametrized = fx.param_values is not None or has_override
        cache_key = f"{name}::{chosen_value!r}" if is_parametrized else name

        if fx.scope == "session" and cache_key in self._session_cache:
            value = self._session_cache[cache_key]
            resolved_all[name] = value
            return value
        if fx.scope == "module" and cache_key in self._module_cache:
            value = self._module_cache[cache_key]
            resolved_all[name] = value
            return value

        dep_values = {
            p: self._resolve_one(p, fixtures, function_stack, resolved_all, overrides)
            for p in fx.params
        }
        if fx.wants_request:
            dep_values["request"] = FixtureRequest(param=chosen_value)

        # ctrlrunner_fixture_setup: notification just before the fixture
        # function runs (not firstresult/override, unlike pytest's own
        # default impl -- ctrlrunner's fixture body is always the real
        # setup code, a hook only observes).
        _call_fixture_hooks(_fixture_setup_hooks, name, fx.scope)
        # Fixture setup timing rides the same step tree `with step(...)` already
        # builds for test authors -- no new data model, no new report
        # shape, it just shows up as more (clearly-labeled) nodes in the
        # timeline that already exists.
        with step(f"fixture:{name}:setup"):
            result = fx.func(**dep_values)

        if inspect.isgenerator(result):
            value = next(result)
            if fx.scope == "session":
                stack = self._session_stack
            elif fx.scope == "module":
                stack = self._module_stack
            else:
                stack = function_stack
            stack.callback(self._finalize_generator, result, name)
        else:
            value = result

        if fx.scope == "session":
            self._session_cache[cache_key] = value
        elif fx.scope == "module":
            self._module_cache[cache_key] = value

        resolved_all[name] = value
        return value

    def _finalize_generator(self, gen, name):
        # StopIteration is the NORMAL way a generator fixture signals
        # "teardown complete" (no more yields) -- it must be handled
        # inside the step's own try/except, not left to propagate into
        # step()'s exception handling, which would otherwise record it
        # as a failed step (StopIteration is a plain Exception subclass).
        cached_result = self._session_cache.get(name, self._module_cache.get(name))
        with step(f"fixture:{name}:teardown") as s:
            try:
                next(gen)
            except StopIteration:
                pass
            except Exception as exc:
                # Never raises out of stack.close() (a teardown error
                # must not mask another fixture's teardown), but no
                # longer silently swallowed either: recorded
                # for the worker to surface on the owning test's result.
                s.error = f"{type(exc).__name__}: {exc}"
                self.teardown_errors.append((name, traceback.format_exc()))
        # ctrlrunner_fixture_post_finalizer: fires after teardown, cached
        # value (if this fixture was module/session-scoped and cached)
        # still reachable via fixturedef.cached_result -- function-scoped
        # fixtures were never cached, so this is None for those.
        fx = get_fixtures().get(name)
        _call_fixture_hooks(
            _fixture_post_finalizer_hooks, name, fx.scope if fx else "function", cached_result
        )

    def drain_teardown_errors(self) -> list[tuple[str, str]]:
        errors, self.teardown_errors = self.teardown_errors, []
        return errors

    def close_session(self):
        """Tears down module- and session-scoped fixtures. Call once when
        the worker has finished all tests in its batch."""
        self._module_stack.close()
        self._session_stack.close()
