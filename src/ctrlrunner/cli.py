import argparse
import re
import sys
import time
from pathlib import Path

from . import __version__
from .config.config import load_config
from .config.projects import load_projects, resolve_project_names, run_projects
from .config.tag_registry import (
    TagValidationError,
    format_unregistered_tags_warning,
    load_tag_registry,
    validate_tags,
    warn_unregistered_cli_tags,
)
from .core.registry import get_tests
from .core.selection import select_tests
from .execution.coverage_support import finalize_coverage, prepare_data_dir, resolve_coverage_config
from .execution.fail_policy import resolve_fail_policy
from .execution.flaky import compute_flaky_report, format_flaky_report
from .execution.orchestrator import Orchestrator, discover_and_import, discover_and_import_multi
from .execution.quarantine import resolve_quarantine_config
from .execution.rerun import (
    RerunError,
    expand_serial_groups,
    load_failed_test_ids,
    match_changed_files_to_test_ids,
    match_rerun_ids,
    resolve_changed_files,
    resolve_repo_root,
)
from .execution.worker_budget import load_worker_constraints, resolve_num_workers
from .reporting import list_output
from .reporting.grouping import load_grouping_dimensions
from .reporting.history import (
    HistoryReporter,
    HistoryStore,
    compute_near_timeout_test_ids,
    resolve_history_config,
)
from .reporting.log_redaction import resolve_redaction_patterns
from .reporting.manifest import build_manifest, write_manifest
from .reporting.report_paths import find_latest_report_dir, resolve_report_dir
from .reporting.reporters import build_reporters

# A run that selected zero tests exits with this
# distinct code instead of 0 -- a typo'd --tag/--test-id (or a wrong
# root) must never produce a green CI run that tested nothing. Rerun
# flags (--last-failed & co) matching zero are exempt: "no failures to
# rerun" / "nothing changed" is a legitimate success.
EXIT_NO_TESTS_SELECTED = 4


def _split_csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _num_workers_arg(value: str):
    """argparse type for -n/--num-workers: 'auto' and 'N%' pass through
    as strings (resolved later by resolve_num_workers), an int string
    >= 1 becomes an int -- anything else fails at parse time with the
    usage text instead of surfacing mid-run."""
    if value == "auto" or (value.endswith("%") and value[:-1].isdigit() and int(value[:-1]) >= 1):
        return value
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer, 'auto', or 'N%' (e.g. '50%'), got {value!r}"
        ) from None
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value!r}")
    return parsed


def _regex_arg(value: str):
    """argparse type= for --grep/--grep-not: a bad regex fails at parse
    time with a clean usage error (exit 2), the same safe path
    -n/--num-workers already uses via _num_workers_arg -- never a raw
    re.error traceback deep inside select_tests()."""
    try:
        re.compile(value)
    except re.error as e:
        raise argparse.ArgumentTypeError(f"invalid regular expression: {e}") from None
    return value


