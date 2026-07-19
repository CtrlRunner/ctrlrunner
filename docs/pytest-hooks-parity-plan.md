# Pytest hook-parity plan

**Status**: All four phases are DONE. Phase 0 (fail-loudly policy), Phase 1
(main-process/collection hooks), Phase 2 (call-phase depth:
makereport/exception_interact/runtest_call/logfinish +
stash/invocation_params/callspec/add_report_section/ExitCode), and Phase 3
(generate_tests/Metafunc, fixture hooks, warning_recorded, assertrepr_compare,
report_teststatus, make_parametrize_id, settable shouldstop/shouldfail,
hookimpl tryfirst/trylast ordering, hookwrapper for makereport) are all
implemented and tested. ctrlrunner now dispatches 27 hooks total (7
pre-existing + 13 Phase 1–2 + 7 Phase 3). Conftest ordering was left
shallowest-first (see Part 3 item 3).

**Goal**: migrated pytest projects keep their conftest.py plugin/hook code
working. For every one of pytest 7.1's 52 hooks and every commonly-used
hook-object attribute, ctrlrunner must do exactly one of three things:

1. **IMPLEMENT** — a real, behaviorally-equivalent hook/attribute.
2. **MAP** — an existing ctrlrunner feature with the same behavior under a
   different name; the migrate tool converts to it (or the docs state the
   1-line change).
3. **REFUSE LOUDLY** — no analogue exists or can exist under ctrlrunner's
   architecture: raise a clear error **with a concrete recommendation** for
   how to achieve the same goal the ctrlrunner way. Never a silent
   placeholder, never a silent no-op.

Audit inputs: the full pytest 7.1.x hook reference (52 hooks, pluggy
semantics, object types) and a file-level map of every ctrlrunner extension
seam. Firing-point references below come from that audit.

---

## Part 1 — Policy reversal: fail loudly (Phase 0, do first)

The current `_CompatNull` silent-placeholder fallback in
`src/ctrlrunner/core/hookcompat.py` is **removed** and replaced with:

### 1a. `CompatibilityError` for unmodeled attributes

`_CompatAttrs.__getattr__` raises `CompatibilityError(AttributeError)` whose
message comes from a curated recommendations table:

```
item.parent is pytest's collection tree -- ctrlrunner has no collection
tree. Use item.module (the module object), item.cls (the test class), or
item.nodeid instead. docs/hooks.md#compatibility
```

Table seeded with (at minimum): `item.parent`, `item.listchain`,
`item.instance`, `item.stash`*, `config.stash`*, `config.hook`,
`config.pluginmanager.add_hookspecs`, `session.shouldstop`*,
`session.shouldfail`*, `session.perform_collect`, `report.result`,
`metafunc.definition`. (* = promoted to real implementations in later
phases; the error message says "planned — see plan" until then.)
Unknown attributes not in the table get a generic
`CompatibilityError` naming the attribute and linking docs/hooks.md.

### 1b. Unknown-hook detection at startup

