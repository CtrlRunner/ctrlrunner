"""
Named projects.

A project is a named override bundle over base config -- resolved the
same way CLI-vs-toml-vs-default already resolves everywhere else:
CLI flag > project config > base ctrlrunner.toml > built-in default.
`tags` in a project config is a SELECTION FILTER ("only run tests
matching these tags", identical in effect to passing --tag), NOT
metadata stamped onto tests -- this keeps "what ran" (a run-time
selection decision) cleanly separate from "what a test is" (its own
declared tags/properties).

No [ctrlrunner.projects.*] config at all = zero behavior change: no
--project flag exists to use, and the normal single-Orchestrator.run()
path is untouched.
"""

from dataclasses import dataclass, field

from ..execution.worker_budget import resolve_num_workers


@dataclass
class ProjectConfig:
    name: str
    tests_dir: list[str]
    tags: list[str] = field(default_factory=list)
    timeout: float | None = None
    # int, "auto", or "N%" -- the RAW spelling is stored (an "auto"
    # resolves on the machine that actually runs the project), but it's
    # validated at load time so a typo fails before any test runs.
    num_workers: int | str | None = None
    # tri-state: None = inherit the base fully_parallel setting.
    fully_parallel: bool | None = None
    # [ctrlrunner.projects.<name>.options] -- per-project custom option
    # values, merged over the base [ctrlrunner.options] (and under any
    # explicitly-typed CLI flags) for this project's workers.
    options: dict = field(default_factory=dict)


def load_projects(config: dict) -> dict[str, ProjectConfig]:
    """Returns {} if `[ctrlrunner.projects]` is absent entirely. Raises
    ValueError immediately (fail fast, before any test runs) for a
    project missing its required `tests_dir`, or carrying an invalid
    num_workers / fully_parallel value."""
    raw = config.get("projects")
    if not raw:
        return {}

    projects = {}
    for name, entry in raw.items():
        tests_dir = entry.get("tests_dir")
        if not tests_dir:
            raise ValueError(f"[ctrlrunner.projects.{name}] is missing required 'tests_dir'.")
        if isinstance(tests_dir, str):
            tests_dir = [tests_dir]
        num_workers = entry.get("num_workers")
        if num_workers is not None:
            try:
                resolve_num_workers(num_workers)  # validate only; raw spec is stored
            except ValueError as e:
                raise ValueError(f"[ctrlrunner.projects.{name}] num_workers: {e}") from None
        fully_parallel = entry.get("fully_parallel")
        if fully_parallel is not None and not isinstance(fully_parallel, bool):
            raise ValueError(
                f"[ctrlrunner.projects.{name}] fully_parallel: expected true/false, "
                f"got {fully_parallel!r}"
            )
        timeout = entry.get("timeout")
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
        ):
            # Same fail-fast contract as num_workers/fully_parallel: a bad
            # timeout must not survive load only to explode mid-run.
            raise ValueError(
                f"[ctrlrunner.projects.{name}] timeout: expected a positive number, got {timeout!r}"
            )
        options = entry.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(
                f"[ctrlrunner.projects.{name}] options: expected a table "
                f"([ctrlrunner.projects.{name}.options]), got {options!r}"
            )
        projects[name] = ProjectConfig(
            name=name,
            tests_dir=list(tests_dir),
            tags=list(entry.get("tags", [])),
            timeout=timeout,
            num_workers=num_workers,
            fully_parallel=fully_parallel,
            options=dict(options),
        )
    return projects


