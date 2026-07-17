# Migrating from pytest to ctrlrunner

`ctrlrunner.migrate` automates the bulk of a pytest -> ctrlrunner migration.
It rewrites test sources with [libcst](https://github.com/Instagram/LibCST)
(formatting and comments are preserved), converts everything that has a
direct ctrlrunner equivalent, and marks everything that doesn't with a
`# TODO(ctrlrunner-migrate): ...` comment at the exact spot plus an entry
in the final report.

libcst is needed only to *run the migration* — it is not a runtime
dependency of ctrlrunner or of the migrated tests:

```
pip install libcst
```

## Usage

```
python -m ctrlrunner.migrate tests/                 # dry-run: diffs + report
python -m ctrlrunner.migrate tests/ --write         # apply in place
python -m ctrlrunner.migrate tests/ --no-diff       # summary only
python -m ctrlrunner.migrate tests/ --report migration.md
python -m ctrlrunner.migrate tests/ --case-id-marker testrail_id   # non-default case-id marker name
python -m ctrlrunner.migrate tests/ --no-config     # skip pyproject.toml -> ctrlrunner.toml
```

Dry-run is the default and changes nothing. `--write` edits files in
place — commit or stash before running it, and use git to review and
roll back. Re-running the tool on already-migrated files is a no-op
(it recognizes ctrlrunner decorators and never duplicates TODO comments).

The tool scans `test_*.py`, `*_test.py` and `conftest.py` under each
directory argument; individual `.py` files can be passed explicitly.
Pass the whole test tree in one invocation: the indirect-parametrize
conversion is cross-file (test file -> conftest.py) and needs to see
both sides at once.

## What is converted automatically

| pytest | ctrlrunner |
|---|---|
| `def test_*()` | `@test()` added (outermost decorator) |
| `@pytest.fixture(scope, autouse, params)` | `@fixture(...)`, same arguments |
| `@pytest.fixture(scope="class")` | `scope="module"` + TODO to verify |
| `@pytest.fixture(scope="package")` | `scope="session"` + TODO to verify |
| `@pytest.mark.parametrize("a,b", vals)` | `@parametrize("a,b", vals)` placed *below* `@test` (ctrlrunner requires that order) |
| `pytest.param(x, y)` in values | `(x, y)` |
| `pytest.param(x, id=..., marks=[...])` in values | `param(x, id=..., case_id=..., xfail=..., xfail_strict=..., skip=..., tags={...})` — the case-id marker becomes `case_id=`, `xfail`/`skip` marks become flat kwargs, other marks become per-param tags; `skipif`/`raises=`/conditions leave the `pytest.param` untouched + TODO |
| `@pytest.mark.test_case_id("7412675")` | `@test(case_id="7412675")` (marker name configurable via `--case-id-marker`; class-level use is flagged instead — `@test_class` has no `case_id`) |
| `request.node.add_marker(pytest.mark.test_case_id(x))` | `record_property("test_case_id", x)` + TODO — the value lands in the JUnit/JSON report as the same property the reporter uses for `case_id`, but is **not** selectable via `--case-id`; a now-unused `request` parameter is dropped from the signature |
| `@pytest.mark.parametrize(..., indirect=...)` (any shape: `indirect=True`, `indirect=["fx"]`, mixed direct+indirect names, non-literal values, conflicting value sets across tests, already-parametrized fixture) | `@parametrize(..., indirect=...)` kept nearly verbatim — ctrlrunner supports `indirect=` natively with pytest semantics (the test's value reaches the fixture as `request.param`, replacing the fixture's own `params=[...]` for that test); `request` is added to the target fixture's signature if missing, even in another file. `pytest.param(...)` rows convert the same way as in a direct parametrize |
| `@pytest.mark.skip(reason=r)` | `skip(description=r)` as the first body statement |
| `@pytest.mark.skipif(cond, reason=r)` | `skip(cond, r)` as the first body statement |
| `@pytest.mark.xfail(cond, reason=r, strict=s)` | `fail(cond, description=r, strict=s)`; `strict=False` pinned explicitly when absent (pytest and ctrlrunner defaults differ) |
| `@pytest.mark.timeout(N)` (pytest-timeout) | `@test(timeout=N)` |
| `@pytest.mark.flaky(reruns=N)` (pytest-rerunfailures) | `@test(retries=N)` |
| `@pytest.mark.usefixtures("db")` | `db` appended to the function signature |
| `@pytest.mark.<custom>` (no args) | `@test(tags={"<custom>"})` |
| `@pytest.mark.<custom>(x)` (has args) | kept as a tag, `x` is **dropped** + TODO — deliberately not auto-converted to `@test(properties=...)`, since a custom marker's argument may be read back at runtime by a fixture/hook (see "Marker-driven guard fixtures" below); there's no static way to tell that apart from a purely descriptive marker |
| `class TestX:` (no base classes) | `@test_class(...)`; class-level `timeout`/`flaky`/custom marks become `test_class` arguments; class-level `skip`/`skipif`/`xfail`/`usefixtures`/`parametrize` are replayed onto *every* method via the same per-method conversion a method's own marker would get (a class-level `parametrize` genuinely parametrizes each method independently, matching pytest) |
| `pytest.skip(msg)` call | `skip(description=msg)` |
| `pytest.fail(msg)` call | `raise AssertionError(msg)` |
| `pytest.xfail(msg)` call | `fail(description=msg)` + `raise AssertionError(msg)` (pytest's xfail also stops the test) |
| pytest-playwright `page` / `context` / `browser` | `from ctrlrunner.playwright.playwright_fixtures import ...` added |
| `record_property` fixture param | param removed; `from ctrlrunner import record_property` added (calls keep working as-is) |
| `record_testsuite_property` fixture param | param removed; calls renamed to `record_suite_property(...)`; `from ctrlrunner import record_suite_property` added |
| `def pytest_addoption(parser):` | renamed to `def ctrlrunner_addoption(parser):`, body unchanged — ctrlrunner's parser shim accepts pytest's `parser.addoption(...)`/`parser.getgroup(...)` signatures (`parser.addini(...)` warns at runtime, pointing at `[ctrlrunner.options]`) |
| `pytestconfig.getoption(x)` / `request.config.getoption(x)` | `get_option(x)` (same args, including `default=`); the `pytestconfig`/`request` parameter is dropped when `.getoption()` was its only use in the function |
| `import pytest` / `from pytest import ...` | removed when nothing pytest-specific remains; kept + reported otherwise |

### pyproject.toml -> ctrlrunner.toml

When a `pyproject.toml` with `[tool.pytest.ini_options]` governs the
migrated paths (found by walking upward, stopping at a `.git` boundary),
a `ctrlrunner.toml` is generated next to it — shown as a diff in dry-run,
written by `--write`, never overwriting an existing `ctrlrunner.toml`.
Disable with `--no-config`.

| pytest option | ctrlrunner.toml |
|---|---|
| `markers = ["name: desc", ...]` | `registered_tags = [...]` (descriptions stripped; the case-id marker and converted-away markers like `timeout`/`flaky` excluded) |
| `--strict-markers` in `addopts` | `strict_tags = true` |
| `-n N` / `--numprocesses N` in `addopts` | `num_workers = N` (`auto` kept as a string) |
| `testpaths = [...]` | `root = "<first>"` (multiple entries flagged) |
| `timeout = N` (pytest-timeout) | `timeout = N` |
| everything else (`filterwarnings`, `pythonpath`, `asyncio_*`, other `addopts` flags) | commented `# TODO(ctrlrunner-migrate)` lines in the generated file |

## What is flagged for manual work

Each of these gets a `# TODO(ctrlrunner-migrate)` comment in place and a
line in the report:

- `pytest.raises` / `pytest.warns` / `pytest.approx` /
  `pytest.importorskip` / `pytest.deprecated_call` — no ctrlrunner
  equivalents; rewrite with try/except, `warnings.catch_warnings`,
  `math.isclose`, etc. The code is left untouched and the `pytest`
  import is kept so the file stays runnable while you convert.
- Builtin fixtures with no ctrlrunner counterpart: `tmp_path`, `tmpdir`,
  `monkeypatch`, `capsys`, `capfd`, `caplog`, `mocker`,
  `cache`, ... — provide your own `@fixture` or inline the behavior.
  (`recwarn` has no direct equivalent either, but note ctrlrunner captures
  Python warnings per-test automatically into the report's `warnings`
  field.) `pytestconfig` is auto-converted for `.getoption()` (see the
  table above) — only OTHER attributes (`.getini()`, `.rootpath`,
  `.invocation_params`, ...) leave the parameter in place with a TODO.
- `request.*` beyond `request.param` (ctrlrunner's `FixtureRequest`
  carries only `.param`): `getfixturevalue`, `addfinalizer`,
  `node`, ... (`request.config.getoption(...)` is auto-converted, see above).
- `unittest.TestCase`-style classes — `@test_class` supports plain
  classes only; the whole class is left untouched.
- `pytest_*` hook functions in `conftest.py` other than `pytest_addoption`
  (which is auto-renamed to `ctrlrunner_addoption`, see above) —
  ctrlrunner is deliberately hook-free; most collection/report hooks map to
  `@test(case_id=..., tags=..., properties=...)` metadata or to a CLI
  flag instead.
- Async tests (`async def` / `@pytest.mark.asyncio`) — ctrlrunner is
  sync-only; wrap the body with `asyncio.run()`.
- `xfail(raises=...)`, string `skipif` conditions (old pytest style),
  fixture `ids=` / `name=` aliases, a class-level case-id marker
  (`@test_class` has no `case_id` — one id can't describe several
  methods), `pytest.skip(allow_module_level=True)`.
- Custom markers with arguments (`@pytest.mark.<custom>(x)`) — see
  "Marker-driven guard fixtures" below if the marker is read back by a
  fixture/hook at runtime, not just reported as metadata.
- pytest-playwright configuration fixtures (`browser_name`,
  `browser_context_args`, ...) — use
  `ctrlrunner.playwright.playwright_fixtures.configure()` or the `--browser`/
  `--trace`/`--screenshot` CLI flags.

## Manual conversion recipes

Patterns the tool intentionally never auto-migrates because doing so
would require inferring runtime behavior it can't see statically.

### Marker-driven guard fixtures

A common pytest pattern: a custom marker carries a value, and a fixture
(pulled in via `usefixtures`) reads that value off the marker at
runtime via `request.node.get_closest_marker(...)` to decide whether to
guard/skip/xfail the test.

```python
# pytest
def _get_guard_value(request):
    marker = request.node.get_closest_marker("some_condition")
    return marker.args[0] if marker is not None else None

@pytest.fixture
def some_guard(request, other_fixture):
    value = _get_guard_value(request)
    if value is None:
        return
    if some_runtime_check(value):
        reason = f"guarded: {value}"
        request.node.add_marker(pytest.mark.xfail(reason=reason, strict=False))
        pytest.xfail(reason=reason)

@pytest.mark.some_condition(SomeEnum.VALUE)
@pytest.mark.usefixtures("some_guard")
def test_thing(other_fixture, request):
    ...
```

The migration tool converts the *shape* of everything except the
marker-reading fixture itself — that part needs a one-time manual
rewrite, after which every call site becomes a mechanical,
find-and-replaceable transform. The fixture **stays a fixture**;
ctrlrunner's `@parametrize(..., indirect=True)` delivers a per-test
value to it as `request.param`, exactly like pytest's indirect
parametrize:

1. **Delete the marker-reading helper** (`_get_guard_value` above) —
   nothing needs `get_closest_marker` once the value arrives as
   `request.param` instead.
2. **Have the fixture read `request.param`** where it used to read the
   marker:

   ```python
   @fixture()
   def some_guard(request, other_fixture):
       value = request.param
       if value is not None and some_runtime_check(value):
           reason = f"guarded: {value}"
           fail(description=reason, strict=False)
           raise AssertionError(reason)
   ```

   (`fail(...)` + `raise` is exactly what the tool already generates
   for a standalone `pytest.xfail(msg)` call — see the conversion
   table above.)
3. **Replace the marker pair on every test with an indirect
   parametrize**, carrying that test's own value:

   ```python
   @test()
   @parametrize("some_guard", [SomeEnum.VALUE], indirect=True)
   def test_thing(some_guard, other_fixture):
       ...
   ```

   (`some_guard` sits in the signature because the original
   `usefixtures("some_guard")` converts to exactly that — an indirect
   target must be requested by the test: signature, transitive fixture
   dependency, or autouse, same rule as pytest.) Different tests pass
   different values, same as the pytest original;
   the value even shows up in each test's id suffix. (If literally
   every test wants the same value, `@fixture(params=[SomeEnum.VALUE])`
   on the fixture itself works too — but the indirect form keeps the
   value visible at the test, which usually reads better for a guard.)

The tool won't do step 1 or 2 for you automatically: recognizing "this
marker's argument is consumed by a fixture at runtime" requires reading
the fixture's implementation, which is exactly the kind of guess that
silently drops behavior when wrong (see the `properties=...` row above).
But tests that already used pytest's `indirect=True` (rather than a
custom marker) to feed the fixture migrate fully automatically — see
the `indirect=` row in the conversion table.

