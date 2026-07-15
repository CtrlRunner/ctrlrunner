# Parallelism, scheduling & test selection

[← Back to README](../README.md)

## Parallelism & scheduling

> **Behavior change (Playwright-style default):** tests in a single
> file run **in order, in the same worker process**; files run in
> parallel across workers. Previously every test was distributed
> individually. Set `fully_parallel = true` to restore per-test
> distribution.

```toml
[ctrlrunner]
num_workers = "auto"    # the default: CPUs - 1. Or an int, or "50%" of CPUs
fully_parallel = false  # true = distribute every test individually
```

- **`num_workers`** accepts `"auto"` (`max(1, CPUs - 1)`), a positive
  int, or `"N%"` of CPUs (`"150%"` allowed for oversubscription). Same
  spellings work for `-n` on the CLI (`-n auto`, `-n 50%`, `-n 8`), in
  project tables, and in the UI. **`"auto"` is the default** when
  nothing is configured.
- **`fully_parallel`** can be set globally, per project, or per class
  (`@test_class(fully_parallel=True)`); the most specific wins
  (class > project > global).
- Batches are duration-balanced (LPT over the historical timing store,
  when present) by whole scheduling units: a file, a serial class, or a
  single test under fully-parallel.

### Scoped worker budgets (`[ctrlrunner.workers]`)

Limit how many workers a file, glob, or class may occupy:

```toml
[ctrlrunner.workers]                # NOTE: nested under [ctrlrunner] -- a bare
"tests/test_checkout.py" = 1      # [workers] table is silently ignored
"tests/api/test_rate_*.py" = 2
"tests/test_login.py::LoginTests" = { count = 2, mode = "dedicated" }
```

- **cap mode** (plain int, the default): at most N workers run that
  group's tests concurrently; `1` serializes the group. Costs nothing
  when unused.
- **`mode = "dedicated"`**: N workers are *reserved* for the group --
  other tests can't use those slots while the group still has work
  (reservations that don't fit the pool are clamped with a warning,
  and released as soon as the group drains).
- The same cap can be declared in code: `@test_class(workers=1)` /
  `@test_class(workers=2, workers_mode="dedicated")`. A matching
  `[ctrlrunner.workers]` entry always beats the decorator; among config
  entries the most specific pattern wins (class-qualified > exact file
  > glob, ties by declaration order).

### Serial classes (`@test_class(serial=True)`)

Inter-dependent tests can be declared serial, like Playwright's
`test.describe.serial`:

```python
@test_class(serial=True, retries=1)
class CheckoutFlow:
    @test()
    def test_login(self, page): ...
    @test()
    def test_add_to_cart(self, page): ...   # skipped if login failed
    @test()
    def test_pay(self, page): ...
```

- Members run in **definition order** in one worker; if one fails, all
  subsequent members are reported `skipped`.
- `retries=N` on the class is the **group** retry budget: on any
  failure the whole group restarts from its first test (all members
  are retried together, and every member reports the group attempt
  number). `retries=` on an individual `@test` inside a serial class
  is a decoration-time error.
- A hard-kill (timeout) mid-group counts as one failed group attempt:
  with budget left the whole group is requeued onto a fresh worker
  (fresh fixtures); out of budget, the stuck test fails and the rest
  are skipped.
- If a selection filter (`--tag`, `--test-id`, ...) picks only a
  subset of a serial class, the selected members still run serially in
  definition order, with skip-on-fail and retries applying to that
  subset. **Rerun flags are the exception**: `--last-failed` /
  `--failed-from` / `--changed-since` automatically expand a partial
  serial selection to the whole class — rerunning only the failed
  member of an inter-dependent flow is almost never what you want.
- `serial=True` and `fully_parallel=True` on the same class are
  mutually exclusive.

### Worker isolation contract

What IS isolated: each worker is its own spawned process with its own
session/module fixtures (e.g. its own browser). What is NOT isolated
between tests that land on the **same** worker: `sys.modules` and
module-level globals (test modules are imported once per worker),
session/module fixture state, `os.environ`, and the working directory.

Which tests share a worker depends on the schedule — selection filters,
`--last-failed`, historical durations (LPT), and worker count all change
the packing between runs. **Do not write tests that depend on a
same-worker neighbor having run first** (the same reproducibility trap
as pytest-xdist's `--lf`): a rerun may place the test on a different
worker and behave differently. Serial classes are the supported way to
express ordered, inter-dependent tests.

## Test selection (replaces `pytest_collection_modifyitems`)

```
--test-id TC_ID1,TC_ID2          # exact internal id (module::func[params])
--case-id TC-1,TC-100-en-US      # exact case ID(s), comma-separated
--case-id-prefix TC-100          # every parametrized variant of a case
--tag smoke,regression           # OR-filter on tags
--tag-not slow,quarantined-ui    # EXCLUDE tests carrying any of these tags
--grep 'login.*flow'             # regex against each test's full id; only matches run
--grep-not slow                  # regex against each test's full id; matches excluded
```

All filters combine with AND; each accepts multiple comma-separated
values (OR within that filter). `--grep`/`--grep-not` match against a
test's full id (`module::[Class.]func[params]`) — named to match this
project's own `--tag-not` negation convention rather than Playwright's
`--grep-invert`. A bad regex fails immediately with a clean usage error
(exit 2), before any discovery/execution work starts. A run whose
selection matches **zero tests exits with code 4** (a typo'd filter
must never produce a green CI run that tested nothing); rerun flags
matching zero stay exit 0. Implemented as a pure function
(`ctrlrunner.core.selection.select_tests`) over the registered test list — no
collection hook, directly unit-testable.

```
--order declared|alpha|random # unit scheduling order (default: declared, unchanged)
--seed N                      # required to reproduce --order random (auto-generated
                               # and printed to stderr if omitted)
```

`--order` never reorders tests *within* a file or a serial class — only
which unit a worker picks up first/next; the resolved order (and seed,
for `random`) lands in JUnit `<properties>`/JSON `suiteProperties` so a
report always says how it was scheduled.

```
--fail-on-flaky                # exit non-zero if any test passed only after a retry
```

A retried test that eventually passes gets `Result.flaky = True` (a
`flaky=true` property in JUnit, a `flaky` field in JSON) — the outcome
itself stays `passed` either way; `--fail-on-flaky` is the only thing
that turns that signal into a non-zero exit code.

## `--list`

Lists discovered (and selected) tests without running a single one --
no worker spawned, no browser launched:

```
ctrlrunner examples --tag smoke --list json --list-output selected.json
ctrlrunner examples --case-id-prefix TC-100 --list text
ctrlrunner examples --list md --list-fields id,timeout,retries
```

```
--list text|json|md              # default fields: id, caseId, tags
--list-output PATH                 # write to a file instead of stdout
--list-fields id,caseId,tags,...   # text/md only; json always includes every field
```

Full `--test-id`/`--case-id`/`--case-id-prefix`/`--tag` support --
`--list` is a view over the exact same selection pipeline a real run
uses, never a separate discovery path. Also honors `registered_tags`/
`strict_tags` the same way a real run does (see
[Registered tag registry](config-reference.md#registered-tag-registry)).
