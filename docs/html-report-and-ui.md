# Named projects, HTML report, coverage & UI Mode

[← Back to README](../README.md)

## Named projects (`--project`)

Run different subsets of tests under different configs, like Playwright
TS projects -- a named override bundle over base config:

```toml
[ctrlrunner.projects.smoke]
tests_dir = ["tests/web", "tests/e2e"]
tags = ["smoke"]
timeout = 15

[ctrlrunner.projects.regression]
tests_dir = ["tests/web"]
timeout = 30
```

```
ctrlrunner --project smoke
ctrlrunner --project smoke,regression
ctrlrunner --project smoke --timeout 45   # CLI still overrides the project's timeout=15
```

`tags` in a project is a **selection filter** ("only run tests matching
these"), not metadata stamped onto tests -- identical in effect to
passing `--tag`, and an explicit `--tag` on the command line overrides
a project's own filter entirely. `timeout`/`num_workers` follow the
same precedence everywhere else in this project: **CLI > project
config > base config > built-in default**. A project's `num_workers`
accepts the same `"auto"`/`"N%"` spellings as the base setting, and a
project can set its own `fully_parallel` to override the base value in
either direction.

`ctrlrunner_addoption` custom options follow the same shape, per key:
**CLI flag > `[ctrlrunner.projects.<name>.options]` > base
`[ctrlrunner.options]` > declared default**:

```toml
[ctrlrunner.options]
env = "qa"                        # base default for every project

[ctrlrunner.projects.smoke.options]
env = "staging"                   # smoke overrides the base for itself
```

Each named project runs its own tests independently, even if their
`tests_dir` overlap; combined results merge into one report. **`test_id`
only gets a `[project]` prefix, and JUnit only wraps in `<testsuites>`,
when 2+ projects are actually active in a given invocation** --
`--project smoke` alone (or no `--project` at all) keeps today's exact
`test_id`/JUnit shape, so existing case_id-based CI integrations never
see a format change unless multi-project genuinely applies. When it
does, `project` also becomes an automatic HTML report / UI Mode
grouping dimension, no extra `[grouping]` config needed.

## Grouping model (HTML report / UI Mode)

Both the HTML report and UI Mode group tests by file (the test's source
file path) by default -- no config needed. Add `[grouping]` to
`ctrlrunner.toml` for additional ways to group, with a dropdown switcher
to pick between them:

```toml
[ctrlrunner.grouping]
dimensions = [
  { name = "file",   strategy = "file" },                     # today's default -- list explicitly to keep it alongside custom ones
  { name = "suite",  strategy = "path", depth = 1 },          # tests/web/cases/... -> "cases"
  { name = "team",   strategy = "tag_prefix", prefix = "team_" },  # team_backend -> "backend"
  { name = "owner",  strategy = "property", key = "owner" },
]
```

(Note the `[ctrlrunner.grouping]` nesting, not a bare `[grouping]` --
everything in `ctrlrunner.toml` lives under the top-level `[ctrlrunner]`
table, so a sub-table needs the dotted prefix to actually nest inside
it rather than becoming its own unrelated top-level table that gets
silently ignored.)

- **`file`** -- the test's source file path, relative to the test root,
  in filesystem form (e.g. `examples/test_x.py`; today's default).
- **`path`** -- a directory segment from the test's file path, `depth`
  segments deep relative to the test root (0-based; `depth=1` with root
  `tests/` and file `tests/web/cases/test_x.py` groups by `cases`).
- **`tag_prefix`** -- strips `prefix` from whichever tag matches it
  (`team_backend` -> `backend` under `prefix = "team_"`).
- **`property`** -- groups by an `@test(properties={...})` value.

No `[grouping]` config at all = file-only grouping. A custom
`dimensions` list does **not** silently add `file` back in -- list it
explicitly if you want it alongside your custom dimensions.

**Breaking change:** the grouping strategy previously named `module`
(the dotted Python module path, e.g. `examples.test_x`) has been
renamed to `file` and now produces a real filesystem path instead
(`examples/test_x.py`). A `ctrlrunner.toml` still using
`strategy = "module"` will now raise `ValueError: unknown strategy
'module'` at startup -- update it to `strategy = "file"`. There's no
silent aliasing between the two.

## Reports directory

JUnit XML, JSON, and the HTML report all live together by default:

```
reports/html-report/
    report.xml
    results.json      (always written -- --last-failed and tooling read it)
    run-manifest.json  (always written -- versions, resolved config, argv, git SHA,
                        failed test ids: the "reproduce this run" summary)
    report.html        (only written if --html-report is passed)
    artifacts/          (screenshots/traces referenced by failed tests)
```

```
--reports-dir reports          # base directory (default: reports)
--report-name html-report      # subdirectory name (default: html-report)
--report-timestamp             # append a timestamp: html-report-20260705-163438
--keep-reports 10              # with --report-timestamp, prune older ones beyond this count
--junit-xml PATH                # override: write JUnit XML to an exact path instead
--json-output PATH               # override: write JSON to an exact path instead
```

Without `--report-timestamp`, the same directory is reused/overwritten
every run (`reports/html-report/`). With it, each run gets its own
timestamped directory and `--keep-reports` prunes the oldest ones so a
long-running project doesn't accumulate one directory per run forever
(default: keep the last 10).

`--junit-xml` / `--json-output` are still available as overrides for
when CI expects those files at a specific fixed path outside the
managed reports directory.

## HTML report

```
--html-report                    # write to <report_dir>/report.html
--html-report custom/path.html   # or: write to this exact path instead
--artifact-mode files|base64     # default: files
--report-title "My Project"      # header title (default: "Test Results")
```

`--report-title` is also settable via `ctrlrunner.toml`'s `report_title` key; the CLI flag
takes precedence.

A single self-contained file (data + markup + styling + JS all inline,
no build step, no server) — open it directly via `file://`. Grouped by
file, filterable by outcome (pass/fail/skip/fixme/expected-failure),
searchable by ID/case ID/tag, with error text, the step tree, and
artifact links shown per test on click.

The header shows both **wall** (actual elapsed run time, same number
the CLI prints) and **sequential** (the sum of every test's own
duration -- what the suite would cost with no parallelism) alongside
a speedup ratio, e.g. `wall 13.7s · sequential 24.8s (1.8×)`. These
differ by design once `num_workers > 1`; the sequential figure isn't
a bug, it's what you'd see running everything on one worker.

A "Timeline" button in the header opens a slide-in panel with a
per-worker Gantt chart of test execution — one row per worker, a
colored bar per test (outcome-colored, flaky tests get an amber ring),
positioned by actual start time and sized by duration. Hover a bar for
a tooltip (id, outcome, duration, worker, case id, attempts); click a
bar to jump to that test's detail view. Deep-linkable via
`#?panel=timeline`. Falls back to a friendly empty state on older
reports generated before this feature.

The per-file summary table (toggle "Show summary by file") is always
sorted by its first column ascending, and ends with a bold **Total**
row. A "Sort" dropdown next to the file/tag grouping switcher separately
reorders the test list: failures first (default), file A→Z/Z→A,
duration slowest/fastest-first, flaky-first, or near-timeout-first —
all computed client-side from the already-embedded report JSON,
deep-linkable via `#?sort=...`.

`--artifact-mode` only affects **images**: `files` (default) copies
every artifact — screenshots and trace zips alike — into
`<report_dir>/artifacts/`, so the report + that folder are portable as
a unit. `base64` embeds only image artifacts directly into the report as
inline data, identified by MIME type; trace zips always stay as
separate files regardless of this setting, since inlining a multi-MB
trace would bloat the report for no benefit (it can't be previewed
inline anyway).

```
python -m ctrlrunner show-report reports/html-report/report.html [--port 0] [--no-browser]
```

Serves the report (and its `artifacts/` folder) over
`http://127.0.0.1:<port>` instead of `file://`, and opens it in the
default browser. This is Phase 2 — needed because a future trace viewer
link would fetch the trace zip via XHR, which browsers block under
`file://` due to CORS; also just a nicer one-command UX than
double-clicking the file. No new dependency (stdlib `http.server`).

## Code coverage

```
--coverage                          # measure coverage across all workers (default: off)
--coverage-html                     # also write a coverage.py HTML report to <report_dir>/coverage-html
--coverage-html custom/dir          # or: write it to this directory instead
```

Config file equivalent:
```toml
[ctrlrunner.coverage]
enabled = true
source = ["ctrlrunner"]              # passthrough to coverage.py; default: its own auto-detection
html_dir = "reports/coverage-html" # default: none (no HTML report)
fail_under = 85                    # default: none (no threshold enforced)
contexts = false                   # default; true calls cov.switch_context(test_id) per test
```

Requires the optional `coverage` extra: `pip install ctrlrunner[coverage]`.

Each spawned worker process runs its own `coverage.Coverage()` instance
around its whole test batch; after every worker (across every project,
in a multi-project run) has exited, the main process combines the data
files and computes an aggregate + per-file percentage via the coverage
Python API (never a `coverage run` shell-out). This is a **whole-run/
whole-file metric only** — it shows up once in the JSON report's
`stats.coveragePercent` (+ optional `coverageByFile`) and as a one-line
summary in the HTML report, never per-test.

- Respects your own `.coveragerc`/`[tool.coverage]` config for
  everything except `data_file`/`data_suffix`/`source` — `omit`,
  `include`, `branch`, etc. stay whatever you've already configured.
- `fail_under` never masks a test failure: the test exit code always
  wins, and the coverage check only runs when every test passed. It's
  also downgraded to a warning (never enforced) whenever a test-selection
  filter is active (`--tag`, `--case-id`, `--case-id-prefix`, `--test-id`,
  `--last-failed`/`--failed-from`/`--changed-since`) — enforcing a
  whole-project threshold on a filtered run is never what you meant.
- A watchdog-killed worker never reaches `cov.save()`; if that happens,
  a `coverage data incomplete: N worker(s) terminated without saving`
  warning is printed rather than silently under-reporting.
- Multi-project runs share one coverage data directory and produce one
  combined report — for projects with genuinely disjoint source trees,
  the single combined percentage is a rough signal at best; use
  `--coverage-html`'s per-file breakdown for the real picture.
- `contexts = true` calls `cov.switch_context(test_id)` once per test
  (not per retry attempt), letting coverage.py's own HTML report answer
  "which tests cover this line" natively, at near-zero extra cost.

## UI Mode

```
python -m ctrlrunner ui [root] [--port 0] [--no-browser] [-n 4] [--timeout 30]
```

A live, interactive local app: a
test tree in the browser, checkboxes to select a subset, **Run
All**/**Run Selected**/**Cancel** buttons, and live pass/fail updates as
the run progresses — no waiting for a finished JSON blob like the static
HTML report.

Built on stdlib `http.server` + Server-Sent Events (not WebSockets —
the browser only ever *receives* progress; commands go out as plain
POST requests, so SSE is enough and needs no new dependency). Cancelling
hard-kills the in-progress worker via its Job Object (same mechanism as
a timeout) and marks whatever didn't finish as `cancelled` — a distinct
outcome from `failed`, so a stopped run doesn't look like a broken one
in reports.

Clicking a test expands its detail: error text, a step timeline (bars
proportional to duration — from `step()`/`auto_step` recordings), and
artifact links. A **View Trace** button next to any `.zip` artifact
launches Playwright's own trace viewer (`playwright show-trace`) — full
DOM snapshots, network waterfall, and action timeline, all of Playwright's
actual trace viewer, not a reimplementation of it. Requires the
`playwright` CLI on PATH; the button reports plainly if it isn't found
rather than failing silently.

Local-only by design: the server binds `127.0.0.1`, allowlists its own
`Host`, validates request origin against its bound port, and requires a
per-session token (embedded in the page) on every state-changing request
— so a malicious web page or another local process can't drive it. It
refuses a non-loopback `--bind` unless you also pass `--allow-remote`.
See [SECURITY.md](SECURITY.md) for the full model, including
`show-report` symlink containment, history-DB permissions, and secret
redaction in captured logs.

**Not yet implemented:** auto re-run on file save (Phase 3e — see the
plan doc for what that would need).