## Recommended workflow

1. Commit a clean tree.
2. `python -m ctrlrunner.migrate tests/ --report migration.md` — read the
   diff and the report.
3. `python -m ctrlrunner.migrate tests/ --write`.
4. Work through the `TODO(ctrlrunner-migrate)` comments (`git grep
   'TODO(ctrlrunner-migrate)'`).
5. Run the suite: `python -m ctrlrunner tests -n 4 --timeout 60`.
6. Compare test counts against the old pytest run — parametrized ids
   differ in shape (ctrlrunner derives the `[suffix]` from values), but
   totals should match.

## Semantics to double-check after migration

- **skip/xfail become runtime calls**, evaluated when the test runs,
  not at collection time. Conditions that referenced collection-time
  state behave the same; conditions with side effects run once per
  test attempt.
- **`fail()` (xfail) does not stop the test** the way an xfail mark
  effectively did on the first assertion — it marks the rest of the
  test as expected-to-fail. Converted `pytest.xfail(...)` *calls* get
  an explicit `raise` to preserve the stop behavior.
- **Fixture teardown scope**: ctrlrunner's `module`/`session` scopes are
  per *worker process*, not global across the run — one browser per
  worker, not one per suite.
- **Retries** (`retries=N`) apply to assertion/exception failures
  only, never to hangs — a hung test is hard-killed and its batch
  requeued.