def _resolve_worker_settings(args, config):
    """CLI > config > default ('auto') resolution for num_workers, plus
    the [ctrlrunner.workers] constraint table and the fully_parallel
    default -- all validated here so a config typo fails fast with a
    clear message instead of mid-run."""
    try:
        num_workers = resolve_num_workers(
            args.num_workers if args.num_workers is not None else config.get("num_workers")
        )
    except ValueError as e:
        print(f"Error: invalid num_workers config: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        worker_constraints = load_worker_constraints(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.workers] config: {e}", file=sys.stderr)
        sys.exit(1)
    fully_parallel = config.get("fully_parallel", False)
    if not isinstance(fully_parallel, bool):
        print(
            f"Error: invalid fully_parallel config: expected true/false, got {fully_parallel!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return num_workers, worker_constraints, fully_parallel


def _resolve_strict_teardown(config) -> bool:
    """strict_teardown (default true) fails a passing test
    whose fixture teardown raised; false downgrades that to a
    teardown_failed property on the result."""
    strict_teardown = config.get("strict_teardown", True)
    if not isinstance(strict_teardown, bool):
        print(
            f"Error: invalid strict_teardown config: expected true/false, got {strict_teardown!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return strict_teardown


def _build_reporters_or_exit(names, json_output):
    try:
        return build_reporters(names, json_output=json_output)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


_LOOPBACK_BINDS = {"127.0.0.1", "localhost", "::1"}


def _resolve_bind_host(bind: str, allow_remote: bool) -> str:
    """Guards the UI / report servers against being exposed on a network
    by accident. Their only access controls are a localhost Host/Origin
    check plus a per-session token (see ctrlrunner/ui/localsec.py) -- that's
    appropriate for loopback, but binding a routable interface would hand
    that surface to anyone who can reach the port. Refuse a non-loopback
    bind unless the operator explicitly opts in with --allow-remote."""
    if bind not in _LOOPBACK_BINDS and not allow_remote:
        print(
            f"Error: refusing to bind to non-loopback address {bind!r} without "
            f"--allow-remote. The UI/report servers authenticate only via a localhost "
            f"Host/Origin check and a per-session token, so exposing them on a network "
            f"is unsafe. Pass --allow-remote to override at your own risk.",
            file=sys.stderr,
        )
        sys.exit(1)
    return bind


class _ResetOnRunStartReporter:
    """run_projects() reuses the SAME console reporter instances
    across every project in a multi-project invocation (its own
    per-project loop is internal to projects.py, invisible from here) --
    LineReporter's `_seen` set (and any other reporter's per-run state)
    would otherwise keep accumulating test_ids from earlier projects,
    overshooting the next project's "[n/total]" progress fraction (e.g.
    "[26/25]"). Wraps any reporter that exposes reset() so its state is
    cleared at on_run_start -- which fires exactly once per project,
    right at the top of that project's run, since each project gets its
    own Orchestrator.run() call. Delegates every other attribute
    unchanged, so it's a transparent duck-typed stand-in wherever the
    orchestrator calls console reporter methods."""

    def __init__(self, inner):
        self._inner = inner

    def on_run_start(self, total):
        reset = getattr(self._inner, "reset", None)
        if reset is not None:
            reset()
        self._inner.on_run_start(total)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _show_report(argv):
    parser = argparse.ArgumentParser(prog="ctrlrunner show-report")
    parser.add_argument(
        "path",
        nargs="?",
        default="reports/html-report/report.html",
        help="HTML report file or its containing directory",
    )
    parser.add_argument("--port", type=int, default=0, help="Port (0 = pick a free one)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Address to bind to (default: 127.0.0.1). Non-loopback requires --allow-remote.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Permit binding a non-loopback address. The report server serves its whole "
        "directory with no authentication -- exposing it on a network is unsafe.",
    )
    args = parser.parse_args(argv)

    from .ui.show_report import serve_report

    bind = _resolve_bind_host(args.bind, args.allow_remote)
    try:
        serve_report(
            args.path, port=args.port, open_browser=not args.no_browser, block=True, bind=bind
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def _build_ui_parser(add_help: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctrlrunner ui", add_help=add_help)
    parser.add_argument("root", nargs="?", default=None, help="Directory to discover tests in")
    parser.add_argument("-n", "--num-workers", type=_num_workers_arg, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Address to bind the UI server to (default: 127.0.0.1). Non-loopback "
        "addresses require --allow-remote.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Permit binding a non-loopback address. The UI server has only a "
        "localhost Host/Origin check plus a per-session token -- exposing it on a "
        "network is unsafe; use only in a trusted, isolated environment.",
    )
    parser.add_argument("--config", default="ctrlrunner.toml")
    parser.add_argument(
        "--trace", choices=["off", "on", "retain-on-failure", "on-first-retry"], default=None
    )
    parser.add_argument("--screenshot", choices=["off", "on", "only-on-failure"], default=None)
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default=None)
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run browsers headed. --no-headed explicitly forces headless, "
        "overriding a truthy ctrlrunner.toml 'headed' (default: headless)",
    )
    return parser


def _ui(argv):
    from .config.addoption import AddoptionError, collect_declarations
    from .core.options import set_options

    # Same two-phase parse as the run command (see _parse_run_args /
    # _guess_root): conftests are imported to learn ctrlrunner_addoption
    # flags, then the real parser (with those flags materialized)
    # parses argv. root is found via _guess_root rather than trusted
    # from this first parse_known_args, since it's the token vulnerable
    # to argparse's positional-run ambiguity against unknown flags.
    base_parser = _build_ui_parser(add_help=False)
    args_a, _unknown = base_parser.parse_known_args(argv)
    config_a = load_config(args_a.config)
    guessed_root = _guess_root(argv, base_parser)

    try:
        shim = collect_declarations([guessed_root or config_a.get("root") or "tests"])
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(
            f"Error: while importing conftest for option declarations: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = _build_ui_parser(add_help=True)
    try:
        shim.apply_to(parser)
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    root = args.root or config.get("root") or "tests"
    try:
        options = shim.resolve(config.get("options", {}), args)
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    set_options(options)
    num_workers, worker_constraints, fully_parallel = _resolve_worker_settings(args, config)
    timeout = args.timeout if args.timeout is not None else config.get("timeout", 30.0)
    headed = args.headed if args.headed is not None else config.get("headed", False)
    playwright_config = {
        "browser_name": args.browser or config.get("browser", "chromium"),
        "headless": not headed,
        "trace_mode": args.trace or config.get("trace", "off"),
        "screenshot_mode": args.screenshot or config.get("screenshot", "off"),
    }

    from .ui.ui_server import serve_ui

    try:
        tag_registry = load_tag_registry(config)  # UI Mode always treats this as warning-only
    except ValueError as e:
        print(f"Error: invalid registered_tags config: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        grouping_dimensions = load_grouping_dimensions(config)
    except ValueError as e:
        print(f"Error: invalid [grouping] config: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        quarantine_config = resolve_quarantine_config(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.quarantine] config: {e}", file=sys.stderr)
        sys.exit(1)
    bind = _resolve_bind_host(args.bind, args.allow_remote)
    serve_ui(
        root,
        num_workers=num_workers,
        timeout=timeout,
        port=args.port,
        open_browser=not args.no_browser,
        block=True,
        playwright_config=playwright_config,
        options=options,
        tag_registry=tag_registry,
        grouping_dimensions=grouping_dimensions,
        quarantine=quarantine_config,
        bind=bind,
        worker_constraints=worker_constraints,
        fully_parallel=fully_parallel,
        strict_teardown=_resolve_strict_teardown(config),
    )


def _flaky_report(argv):
    parser = argparse.ArgumentParser(prog="ctrlrunner flaky-report")
    parser.add_argument(
        "--window",
        type=int,
        default=None,
        help="How many recent runs per test to consider (default: config's "
        "[ctrlrunner.history].window_runs, or 20)",
    )
    parser.add_argument("--project", default=None, help="Scope to a single project's history")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", default=None, help="Write to a file instead of stdout")
    parser.add_argument("--config", default="ctrlrunner.toml")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    try:
        history_config = resolve_history_config(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.history] config: {e}", file=sys.stderr)
        sys.exit(1)
    if not history_config.enabled:
        print(
            "Error: [ctrlrunner.history] is disabled -- flaky-report needs history data.",
            file=sys.stderr,
        )
        sys.exit(1)

    reports_dir = config.get("reports_dir", "reports")
    history_db_path = history_config.db_path or str(Path(reports_dir) / ".history.db")
    if not Path(history_db_path).exists():
        print(
            f"Error: no history database found at {history_db_path} -- "
            f"run tests at least a few times first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        quarantine_config = resolve_quarantine_config(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.quarantine] config: {e}", file=sys.stderr)
        sys.exit(1)
    window = args.window if args.window is not None else history_config.window_runs

    with HistoryStore(history_db_path) as store:
        stats = compute_flaky_report(store, quarantine_config, project=args.project, window=window)

    output = format_flaky_report(stats, fmt=args.format)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote flaky report ({len(stats)} test(s)) to {args.output}")
    else:
        print(output)
    sys.exit(0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "show-report":
        return _show_report(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "ui":
        return _ui(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "flaky-report":
        return _flaky_report(sys.argv[2:])

    args, shim = _parse_run_args()
    return _run_main(args, shim)


def _build_run_parser(add_help: bool = True) -> argparse.ArgumentParser:
    """The run subcommand's full argparse surface, buildable twice: once
    with add_help=False for the phase-A parse_known_args (so -h can't
    exit early with help that lacks the conftest-declared custom
    options), and once with add_help=True for the real phase-B parse.
    --version stays registered here, so `ctrlrunner --version` exits in
    phase A before any conftest import."""
    parser = argparse.ArgumentParser(prog="ctrlrunner", add_help=add_help)
    parser.add_argument("--version", action="version", version=f"ctrlrunner {__version__}")
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="Directory to discover test_*.py files in, or a single test file "
        "(falls back to ctrlrunner.toml's 'root', then 'tests')",
    )
    parser.add_argument("-n", "--num-workers", type=_num_workers_arg, default=None)
    parser.add_argument("--timeout", type=float, default=None, help="Default per-test timeout (s)")
    parser.add_argument(
        "--import-timeout",
        type=float,
        default=None,
        help="Watchdog budget (s) for a worker's suite-import phase before it is "
        "hard-killed (default: 60). Raise for suites with heavy imports.",
    )
    parser.add_argument(
        "--order",
        choices=["declared", "alpha", "random"],
        default=None,
        help="Unit scheduling order (default: declared -- registration/selection "
        "order, unchanged). 'alpha' sorts by file/class key; 'random' shuffles "
        "(use --seed to reproduce). Never reorders tests WITHIN a file or serial "
        "class -- only which unit a worker picks up first.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for --order random. If omitted with --order random, one is "
        "generated and printed to stderr so the run can be reproduced.",
    )

    parser.add_argument(
        "--reports-dir", default=None, help="Base directory for reports (default: reports)"
    )
    parser.add_argument(
        "--report-name", default=None, help="Report subdirectory name (default: html-report)"
    )
    parser.add_argument(
        "--report-timestamp",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Append a timestamp to the report directory name. --no-report-timestamp "
        "explicitly forces it off, overriding a truthy ctrlrunner.toml 'report_timestamp'",
    )
    parser.add_argument(
        "--keep-reports",
        type=int,
        default=None,
        help="How many timestamped report dirs to retain (default: 10)",
    )
    parser.add_argument(
        "--artifact-mode",
        choices=["files", "base64"],
        default=None,
        help="How screenshots are stored in the HTML report (default: files). "
        "base64 only applies to images -- traces always stay as separate files.",
    )

    parser.add_argument(
        "--junit-xml",
        default=None,
        help="Override JUnit XML path (default: <report_dir>/report.xml)",
    )
    parser.add_argument(
        "--full-trace",
        action="store_true",
        help="Show full failure tracebacks including ctrlrunner-internal frames "
        "(default: internal frames are filtered out for readability).",
    )
    parser.add_argument(
        "--junit-logs",
        choices=["off", "system-out", "split"],
        default=None,
        help="Embed captured stdout/stderr in the JUnit XML: 'system-out' puts "
        "both streams in <system-out>, 'split' routes stderr to <system-err>. "
        "Requires --logs capture to be on for logs to exist. Default: off.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Override JSON path (default: <report_dir>/results.json)",
    )
    parser.add_argument(
        "--html-report",
        nargs="?",
        const="__default__",
        default=None,
        help="Generate an HTML report. With no value: <report_dir>/report.html. "
        "With a value: write to that exact path instead.",
    )
    parser.add_argument(
        "--reporter",
        default=None,
        help="Comma-separated: line,dots,json, or a custom 'module.path:ClassName'",
    )
    parser.add_argument("--config", default="ctrlrunner.toml")

    parser.add_argument(
        "--trace",
        choices=["off", "on", "retain-on-failure", "on-first-retry"],
        default=None,
        help="Playwright trace capture mode (default: off)",
    )
    parser.add_argument(
        "--screenshot",
        choices=["off", "on", "only-on-failure"],
        default=None,
        help="Playwright screenshot capture mode (default: off)",
    )
    parser.add_argument(
        "--logs",
        choices=["off", "on", "only-on-failure"],
        default=None,
        help="Capture stdout/stderr/logging per test (default: off)",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Measure code coverage across all workers via coverage.py "
        "(requires the 'coverage' extra: pip install ctrlrunner[coverage])",
    )
    parser.add_argument(
        "--coverage-html",
        nargs="?",
        const="__default__",
        default=None,
        help="Generate a coverage.py HTML report (implies --coverage). "
        "Bare flag: <report-dir>/coverage-html. Or pass an explicit directory.",
    )
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default=None,
        help="Browser for ctrlrunner.playwright_fixtures (default: chromium)",
    )
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run browsers headed. --no-headed explicitly forces headless, "
        "overriding a truthy ctrlrunner.toml 'headed' (default: headless)",
    )

    parser.add_argument("--test-id", help="Comma-separated exact TestItem.id values to run")
    parser.add_argument(
        "--case-id", help="Comma-separated exact case IDs to run (e.g. TC-100-chromium)"
    )
    parser.add_argument(
        "--case-id-prefix",
        help="Comma-separated case ID prefixes (e.g. TC-100 selects every parametrized variant)",
    )
    parser.add_argument("--tag", help="Comma-separated tags; a test matches if it has any of them")
    parser.add_argument(
        "--tag-not",
        help="Comma-separated tags to EXCLUDE; a test is dropped if it has any of them",
    )
    parser.add_argument(
        "--grep",
        type=_regex_arg,
        help="Regex matched against each test's full id (module::[Class.]func[params]); "
        "only matching tests run",
    )
    parser.add_argument(
        "--grep-not",
        type=_regex_arg,
        help="Regex matched against each test's full id; matching tests are EXCLUDED",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Comma-separated project names to run (see [ctrlrunner.projects.*] "
        "in config). Unset: today's single-project behavior, unchanged.",
    )

    parser.add_argument(
        "--max-failures",
        type=int,
        default=None,
        help="Stop the run once this many tests have failed (0/unset = unlimited)",
    )
    parser.add_argument(
        "--max-timeouts",
        type=int,
        default=None,
        help="Stop the run once this many tests have been hard-killed by timeout "
        "(0/unset = unlimited)",
    )
    parser.add_argument(
        "--stop-on-worker-crash",
        action="store_true",
        help="Stop the run if a worker process crashes on its own "
        "(distinct from a timeout hard-kill)",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Sugar for --max-failures 1")
    parser.add_argument(
        "--fail-on-flaky",
        action="store_true",
        help="Exit non-zero if any test passed only after a retry this run "
        "(individual JUnit/JSON entries stay 'passed' with a flaky=true property)",
    )

    parser.add_argument(
        "--last-failed",
        action="store_true",
        help="Rerun only tests that failed in the most recent report "
        "(results.json is written by every run)",
    )
    parser.add_argument(
        "--failed-from", default=None, help="Rerun only tests that failed in this JSON report file"
    )
    parser.add_argument(
        "--changed-since",
        default=None,
        help="Rerun only tests in files changed since this git ref (e.g. origin/main)",
    )
    parser.add_argument(
        "--strict-tags",
        action="store_true",
        help="Fail collection (0 tests run) if any test uses a tag not in "
        "registered_tags, overriding ctrlrunner.toml's strict_tags for this run",
    )

    parser.add_argument(
        "--list",
        choices=["text", "json", "md"],
        default=None,
        help="List discovered (and selected) tests without running them",
    )
    parser.add_argument(
        "--list-output", default=None, help="Write --list output to this file instead of stdout"
    )
    parser.add_argument(
        "--list-fields",
        default=None,
        help="Comma-separated fields for text/md --list output "
        f"(default: id,caseId,tags). json always includes every field. "
        f"Valid: {', '.join(list_output.ALL_FIELDS)}",
    )
    return parser


def _guess_root(argv: list, parser: argparse.ArgumentParser) -> str | None:
    """Deterministically finds the `root` positional in `argv` WITHOUT
    relying on argparse's parse_known_args -- which, given an unknown
    flag whose value looks positional (`--env staging spec/`), binds
    the FIRST available positional-looking token to `root` ("staging",
    wrongly) instead of the intended one, since custom options aren't
    registered yet at this point. That silently sends conftest
    discovery to a nonexistent root, custom options never get declared,
    and the real parse then fails outright.

    Instead, walk argv once: for each token starting with '-', consult
    `parser`'s already-registered actions to know whether it consumes a
    following value (nargs=0 actions -- store_true/store_false/help/
    version/BooleanOptionalAction -- don't; everything else does).
    An UNKNOWN flag (not yet declared -- we don't know its arity before
    collecting ctrlrunner_addoption) is assumed to consume one value,
    matching the common case (`--env staging`) and the recommended
    invocation order (root first, flags after) that sidesteps the
    ambiguity entirely for any flag shape. `--flag=value` single-token
    form is recognized and never consumes a second token. The first
    remaining non-flag token is the root guess."""
    nargs0_options: set = set()
    for action in parser._actions:
        if action.nargs == 0:
            nargs0_options.update(action.option_strings)
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("-") and tok != "-":
            if "=" in tok:
                i += 1
                continue
            i += 1 if tok in nargs0_options else 2
            continue
        return tok
    return None


def _parse_run_args():
    """Two-phase parse enabling ctrlrunner_addoption: conftests must be
    imported to learn the custom flags, but the root that locates
    conftests is itself a CLI arg. Phase A (parse_known_args, no -h)
    extracts --config/--project (unambiguous -- always an explicit
    `--flag value` pair); root is found via _guess_root instead, since
    it's the one token vulnerable to argparse's positional-run
    ambiguity. Conftests are then imported and their
    ctrlrunner_addoption declarations collected; phase B parses for
    real with the declared flags materialized (typed, validated,
    visible in --help) -- now unambiguous, since every flag actually
    used is registered. Returns (args, shim)."""
    from .config.addoption import AddoptionError, collect_declarations

    base_parser = _build_run_parser(add_help=False)
    args_a, _unknown = base_parser.parse_known_args()
    config_a = load_config(args_a.config)
    guessed_root = _guess_root(sys.argv[1:], base_parser)

    def declaration_roots() -> list[str]:
        roots = [guessed_root or config_a.get("root") or "tests"]
        for name in _split_csv(args_a.project) or []:
            # Best effort only -- an invalid [projects] config gets its
            # proper fail-fast error later in _run_main, as today.
            try:
                project = load_projects(config_a).get(name)
            except ValueError:
                break
            if project is not None:
                roots.extend(project.tests_dir)
        return roots

    try:
        shim = collect_declarations(declaration_roots())
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(
            f"Error: while importing conftest for option declarations: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = _build_run_parser(add_help=True)
    try:
        shim.apply_to(parser)
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    args = parser.parse_args()
    return args, shim


def _run_main(args, shim):
    from .config.addoption import AddoptionError
    from .core.options import set_options

    config = load_config(args.config)

    try:
        grouping_dimensions = load_grouping_dimensions(config)
    except ValueError as e:
        print(f"Error: invalid [grouping] config: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        projects_config = load_projects(config)
    except ValueError as e:
        print(f"Error: invalid [projects] config: {e}", file=sys.stderr)
        sys.exit(1)

    requested_projects = _split_csv(args.project)
    if requested_projects:
        try:
            resolve_project_names(requested_projects, projects_config)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Seed the custom-options store NOW, before the --list/rerun
    # branches below import test modules in THIS process -- so
    # module-level get_option(...) in test files sees real values on
    # discovery-only paths too (those imports use force_reload=True,
    # re-executing modules already imported during declaration
    # collection). Workers get the same dict via run_worker's args.
    try:
        base_options = shim.base_values(config.get("options", {}))
    except AddoptionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    cli_option_values = shim.cli_values(args)
    options = {**base_options, **cli_option_values}
    set_options(options)

    root = args.root or config.get("root") or "tests"
    num_workers, worker_constraints, fully_parallel = _resolve_worker_settings(args, config)
    timeout = args.timeout if args.timeout is not None else config.get("timeout", 30.0)
    import_timeout = (
        args.import_timeout
        if args.import_timeout is not None
        else config.get("import_timeout", 60.0)
    )
    if (
        isinstance(import_timeout, bool)
        or not isinstance(import_timeout, (int, float))
        or import_timeout <= 0
    ):
        print(
            f"Error: invalid import_timeout config: expected a positive number, "
            f"got {import_timeout!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    import_timeout = float(import_timeout)
    order = args.order or config.get("order", "declared")
    if order not in ("declared", "alpha", "random"):
        print(
            f"Error: invalid order config: expected declared/alpha/random, got {order!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    seed = args.seed if args.seed is not None else config.get("seed")
    if order == "random":
        if seed is None:
            import random as _random_module

            seed = _random_module.SystemRandom().randrange(2**31)
            print(
                f"ctrlrunner: --order random with no --seed -- using seed {seed}", file=sys.stderr
            )
        elif not isinstance(seed, int) or isinstance(seed, bool):
            print(f"Error: invalid seed config: expected an integer, got {seed!r}", file=sys.stderr)
            sys.exit(1)
    reports_dir = args.reports_dir or config.get("reports_dir", "reports")
    report_name = args.report_name or config.get("report_name", "html-report")

    strict_override = True if args.strict_tags else None
    try:
        tag_registry = load_tag_registry(config, strict_override=strict_override)
    except ValueError as e:
        print(f"Error: invalid registered_tags config: {e}", file=sys.stderr)
        sys.exit(1)
    cli_tags = _split_csv(args.tag) or []
    warn_unregistered_cli_tags(cli_tags, tag_registry)
    cli_exclude_tags = _split_csv(args.tag_not) or []
    warn_unregistered_cli_tags(cli_exclude_tags, tag_registry)
    cli_grep = args.grep
    cli_grep_not = args.grep_not

    # A project's own `tags` filter is a config value, not something
    # a person typed on this invocation's command line -- so a typo
    # deserves the same clear "unregistered tag" treatment the CLI's
    # own --tag/test-tag validation gets, not a silent "0 tests
    # selected" further down the pipeline. Checked once here,
    # up front, so it applies uniformly whether this invocation ends
    # up going through --list or a real run.
    if requested_projects and tag_registry is not None:
        for _name in requested_projects:
            _project_tags = projects_config[_name].tags
            if not _project_tags:
                continue
            _unregistered = sorted(tag_registry.unregistered(_project_tags))
            if _unregistered:
                _message = (
                    f"[ctrlrunner.projects.{_name}] tags: "
                    f"{format_unregistered_tags_warning(_unregistered)}"
                )
                if tag_registry.strict:
                    print(f"Error: {_message}", file=sys.stderr)
                    sys.exit(1)
                print(f"Warning: {_message}", file=sys.stderr)

    # Resolved up here (rather than only below, near the run itself) so
    # the --list branch can consult history for the near-timeout
    # risk flag before it exits. Side-effect-free and cheap; the run
    # path below reuses this same value.
    try:
        history_config = resolve_history_config(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.history] config: {e}", file=sys.stderr)
        sys.exit(1)

    if args.list:
        # --list is a pure discovery-time view over the selection
        # pipeline; it intentionally runs (and exits) before rerun
        # flag resolution below, since --last-failed/--failed-from/
        # --changed-since are run-time concepts needing a previous
        # run's results.json, not applicable to a discovery-only view.
        if requested_projects:
            from .core import registry as registry_module

            all_tests = []
            for name in requested_projects:
                project = projects_config[name]
                registry_module.clear_tests()
                discover_and_import_multi(project.tests_dir, force_reload=True)
                project_tests = get_tests()
                for t in project_tests:
                    t.project = name
                # --list is a view over exactly the same selection
                # pipeline a real run uses -- a real run (run_projects())
                # applies the project's own `tags` filter unless an
                # explicit CLI --tag overrides it entirely; --list must
                # match that, not just list every test under the
                # project's tests_dir regardless of its tags config.
                effective_tags = cli_tags if cli_tags else (project.tags or None)
                all_tests.extend(
                    select_tests(
                        project_tests,
                        tags=effective_tags,
                        exclude_tags=cli_exclude_tags or None,
                        grep=cli_grep,
                        grep_not=cli_grep_not,
                    )
                )
        else:
            discover_and_import(root, force_reload=True)
            all_tests = get_tests()

        if tag_registry is not None:
            unregistered = validate_tags(all_tests, tag_registry)
            if unregistered:
                message = format_unregistered_tags_warning(unregistered)
                if tag_registry.strict:
                    print(f"Error: {message}", file=sys.stderr)
                    sys.exit(1)
                print(f"Warning: {message}", file=sys.stderr)

        tests = select_tests(
            all_tests,
            test_ids=_split_csv(args.test_id),
            case_ids=_split_csv(args.case_id),
            case_id_prefixes=_split_csv(args.case_id_prefix),
            tags=cli_tags,
            exclude_tags=cli_exclude_tags or None,
            grep=cli_grep,
            grep_not=cli_grep_not,
        )

        # Stamp the hang-risk near-timeout flag onto each selected
        # test, using its HISTORICAL median duration vs. its configured
        # timeout (--list never runs anything, so live duration doesn't
        # exist yet -- history is the only signal available here). Only
        # when history is enabled and a store already exists on disk;
        # otherwise every test simply stays unflagged (risk_flag=False).
        if history_config.enabled:
            history_db_path = history_config.db_path or str(Path(reports_dir) / ".history.db")
            if Path(history_db_path).exists():
                with HistoryStore(history_db_path) as store:
                    timeouts = {
                        t.id: (t.timeout if t.timeout is not None else timeout) for t in tests
                    }
                    flagged = compute_near_timeout_test_ids(
                        [t.id for t in tests],
                        timeouts,
                        store,
                        project=(
                            requested_projects[0]
                            if requested_projects and len(requested_projects) == 1
                            else None
                        ),
                        window=history_config.window_runs,
                    )
                for t in tests:
                    t.risk_flag = t.id in flagged

        try:
            output = list_output.format_list(tests, args.list, fields=_split_csv(args.list_fields))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if args.list_output:
            Path(args.list_output).write_text(output, encoding="utf-8")
            print(f"Listed {len(tests)} test(s) to {args.list_output}")
        else:
            print(output)
        sys.exit(0)

    rerun_requested = args.last_failed or args.failed_from or args.changed_since
    rerun_test_ids = None
    if rerun_requested:
        # force_reload=True: defends against the same class of problem
        # --project's run_projects() already handles -- if ctrlrunner's
        # CLI entry point ever gets invoked twice in the same process
        # (e.g. from a test harness, or an embedding tool), a plain
        # re-import would be a sys.modules no-op and see zero tests
        # after a registry reset. Real separate CLI process invocations
        # (the normal case) are unaffected either way.
        discover_and_import(root, force_reload=True)
        all_tests = get_tests()
        current_ids = [t.id for t in all_tests]

        requested_ids = []
        try:
            if args.last_failed:
                latest_dir = find_latest_report_dir(reports_dir, report_name)
                if latest_dir is None:
                    raise RerunError(
                        "No previous report found -- run tests at least once "
                        "(with --reporter including 'json') before using --last-failed."
                    )
                requested_ids.extend(load_failed_test_ids(latest_dir / "results.json"))
            if args.failed_from:
                requested_ids.extend(load_failed_test_ids(Path(args.failed_from)))
            if args.changed_since:
                repo_root = resolve_repo_root()
                changed_files = resolve_changed_files(args.changed_since)
                requested_ids.extend(
                    match_changed_files_to_test_ids(changed_files, all_tests, repo_root)
                )
        except RerunError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # A rerun flag was given: the result is now an EXPLICIT
        # selection, even if it resolves to zero ids. rerun_test_ids
        # stays a real (possibly empty) list from this point on --
        # never None again -- so downstream `test_ids=... if ... is
        # not None else ...` never mistakes "matched nothing" for
        # "no rerun flag was given" and falls through to running
        # everything.
        rerun_test_ids = match_rerun_ids(requested_ids, current_ids)
        # A rerun selection that touches a serial class pulls
        # in the WHOLE class -- a partial serial group would run
        # skip-on-fail/group-retries over a subset the author never
        # intended. Explicit --test-id selections are not expanded.
        rerun_test_ids = expand_serial_groups(rerun_test_ids, all_tests)
        if not rerun_test_ids:
            print(
                "Warning: --last-failed/--failed-from/--changed-since matched zero tests "
                "-- 0 tests will run.",
                file=sys.stderr,
            )

        if args.test_id:
            print(
                "Warning: --last-failed/--failed-from/--changed-since is set -- "
                "the explicit --test-id value is ignored for this run.",
                file=sys.stderr,
            )

    report_timestamp = (
        args.report_timestamp
        if args.report_timestamp is not None
        else config.get("report_timestamp", False)
    )
    keep_reports = (
        args.keep_reports if args.keep_reports is not None else config.get("keep_reports", 10)
    )
    artifact_mode = args.artifact_mode or config.get("artifact_mode", "files")

    trace_mode = args.trace or config.get("trace", "off")
    screenshot_mode = args.screenshot or config.get("screenshot", "off")
    logs_mode = args.logs or config.get("logs", "off")
    try:
        log_redaction = resolve_redaction_patterns(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.log_redaction] config: {e}", file=sys.stderr)
        sys.exit(1)
    browser_name = args.browser or config.get("browser", "chromium")
    headed = args.headed if args.headed is not None else config.get("headed", False)
    playwright_config = {
        "browser_name": browser_name,
        "headless": not headed,
        "trace_mode": trace_mode,
        "screenshot_mode": screenshot_mode,
    }

    report_dir = resolve_report_dir(reports_dir, report_name, report_timestamp, keep_reports)

    junit_xml = args.junit_xml or config.get("junit_xml") or str(report_dir / "report.xml")
    json_output = args.json_output or config.get("json_output") or str(report_dir / "results.json")

    junit_logs = args.junit_logs or config.get("junit_logs", "off")
    if junit_logs not in ("off", "system-out", "split"):
        print(
            f"Error: junit_logs must be 'off', 'system-out' or 'split', got {junit_logs!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    strict_teardown = _resolve_strict_teardown(config)
    junit_infra_errors = config.get("junit_infra_errors", False)
    if not isinstance(junit_infra_errors, bool):
        print(
            f"Error: invalid junit_infra_errors config: expected true/false, "
            f"got {junit_infra_errors!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    full_trace = bool(args.full_trace) or bool(config.get("full_trace", False))

    html_report_arg = (
        args.html_report if args.html_report is not None else config.get("html_report")
    )
    html_report_path = None
    html_artifacts_dir = report_dir
    if html_report_arg == "__default__" or html_report_arg is True:
        html_report_path = str(report_dir / "report.html")
    elif isinstance(html_report_arg, str) and html_report_arg:
        html_report_path = html_report_arg
        html_artifacts_dir = Path(html_report_arg).resolve().parent

    reporter_names = _split_csv(args.reporter) or config.get("reporter") or ["line"]
    # results.json always lands in the managed report dir even when the
    # 'json' console reporter wasn't requested -- --last-failed (and any
    # external tooling) reads it, and a line/dots-only run used to
    # silently break the NEXT run's --last-failed.
    if "json" not in reporter_names:
        reporter_names = [*reporter_names, "json"]

    try:
        Path(junit_xml).parent.mkdir(parents=True, exist_ok=True)
        Path(json_output).parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # A bad junit_xml/json_output path used to surface as a raw
        # OSError traceback -- fail with a clear message instead.
        print(f"Error: cannot create report directory: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolved here -- before console_reporters is built just below, since
    # that build needs to know whether to defer the "json" reporter -- and
    # before fail_policy/quarantine resolution, which console_reporters'
    # subsequent history_reporter.append() step depends on running only
    # after console_reporters already exists. All of coverage_config's own
    # inputs (config, args.*, report_dir, rerun_test_ids) are already
    # available by this point.
    coverage_html_dir = None
    if args.coverage_html is not None:
        coverage_html_dir = (
            str(report_dir / "coverage-html")
            if args.coverage_html == "__default__"
            else args.coverage_html
        )
    selection_filtered = bool(
        args.tag
        or args.case_id
        or args.case_id_prefix
        or (rerun_test_ids if rerun_test_ids is not None else args.test_id)
    )
    try:
        coverage_config = resolve_coverage_config(
            config,
            cli_enabled=args.coverage or args.coverage_html is not None,
            cli_html_dir=coverage_html_dir,
            report_dir=str(report_dir),
            selection_filtered=selection_filtered,
        )
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.coverage] config: {e}", file=sys.stderr)
        sys.exit(1)
    if coverage_config is not None:
        prepare_data_dir(coverage_config)

    json_deferred = coverage_config is not None and "json" in reporter_names
    console_reporters = _build_reporters_or_exit(
        [n for n in reporter_names if n != "json"] if json_deferred else reporter_names,
        json_output,
    )

    # history_config was already resolved (and validated) above the
    # --list branch -- reuse it here rather than resolving a second time.
    history_reporter = None
    history_store = None
    if history_config.enabled:
        # Deliberately NOT inside report_dir -- that directory can be
        # pruned by --keep-reports, but history is meant to accumulate
        # across many runs over time. Defaults to reports_dir's stable
        # root; [ctrlrunner.history].db_path overrides this explicitly.
        history_db_path = history_config.db_path or str(Path(reports_dir) / ".history.db")
        history_reporter = HistoryReporter(history_db_path)
        console_reporters.append(history_reporter)
        # A separate read-side connection for LPT sharding lookups
        # (Orchestrator.run() reads from this before scheduling;
        # HistoryReporter opens its own short-lived connection to write,
        # at on_run_end -- two connections to the same SQLite file is
        # fine, and keeps read/write concerns independent).
        history_store = HistoryStore(history_db_path)

    try:
        fail_policy = resolve_fail_policy(
            config,
            cli_max_failures=args.max_failures,
            cli_max_timeouts=args.max_timeouts,
            cli_fail_fast=args.fail_fast,
            cli_stop_on_worker_crash=args.stop_on_worker_crash,
        )
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.fail_policy] config: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        quarantine_config = resolve_quarantine_config(config)
    except ValueError as e:
        print(f"Error: invalid [ctrlrunner.quarantine] config: {e}", file=sys.stderr)
        sys.exit(1)

    multi_project_json_duration = None

    if requested_projects:
        # JsonReporter writes its file via on_run_end(), which each
        # project's own Orchestrator.run() calls separately -- passing
        # it through as a per-project console reporter would have each
        # project's call overwrite results.json with just THAT
        # project's results, silently losing every earlier project's
        # data. Exclude it here; write the combined JSON once at the
        # end instead, same pattern JUnit already uses.
        per_project_names = [n for n in reporter_names if n != "json"]
        per_project_console_reporters = _build_reporters_or_exit(per_project_names, json_output)
        if history_reporter is not None:
            per_project_console_reporters.append(history_reporter)
        # Reset per-run progress state (e.g. LineReporter._seen) at
        # the top of every project's run, since the same reporter
        # instances are reused across projects -- see
        # _ResetOnRunStartReporter's docstring.
        per_project_console_reporters = [
            _ResetOnRunStartReporter(r) if hasattr(r, "reset") else r
            for r in per_project_console_reporters
        ]

        # The combined JSON's `duration` field must carry the same
        # wall-clock semantics as single-project mode's (Orchestrator.run()
        # times itself with time.time() around the whole scheduler loop);
        # summing every individual test's own duration double-counts time
        # tests spent running concurrently across workers, and undercounts
        # nothing -- it's just a different, incompatible number under the
        # same field name.
        multi_project_run_start = time.time()
        try:
            reporter, multi_project = run_projects(
                requested_projects,
                projects_config,
                base_root=root,
                base_num_workers=num_workers,
                base_timeout=timeout,
                cli_num_workers=args.num_workers,
                cli_timeout=args.timeout,
                worker_constraints=worker_constraints,
                base_fully_parallel=fully_parallel,
                cli_tags=cli_tags or None,
                exclude_tags=cli_exclude_tags or None,
                grep=cli_grep,
                grep_not=cli_grep_not,
                test_ids=rerun_test_ids if rerun_test_ids is not None else _split_csv(args.test_id),
                case_ids=_split_csv(args.case_id),
                case_id_prefixes=_split_csv(args.case_id_prefix),
                console_reporters=per_project_console_reporters,
                playwright_config=playwright_config,
                base_options=base_options,
                cli_option_values=cli_option_values,
                tag_registry=tag_registry,
                grouping_dimensions=grouping_dimensions,
                fail_policy=fail_policy,
                history_store=history_store,
                history_window=history_config.window_runs,
                quarantine=quarantine_config,
                logs_mode=logs_mode,
                coverage_config=coverage_config,
                log_redaction=log_redaction,
                junit_logs=junit_logs,
                junit_infra_errors=junit_infra_errors,
                strict_teardown=strict_teardown,
                full_trace=full_trace,
                import_timeout=import_timeout,
                order=order,
                seed=seed,
            )
        except TagValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            print(
                "(collection stopped -- strict_tags/--strict-tags is enabled, 0 tests were run)",
                file=sys.stderr,
            )
            sys.exit(1)
        # Project becomes an automatic grouping dimension with no extra
        # config -- only when 2+ projects actually ran this invocation,
        # matching the same "multi_project" condition as the test_id
        # prefix and the JUnit <testsuites> wrapper.
        if multi_project:
            for r in reporter.results:
                r.groups = {**r.groups, "project": r.project or "unknown"}

        if "json" in reporter_names and coverage_config is None:
            from .reporting.reporters import JsonReporter

            total_duration = time.time() - multi_project_run_start
            JsonReporter(json_output).on_run_end(
                reporter.results, total_duration, suite_properties=reporter.suite_properties
            )
        elif "json" in reporter_names:
            multi_project_json_duration = time.time() - multi_project_run_start
    else:
        orch = Orchestrator(
            root,
            num_workers,
            timeout,
            test_ids=rerun_test_ids if rerun_test_ids is not None else _split_csv(args.test_id),
            case_ids=_split_csv(args.case_id),
            case_id_prefixes=_split_csv(args.case_id_prefix),
            tags=cli_tags,
            exclude_tags=cli_exclude_tags or None,
            grep=cli_grep,
            grep_not=cli_grep_not,
            console_reporters=console_reporters,
            playwright_config=playwright_config,
            options=options,
            tag_registry=tag_registry,
            grouping_dimensions=grouping_dimensions,
            fail_policy=fail_policy,
            history_store=history_store,
            history_window=history_config.window_runs,
            quarantine=quarantine_config,
            logs_mode=logs_mode,
            coverage_config=coverage_config,
            log_redaction=log_redaction,
            worker_constraints=worker_constraints,
            fully_parallel=fully_parallel,
            junit_logs=junit_logs,
            junit_infra_errors=junit_infra_errors,
            strict_teardown=strict_teardown,
            full_trace=full_trace,
            import_timeout=import_timeout,
            order=order,
            seed=seed,
        )
        try:
            reporter = orch.run()
        except TagValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            print(
                "(collection stopped -- strict_tags/--strict-tags is enabled, 0 tests were run)",
                file=sys.stderr,
            )
            sys.exit(1)
        multi_project = False

    # Timeline feature (2026-07-12): a single wall-clock span/start for
    # the HTML report's timeline panel, regardless of which branch above
    # ran. Multi-project mode has no single Orchestrator instance, so
    # this is computed fresh here rather than reusing either of the
    # branch-local duration variables above (which exist only
    # conditionally, depending on whether the json reporter ran).
    run_started_at = multi_project_run_start if requested_projects else orch.run_start
    run_duration_value = (
        (time.time() - multi_project_run_start) if requested_projects else orch.run_duration
    )

    coverage_summary = None
    if coverage_config is not None:
        coverage_summary = finalize_coverage(coverage_config)
        if coverage_config.hard_kills:
            print(
                f"coverage data incomplete: {coverage_config.hard_kills} worker(s) "
                "terminated without saving",
                file=sys.stderr,
            )
        if "json" in reporter_names:
            from .reporting.reporters import JsonReporter

            duration = multi_project_json_duration if requested_projects else orch.run_duration
            json_reporter = JsonReporter(json_output)
            json_reporter.set_coverage_summary(coverage_summary)
            json_reporter.on_run_end(
                reporter.results, duration, suite_properties=reporter.suite_properties
            )

    reporter.write(junit_xml, multi_project=multi_project)

    failed_test_ids = [r.test_id for r in reporter.results if r.outcome == "failed"]
    manifest = build_manifest(
        argv=sys.argv[1:],
        root=root,
        num_workers=num_workers,
        timeout=timeout,
        import_timeout=import_timeout,
        order=order,
        seed=seed if order == "random" else None,
        total_tests=len(reporter.results),
        failed_test_ids=failed_test_ids,
    )
    write_manifest(str(report_dir / "run-manifest.json"), manifest)

    if html_report_path:
        from .reporting.html_report import render_html

        report_path = Path(html_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_html(
                reporter.results,
                suite_name=Path(root).name,
                artifact_mode=artifact_mode,
                report_dir=str(html_artifacts_dir),
                coverage_summary=(
                    {"percent": coverage_summary.percent, "htmlDir": coverage_summary.html_dir}
                    if coverage_summary is not None
                    else None
                ),
                run_started_at=run_started_at,
                run_duration=run_duration_value,
                num_workers=num_workers,
            ),
            encoding="utf-8",
        )
        print(f"Reports written to {report_dir}")
        print(
            f"HTML report: {report_path} "
            f"(run 'python -m ctrlrunner show-report {report_path}' to view it)"
        )
    else:
        print(f"Reports written to {report_dir}")

    if coverage_summary is not None:
        print(f"Coverage: {coverage_summary.percent:.1f}%")
        if coverage_summary.html_dir:
            print(f"Coverage HTML report: {coverage_summary.html_dir}")

    failed = sum(1 for r in reporter.results if r.outcome == "failed")
    flaky_count = sum(1 for r in reporter.results if r.flaky)
    if flaky_count and args.fail_on_flaky:
        print(
            f"{flaky_count} test(s) passed only after a retry this run (--fail-on-flaky is set)",
            file=sys.stderr,
        )

    coverage_exit = 0
    if (
        coverage_config is not None
        and coverage_summary is not None
        and failed == 0
        and coverage_config.fail_under is not None
    ):
        if not coverage_config.fail_under_enforced:
            print(
                "coverage: fail-under not enforced -- test selection filter active",
                file=sys.stderr,
            )
        elif coverage_summary.percent < coverage_config.fail_under:
            print(
                f"coverage {coverage_summary.percent:.1f}% is below "
                f"fail-under {coverage_config.fail_under:.1f}%",
                file=sys.stderr,
            )
            coverage_exit = 1

    if history_store is not None:
        history_store.close()

    if not reporter.results and not rerun_requested:
        print(
            "Error: no tests were selected -- 0 tests ran (exit code 4). Check the "
            "test root directory and any --test-id/--case-id/--tag filters.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_TESTS_SELECTED)

    sys.exit(1 if (failed or (args.fail_on_flaky and flaky_count)) else coverage_exit)


if __name__ == "__main__":
    main()
