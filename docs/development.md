# Developing ctrlrunner

[← Back to README](../README.md)

See also [CONTRIBUTING.md](../CONTRIBUTING.md) for PR expectations.

## Running ctrlrunner's own test suite

ctrlrunner is tested with the standard library `unittest`, not itself or
pytest — avoids both the irony and a dependency on either:

```
uv run python scripts/run_tests_parallel.py
```

`scripts/run_tests_parallel.py` runs each `tests/test_*.py` file as its own
`python -m unittest tests.<module>` subprocess, spread across worker
processes (default: CPU count, override with `-j`), to cut down the suite's
wall-clock time. It's still plain stdlib `unittest` underneath — the script
only adds process orchestration, no new dependency. For a plain serial run
(e.g. to compare against), `uv run python -m unittest discover -s tests`
still works as before.

## Dev tooling (uv / ruff / ty)

```
uv sync --group dev       # installs ruff + ty alongside the project
uv run ruff check .       # lint
uv run ruff format .      # format
uv run ty check           # type check (src/ctrlrunner/ only; see [tool.ty.src])
```

Config for all three lives in `pyproject.toml` (`[tool.ruff]`, `[tool.ty]`).

## Project layout

```
src/ctrlrunner/
    core/
        registry.py       @test / @fixture / @parametrize, TestItem/Fixture models
        di.py              Fixture dependency resolution (scopes, request.param)
        selection.py       Pure test-selection engine (case_id/tag/test_id filters)
        annotations.py     skip / fail / fixme / slow runtime calls
        steps.py           step() context manager
    execution/
        worker.py          Runs inside each spawned process; retry + artifact capture
        jobobject.py        Windows Job Object wrapper (POSIX fallback for dev)
        orchestrator.py     Discovery, worker pool, timeout watchdog, requeue
        rerun.py            --last-failed / --failed-from / --changed-since
        flaky.py            flaky-report score computation
        quarantine.py       quarantine config resolution
        fail_policy.py      --max-failures / --max-timeouts / --stop-on-worker-crash
        worker_budget.py    scoped worker budgets ([ctrlrunner.workers])
        coverage_support.py coverage.py integration
        sharding.py         batch scheduling
        run_controller.py   shared run orchestration for CLI/UI Mode
    reporting/
        reporter.py          JUnit XML (Teams pipeline)
        reporters.py          line / dots / json console reporters
        events.py              EventSubscriber / EventEnvelope
        history.py             historical timing SQLite store
        html_report.py         static self-contained HTML report generator
        grouping.py             HTML report / UI Mode grouping dimensions
    config/
        config.py           ctrlrunner.toml loader
        projects.py          named projects ([ctrlrunner.projects.*])
        tag_registry.py      registered_tags / strict_tags
    ui/
        ui_server.py          UI Mode local server (stdlib http.server + SSE)
        ui_frontend.py        UI Mode browser frontend
        trace_viewer.py       Playwright trace viewer launcher
        show_report.py        show-report local server
        localsec.py            local-server security helpers (see SECURITY.md)
    playwright/
        playwright_fixtures.py  built-in browser/context/page fixtures
        playwright_actions.py   auto_step (auto-recorded action wrapping)
    migrate/                pytest -> ctrlrunner source migration (libcst)
    cli.py / __main__.py
examples/               Runnable example test suites
tests/                  ctrlrunner's own unittest suite
```