def run_projects(
    project_names,
    projects,
    *,
    base_root,
    base_num_workers,
    base_timeout,
    cli_num_workers=None,
    cli_timeout=None,
    cli_tags=None,
    exclude_tags=None,
    grep=None,
    grep_not=None,
    test_ids=None,
    case_ids=None,
    case_id_prefixes=None,
    console_reporters=None,
    cancel_event=None,
    playwright_config=None,
    tag_registry=None,
    event_subscribers=None,
    grouping_dimensions=None,
    fail_policy=None,
    history_store=None,
    history_window=20,
    logs_mode="off",
    quarantine=None,
    coverage_config=None,
    log_redaction=None,
    worker_constraints=None,
    base_fully_parallel=False,
    junit_logs="off",
    junit_infra_errors=False,
    strict_teardown=True,
    full_trace=False,
    import_timeout=None,
    order="declared",
    seed=None,
    base_options=None,
    cli_option_values=None,
    raw_config=None,
):
    """Runs each named project as its own Orchestrator.run() within this
    process, merging every project's results into one combined
    JUnitReporter. `multi_project` (the second return value) controls
    whether test_id gets a [project] prefix and JUnit gets wrapped in
    <testsuites> -- both True only when 2+ projects are actually active
    this run (see Orchestrator's own docstring for why).

    Per-project precedence for num_workers/timeout: CLI (if explicitly
    given) > the project's own config > the already-resolved base
    value. `tags`: an explicit CLI --tag overrides a project's own tags
    filter entirely (CLI stays highest precedence); otherwise the
    project's tags filter applies.

    Custom options (ctrlrunner_addoption) merge per KEY with the same
    precedence shape: an explicitly-typed CLI flag (cli_option_values)
    > the project's own [ctrlrunner.projects.<name>.options] >
    base_options (declared defaults <- [ctrlrunner.options]). The
    merged dict is what this project's workers see via get_option();
    the MAIN process keeps the global base+CLI merge (seeded in
    cli.py), since it isn't scoped to any one project.

    `fail_policy`, if given, is the SAME FailPolicyState instance passed
    to every project's Orchestrator -- --max-failures/--max-timeouts
    count across the whole multi-project invocation, not per project,
    and a threshold crossed partway through project 1 stops project 2
    from ever starting (checked via the shared cancel_event before each
    subsequent project's Orchestrator.run() call).

    `history_store`, if given, is passed to every project's Orchestrator
    the same way -- LPT sharding (ctrlrunner/sharding.py) is scoped by
    project already (durations are looked up per test_id + project), so
    no special multi-project handling is needed beyond passing the same
    store through.

    Registry reset: the test registry is module-level and never resets
    on its own between Orchestrator.run() calls, so it's cleared before
    each project's discovery here -- and Orchestrator's own
    force_reload=True (set for every project run) re-executes
    (importlib.reload) any module already in sys.modules from a
    previous project's overlapping tests_dir, since a plain re-import
    would otherwise be a no-op against the freshly-cleared registry.
    """
    import threading

    from ..core import registry as registry_module
    from ..execution.orchestrator import IMPORT_PHASE_TIMEOUT, Orchestrator
    from ..reporting.reporter import JUnitReporter

    multi_project = len(project_names) >= 2
    # Only the combined reporter ever writes XML in a multi-project run,
    # so junit_logs applies here; per-project reporters just feed it.
    combined_reporter = JUnitReporter(junit_logs=junit_logs, junit_infra_errors=junit_infra_errors)

    # A fail policy needs ONE shared cancel_event across every project's
    # Orchestrator -- otherwise each Orchestrator would create its own
    # internal Event (since Orchestrator always ensures it has a real
    # one), and a threshold crossed in project 1 would never stop
    # project 2 from starting.
    if cancel_event is None and fail_policy is not None:
        cancel_event = threading.Event()

    # Strict tag validation must see every requested project's
    # tests BEFORE any project starts executing -- otherwise project 1
    # runs to completion, then project 2's bad tag raises and aborts
    # the whole invocation (sys.exit(1) before reporter.write()),
    # discarding project 1's already-completed results for nothing.
    _validate_all_projects_tags_upfront(project_names, projects, tag_registry)

    for name in project_names:
        if cancel_event is not None and cancel_event.is_set():
            # A fail-policy threshold (or external cancel) already
            # fired -- don't start this project, but still give its
            # tests an explicit report entry (not_run) instead of
            # letting them vanish from the report entirely, the same
            # visibility unstarted-within-a-project tests already get.
            _report_project_not_run(name, projects[name], combined_reporter, grouping_dimensions)
            continue

        project = projects[name]
        registry_module.clear_tests()
        registry_module.clear_fixtures()  # a stale fixture from project N-1's conftest must
        # never silently resolve for project N -- clear_tests() alone left it registered.

        # resolve_num_workers is idempotent on ints, so wrapping the
        # whole precedence chain is safe whether the winning value is an
        # already-resolved base int, a project's raw "auto"/"N%", or a
        # CLI "auto" passed through unresolved.
        effective_num_workers = resolve_num_workers(
            cli_num_workers
            if cli_num_workers is not None
            else (project.num_workers if project.num_workers is not None else base_num_workers)
        )
        effective_timeout = (
            cli_timeout
            if cli_timeout is not None
            else (project.timeout if project.timeout is not None else base_timeout)
        )
        effective_tags = cli_tags if cli_tags else (project.tags or None)
        effective_fully_parallel = (
            project.fully_parallel if project.fully_parallel is not None else base_fully_parallel
        )
        effective_options = {
            **(base_options or {}),
            **project.options,
            **(cli_option_values or {}),
        }

        root = project.tests_dir[0]
        extra_roots = project.tests_dir[1:]

        orch = Orchestrator(
            root,
            effective_num_workers,
            effective_timeout,
            test_ids=test_ids,
            case_ids=case_ids,
            case_id_prefixes=case_id_prefixes,
            tags=effective_tags,
            exclude_tags=exclude_tags,
            grep=grep,
            grep_not=grep_not,
            console_reporters=console_reporters,
            cancel_event=cancel_event,
            playwright_config=playwright_config,
            options=effective_options,
            tag_registry=tag_registry,
            event_subscribers=event_subscribers,
            grouping_dimensions=grouping_dimensions,
            extra_roots=extra_roots,
            force_reload=True,
            project=name,
            multi_project=multi_project,
            fail_policy=fail_policy,
            history_store=history_store,
            history_window=history_window,
            logs_mode=logs_mode,
            quarantine=quarantine,
            coverage_config=coverage_config,
            log_redaction=log_redaction,
            worker_constraints=worker_constraints,
            fully_parallel=effective_fully_parallel,
            strict_teardown=strict_teardown,
            full_trace=full_trace,
            import_timeout=import_timeout if import_timeout is not None else IMPORT_PHASE_TIMEOUT,
            order=order,
            seed=seed,
            raw_config=raw_config,
        )
        project_reporter = orch.run()
        combined_reporter.results.extend(project_reporter.results)
        # record_suite_property() values from every project land on
        # the one reporter that actually writes; last write per key wins,
        # consistent with the cross-worker contract. getattr: run() is
        # duck-typed in tests (any Result-carrying reporter works), so a
        # reporter without suite_properties just contributes none.
        combined_reporter.suite_properties.update(getattr(project_reporter, "suite_properties", {}))

    return combined_reporter, multi_project


