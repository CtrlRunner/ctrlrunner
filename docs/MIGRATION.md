# Migrating from pytest to pyrunner

`pyrunner.migrate` automates the bulk of a pytest -> pyrunner migration.
It rewrites test sources with [libcst](https://github.com/Instagram/LibCST)
(formatting and comments are preserved), converts everything that has a
direct pyrunner equivalent, and marks everything that doesn't with a
`# TODO(pyrunner-migrate): ...` comment at the exact spot plus an entry
in the final report.

libcst is needed only to *run the migration* — it is not a runtime
dependency of pyrunner or of the migrated tests:

```
pip install libcst
```

## Usage

```
python -m pyrunner.migrate tests/                 # dry-run: diffs + report
python -m pyrunner.migrate tests/ --write         # apply in place
python -m pyrunner.migrate tests/ --no-diff       # summary only
python -m pyrunner.migrate tests/ --report migration.md
python -m pyrunner.migrate tests/ --case-id-marker testrail_id   # non-default case-id marker name
python -m pyrunner.migrate tests/ --no-config     # skip pyproject.toml -> pyrunner.toml
```

Dry-run is the default and changes nothing. `--write` edits files in
place — commit or stash before running it, and use git to review and
roll back. Re-running the tool on already-migrated files is a no-op
(it recognizes pyrunner decorators and never duplicates TODO comments).

The tool scans `test_*.py`, `*_test.py` and `conftest.py` under each
directory argument; individual `.py` files can be passed explicitly.
Pass the whole test tree in one invocation: the indirect-parametrize
conversion is cross-file (test file -> conftest.py) and needs to see
both sides at once.

## What is converted automatically

| pytest | pyrunner |
|---|---|
| `def test_*()` | `@test()` added (outermost decorator) |
| `@pytest.fixture(scope, autouse, params)` | `@fixture(...)`, same arguments |
| `@pytest.fixture(scope="class")` | `scope="module"` + TODO to verify |
| `@pytest.fixture(scope="package")` | `scope="session"` + TODO to verify |
| `@pytest.mark.parametrize("a,b", vals)` | `@parametrize("a,b", vals)` placed *below* `@test` (pyrunner requires that order) |
| `pytest.param(x, y)` in values | `(x, y)` |
| `pytest.param(x, id=..., marks=[...])` in values | `param(x, id=..., case_id=..., xfail=..., xfail_strict=..., skip=..., tags={...})` — the case-id marker becomes `case_id=`, `xfail`/`skip` marks become flat kwargs, other marks become per-param tags; `skipif`/`raises=`/conditions leave the `pytest.param` untouched + TODO |
| `@pytest.mark.test_case_id("7412675")` | `@test(case_id="7412675")` (marker name configurable via `--case-id-marker`; class-level use is flagged instead — `@test_class` has no `case_id`) |
| `request.node.add_marker(pytest.mark.test_case_id(x))` | `record_property("test_case_id", x)` + TODO — the value lands in the JUnit/JSON report as the same property the reporter uses for `case_id`, but is **not** selectable via `--case-id`; a now-unused `request` parameter is dropped from the signature |
| `@pytest.mark.parametrize("fx", vals, indirect=True)` | decorator removed; `params=vals` added to the `fx` fixture definition, even in another file; `request` added to its signature if missing |
| `@pytest.mark.skip(reason=r)` | `skip(description=r)` as the first body statement |
| `@pytest.mark.skipif(cond, reason=r)` | `skip(cond, r)` as the first body statement |
| `@pytest.mark.xfail(cond, reason=r, strict=s)` | `fail(cond, description=r, strict=s)`; `strict=False` pinned explicitly when absent (pytest and pyrunner defaults differ) |
| `@pytest.mark.timeout(N)` (pytest-timeout) | `@test(timeout=N)` |
| `@pytest.mark.flaky(reruns=N)` (pytest-rerunfailures) | `@test(retries=N)` |
| `@pytest.mark.usefixtures("db")` | `db` appended to the function signature |
| `@pytest.mark.<custom>` | `@test(tags={"<custom>"})` |
| `class TestX:` (no base classes) | `@test_class(...)`; class-level `timeout`/`flaky`/custom marks become `test_class` arguments |
| `pytest.skip(msg)` call | `skip(description=msg)` |
| `pytest.fail(msg)` call | `raise AssertionError(msg)` |
| `pytest.xfail(msg)` call | `fail(description=msg)` + `raise AssertionError(msg)` (pytest's xfail also stops the test) |
| pytest-playwright `page` / `context` / `browser` | `from pyrunner.playwright.playwright_fixtures import ...` added |
| `record_property` fixture param | param removed; `from pyrunner import record_property` added (calls keep working as-is) |
| `record_testsuite_property` fixture param | param removed; calls renamed to `record_suite_property(...)`; `from pyrunner import record_suite_property` added |
| `import pytest` / `from pytest import ...` | removed when nothing pytest-specific remains; kept + reported otherwise |

### pyproject.toml -> pyrunner.toml

When a `pyproject.toml` with `[tool.pytest.ini_options]` governs the
migrated paths (found by walking upward, stopping at a `.git` boundary),
a `pyrunner.toml` is generated next to it — shown as a diff in dry-run,
written by `--write`, never overwriting an existing `pyrunner.toml`.
Disable with `--no-config`.

| pytest option | pyrunner.toml |
|---|---|
| `markers = ["name: desc", ...]` | `registered_tags = [...]` (descriptions stripped; the case-id marker and converted-away markers like `timeout`/`flaky` excluded) |
| `--strict-markers` in `addopts` | `strict_tags = true` |
| `-n N` / `--numprocesses N` in `addopts` | `num_workers = N` (`auto` kept as a string) |
| `testpaths = [...]` | `root = "<first>"` (multiple entries flagged) |
| `timeout = N` (pytest-timeout) | `timeout = N` |
| everything else (`filterwarnings`, `pythonpath`, `asyncio_*`, other `addopts` flags) | commented `# TODO(pyrunner-migrate)` lines in the generated file |

## What is flagged for manual work

Each of these gets a `# TODO(pyrunner-migrate)` comment in place and a
line in the report:

- `pytest.raises` / `pytest.warns` / `pytest.approx` /
  `pytest.importorskip` / `pytest.deprecated_call` — no pyrunner
  equivalents; rewrite with try/except, `warnings.catch_warnings`,
  `math.isclose`, etc. The code is left untouched and the `pytest`
  import is kept so the file stays runnable while you convert.
- Builtin fixtures with no pyrunner counterpart: `tmp_path`, `tmpdir`,
  `monkeypatch`, `capsys`, `capfd`, `caplog`, `mocker`, `pytestconfig`,
  `cache`, ... — provide your own `@fixture` or inline the behavior.
  (`recwarn` has no direct equivalent either, but note pyrunner captures
  Python warnings per-test automatically into the report's `warnings`
  field.)
- `request.*` beyond `request.param` (pyrunner's `FixtureRequest`
  carries only `.param`): `getfixturevalue`, `addfinalizer`,
  `config`, `node`, ...
- `unittest.TestCase`-style classes — `@test_class` supports plain
  classes only; the whole class is left untouched.
- `pytest_*` hook functions in `conftest.py` — pyrunner is
  deliberately hook-free; most collection/report hooks map to
  `@test(case_id=..., tags=..., properties=...)` metadata or to a CLI
  flag instead.
- Async tests (`async def` / `@pytest.mark.asyncio`) — pyrunner is
  sync-only; wrap the body with `asyncio.run()`.
- `xfail(raises=...)`, string `skipif` conditions (old pytest style),
  fixture `ids=` / `name=` aliases, class-level `skip`/`skipif`/
  `xfail`/`usefixtures`/`parametrize`, non-trivial `indirect=`
  shapes, `pytest.skip(allow_module_level=True)`.
- pytest-playwright configuration fixtures (`browser_name`,
  `browser_context_args`, ...) — use
  `pyrunner.playwright.playwright_fixtures.configure()` or the `--browser`/
  `--trace`/`--screenshot` CLI flags.

## Recommended workflow

1. Commit a clean tree.
2. `python -m pyrunner.migrate tests/ --report migration.md` — read the
   diff and the report.
3. `python -m pyrunner.migrate tests/ --write`.
4. Work through the `TODO(pyrunner-migrate)` comments (`git grep
   'TODO(pyrunner-migrate)'`).
5. Run the suite: `python -m pyrunner tests -n 4 --timeout 60`.
6. Compare test counts against the old pytest run — parametrized ids
   differ in shape (pyrunner derives the `[suffix]` from values), but
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
- **Fixture teardown scope**: pyrunner's `module`/`session` scopes are
  per *worker process*, not global across the run — one browser per
  worker, not one per suite.
- **Retries** (`retries=N`) apply to assertion/exception failures
  only, never to hangs — a hung test is hard-killed and its batch
  requeued.
