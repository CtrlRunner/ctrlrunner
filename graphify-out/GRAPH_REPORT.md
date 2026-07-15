# Graph Report - pyrunner  (2026-07-15)

## Corpus Check
- 166 files · ~140,214 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2972 nodes · 6828 edges · 202 communities (118 shown, 84 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 1216 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `fd719810`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- JobObject & Fixture Core
- Test Orchestrator Core
- Historical Timing & Reporter
- Worker Budget & Sharding Units
- Live Run Controller & Event Reporter
- Worker Count & Project Loading
- Named Projects & Tag Registry
- Multi-Project Execution
- Flaky Test Analytics
- CLI History DB Path Tests
- Assert Details & Event Integration Tests
- Coverage.py Integration
- Playwright Fixture Config Tests
- HTML Report Artifacts
- UI Server API Tests
- Deterministic Report Ordering
- Fixture Dependency Resolution
- CLI Entry Point & Argument Parsing
- Test Grouping Dimensions
- Biome Lint Config
- Frontend Theme Toggle
- Rerun Workflows
- Test Detail Markdown Export
- Fail Policy State Tracking
- Frontend Package Dependencies
- Log Secret Redaction
- LPT Sharding Algorithm
- Frontend Build & Metrics Plans
- Report Directory Resolution
- --list Output Formatting
- JUnit XML Reporter
- Migration Import Rewriting Tests
- Migration AST Transformer Core
- graphify Skill Reference Docs
- pyrunner.toml Config Loading
- Step Tree Recording
- Migration Function Plan Builder
- Assert Introspection Tests
- Log Capture Buffer
- Selftest Fakes & Fixtures
- Test Selection Filters
- Test Class Decorator Tests
- Migration CLI Entry Point
- Migration CST Transformer
- Frontend Test Filter Parsing
- Frontend Header & Navigation
- Coverage Integration Tests
- Playwright Auto-Step Tests
- JSON Reporter
- ExecUnit Ordering & Requeue
- Frontend Stats Model
- TypeScript Config
- Grouping Config Backward Compatibility
- Fail Annotation Tests
- Migration File Scanner
- Rerun Serial Group Expansion
- Local Server Security Helpers
- Pytest-Parity Fixes Plan
- Frontend Chip & Icon Components
- Pytest Config Migration
- UnifiedResultShapeTests
- Advanced Examples Fixtures
- Fixture Resolution Engine
- Fail Policy Resolution Tests
- Migration Dry-Run & Idempotency Tests
- Parametrize Helper Tests
- Test Registry Core Tests
- resolve_coverage_config
- Empty Selection Exit Code Tests
- Worker Config CLI Tests
- README.md
- Timeline Gantt Chart
- lpt_shard
- Static Report Server
- Contributing
- Absent-Config Defaults Tests
- UI Server HTTP Handling
- Config Migration Tests
- Grep Filter & Order Seed Tests
- Migration Report Rendering
- Runtime Test Context Info
- Reproducibility Manifest
- Report Server Host Validation
- Worker Reservation Batch Tests
- Event Envelope Model
- Named projects, HTML report, coverage & UI Mode
- Traceback Filtering Tests
- UI Server Request Handler
- Parallelism & Scheduling Docs
- Pytest Migration Conversion Table
- CoverageIntegrationTests
- Frontend App Entry & Dev Fixture
- Unified Result Serialization
- Project CLI Integration Tests
- ParamMetadataExecutionTests
- Security & UI Mode Plan Docs
- Playwright Fixture Definitions
- HTML Report Artifact Embedding
- Context Info Tests
- Log Capture Tests
- Config file, tags & test metadata reference
- Parametrize Cartesian Product
- test_backward_compatibility.py
- Origin Validation Tests
- Coverage CLI Integration Tests
- Case-ID Marker Migration Tests
- Test Class Workers Mode Tests
- CollectionSummaryPrintTests
- Rerun ID Matching
- ExecUnit
- Serial Test Class Tests
- Atomic JUnit Write Tests
- Worker Module Import
- add_marker Migration Tests
- Flaky Flag Tests
- Backward-Compat CLI Tests
- Multi-Project Duration Tests
- Multi-Project Line Reporter Tests
- record_property Migration Tests
- Sharding Integration Tests
- Wall-Clock Parallelism Tests
- Fully-Parallel Class Tests
- TagRegistry
- Fixture Conversion Migration Tests
- Param Metadata Execution Tests
- Config Package Docstring
- Fixture Session Teardown
- Core Package Docstring
- Execution Package Docstring
- Playwright Package Docstring
- Reporting Package Docstring
- UI Package Docstring
- Project Package Metadata
- Core concepts
- load_projects
- ReportTimestampCliOverrideTests
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- pyrunner frontend
- FakeLocator
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- CLAUDE.md
- CLAUDE.md
- extraction-spec.md
- graphify skill trigger (.claude/CLAUDE.md)
- graphify skill trigger (project CLAUDE.md)
- /graphify add <url> (ingest)
- --watch background auto-rebuild
- graphify MCP stdio server
- Neo4j / FalkorDB export
- graphify export wiki
- Confidence score rubric (EXTRACTED/INFERRED/AMBIGUOUS)
- Node ID format rule ({stem}_{entity})
- Semantic extraction subagent prompt
- GitHub clone + full pipeline flow
- graphify merge-graphs (cross-repo)
- graphify claude install (native CLAUDE.md integration)
- graphify hook install (post-commit auto-rebuild)
- BFS/DFS graph traversal
- /graphify path and /graphify explain
- Constrained query vocabulary expansion
- save-result work-memory feedback loop (reflect/LESSONS.md)
- Whisper transcription with domain-hint prompt
- graphify --cluster-only
- graphify --update (incremental re-extraction)
- graphify structural + semantic extraction (Step 3)
- pytest -> pyrunner automatic conversion table
- pyrunner.migrate (pytest -> pyrunner migration tool)
- Local HTTP server defenses (Host allowlist, origin validation, session token)
- Captured log secret redaction
- After src/ changes, npm run build + commit regenerated bundles (staleness cannot be auto-detected)
- frontend/index.html (report app HTML shell, dev source)
- frontend/ui.html (UI Mode HTML shell, dev source)
- pyrunner/reporting/_static/report/index.html (prebuilt, self-contained report bundle)
- pyrunner/ui/_static/ui/ui.html (prebuilt, self-contained UI Mode bundle)
- Class-level test metadata (@test_class)
- Event model (ConsoleReporter vs EventSubscriber)
- Fixture and execution profiling (step tree)
- Fixture teardown failures are never silent (strict_teardown)
- JUnit XML hardening (atomic write, sanitized text)
- --list (list discovered tests)
- Named projects (--project)
- pyrunner project
- record_property / record_suite_property runtime API
- Serial test classes (@test_class(serial=True))
- Test selection filters (--tag, --grep, --case-id)
- Windows Job Object hard-kill mechanism
- Every @test needs a case_id
- Decorator order rule: @test outermost, @parametrize innermost
- No pytest imports/plugins in this repo
- Writing tests with pyrunner (skill)
- load_worker_constraints
- annotations.py
- test_example.py
- tb_format.py
- FixtureParametrizeTests
- MultiProjectLineReporterResetTests
- .close_session

## God Nodes (most connected - your core abstractions)
1. `Orchestrator` - 219 edges
2. `Result` - 146 edges
3. `HistoryStore` - 126 edges
4. `TestItem` - 98 edges
5. `FailPolicyState` - 90 edges
6. `TagRegistry` - 88 edges
7. `ProjectConfig` - 84 edges
8. `main()` - 79 edges
9. `QuarantineConfig` - 77 edges
10. `CoverageConfig` - 74 edges

## Surprising Connections (you probably didn't know these)
- `AbsentConfigDefaultsToOffTests` --uses--> `ProjectConfig`  [INFERRED]
  tests/test_backward_compatibility.py → pyrunner/config/projects.py
- `CliEndToEndBackwardCompatibilityTests` --uses--> `ProjectConfig`  [INFERRED]
  tests/test_backward_compatibility.py → pyrunner/config/projects.py
- `ConfigNestingGotchaTests` --uses--> `ProjectConfig`  [INFERRED]
  tests/test_backward_compatibility.py → pyrunner/config/projects.py
- `NoHistoryStoreRoundRobinUnchangedTests` --uses--> `ProjectConfig`  [INFERRED]
  tests/test_backward_compatibility.py → pyrunner/config/projects.py
- `AlwaysCaptureOrderingRegressionTests` --uses--> `ProjectConfig`  [INFERRED]
  tests/test_orchestrator_and_worker.py → pyrunner/config/projects.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **graphify skill pipeline stages (query, update, extraction spec, github merge)** — claude_skills_graphify_skill_graphify, claude_skills_graphify_references_query_query_expansion, claude_skills_graphify_references_update_incremental_update, claude_skills_graphify_references_extraction_spec_subagent_prompt, claude_skills_graphify_references_github_and_merge_clone_flow [EXTRACTED 1.00]

## Communities (202 total, 84 thin omitted)

### Community 0 - "JobObject & Fixture Core"
Cohesion: 0.05
Nodes (35): Fixture, Decorator to register a fixture. Supports plain-return and     generator (yield-, _chunk(), discover_conftests(), Finds every conftest.py under root, shallowest first, so shared     fixtures def, Batch, One worker process's workload: an ordered list of ExecUnits.     `group`/`dedica, _call_on_failure() (+27 more)

### Community 1 - "Test Orchestrator Core"
Cohesion: 0.07
Nodes (8): AssertDetailsIntegrationTests, EventEnvelopeIntegrationTests, LogCaptureIntegrationTests, An exception from an EventSubscriber or ConsoleReporter must     never orphan a, Safety belt for the exactly-once result contract:     a selected test that someh, Verifies the two-tier design through a real Orchestrator.run():     EventSubscri, ReconciliationInvariantTests, SchedulerCrashSafetyTests

### Community 2 - "Historical Timing & Reporter"
Cohesion: 0.05
Nodes (22): compute_near_timeout_test_ids(), HistoryConfig, HistoryReporter, HistoryStore, Historical timing store (storage half; smart sharding is a separate follow-up th, `CREATE TABLE IF NOT EXISTS` in _SCHEMA is a no-op against a         table that, Writes one `runs` row plus one `test_runs` row per result, all         in a sing, Most recent `window` durations for a test, newest first --         the direct in (+14 more)

### Community 3 - "Worker Budget & Sharding Units"
Cohesion: 0.05
Nodes (29): assign_worker_groups(), build_units(), _cpu_count(), group_aware_shard(), load_worker_constraints(), _normalized_path(), Worker-count resolution and scoped worker-budget planning.  `num_workers` accept, Posix path used for [pyrunner.workers] matching: relative to cwd     when the fi (+21 more)

### Community 4 - "Live Run Controller & Event Reporter"
Cohesion: 0.13
Nodes (3): Collects broadcast events off `q` (keyed by their "type") until         one matc, A throwaway one-test suite, isolated from "examples" (used by         every othe, RunControllerTests

### Community 5 - "Worker Count & Project Loading"
Cohesion: 0.15
Nodes (8): EventEnvelope, EventSubscriber, A versioned, serializable event envelope -- the stable public shape for anything, The stable, envelope-based observation interface -- what hooks     and reporter-, EventEnvelopeTests, EventSubscriberTests, GuardedOnRunEndTests, A reporter whose on_run_end raises     (e.g. a locked/corrupt history store) mus

### Community 6 - "Named Projects & Tag Registry"
Cohesion: 0.19
Nodes (5): load_tag_registry(), Returns None (no validation at all) if `registered_tags` isn't in     config --, AbsentConfigDefaultsToOffTests, Every opt-in [pyrunner.*] section, when absent entirely, must     resolve to its, LoadTagRegistryTests

### Community 7 - "Multi-Project Execution"
Cohesion: 0.07
Nodes (30): ProjectConfig, Named projects.  A project is a named override bundle over base config -- resolv, Runs each named project as its own Orchestrator.run() within this     process, m, Only strict mode needs this early pass -- warning-mode     validation happens fi, Gives every test in a project that never got to start (an     earlier project's, Validates every requested name exists; raises ValueError listing     what IS ava, _report_project_not_run(), resolve_project_names() (+22 more)

### Community 8 - "Flaky Test Analytics"
Cohesion: 0.14
Nodes (12): compute_flake_score(), compute_flaky_report(), FlakyStats, format_flaky_report(), Flaky analytics.  "Flaky" is already latent in existing history data: a run wher, outcome_rows: HistoryStore.get_outcomes()'s own shape. Returns     (flake_score,, One row per test_id with history, sorted most-flaky-first (an     unknown/no-sam, ComputeFlakeScoreTests (+4 more)

### Community 9 - "CLI History DB Path Tests"
Cohesion: 0.13
Nodes (7): LineReporter, Overwrites a single progress line as tests run, printing failures     as they ha, Clears per-run progress state. The reporter instance is         reused across pr, _summary_lines(), LineReporterTests, SummaryLinesFlakyTests, SummaryLinesModuleBreakdownTests

### Community 10 - "Assert Details & Event Integration Tests"
Cohesion: 0.23
Nodes (6): Crossing a fail-policy threshold reuses the exact same         cancel_event/hard, Returns (effective_outcome, is_quarantined, reason).          A quarantined test, Builds an EventEnvelope and hands it to every registered         EventSubscriber, Runs one ConsoleReporter method call, catching any         exception so a broken, A cancelled/not_run/hard-killed/crashed test_end can fire         for a test tha, Safety belt for the exactly-once result contract: every         selected test mu

### Community 11 - "Coverage.py Integration"
Cohesion: 0.19
Nodes (12): CoverageConfig, CoverageSummary, finalize_coverage(), prepare_data_dir(), Coverage.py integration support: config resolution and per-run data-dir lifecycl, Combine every worker's data file in coverage_config.data_dir,     generate the o, Resolved, run-scoped coverage configuration. The SAME instance is     passed to, Purge and recreate the per-run data directory. Call once, before     any worker (+4 more)

### Community 12 - "Playwright Fixture Config Tests"
Cohesion: 0.05
Nodes (14): ClosableFakeContext, ConfigureTests, ContextFixtureTeardownTests, ContextSetupTracingDecisionTests, CrashingPage, FakeBrowser, FakeContext, FakePage (+6 more)

### Community 13 - "HTML Report Artifacts"
Cohesion: 0.15
Nodes (6): report_dir: where artifacts get copied to (as <report_dir>/artifacts/).     If N, render_html(), Result, ArtifactModeTests, _extract_embedded_data(), HtmlReportTests

### Community 15 - "Deterministic Report Ordering"
Cohesion: 0.15
Nodes (11): build_reporters(), DotsReporter, _load_custom_reporter(), Pluggable console reporters, modeled on Playwright TS's reporter set. The orches, One character per test: '.' pass, 'F' fail, 's' skip, 'f' fixme,     'x' expecte, Loads a user-supplied reporter from a 'module.path:ClassName'     spec (--report, BuildReportersTests, CustomReporterLoaderTests (+3 more)

### Community 16 - "Fixture Dependency Resolution"
Cohesion: 0.12
Nodes (9): ExitStack, FixtureResolver, Call before running each test. Tears down module-scoped         fixtures when th, DiTests, FixtureProfilingStepTests, Fixture setup/teardown timing rides the existing step tree., Teardown exceptions must not vanish -- the resolver     records them so the work, TeardownErrorCollectionTests (+1 more)

### Community 17 - "CLI Entry Point & Argument Parsing"
Cohesion: 0.11
Nodes (4): main(), ConfigValidationCliTests, OrderSeedCliTests, RunManifestCliTests

### Community 18 - "Test Grouping Dimensions"
Cohesion: 0.22
Nodes (12): TestItem, compute_groups(), _group_by_module(), _group_by_path(), _group_by_property(), _group_by_tag_prefix(), GroupingDimension, A generic grouping strategy system for the HTML report / UI Mode, replacing the (+4 more)

### Community 19 - "Biome Lint Config"
Cohesion: 0.06
Nodes (32): noStaticElementInteractions, useKeyWithClickEvents, useSemanticElements, source, assist, actions, enabled, files (+24 more)

### Community 20 - "Frontend Theme Toggle"
Cohesion: 0.13
Nodes (22): applyTheme(), cycleTheme(), resolved(), setThemeSetting(), apiPost(), fetchStatus(), fetchTests(), LiveResult (+14 more)

### Community 21 - "Rerun Workflows"
Cohesion: 0.07
Nodes (27): expand_serial_groups(), load_failed_test_ids(), match_changed_files_to_test_ids(), match_rerun_ids(), Exception, Path, Rerun workflows -- --last-failed, --failed-from, --changed-since. All three are, Returns the absolute repo root via `git rev-parse --show-toplevel`     -- `git d (+19 more)

### Community 22 - "Test Detail Markdown Export"
Cohesion: 0.13
Nodes (23): react, Lightbox(), fence(), logsToMarkdown(), stepsToMarkdown(), testToMarkdown(), testToPrompt(), ArtifactView() (+15 more)

### Community 23 - "Fail Policy State Tracking"
Cohesion: 0.11
Nodes (8): FailPolicyState, Call once per Result with outcome == 'failed' (including         timeout-kills,, Call once per hard-kill-due-to-timeout specifically (a         subset of failure, FailPolicyStateTests, FailPolicyIntegrationTests, PolicyCancelDoesNotOverwriteExternalCancelTests, Real Orchestrator.run() verification -- this is where the     trickiest bug in t, A policy trip must not overwrite an already-set external     (UI/user) cancel re

### Community 24 - "Frontend Package Dependencies"
Cohesion: 0.07
Nodes (29): @biomejs/biome, dependencies, react-dom, devDependencies, @biomejs/biome, @types/react, @types/react-dom, typescript (+21 more)

### Community 25 - "Log Secret Redaction"
Cohesion: 0.13
Nodes (10): Pattern, Best-effort redaction of obvious secrets from captured test logs before they're, Reads [pyrunner.log_redaction]. Returns compiled patterns (built-in     defaults, Applies redaction to a worker's per-attempt log list (the shape     log_capture., redact_log_entries(), redact_text(), resolve_redaction_patterns(), RedactLogEntriesTests (+2 more)

### Community 26 - "LPT Sharding Algorithm"
Cohesion: 0.18
Nodes (9): duration_weights(), lookup_median_durations(), Longest-processing-time-first (LPT) greedy bin-packing across workers, using eac, (key, weight) pairs for _lpt_shard_weighted: a known median is     used as-is; N, One history query per test -- fine at real suite sizes (this runs     once per i, (unit, weight) pairs; a unit's weight is the sum of its members'     durations,, _unit_weights(), _FakeStore (+1 more)

### Community 27 - "Frontend Build & Metrics Plans"
Cohesion: 0.36
Nodes (4): format_collection_summary(), A one-line "what did we collect" summary printed before a real run starts, regar, FormatCollectionSummaryTests, _item()

### Community 28 - "Report Directory Resolution"
Cohesion: 0.15
Nodes (9): find_latest_report_dir(), _prune_old_reports(), Path, Resolves where a managed HTML report directory lives, and prunes old timestamped, Read-only counterpart to resolve_report_dir(), for --last-failed     (section 4., Keeps only the `keep - 1` most recent '<report_name>-<timestamp>'     directorie, resolve_report_dir(), FindLatestReportDirTests (+1 more)

### Community 29 - "--list Output Formatting"
Cohesion: 0.17
Nodes (7): format_list(), _format_scalar(), --list output formatting. A pure view over already-selected TestItems: never a s, fmt: "text" | "json" | "md". `fields` only affects text/md --     json always in, _row(), FormatListTests, _item()

### Community 30 - "JUnit XML Reporter"
Cohesion: 0.05
Nodes (21): JUnitReporter, multi_project=True wraps output in <testsuites> with one         <testsuite> per, Emits standard JUnit XML so the existing JUnit-XML-to-Teams pipeline     keeps w, _render_steps_text(), _sanitize_xml_text(), AtomicWriteTests, DeterministicOrderTests, JUnitGoldenBytesTests (+13 more)

### Community 31 - "Migration Import Rewriting Tests"
Cohesion: 0.13
Nodes (4): PlaywrightAndImportTests, PytestParamConversionTests, Returns (report, {relative_name: new_source})., TestFunctionConversionTests

### Community 32 - "Migration AST Transformer Core"
Cohesion: 0.12
Nodes (14): BaseExpression, Import, ImportFrom, _asname_str(), _dotted(), _has_todo(), _PytestParamConverter, Pass 2 of the migration: the libcst rewrite of one file.  What gets converted au (+6 more)

### Community 33 - "graphify Skill Reference Docs"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 34 - "pyrunner.toml Config Loading"
Cohesion: 0.14
Nodes (7): load_config(), Optional pyrunner.toml config file. CLI flags always take precedence over it; it, ConfigTests, ConfigValidationTests, NestedGroupingTableTests, A typo'd key or mis-nested table used to be silently     ignored -- the run proc, Regression test for a real gotcha hit during manual verification:     a bare `[g

### Community 35 - "Step Tree Recording"
Cohesion: 0.14
Nodes (9): begin_test(), collect_steps(), test.step()-equivalent for pyrunner: a context manager (not a decorator, since P, Called by the worker right before each test attempt., Called by the worker right after each test attempt to grab the     recorded tree, Plain-text tree rendering, used for JUnit <system-out> since JUnit     has no na, render_text(), Step (+1 more)

### Community 36 - "Migration Function Plan Builder"
Cohesion: 0.15
Nodes (8): Arg, Decorator, EmptyLine, _FnPlan, Everything decided about one function before rebuilding it., Classify and collect every decision; None -> leave untouched., @pytest.mark.<case-id-marker>("7412675") -> @test(case_id="7412675").         Th, _todo_line()

### Community 37 - "Assert Introspection Tests"
Cohesion: 0.07
Nodes (23): Assert, AssertionError, AST, Module, _build(), build_assert_details(), _collect_names(), _contains_forbidden() (+15 more)

### Community 38 - "Log Capture Buffer"
Cohesion: 0.08
Nodes (10): _BoundedBuffer, capture_logs(), _CaptureHandler, Buffered stdout/stderr + logging capture for one test attempt, used by worker.py, Captures stdout, stderr, and Python logging records for the     duration of the, A tail-keeping, byte-capped text buffer -- a chatty test must     not OOM the wo, Writes to both the bounded buffer and the original stream, so     worker output, Appends one dict per log record to a plain list. Never raises:     record.getMes (+2 more)

### Community 39 - "Selftest Fakes & Fixtures"
Cohesion: 0.10
Nodes (9): # NOTE: decorators apply bottom-up, so @parametrize must sit closer to the, test_fail_non_strict_allows_unexpected_pass(), test_fail_strict_flags_unexpected_pass(), test_fail_strict_reports_expected_failure(), test_slow_extends_timeout(), fail(), Marks the rest of this test as expected to fail (pytest's xfail,     named after, Extends this test's timeout by `factor` for this run. Call before     the slow p (+1 more)

### Community 40 - "Test Selection Filters"
Cohesion: 0.15
Nodes (5): Pure-function test selection. This is the direct replacement for the pytest_coll, All filters are AND-ed together; each accepts multiple values (OR     within tha, select_tests(), _item(), SelectionTests

### Community 42 - "Migration CLI Entry Point"
Cohesion: 0.16
Nodes (19): ArgumentParser, build_parser(), main(), CLI: python -m pyrunner.migrate <paths> [--write] [--no-diff] [--report FILE], _alias_local_name(), fix_imports(), _import_module_name(), _is_docstring() (+11 more)

### Community 43 - "Migration CST Transformer"
Cohesion: 0.16
Nodes (6): JsonReporter, Machine-readable summary, loosely modeled on Playwright TS's json     reporter (, Optional capability, duck-typed via hasattr() at the call site         (same pat, Same duck-typed optional-capability pattern as         set_coverage_summary: the, JsonReporterTests, _results()

### Community 44 - "Frontend Test Filter Parsing"
Cohesion: 0.15
Nodes (18): blobCache, Filter, filterWithToken(), Parsed, parseToken(), quoteIfNeeded(), searchBlob(), Token (+10 more)

### Community 45 - "Frontend Header & Navigation"
Cohesion: 0.21
Nodes (20): StatNav(), report, root, hashFor(), Link(), navigate(), parseHash(), SearchParamsContext (+12 more)

### Community 46 - "Coverage Integration Tests"
Cohesion: 0.14
Nodes (6): TagRegistry, Runtime record_property()/record_suite_property() flow     from a worker process, Verifies validation actually happens where the plan specifies:     immediately a, RecordPropertyE2ETests, TagRegistryOrchestratorIntegrationTests, TagRegistryTests

### Community 47 - "Playwright Auto-Step Tests"
Cohesion: 0.12
Nodes (8): JobObject, Hard-kills every process currently in the job., EventOrderingTests, ProcessGroupKillTests, QueueDrainTests, JobObject.terminate() on POSIX must kill the whole process     group, not just t, B1/B2: a result already sitting in a slot's queue at the moment     the slot is, test_end for a test a worker was killed/crashed over must     precede that worke

### Community 48 - "JSON Reporter"
Cohesion: 0.14
Nodes (6): auto_step(), AutoStepPage, Wrap a Playwright Page (or Locator) so its actions are     automatically recorde, AutoStepTests, FakeLocator, FakePage

### Community 49 - "ExecUnit Ordering & Requeue"
Cohesion: 0.18
Nodes (7): Reporting + requeue decision for a hard-killed slot. Returns         the ExecUni, The units of a killed slot, trimmed to the tests actually being     requeued --, One live worker process and everything the scheduler needs to     supervise it:, Reads every message currently available on slot.queue without         blocking,, Index of the first pending batch allowed to spawn right now,         or None. En, _trim_units(), _WorkerSlot

### Community 50 - "Frontend Stats Model"
Cohesion: 0.16
Nodes (24): formatMetaDuration(), HeaderView(), PassRateBadge(), statusTokenActive(), addToStats(), buildModel(), emptyStats(), flakyCount() (+16 more)

### Community 51 - "TypeScript Config"
Cohesion: 0.10
Nodes (20): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+12 more)

### Community 52 - "Grouping Config Backward Compatibility"
Cohesion: 0.13
Nodes (6): _looks_like_locator(), Wraps a Playwright Page (or Locator) so common actions are automatically recorde, _capture_trace(), page(), Built-in Playwright fixtures with trace/screenshot capture controlled entirely b, Registered with always_capture=True so this always runs, then     decides for it

### Community 53 - "Fail Annotation Tests"
Cohesion: 0.10
Nodes (3): FailAnnotationTests, SkipFixmeTests, SlowAnnotationTests

### Community 54 - "Migration File Scanner"
Cohesion: 0.16
Nodes (16): expr, pytest -> pyrunner source migration.  Usage:     python -m pyrunner.migrate test, _decorator_dotted_name(), discover_files(), FixtureInfo, IndirectInjection, _is_fixture_decorator(), ProjectIndex (+8 more)

### Community 55 - "Rerun Serial Group Expansion"
Cohesion: 0.13
Nodes (8): open_trace(), PersistentTraceViewer, playwright_cli_available(), Launches Playwright's own trace viewer for a given trace.zip, rather than reimpl, Launches `playwright show-trace <path>` in the background.     Returns False (do, One long-lived `playwright show-trace --stdin` server for a whole     UI Mode se, PersistentTraceViewerTests, TraceViewerTests

### Community 56 - "Local Server Security Helpers"
Cohesion: 0.16
Nodes (13): allowed_hosts(), allowed_origins(), new_session_token(), Shared localhost-server hardening for pyrunner's two stdlib http.server based se, The exact Host header values this loopback server answers to.     Anything else, A fresh, unguessable per-launch token. token_urlsafe(32) is 256     bits of CSPR, Constant-time comparison so a wrong token can't be narrowed down     by response, token_matches() (+5 more)

### Community 58 - "Frontend Chip & Icon Components"
Cohesion: 0.28
Nodes (14): BanIcon(), CheckIcon(), ChevronIcon(), ClockIcon(), CopyIcon(), CrossIcon(), IconProps, ImageIcon() (+6 more)

### Community 59 - "Pytest Config Migration"
Cohesion: 0.18
Nodes (17): build_pyrunner_toml(), ConfigMigration, find_pyproject(), _map_addopts(), _marker_names(), migrate_config(), _parse_addopts(), _prefix_hint() (+9 more)

### Community 60 - "UnifiedResultShapeTests"
Cohesion: 0.24
Nodes (6): THE public serialization of one test Result -- the single source     of truth fo, result_to_public_dict(), Deterministic report order (JUnit + JSON writers): worker     completion timing, result_sort_key(), This module promises ONE schema for streaming and reporting.     The test_end ev, UnifiedResultShapeTests

### Community 61 - "Advanced Examples Fixtures"
Cohesion: 0.18
Nodes (5): audit_log(), module_resource(), Shared fixtures for every test_*.py under examples/advanced/. Discovered and imp, One instance per test module per worker, not per test. Torn down     when the wo, Runs for every test automatically, even though no test lists it     as a paramet

### Community 62 - "Fixture Resolution Engine"
Cohesion: 0.14
Nodes (16): FixtureRequest, Fixture dependency resolution. Fixtures are resolved recursively by parameter na, Passed to fixtures that declare a `request` parameter, so a     parametrized fix, Returns (values, resolved_all).          `values` has one entry per name in `nam, get_fixtures(), get_tests(), _execute_test(), _finish_failure() (+8 more)

### Community 63 - "Fail Policy Resolution Tests"
Cohesion: 0.21
Nodes (4): Fail policies.  A single mutable FailPolicyState is shared across every Orchestr, CLI > config > built-in default (0/0/False), same precedence as     everywhere e, resolve_fail_policy(), ResolveFailPolicyTests

### Community 64 - "Migration Dry-Run & Idempotency Tests"
Cohesion: 0.12
Nodes (6): DryRunWriteAndIdempotencyTests, HookAndAsyncTests, IndirectParametrizeTests, MigrateTestCase, RuntimeCallTests, TestClassConversionTests

### Community 67 - "resolve_coverage_config"
Cohesion: 0.27
Nodes (3): Mirrors resolve_fail_policy()/resolve_quarantine_config(): reads     config["cov, resolve_coverage_config(), ResolveCoverageConfigTests

### Community 68 - "Empty Selection Exit Code Tests"
Cohesion: 0.19
Nodes (3): EmptySelectionExitCodeTests, FailOnFlakyCliTests, A run that selected zero tests must exit     with code 4, not 0 -- a typo'd --ta

### Community 69 - "Worker Config CLI Tests"
Cohesion: 0.09
Nodes (4): CoverageCliIntegrationTests, GrepCliTests, RerunCliIntegrationTests, WorkerConfigCliTests

### Community 70 - "README.md"
Cohesion: 0.23
Nodes (3): Event model (for reporter/hook/plugin authors), Explicitly not included, Migrating from pytest

### Community 71 - "Timeline Gantt Chart"
Cohesion: 0.18
Nodes (17): BarTooltipContent(), formatSeconds(), formatZoomLabel(), GanttChart(), roundZoom(), rowHeight(), trackHeight(), assignLanes() (+9 more)

### Community 72 - "lpt_shard"
Cohesion: 0.26
Nodes (5): lpt_shard(), _lpt_shard_weighted(), Generic LPT greedy bin-packer over (item, weight) pairs. With     all-equal weig, durations: test_id -> known median duration, or None/absent for a     test with, LptShardTests

### Community 73 - "Static Report Server"
Cohesion: 0.21
Nodes (5): A tiny local static file server for viewing a generated HTML report (and any art, Serves the directory containing `path` (or `path` itself if it's     already a d, serve_report(), NoPortProbeTests, ServeReportTests

### Community 74 - "Contributing"
Cohesion: 0.18
Nodes (9): Before opening a PR, Contributing, Dev setup, Linting, formatting, type checking, Running the test suite, Dev tooling (uv / ruff / ty), Developing pyrunner, Project layout (+1 more)

### Community 75 - "Absent-Config Defaults Tests"
Cohesion: 0.17
Nodes (7): ClassDef, CSTNode, _code(), MigrationTransformer, pytest.skip/fail/xfail as a standalone statement., Value of a positional-or-keyword argument, or None., _str_arg()

### Community 76 - "UI Server HTTP Handling"
Cohesion: 0.21
Nodes (7): _QuietHTTPServer, A page reload tears down the browser's in-flight EventSource     connection (and, serve_ui(), QuietHTTPServerTests, A page reload aborts the browser's in-flight EventSource     connection with a T, ServeUICtrlCTests, ThreadingHTTPServer

### Community 77 - "Config Migration Tests"
Cohesion: 0.24
Nodes (3): ConfigMigrationTests, Path, _write_tree()

### Community 79 - "Migration Report Rendering"
Cohesion: 0.19
Nodes (4): Counter, FileReport, MigrationReport, Migration report model + rendering (console and markdown).

### Community 80 - "Runtime Test Context Info"
Cohesion: 0.26
Nodes (12): _artifact_data_uri(), _bundle_trace_viewer(), _has_copied_trace(), _load_static_page(), _process_artifacts(), Path, Static, self-contained HTML report, analogous to Playwright TS's html-reporter p, Copies the trace-viewer web app bundled with the installed Playwright     packag (+4 more)

### Community 81 - "Reproducibility Manifest"
Cohesion: 0.22
Nodes (8): build_manifest(), _git_sha(), _pyrunner_version(), A lightweight reproducibility bundle written next to results.json -- pyrunner/Py, Same atomic-write contract as JsonReporter/JUnitReporter: a crash     mid-write, write_manifest(), BuildManifestTests, WriteManifestTests

### Community 82 - "Report Server Host Validation"
Cohesion: 0.23
Nodes (5): host_allowed(), True only if the Host header is one of this server's own loopback     names. A m, SimpleHTTPRequestHandler already strips `..` from URL paths, but     adds two th, _ReportRequestHandler, HostAllowedTests

### Community 84 - "Event Envelope Model"
Cohesion: 0.20
Nodes (9): Artifacts on failure, Auto-recorded actions (`auto_step`), Built-in Playwright fixtures with native trace/screenshot capture, Log/stdout capture, Rich assertion failures, Steps (`test.step()` equivalent), Trace/screenshot for every test, not just failures (`always_capture`), Tracing, artifacts & assertion details (+1 more)

### Community 85 - "Named projects, HTML report, coverage & UI Mode"
Cohesion: 0.29
Nodes (7): Code coverage, Grouping model (HTML report / UI Mode), HTML report, Named projects, HTML report, coverage & UI Mode, Named projects (`--project`), Reports directory, UI Mode

### Community 86 - "Traceback Filtering Tests"
Cohesion: 0.26
Nodes (4): Failure tracebacks start at the user's code -- frames     from inside the pyrunn, TbFilterTests, _user_code_chained(), _user_code_that_raises()

### Community 87 - "UI Server Request Handler"
Cohesion: 0.31
Nodes (3): BaseHTTPRequestHandler, Serves failure screenshots/other artifacts the frontend         links to (`<a hr, UIRequestHandler

### Community 88 - "Parallelism & Scheduling Docs"
Cohesion: 0.29
Nodes (7): `--list`, Parallelism & scheduling, Parallelism, scheduling & test selection, Scoped worker budgets (`[pyrunner.workers]`), Serial classes (`@test_class(serial=True)`), Test selection (replaces `pytest_collection_modifyitems`), Worker isolation contract

### Community 89 - "Pytest Migration Conversion Table"
Cohesion: 0.29
Nodes (7): Fail policies, Fixture and execution profiling, Flaky analytics and quarantine, Historical timing store, Reporters, Reporters, history & flake management, Rerun workflows

### Community 90 - "CoverageIntegrationTests"
Cohesion: 0.29
Nodes (3): CoverageIntegrationTests, Spawns a real worker process with coverage enabled and checks a     data file la, A worker that never finishes its batch (timeout) is         hard-killed via JobO

### Community 91 - "Frontend App Entry & Dev Fixture"
Cohesion: 0.24
Nodes (9): devFixture, Window, Artifact, AssertDetails, AssertSide, CoverageSummary, LogRecord, Outcome (+1 more)

### Community 92 - "Unified Result Serialization"
Cohesion: 0.53
Nodes (5): main(), Path, Standalone benchmark for pyrunner's test discovery/import speed -- NOT part of t, _run_one(), _write_suite()

### Community 93 - "Project CLI Integration Tests"
Cohesion: 0.13
Nodes (3): ListProjectScopingTests, ProjectCliIntegrationTests, First CLI-level tests in this project (prior verification was all     manual `py

### Community 95 - "Security & UI Mode Plan Docs"
Cohesion: 0.25
Nodes (8): Binding a non-loopback address, Captured logs may contain secrets, `--changed-since` and git, On-disk state, Report rendering (XSS), Security model, The local HTTP servers, Threat model

### Community 96 - "Playwright Fixture Definitions"
Cohesion: 0.10
Nodes (7): Imports test/conftest modules once at startup so list_tests()         works befo, Takes effect on the next start_run() call -- each run         constructs a fresh, Returns False (does nothing) if a run is already in progress., Test helper: blocks until the current run finishes or timeout         elapses. R, RunController, LastResultsThreadSafetyTests, _last_results is written from the background run thread and     read from last_r

### Community 98 - "Context Info Tests"
Cohesion: 0.11
Nodes (6): Exposes the current test's id/attempt number to fixture code, so built-in Playwr, pytest-record_property equivalent: call from a test     body or fixture to attac, record_property(), ContextInfoTests, pytest's record_property equivalent -- runtime per-test     metadata that lands, RecordPropertyTests

### Community 99 - "Log Capture Tests"
Cohesion: 0.40
Nodes (4): [0.1.0] - 2026-07-15, Added, Changelog, [Unreleased]

### Community 100 - "Config file, tags & test metadata reference"
Cohesion: 0.40
Nodes (5): Class-level test metadata (`@test_class`), Config file (`pyrunner.toml`), Config file, tags & test metadata reference, Registered tag registry, Runtime annotations: `skip`, `fail`, `fixme`, `slow`

### Community 101 - "Parametrize Cartesian Product"
Cohesion: 0.10
Nodes (19): _cartesian(), _collect_parametrized_fixtures(), param, parametrize(), _ParamSet, Any, Test/fixture registration. This replaces pytest's collection machinery. No file-, One fully-merged parametrize combination attached to a function as     func._par (+11 more)

### Community 102 - "test_backward_compatibility.py"
Cohesion: 0.11
Nodes (12): _build_reporters_or_exit(), _flaky_report(), run_projects() reuses the SAME console reporter instances     across every proje, argparse type= for --grep/--grep-not: a bad regex fails at parse     time with a, _regex_arg(), _ResetOnRunStartReporter, _split_csv(), Quarantine.  A config-driven allowlist, populated by a human after reviewing `py (+4 more)

### Community 103 - "Origin Validation Tests"
Cohesion: 0.36
Nodes (3): origin_allowed(), Defense against a malicious page fetch()ing state-changing     endpoints. Reject, OriginAllowedTests

### Community 104 - "Coverage CLI Integration Tests"
Cohesion: 0.17
Nodes (11): Every test needs a `case_id`, Fixtures, Golden rule: decorator order, Imports, Retries, Screenshots/traces on failure, Skill: Writing tests with pyrunner, Skip / fail / fixme / slow (+3 more)

### Community 109 - "Rerun ID Matching"
Cohesion: 0.29
Nodes (7): Migrating from pytest to pyrunner, pyproject.toml -> pyrunner.toml, Recommended workflow, Semantics to double-check after migration, Usage, What is converted automatically, What is flagged for manual work

### Community 111 - "ExecUnit"
Cohesion: 0.05
Nodes (21): Orchestrator, QuarantineConfig, NoHistoryStoreRoundRobinUnchangedTests, Orchestrator without a history_store still runs every test to     completion --, GroupingIntegrationTests, ImportTimeoutConfigTests, ProfilingIntegrationTests, QuarantineIntegrationTests (+13 more)

### Community 113 - "Atomic JUnit Write Tests"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 117 - "Worker Module Import"
Cohesion: 0.18
Nodes (14): Windows Job Objects give us what pytest-timeout's thread-mode kill cannot: a gua, discover_and_import(), discover_and_import_multi(), discover_modules(), _dotted_module_name(), Path, Runs conftest + test module discovery and imports everything --     the shared f, Same as discover_and_import, but merges discovery across several     root direct (+6 more)

### Community 122 - "Multi-Project Duration Tests"
Cohesion: 0.16
Nodes (5): load_grouping_dimensions(), Returns DEFAULT_DIMENSIONS (just "module") if `[grouping]` is     absent from co, ConfigNestingGotchaTests, Regression test for a real gotcha hit during manual verification:     a bare `[g, LoadGroupingDimensionsTests

### Community 123 - "Multi-Project Line Reporter Tests"
Cohesion: 0.07
Nodes (11): Guards the UI / report servers against being exposed on a network     by acciden, _resolve_bind_host(), _show_report(), BindHostGuardCliTests, HistoryDbPathDerivationTests, HtmlReportTimelineFieldsTests, ListRiskFlagTests, --tag-not drops tests carrying any of the     excluded tags, AND-ed after the in (+3 more)

### Community 126 - "Sharding Integration Tests"
Cohesion: 0.17
Nodes (9): ExecUnit, order_units(), The schedulable atom: an ordered list of test ids that must stay     together in, Reorders ExecUnits -- NEVER the tests inside one -- so a serial     group's memb, FilteredTracebackE2ETests, ImportPhaseTimeoutTests, Suite import time must not be charged against the first     test's own timeout b, A real failed run's error text starts at user code --     no pyrunner/execution/ (+1 more)

### Community 133 - "TagRegistry"
Cohesion: 0.13
Nodes (13): format_unregistered_tags_warning(), Optional tag registry (pyrunner.toml `registered_tags`) -- catches typos in @tes, Returns the sorted list of unregistered tags found across every     collected te, Single shared message format for the 'some tags aren't in     registered_tags' w, Separate, always-warning-only check (never blocking, even in     strict mode) fo, validate_tags(), warn_unregistered_cli_tags(), clear_tests() (+5 more)

### Community 144 - "Fixture Session Teardown"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 155 - "Core concepts"
Cohesion: 0.15
Nodes (13): Core concepts, Documentation, `@fixture`, Install, `param()` — per-combination metadata, `@parametrize`, pyrunner, Quick start (+5 more)

### Community 159 - "load_projects"
Cohesion: 0.27
Nodes (3): load_projects(), Returns {} if `[pyrunner.projects]` is absent entirely. Raises     ValueError im, LoadProjectsTests

### Community 161 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 162 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 163 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 166 - "pyrunner frontend"
Cohesion: 0.50
Nodes (3): Layout, pyrunner frontend, Workflow

### Community 167 - "FakeLocator"
Cohesion: 0.15
Nodes (5): LiveEventReporter, Every test's most recent result keyed by test id, accumulated         across run, Shared shape between the live `test_end` SSE event and     RunController.last_re, Turns orchestrator lifecycle hooks into plain dict events, handed     to a broad, _result_to_event()

### Community 294 - "load_worker_constraints"
Cohesion: 0.18
Nodes (10): _num_workers_arg(), strict_teardown (default true) fails a passing test     whose fixture teardown r, argparse type for -n/--num-workers: 'auto' and 'N%' pass through     as strings, CLI > config > default ('auto') resolution for num_workers, plus     the [pyrunn, _resolve_strict_teardown(), _resolve_worker_settings(), _ui(), get_config() (+2 more)

### Community 295 - "annotations.py"
Cohesion: 0.13
Nodes (15): test_fixme_marks_known_broken(), test_skipped_via_runtime_condition(), begin_test(), fixme(), FixmeTest, Exception, Called by the worker before each test attempt., Stops the test immediately; reported as 'skipped', not a failure.     Nothing af (+7 more)

### Community 302 - "test_example.py"
Cohesion: 0.20
Nodes (3): No manual browser/context/page fixtures needed anymore -- trace and screenshot c, Decorator to register a test.      `timeout` is per-test, in seconds, enforced b, test()

### Community 307 - "tb_format.py"
Cohesion: 0.33
Nodes (5): _filter_chain(), format_filtered_exc(), Failure tracebacks shown to test authors should start at THEIR code, not at the, Drops pyrunner-internal frames from every link of the exception     chain (__cau, traceback.format_exc() with pyrunner-internal frames removed.     Call from an e

## Knowledge Gaps
- **228 isolated node(s):** `$schema`, `enabled`, `src/**`, `*.ts`, `index.html` (+223 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **84 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_config()` connect `pyrunner.toml Config Loading` to `Migration Dry-Run & Idempotency Tests`, `load_worker_constraints`, `test_backward_compatibility.py`, `Config Migration Tests`, `CLI Entry Point & Argument Parsing`, `Multi-Project Duration Tests`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `Orchestrator` connect `ExecUnit` to `JobObject & Fixture Core`, `Test Orchestrator Core`, `TagRegistry`, `Named Projects & Tag Registry`, `Multi-Project Execution`, `Worker Count & Project Loading`, `Assert Details & Event Integration Tests`, `Coverage.py Integration`, `CLI Entry Point & Argument Parsing`, `Test Grouping Dimensions`, `Fail Policy State Tracking`, `load_projects`, `FakeLocator`, `Coverage Integration Tests`, `Playwright Auto-Step Tests`, `ExecUnit Ordering & Requeue`, `UnifiedResultShapeTests`, `Grep Filter & Order Seed Tests`, `Worker Reservation Batch Tests`, `CoverageIntegrationTests`, `ParamMetadataExecutionTests`, `Playwright Fixture Definitions`, `HTML Report Artifact Embedding`, `test_backward_compatibility.py`, `CollectionSummaryPrintTests`, `Worker Module Import`, `Flaky Flag Tests`, `Backward-Compat CLI Tests`, `Multi-Project Duration Tests`, `Sharding Integration Tests`, `Wall-Clock Parallelism Tests`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `main()` connect `CLI Entry Point & Argument Parsing` to `Historical Timing & Reporter`, `TagRegistry`, `Named Projects & Tag Registry`, `Multi-Project Execution`, `Coverage.py Integration`, `HTML Report Artifacts`, `Rerun Workflows`, `Log Secret Redaction`, `Report Directory Resolution`, `load_projects`, `ReportTimestampCliOverrideTests`, `pyrunner.toml Config Loading`, `load_worker_constraints`, `Test Selection Filters`, `Migration CST Transformer`, `Pytest-Parity Fixes Plan`, `MultiProjectLineReporterResetTests`, `Fixture Resolution Engine`, `Fail Policy Resolution Tests`, `resolve_coverage_config`, `Empty Selection Exit Code Tests`, `Worker Config CLI Tests`, `Reproducibility Manifest`, `Project CLI Integration Tests`, `test_backward_compatibility.py`, `ExecUnit`, `Worker Module Import`, `Backward-Compat CLI Tests`, `Multi-Project Duration Tests`, `Multi-Project Line Reporter Tests`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 73 inferred relationships involving `Orchestrator` (e.g. with `FailPolicyState` and `JobObject`) actually correct?**
  _`Orchestrator` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 92 inferred relationships involving `Result` (e.g. with `ConsoleReporter` and `DotsReporter`) actually correct?**
  _`Result` has 92 INFERRED edges - model-reasoned connections that need verification._
- **Are the 76 inferred relationships involving `HistoryStore` (e.g. with `ConsoleReporter` and `BindHostGuardCliTests`) actually correct?**
  _`HistoryStore` has 76 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `TestItem` (e.g. with `FormatCollectionSummaryTests` and `ComputeGroupsTests`) actually correct?**
  _`TestItem` has 70 INFERRED edges - model-reasoned connections that need verification._