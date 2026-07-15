"""
Optional pyrunner.toml config file. CLI flags always take precedence over
it; it just sets defaults so CI/dev don't need to repeat the same flags.

    [pyrunner]
    root = "tests"
    num_workers = "auto"   # default; or an int, or "N%" of CPUs
    timeout = 30.0
    # import_timeout = 60.0  # watchdog budget (s) for a worker's suite-import phase
    # order = "declared"      # "declared" | "alpha" | "random" -- unit scheduling order
    # seed = 12345             # required (or auto-generated) for order="random"
    reporter = ["line"]      # 'json' is always appended by the CLI; custom
                             # reporters load via "module.path:ClassName"
    # fully_parallel = false  # default: a file's tests share one worker, in order

    # Optional: scoped worker budgets (cap or dedicated) by file/glob/
    # class -- note the nesting: [pyrunner.workers], not a bare [workers]
    # (a sibling table, silently ignored).
    # [pyrunner.workers]
    # "tests/test_checkout.py" = 1
    # "tests/test_login.py::LoginTests" = { count = 2, mode = "dedicated" }

    reports_dir = "reports"
    report_name = "html-report"
    report_timestamp = false
    keep_reports = 10
    artifact_mode = "files"

    trace = "retain-on-failure"    # off | on | retain-on-failure | on-first-retry
    screenshot = "only-on-failure"  # off | on | only-on-failure
    logs = "only-on-failure"       # off | on | only-on-failure
    browser = "chromium"            # chromium | firefox | webkit
    headed = false

    # Optional: catches typos in @test(tags=...) -- absent entirely,
    # this validates nothing (zero behavior change). Prefix patterns
    # like "team:*" match any tag starting with "team:".
    # registered_tags = ["smoke", "regression", "team:*"]
    # strict_tags = false   # true = unregistered tag -> 0 tests run, non-zero exit

    # Optional: additional ways to group tests in the HTML report / UI
    # Mode, with a dropdown to switch between them. Note the nesting --
    # [pyrunner.grouping], not a bare [grouping] (which would be a
    # sibling table, silently ignored). Absent entirely = "module" only,
    # exactly like today.
    # [pyrunner.grouping]
    # dimensions = [
    #     { name = "module", strategy = "module" },
    #     { name = "team", strategy = "tag_prefix", prefix = "team_" },
    # ]

    # [pyrunner.fail_policy]
    # max_failures = 0
    # max_timeouts = 0
    # stop_on_worker_crash = false

    # [pyrunner.history]
    # enabled = true                    # default; stable across pruned report dirs
    # db_path = "reports/.history.db"    # default: <reports_dir>/.history.db
    # window_runs = 20

    # [pyrunner.log_redaction]
    # enabled = true                     # default; masks obvious secrets in captured
    #                                    #   logs (--logs) before they land in reports.
    #                                    #   false disables redaction entirely.
    # patterns = ["MYCORP-[0-9]+"]        # extra regexes applied on top of the built-ins
    # -- a best-effort safety net, NOT a guarantee: treat any report that
    #    contains captured logs as sensitive regardless.

    # [pyrunner.quarantine]
    # test_ids = ["tests.test_demo::test_flaky_checkout"]
    # reason = "JIRA-4821, flaky since 2026-06"
    # -- populated by a human after reviewing `pyrunner flaky-report` output

    # [pyrunner.coverage]
    # enabled = true                    # default false; --coverage also enables it
    # source = ["pyrunner"]              # passthrough to coverage.py; default: its own auto-detection
    # html_dir = "reports/coverage-html" # default: none (no HTML report generated)
    # fail_under = 85                    # default: none (no threshold enforced)
    # contexts = false                   # default; true calls cov.switch_context(test_id) per test
    # -- respects your own .coveragerc/[tool.coverage] for everything else
    #    (omit, include, branch, ...); pyrunner only ever sets data_file/
    #    data_suffix/source. A whole-run/whole-file metric only -- never
    #    added to per-test output.

    # junit_xml = "report.xml"      # override the managed <report_dir>/report.xml
    # json_output = "results.json"  # override the managed <report_dir>/results.json
    # html_report = true            # equivalent to passing --html-report

    # junit_logs = "off"            # "system-out"/"split": captured stdout/stderr into JUnit XML
    # junit_infra_errors = false    # true: timeout-kill/crash render as <error>, not <failure>
    # strict_teardown = true        # false: broken teardown -> teardown_failed property, not failure
    # full_trace = false            # true: keep pyrunner-internal frames in failure tracebacks

Unknown [pyrunner] keys and mis-nested top-level tables (a bare
[workers] instead of [pyrunner.workers]) produce a stderr warning --
never an error, so configs written for other pyrunner versions still
load.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Always resolved for the type checker; requires-python >=3.12
    # guarantees this at runtime too, but we still fall back gracefully
    # in case pyrunner ever runs under an older interpreter.
    import tomllib
else:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        tomllib = None


# Every scalar key ever read out of the [pyrunner] table (unknown
# keys used to be silently ignored, so a typo'd option quietly
# ran the suite with defaults). Grep-derived from `config.get(...)`
# call sites; extend when adding an option.
KNOWN_KEYS = frozenset(
    {
        "root",
        "num_workers",
        "timeout",
        "import_timeout",
        "order",
        "seed",
        "reporter",
        "fully_parallel",
        "reports_dir",
        "report_name",
        "report_timestamp",
        "keep_reports",
        "artifact_mode",
        "trace",
        "screenshot",
        "logs",
        "browser",
        "headed",
        "registered_tags",
        "strict_tags",
        "junit_xml",
        "json_output",
        "html_report",
        "junit_logs",
        "strict_teardown",
        "full_trace",
        "junit_infra_errors",
    }
)

# Nested tables under [pyrunner.<name>]. A bare top-level [<name>] is
# the classic mis-nesting footgun this module's docstring warns about
# -- now detected instead of just documented.
KNOWN_TABLES = frozenset(
    {
        "workers",
        "projects",
        "grouping",
        "fail_policy",
        "history",
        "log_redaction",
        "quarantine",
        "coverage",
    }
)


def _default_warn(message: str) -> None:
    print(f"pyrunner: config warning: {message}", file=sys.stderr)


def load_config(path: str, warn=None) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    if tomllib is None:
        raise RuntimeError(
            f"Found {path} but this Python ({sys.version.split()[0]}) lacks tomllib "
            f"(needs 3.11+). Upgrade Python, or don't rely on a config file and pass "
            f"all options via CLI flags instead."
        )
    with open(p, "rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            # The raw TOMLDecodeError has line/column but no filename --
            # useless when the config was picked up implicitly from cwd.
            raise ValueError(f"Could not parse {path}: {e}") from e

    # Warnings, never errors: an unknown key must not brick a config
    # that a newer/older pyrunner wrote, it just should not be silent.
    warn = warn or _default_warn
    for key in data:
        if key == "pyrunner":
            continue
        hint = f" -- did you mean [pyrunner.{key}]?" if key in KNOWN_TABLES else ""
        warn(f"top-level {key!r} in {path} is ignored{hint}")
    section = data.get("pyrunner", {})
    for key, value in section.items():
        if key in KNOWN_TABLES and isinstance(value, dict):
            continue
        if key not in KNOWN_KEYS:
            warn(f"unknown key {key!r} in [pyrunner] is ignored (typo?)")
    return section