`collect_declarations()` (`config/addoption.py:201`) and the worker's
conftest scan (`worker.py:755`) currently ignore unrecognized functions. New
behavior: any module-level `pytest_*` or `ctrlrunner_*` function in a
conftest whose name is not in the supported set **aborts the run** with the
per-hook recommendation from the table in Part 3 (e.g. "pytest_enter_pdb:
ctrlrunner has no pdb integration -- run the failing test with
`--num-workers 1` and use breakpoint() in the test body"). An escape hatch
`allow_unknown_hooks = true` in ctrlrunner.toml downgrades to a warning
(for shared conftests serving both runners during migration).

### 1c. Migrate tool alignment

The generic `pytest_*` TODO branch (`migrate/transformer.py:643`) emits the
same per-hook recommendation text instead of the generic "no ctrlrunner
equivalent" message.

---

## Part 2 — Hook-by-hook classification (all 52)

### Already implemented (20, Phases 0–2)

| pytest hook | ctrlrunner | Note |
|---|---|---|
| `pytest_addoption(parser)` | `ctrlrunner_addoption` | done; `parser.addini` still warns → route to `[ctrlrunner.options]` |
| `pytest_configure(config)` | `ctrlrunner_configure` | done; runs before tag-registry load so `addinivalue_line("markers", …)` is real |
| `pytest_sessionfinish(session, exitstatus)` | `ctrlrunner_sessionfinish` | done |
| `pytest_runtest_setup(item)` | `ctrlrunner_runtest_setup` | done; `skip()`/`fixme()`/`fail()` control outcome |
| `pytest_runtest_teardown(item, nextitem)` | `ctrlrunner_runtest_teardown` | done; `nextitem` is REAL: the next test in this worker's batch / next serial-group member, None for the last (pytest-xdist semantics) |
| `pytest_runtest_logstart(nodeid, location)` | `ctrlrunner_runtest_logstart` | done |
| `pytest_runtest_logreport(report)` | `ctrlrunner_runtest_logreport` | done; **semantic delta**: one report per attempt (`when="call"`), not three per phase — document + `report.when` stays `"call"` |
| `pytest_sessionstart(session)` | `ctrlrunner_sessionstart` | done (Phase 1) — cli.py, right after configure hooks, before discovery |
| `pytest_unconfigure(config)` | `ctrlrunner_unconfigure` | done (Phase 1) — cli.py, the very last hook, `finally`-guaranteed |
| `pytest_collection_modifyitems(session, config, items)` | `ctrlrunner_collection_modifyitems` | done (Phase 1) — orchestrator.py, right after `select_tests()`; `items` = Item shims, `add_marker`/reorder/remove write through to the real TestItems |
| `pytest_collection_finish(session)` | `ctrlrunner_collection_finish` | done (Phase 1) |
| `pytest_deselected(items)` | `ctrlrunner_deselected` | done (Phase 1) |
| `pytest_itemcollected(item)` | `ctrlrunner_itemcollected` | done (Phase 1) |
| `pytest_ignore_collect(collection_path, config)` | `ctrlrunner_ignore_collect` | done (Phase 1) — firstresult, fires before a test file is even imported |
| `pytest_report_header(config, start_path)` | `ctrlrunner_report_header` | done (Phase 1) — printed after "Collected N tests" |
| `pytest_terminal_summary(terminalreporter, exitstatus, config)` | `ctrlrunner_terminal_summary` | done (Phase 1) — real `TerminalReporter` shim: `.section`/`.write_line`/`.write_sep`/`.stats` |
| `pytest_runtest_call(item)` | `ctrlrunner_runtest_call` | done (Phase 2) — notification before the test body; an exception here fails the test (matches pytest, unlike every other per-test hook) |
| `pytest_runtest_makereport(item, call)` | `ctrlrunner_runtest_makereport` | done (Phase 2) — fires once ctrlrunner's one consolidated report is ready; `call` is a real `CallInfo` with live `.excinfo`; a truthy return value replaces the report `exception_interact`/`logreport` receive |
| `pytest_exception_interact(node, call, report)` | `ctrlrunner_exception_interact` | done (Phase 2) — fires only on `outcome == "failed"`, live excinfo |
| `pytest_runtest_logfinish(nodeid, location)` | `ctrlrunner_runtest_logfinish` | done (Phase 2) — right after logreport |

Also done (Phase 2 object work): `item.stash`/`config.stash` (real mutable
dicts), `config.invocation_params` (`.args`, `.dir`), `item.add_report_section`,
`item.callspec` (only on parametrized tests, `hasattr`-gated like pytest),
and `ctrlrunner.ExitCode` (top-level export; numerically differs from
pytest's own enum — documented).

### Done — Phase 3: advanced parity (7 hooks + ordering/wrapper mechanics)

| pytest hook | New ctrlrunner hook | Notes |
|---|---|---|
| `pytest_generate_tests(metafunc)` | `ctrlrunner_generate_tests(metafunc)` | done — fires from `registry.py`'s `test()` decorator (only when no static `@parametrize` already set `_param_sets`); **Metafunc shim** buffers `.parametrize(argnames, argvalues, indirect, ids)` calls, replayed through the real `parametrize()` decorator so the existing cartesian-product/id/tag logic runs unmodified |
| `pytest_make_parametrize_id(config, val, argname)` | `ctrlrunner_make_parametrize_id(config, val, argname)` | done — consulted first (firstresult) in `registry._stable_param_str`; registered incrementally per-conftest in both the main process (`orchestrator.py`, needed for scheduling) and each worker |
| `pytest_fixture_setup(fixturedef, request)` / `pytest_fixture_post_finalizer(fixturedef, request)` | `ctrlrunner_fixture_setup` / `ctrlrunner_fixture_post_finalizer` | done — notification form (not firstresult-override) at `FixtureResolver` resolve/teardown seams (`core/di.py`); `fixturedef` shim: `.argname`/`.scope`/`.cached_result` |
| `pytest_warning_recorded(warning_message, when, nodeid, location)` | `ctrlrunner_warning_recorded(...)` | done — fired from the per-attempt warning collection loop (worker.py wlist processing); `when` is always `"runtest"` (documented delta, see Part 3) |
| `pytest_assertrepr_compare(config, op, left, right)` | `ctrlrunner_assertrepr_compare(config, op, left, right)` | done — consulted by `assert_introspect._build` for `==`/`!=` comparisons; a non-empty return augments the failure message |
| `pytest_report_teststatus(report, config)` | `ctrlrunner_report_teststatus(report, config)` | done — consulted by `DotsReporter`/`LineReporter` via `_custom_status_symbol`; only the `shortletter` element is used |
| `session.shouldstop` / `session.shouldfail` | real, settable | done — a worker setting either streams a new `("shouldstop_requested", worker_id, reason)` IPC message; the orchestrator sets `cancel_event` and reports `"not_run"` for the rest of the run, same shape as an existing fail-policy cancellation |
| `@ctrlrunner.hookimpl(tryfirst/trylast)` | ordering hints | done — `hookcompat.sort_hooks()` applied at every hook-consultation call site (worker.py, di.py, assert_introspect.py, registry.py, reporters.py); conftest order itself stayed shallowest-first (pytest's LIFO/deepest-first was **not** adopted — see Part 3 item 3) |
| `hookwrapper=True` | generator hooks with one `yield` + `outcome.get_result()`/`.force_result()` | done — supported for `ctrlrunner_runtest_makereport` only (the one hook where wrappers dominate real-world usage) via `hookcompat.run_makereport_hook()`/`_HookCallOutcome`; other hooks ignore the flag |

### REFUSE LOUDLY — no analogue by architecture (with the recommendation text)

| pytest hook | Recommendation (goes in the error + migrate TODO) |
|---|---|
| `pytest_cmdline_preparse` / `pytest_cmdline_parse` / `pytest_cmdline_main` / `pytest_load_initial_conftests` | Bootstrapping hooks never fired for conftest.py even in pytest. Wrap the CLI instead: a shell alias or a small driver script calling `python -m ctrlrunner` with your args. |
| `pytest_addhooks` / `pytest_plugin_registered` | ctrlrunner has no plugin manager to extend. Custom cross-cutting behavior lives in conftest hooks + `--reporter module:Class`. |
| `pytest_collection` / `pytest_runtestloop` / `pytest_runtest_protocol` | Replacing the collection/run loop is the runner's job. Retries: `@test(retries=N)`. Custom scheduling: `[ctrlrunner.workers]`, `--order`, serial classes. Whole-run orchestration: drive `Orchestrator` from Python. |
| `pytest_collect_file` / `pytest_pycollect_makemodule` / `pytest_pycollect_makeitem` / `pytest_collectstart` / `pytest_make_collect_report` / `pytest_collectreport` | ctrlrunner collects `test_*.py` via `@test` registration only — there is no collector tree. Non-Python test sources: generate `@test` functions at conftest import time (a loop calling `test()(fn)`). |
| `pytest_report_to_serializable` / `pytest_report_from_serializable` | xdist wire-format internals. ctrlrunner's cross-process transport is internal; consume results via the JSON report or an `EventSubscriber`. |
| `pytest_markeval_namespace` | ctrlrunner's `skip()`/`fail()` take real Python booleans, not string conditions — evaluate the expression directly at the call site. |
| `pytest_assertion_pass` | Not supported (pytest itself gates it behind an off-by-default ini). Use `step()` blocks for pass-path tracing. |
| `pytest_enter_pdb` / `pytest_leave_pdb` | No pdb integration (tests run in workers). Debug with `--num-workers 1` and `breakpoint()` in the test body. |
| `pytest_internalerror` / `pytest_keyboard_interrupt` | Runner-internal failure handling is not hookable. Observe run termination via `ctrlrunner_sessionfinish` / an `EventSubscriber`. |

---

## Part 2b — Argument-level parity (every simplified argument, audited)

Hook-name parity is not enough: a renamed hook whose arguments are stubs
(`nextitem=None` forever) silently breaks migrated logic. Every argument of
every supported hook gets the same three-way treatment as the hooks
themselves.

### Call mechanics: name-based argument binding (Phase 1, blocking)

pluggy binds hook arguments **by parameter name, not position** — in pytest,
`def pytest_collection_modifyitems(items)` and
`def pytest_collection_modifyitems(config, items)` are both legal because
each impl receives exactly the named subset it declares. ctrlrunner's
current `trim_args()` trims a **positional prefix**, which coincidentally
works for the seven existing hooks (their first arg is the one people keep)
but is wrong for any multi-arg hook where a body skips a leading parameter.
Replace `trim_args` with `bind_hook_args(hook, available: dict) -> args`:
inspect the hook's parameter names, pass the matching values from the
hook's full argument dict (e.g. `{"session": ..., "config": ...,
"items": ...}`), and raise `CompatibilityError` naming any parameter the
hook declares that the hookspec doesn't provide (pytest errors on unknown
params too). All existing and future hooks route through it.

### Argument status table

| Hook | Argument | Status |
|---|---|---|
| `ctrlrunner_runtest_teardown` | `nextitem` | **DONE** — real Item shim: next test in this worker's batch / next serial-group member; `None` only for the worker's last test (pytest-xdist semantics) |
| `ctrlrunner_addoption` | `pluginmanager` (pytest passes `(parser, pluginmanager)`) | IMPLEMENT (Phase 1): pass the `_PluginManager` shim as a second arg; name-based binding keeps 1-arg impls working |
| `ctrlrunner_runtest_logstart`/`logfinish` | `location` | DONE — real `(filename, lineno, testname)` |
| `ctrlrunner_sessionfinish` | `exitstatus` | DONE (documented delta: coverage/fail-on-flaky gates can adjust the final process code afterward) |
| `ctrlrunner_runtest_makereport` | `call` (`CallInfo`) | **DONE** (Phase 2): `.when`, `.start/.stop/.duration`, and `.excinfo` carrying the **live** exception object (a real `ExceptionInfo` with `.value`/`.type`/`.tb`) — not a string |
| `ctrlrunner_exception_interact` | `node`, `call`, `report` | **DONE** (Phase 2): all three real — `node` is the Item shim |
| `ctrlrunner_fixture_setup`/`post_finalizer` | `request` | **DONE** (Phase 3): `FixtureRequest` extended with `.scope`/`.config`/`.fixturename`; `.node` (Item) still raises `CompatibilityError` — not threaded through `di.py`'s resolver |
| `ctrlrunner_collection_modifyitems` | `session`, `config`, `items` | **DONE** (Phase 1): all three real; `items` entries are write-through proxies (see Part 2) |
| `ctrlrunner_ignore_collect` | `collection_path`, `config` | **DONE** (Phase 1) |
| any path-taking hook | legacy py.path duals (`path`, `startdir`) | REFUSE — deprecated in pytest 7 itself; only the `pathlib` variants (`collection_path`, `file_path`, `start_path`) exist, and name-based binding gives a clear error if a body requests the legacy name (recommendation: rename the parameter) |
| `ctrlrunner_warning_recorded` | `warning_message`, `when`, `nodeid`, `location` | **DONE** (Phase 3): `when` limited to `"runtest"` (config/collect-phase warnings aren't captured today — documented delta) |
| `ctrlrunner_report_header` | `start_path` | **DONE** (Phase 1); `startdir` legacy dual refused as above |

**Rule going forward**: no hook ships with a permanently-stubbed argument.
An argument is either real, real-with-documented-scope (like `nextitem`'s
worker-batch horizon), or absent-with-a-clear-error via name-based binding —
never a silent constant.

## Part 3 — Semantic deltas to document (not bugs, architecture)

1. **Per-attempt, not per-phase reports** — 1 logreport per attempt with
   `when="call"`; pytest emits 3 (setup/call/teardown). Migrated bodies
   filtering `if report.when == "call"` work unchanged.
2. **Two execution contexts** — main-process hooks vs in-worker hooks;
   worker hooks re-fire per retry attempt; no shared state between workers
   (module globals are per-worker).
3. **Conftest ordering** — shallowest-first (pytest: LIFO, deepest-first).
   Resolved in Phase 3 as: kept shallowest-first, unchanged. `sort_hooks()`
   (tryfirst/trylast) gives conftest authors an escape hatch for cases that
   need a specific hook to run first/last regardless of discovery order;
   switching the base discovery order itself would risk breaking every
   already-migrated conftest relying on the current order, for a pytest
   compatibility detail few hook authors depend on in practice.
4. **Exit codes** — ctrlrunner: 0 ok / 1 failed / 4 no-tests; pytest
   `ExitCode` enum differs (5 = no tests). Provide `ctrlrunner.ExitCode`
   with honest values + docs table.
5. **`nextitem` scope is the worker's batch** — implemented for real, but its
   horizon is this worker's queue (exactly pytest-xdist's semantics), not the
   global run order a single-process pytest sees.

## Part 4 — Execution order & estimates

| Phase | Content | Size | Status |
|---|---|---|---|
| 0 | Fail-loudly policy: CompatibilityError + recommendations table, unknown-hook startup detection, migrate messages, remove `_CompatNull` silent path, update all affected tests/docs | S–M | DONE |
| 1 | 9 main-process/collection hooks + Item-proxy design for modifyitems | M–L | DONE |
| 2 | makereport + CallInfo (live excinfo), exception_interact, logfinish, runtest_call, stash/invocation_params/callspec/add_report_section/ExitCode | M–L | DONE |
| 3 | generate_tests + Metafunc, fixture hooks, warning/assertrepr/teststatus, shouldstop, hookimpl ordering + makereport hookwrapper, conftest-order decision | L | DONE |

Each phase: TDD throughout; migrate-tool rename additions
(`_HOOK_RENAMES` grows per phase); `docs/hooks.md` + MIGRATION.md tables
updated per phase; full regression (`test_orchestrator_and_worker`,
`test_cli`, `test_options`, `test_migrate`, `test_hookcompat`) + live CLI
smoke of a real pytest conftest converted by `python -m ctrlrunner.migrate`.

## Part 5 — Verification per phase

- Unit: every new hook — discovery, firing order, arity-trimming,
  error-isolation (or deliberate propagation), per-attempt semantics.
- Integration: a "kitchen-sink conftest" fixture exercising every supported
  hook in one CLI run, asserting the full event sequence.
- Negative: every REFUSE hook name in a conftest → startup abort with its
  exact recommendation text; every table attribute → CompatibilityError.
- Migration: real pytest conftests (the user's `mac_only` example, a
  generate_tests example, a makereport-hookwrapper screenshot example)
  through `ctrlrunner.migrate` → run green or fail with the recommendation.