def _validate_all_projects_tags_upfront(project_names, projects, tag_registry) -> None:
    """Only strict mode needs this early pass -- warning-mode
    validation happens fine per-project (inside each Orchestrator.run())
    exactly as before, since a warning never discards completed
    results. Strict mode is different: raising mid-invocation (after
    project 1 already ran) throws away project 1's results for a typo
    in project 2's tags, so strict validation must see every project's
    tests before the first one is allowed to start."""
    if tag_registry is None or not tag_registry.strict:
        return

    from ..config.tag_registry import (
        TagValidationError,
        format_unregistered_tags_warning,
        validate_tags,
    )
    from ..core import registry as registry_module
    from ..execution.orchestrator import discover_and_import_multi

    all_unregistered: set[str] = set()
    for name in project_names:
        project = projects[name]
        registry_module.clear_tests()
        registry_module.clear_fixtures()
        discover_and_import_multi(project.tests_dir, force_reload=True)
        all_unregistered.update(validate_tags(registry_module.get_tests(), tag_registry))

    # Leave the registry clean -- the real per-project loop below does
    # its own clear + discover + force_reload regardless.
    registry_module.clear_tests()
    registry_module.clear_fixtures()

    if all_unregistered:
        message = format_unregistered_tags_warning(sorted(all_unregistered))
        raise TagValidationError(message)


def _report_project_not_run(name, project, combined_reporter, grouping_dimensions) -> None:
    """Gives every test in a project that never got to start (an
    earlier project's fail-policy threshold, or an external cancel,
    fired first) an explicit 'not_run' Result entry -- the same
    visibility an unstarted-within-a-project test already gets,
    instead of silently vanishing from the combined report."""
    from ..core import registry as registry_module
    from ..execution.orchestrator import discover_and_import_multi
    from ..reporting.grouping import DEFAULT_DIMENSIONS, compute_groups

    registry_module.clear_tests()
    registry_module.clear_fixtures()
    discover_and_import_multi(project.tests_dir, force_reload=True)

    root = project.tests_dir[0]
    dims = grouping_dimensions or DEFAULT_DIMENSIONS
    for t in registry_module.get_tests():
        combined_reporter.add_result(
            t.id,
            "not_run",
            "Run stopped before this project could start (an earlier project's "
            "fail-policy threshold or an external cancel fired first).",
            0.0,
            case_id=t.case_id,
            tags=t.tags,
            properties=t.properties,
            groups=compute_groups(t, dims, root),
            project=name,
            retries_configured=t.retries,
        )

    registry_module.clear_tests()
    registry_module.clear_fixtures()


def resolve_project_names(requested: list[str], available: dict[str, ProjectConfig]) -> list[str]:
    """Validates every requested name exists; raises ValueError listing
    what IS available (a likely typo shouldn't just silently no-op)."""
    unknown = [n for n in requested if n not in available]
    if unknown:
        known = ", ".join(sorted(available)) or "(none configured)"
        raise ValueError(f"Unknown project(s): {', '.join(unknown)}. Available: {known}")
    return requested
