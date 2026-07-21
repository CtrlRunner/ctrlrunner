# Graph Report - pyrunner  (2026-07-21)

## Corpus Check
- 176 files · ~182,271 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3682 nodes · 8265 edges · 234 communities (130 shown, 104 thin omitted)
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 2792 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6d66cfcf`
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
- ctrlrunner.toml Config Loading
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
- ConfigValidationTests
- Rerun ID Matching
- JunitLogsTests
- ExecUnit
- Serial Test Class Tests
- Atomic JUnit Write Tests
- XmlSanitizationTests
- PytestParamConversionTests
- RunProjectsIntegrationTests
- Worker Module Import
- add_marker Migration Tests
- Flaky Flag Tests
- tb_format.py
- Backward-Compat CLI Tests
- Multi-Project Duration Tests
- Multi-Project Line Reporter Tests
- AddMarkerTests
- record_property Migration Tests
- Sharding Integration Tests
- match_rerun_ids
- Fully-Parallel Class Tests
- FlakyReportCliTests
- compute_near_timeout_test_ids
- AbsentConfigDefaultsToOffTests
- PlaywrightAndImportTests
- IndirectParametrizeTests
- CoverageCliIntegrationTests
- origin_allowed
- Param Metadata Execution Tests
- SingleProjectRunUnchangedTests
- ChunkTests
- FixtureParametrizeTests
- import_module_by_path
- AddoptionMigrationTests
- ui_server.py
- Config Package Docstring
- Fixture Session Teardown
- warn_unregistered_cli_tags
- Execution Package Docstring
- Playwright Package Docstring
- Reporting Package Docstring
- UI Package Docstring
- Project Package Metadata
- PytestParamConversionTests
- CtrlRunner
- Core concepts
- LineReporter
- ItemTests
- Session & test hooks
- load_projects
- TbFilterTests
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- AutoStepPage
- MultiProjectDurationTests
- ctrlrunner frontend
- WallClockParallelismTests
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
- FlakyFlagTests
- load_tag_registry
- TerminalReporter
- GrepCliTests
- pytest -> ctrlrunner automatic conversion table
- ctrlrunner.migrate (pytest -> ctrlrunner migration tool)
- projects.py
- HookAndAsyncTests
- FixtureConversionTests
- ReportCharsThreadingTests
- localsec.py
- serve_report
- UIRequestHandler
- _build_run_parser
- origin_allowed
- Local HTTP server defenses (Host allowlist, origin validation, session token)
- Captured log secret redaction
- After src/ changes, npm run build + commit regenerated bundles (staleness cannot be auto-detected)
- HistoryDbPathDerivationTests
- frontend/index.html (report app HTML shell, dev source)
- frontend/ui.html (UI Mode HTML shell, dev source)
- ctrlrunner/reporting/_static/report/index.html (prebuilt, self-contained report bundle)
- ctrlrunner/ui/_static/ui/ui.html (prebuilt, self-contained UI Mode bundle)
- Class-level test metadata (@test_class)
- Event model (ConsoleReporter vs EventSubscriber)
- Fixture and execution profiling (step tree)
- Fixture teardown failures are never silent (strict_teardown)
- JUnit XML hardening (atomic write, sanitized text)
- --list (list discovered tests)
- Named projects (--project)
- ctrlrunner project
- record_property / record_suite_property runtime API
- Serial test classes (@test_class(serial=True))
- Test selection filters (--tag, --grep, --case-id)
- Windows Job Object hard-kill mechanism
- Every @test needs a case_id
- Decorator order rule: @test outermost, @parametrize innermost
- No pytest imports/plugins in this repo
- Writing tests with ctrlrunner (skill)

## God Nodes (most connected - your core abstractions)
1. `Orchestrator` - 257 edges
2. `Result` - 205 edges
3. `HistoryStore` - 145 edges
4. `TestItem` - 100 edges
5. `FailPolicyState` - 96 edges
6. `TagRegistry` - 94 edges
7. `ProjectConfig` - 90 edges
8. `QuarantineConfig` - 83 edges
9. `CoverageConfig` - 80 edges
10. `GroupingDimension` - 80 edges

## Surprising Connections (you probably didn't know these)
- `test_skipped_via_runtime_condition()` --calls--> `skip()`  [INFERRED]
  examples/test_selftest.py → src/ctrlrunner/core/annotations.py
- `test_fixme_marks_known_broken()` --calls--> `fixme()`  [INFERRED]
  examples/test_selftest.py → src/ctrlrunner/core/annotations.py
- `test_fail_strict_reports_expected_failure()` --calls--> `fail()`  [INFERRED]
  examples/test_selftest.py → src/ctrlrunner/core/annotations.py
- `test_fail_strict_flags_unexpected_pass()` --calls--> `fail()`  [INFERRED]
  examples/test_selftest.py → src/ctrlrunner/core/annotations.py
- `test_fail_non_strict_allows_unexpected_pass()` --calls--> `fail()`  [INFERRED]
  examples/test_selftest.py → src/ctrlrunner/core/annotations.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **graphify skill pipeline stages (query, update, extraction spec, github merge)** — claude_skills_graphify_skill_graphify, claude_skills_graphify_references_query_query_expansion, claude_skills_graphify_references_update_incremental_update, claude_skills_graphify_references_extraction_spec_subagent_prompt, claude_skills_graphify_references_github_and_merge_clone_flow [EXTRACTED 1.00]

## Communities (234 total, 104 thin omitted)

### Community 0 - "JobObject & Fixture Core"
Cohesion: 0.17
Nodes (9): CallInfo, ExceptionInfo, The object for ctrlrunner_runtest_makereport's `call` argument --     pytest Cal, The live-exception half of CallInfo.excinfo -- pytest's     ExceptionInfo's most, CallInfoTests, ExceptionInfoTests, ExitCodeTests, HookimplTopLevelExportTests (+1 more)

### Community 1 - "Test Orchestrator Core"
Cohesion: 0.05
Nodes (17): Orchestrator, CallPhaseHooksTests, CollectionHooksTests, Phase3HookTests, ProfilingIntegrationTests, ctrlrunner_runtest_logstart/setup/teardown/logreport: conftest-     discovered p, The file-grouped default and the cap-mode worker constraints:     a file's tests, Real Orchestrator.run() verification for section 4.12 -- retry     accumulation (+9 more)

### Community 2 - "Historical Timing & Reporter"
Cohesion: 0.07
Nodes (16): compute_near_timeout_test_ids(), HistoryReporter, HistoryStore, `CREATE TABLE IF NOT EXISTS` in _SCHEMA is a no-op against a         table that, Writes one `runs` row plus one `test_runs` row per result, all         in a sing, Most recent `window` durations for a test, newest first --         the direct in, Most recent `window` (outcome, attempts, retries_configured)         rows for a, Every distinct test_id with at least one recorded run,         scoped by project (+8 more)

### Community 3 - "Worker Budget & Sharding Units"
Cohesion: 0.20
Nodes (3): load_grouping_dimensions(), Returns DEFAULT_DIMENSIONS (just "file") if `[grouping]` is     absent from conf, LoadGroupingDimensionsTests

### Community 4 - "Live Run Controller & Event Reporter"
Cohesion: 0.05
Nodes (13): LiveEventReporter, Every test's most recent result keyed by test id, accumulated         across run, Returns False (does nothing) if a run is already in progress., Shared shape between the live `test_end` SSE event and     RunController.last_re, Test helper: blocks until the current run finishes or timeout         elapses. R, Turns orchestrator lifecycle hooks into plain dict events, handed     to a broad, _result_to_event(), RunController (+5 more)

### Community 5 - "Worker Count & Project Loading"
Cohesion: 0.13
Nodes (8): EventEnvelope, EventSubscriber, A versioned, serializable event envelope -- the stable public shape for anything, The stable, envelope-based observation interface -- what hooks     and reporter-, EventEnvelopeTests, EventSubscriberTests, EventOrderingTests, test_end for a test a worker was killed/crashed over must     precede that worke

### Community 6 - "Named Projects & Tag Registry"
Cohesion: 0.17
Nodes (5): AbsentConfigDefaultsToOffTests, NoHistoryStoreRoundRobinUnchangedTests, Dedicated backward-compatibility suite. This is the single most important test c, Every opt-in [ctrlrunner.*] section, when absent entirely, must     resolve to i, Orchestrator without a history_store still runs every test to     completion --

### Community 7 - "Multi-Project Execution"
Cohesion: 0.08
Nodes (18): ProjectConfig, Runs each named project as its own Orchestrator.run() within this     process, m, run_projects(), Real end-to-end verification via actual Orchestrator.run() calls     -- this is, RunProjectsIntegrationTests, CoverageConfigThreadingTests, FixtureRegistryClearedBetweenProjectsTests, ModuleCollisionAcrossProjectsTests (+10 more)

### Community 8 - "Flaky Test Analytics"
Cohesion: 0.13
Nodes (12): compute_flake_score(), compute_flaky_report(), FlakyStats, format_flaky_report(), Flaky analytics.  "Flaky" is already latent in existing history data: a run wher, outcome_rows: HistoryStore.get_outcomes()'s own shape. Returns     (flake_score,, One row per test_id with history, sorted most-flaky-first (an     unknown/no-sam, ComputeFlakeScoreTests (+4 more)

### Community 9 - "CLI History DB Path Tests"
Cohesion: 0.11
Nodes (10): DotsReporter, LineReporter, One character per test: '.' pass, 'F' fail, 's' skip, 'f' fixme,     'x' expecte, Overwrites a single progress line as tests run, printing failures     as they ha, Clears per-run progress state. The reporter instance is         reused across pr, BuildReportersTests, DotsReporterTests, LineReporterTests (+2 more)

### Community 10 - "Assert Details & Event Integration Tests"
Cohesion: 0.06
Nodes (32): Exposes the current test's id/attempt number to fixture code, so built-in Playwr, pytest-record_property equivalent: call from a test     body or fixture to attac, record_property(), _CompatAttrs, ExitCode, FixtureDef, FixtureRequest, Metafunc (+24 more)

### Community 11 - "Coverage.py Integration"
Cohesion: 0.15
Nodes (8): CoverageSummary, finalize_coverage(), Combine every worker's data file in coverage_config.data_dir,     generate the o, Mirrors resolve_fail_policy()/resolve_quarantine_config(): reads     config["cov, resolve_coverage_config(), FinalizeCoverageTests, Runs real coverage.py instrumentation against a scratch module,         saving a, ResolveCoverageConfigTests

### Community 12 - "Playwright Fixture Config Tests"
Cohesion: 0.05
Nodes (14): ClosableFakeContext, ConfigureTests, ContextFixtureTeardownTests, ContextSetupTracingDecisionTests, CrashingPage, FakeBrowser, FakeContext, FakePage (+6 more)

### Community 13 - "HTML Report Artifacts"
Cohesion: 0.12
Nodes (5): report_dir: where artifacts get copied to (as <report_dir>/artifacts/).     If N, render_html(), ArtifactModeTests, _extract_embedded_data(), HtmlReportTests

### Community 15 - "Deterministic Report Ordering"
Cohesion: 0.21
Nodes (6): The @test_class class object, resolved by name from the         test's own modul, build_reporters(), _load_custom_reporter(), Loads a user-supplied reporter from a 'module.path:ClassName'     spec (--report, CustomReporterLoaderTests, --reporter accepts 'module.path:ClassName'     specs -- the class is imported an

### Community 16 - "Fixture Dependency Resolution"
Cohesion: 0.06
Nodes (18): ExitStack, _call_fixture_hooks(), FixtureRequest, FixtureResolver, Tears down module- and session-scoped fixtures. Call once when         the worke, Passed to fixtures that declare a `request` parameter, so a     parametrized fix, Call before running each test. Tears down module-scoped         fixtures when th, Returns (values, resolved_all).          `values` has one entry per name in `nam (+10 more)

### Community 17 - "CLI Entry Point & Argument Parsing"
Cohesion: 0.10
Nodes (14): Reads every message currently available on slot.queue without         blocking,, Index of the first pending batch allowed to spawn right now,         or None. En, Reporting + requeue decision for a hard-killed slot. Returns         the ExecUni, One live worker process and everything the scheduler needs to     supervise it:, Crossing a fail-policy threshold reuses the exact same         cancel_event/hard, Returns (effective_outcome, is_quarantined, reason).          A quarantined test, Builds an EventEnvelope and hands it to every registered         EventSubscriber, Runs one ConsoleReporter method call, catching any         exception so a broken (+6 more)

### Community 18 - "Test Grouping Dimensions"
Cohesion: 0.15
Nodes (14): TestItem, A one-line "what did we collect" summary printed before a real run starts, regar, compute_groups(), group_by_file(), _group_by_path(), _group_by_property(), _group_by_tag_prefix(), GroupingDimension (+6 more)

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
Cohesion: 0.12
Nodes (28): react, Lightbox(), fence(), logsToMarkdown(), stepsToMarkdown(), testToMarkdown(), testToPrompt(), ArtifactView() (+20 more)

### Community 23 - "Fail Policy State Tracking"
Cohesion: 0.11
Nodes (8): FailPolicyState, Call once per Result with outcome == 'failed' (including         timeout-kills,, Call once per hard-kill-due-to-timeout specifically (a         subset of failure, FailPolicyStateTests, FailPolicyIntegrationTests, PolicyCancelDoesNotOverwriteExternalCancelTests, Real Orchestrator.run() verification -- this is where the     trickiest bug in t, A policy trip must not overwrite an already-set external     (UI/user) cancel re

### Community 24 - "Frontend Package Dependencies"
Cohesion: 0.07
Nodes (29): @biomejs/biome, dependencies, react-dom, devDependencies, @biomejs/biome, @types/react, @types/react-dom, typescript (+21 more)

### Community 25 - "Log Secret Redaction"
Cohesion: 0.11
Nodes (13): BaseException, _HookCallOutcome, hookimpl(), _hookimpl_flags(), is_hookwrapper(), pytest/pluggy's @pytest.hookimpl -- usable as `@hookimpl` or     `@hookimpl(tryf, pluggy's yield-protocol outcome object, handed to a hookwrapper     generator's, Calls one ctrlrunner_runtest_makereport hook, honoring     hookwrapper=True: a w (+5 more)

### Community 26 - "LPT Sharding Algorithm"
Cohesion: 0.11
Nodes (14): duration_weights(), lookup_median_durations(), lpt_shard(), _lpt_shard_weighted(), Longest-processing-time-first (LPT) greedy bin-packing across workers, using eac, Generic LPT greedy bin-packer over (item, weight) pairs. With     all-equal weig, (key, weight) pairs for _lpt_shard_weighted: a known median is     used as-is; N, durations: test_id -> known median duration, or None/absent for a     test with (+6 more)

### Community 27 - "Frontend Build & Metrics Plans"
Cohesion: 0.05
Nodes (12): TagRegistry, AssertDetailsIntegrationTests, EventEnvelopeIntegrationTests, LogCaptureIntegrationTests, Verifies validation actually happens where the plan specifies:     immediately a, Verifies the two-tier design through a real Orchestrator.run():     EventSubscri, An exception from an EventSubscriber or ConsoleReporter must     never orphan a, Safety belt for the exactly-once result contract:     a selected test that someh (+4 more)

### Community 28 - "Report Directory Resolution"
Cohesion: 0.14
Nodes (9): find_latest_report_dir(), _prune_old_reports(), Path, Resolves where a managed HTML report directory lives, and prunes old timestamped, Read-only counterpart to resolve_report_dir(), for --last-failed     (section 4., Keeps only the `keep - 1` most recent '<report_name>-<timestamp>'     directorie, resolve_report_dir(), FindLatestReportDirTests (+1 more)

### Community 29 - "--list Output Formatting"
Cohesion: 0.17
Nodes (7): format_list(), _format_scalar(), --list output formatting. A pure view over already-selected TestItems: never a s, fmt: "text" | "json" | "md". `fields` only affects text/md --     json always in, _row(), FormatListTests, _item()

### Community 30 - "JUnit XML Reporter"
Cohesion: 0.05
Nodes (21): JUnitReporter, multi_project=True wraps output in <testsuites> with one         <testsuite> per, Emits standard JUnit XML so the existing JUnit-XML-to-Teams pipeline     keeps w, _sanitize_xml_text(), AtomicWriteTests, ConsoleCapturedFieldTests, DeterministicOrderTests, JUnitGoldenBytesTests (+13 more)

### Community 31 - "Migration Import Rewriting Tests"
Cohesion: 0.11
Nodes (4): AddMarkerTests, CaseIdMarkerTests, Returns (report, {relative_name: new_source})., TestFunctionConversionTests

### Community 32 - "Migration AST Transformer Core"
Cohesion: 0.13
Nodes (14): BaseExpression, EmptyLine, _dotted(), _has_todo(), _PytestParamConverter, Pass 2 of the migration: the libcst rewrite of one file.  What gets converted au, request.node.add_marker(pytest.mark.<case-id-marker>(x)) ->         record_prope, pytest.skip/fail/xfail as a standalone statement. (+6 more)

### Community 33 - "graphify Skill Reference Docs"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 34 - "ctrlrunner.toml Config Loading"
Cohesion: 0.17
Nodes (10): CoverageConfig, prepare_data_dir(), Coverage.py integration support: config resolution and per-run data-dir lifecycl, Resolved, run-scoped coverage configuration. The SAME instance is     passed to, Purge and recreate the per-run data directory. Call once, before     any worker, PrepareDataDirTests, CoverageIntegrationTests, Spawns a real worker process with coverage enabled and checks a     data file la (+2 more)

### Community 35 - "Step Tree Recording"
Cohesion: 0.13
Nodes (9): _BoundedBuffer, capture_logs(), _CaptureHandler, Buffered stdout/stderr + logging capture for one test attempt, used by worker.py, Captures stdout, stderr, and Python logging records for the     duration of the, A tail-keeping, byte-capped text buffer -- a chatty test must     not OOM the wo, Writes to the bounded buffer, and to the original stream too when     forward_li, Appends one dict per log record to a plain list. Never raises:     record.getMes (+1 more)

### Community 36 - "Migration Function Plan Builder"
Cohesion: 0.10
Nodes (15): Arg, ClassDef, CSTNode, Decorator, FunctionDef, _code(), _FnPlan, MigrationTransformer (+7 more)

### Community 37 - "Assert Introspection Tests"
Cohesion: 0.07
Nodes (23): Assert, AssertionError, AST, Module, _build(), build_assert_details(), _collect_names(), _contains_forbidden() (+15 more)

### Community 39 - "Selftest Fakes & Fixtures"
Cohesion: 0.05
Nodes (25): _capture_custom_screenshot(), _fake_capture(), # NOTE: decorators apply bottom-up, so @parametrize must sit closer to the, test_fail_non_strict_allows_unexpected_pass(), test_fail_strict_flags_unexpected_pass(), test_fail_strict_reports_expected_failure(), test_fixme_marks_known_broken(), test_skipped_via_runtime_condition() (+17 more)

### Community 40 - "Test Selection Filters"
Cohesion: 0.07
Nodes (5): All filters are AND-ed together; each accepts multiple values (OR     within tha, select_tests(), ParamHelperTests, _item(), SelectionTests

### Community 42 - "Migration CLI Entry Point"
Cohesion: 0.11
Nodes (22): build_parser(), main(), ArgumentParser, CLI: python -m ctrlrunner.migrate <paths> [--write] [--no-diff] [--report FILE], FileReport, MigrationReport, Migration report model + rendering (console and markdown)., _alias_local_name() (+14 more)

### Community 43 - "Migration CST Transformer"
Cohesion: 0.15
Nodes (6): JsonReporter, Machine-readable summary, loosely modeled on Playwright TS's json     reporter (, Optional capability, duck-typed via hasattr() at the call site         (same pat, Same duck-typed optional-capability pattern as         set_coverage_summary: the, JsonReporterTests, _results()

### Community 44 - "Frontend Test Filter Parsing"
Cohesion: 0.22
Nodes (11): blobCache, Filter, filterWithToken(), Parsed, parseToken(), quoteIfNeeded(), searchBlob(), Token (+3 more)

### Community 45 - "Frontend Header & Navigation"
Cohesion: 0.18
Nodes (23): StatNav(), labelColorIndex(), LabelsContext, LabelsRow(), LabelsRowStatic(), TagLabel(), useApplyToken(), hashFor() (+15 more)

### Community 46 - "Coverage Integration Tests"
Cohesion: 0.12
Nodes (6): QuarantineConfig, ParamMetadataExecutionTests, QuarantineIntegrationTests, Real Orchestrator.run() verification for section 4.9's     quarantine mechanism, param(xfail=/skip=) must ride the existing runtime fail()/SkipTest     pipelines, QuarantineConfigTests

### Community 48 - "JSON Reporter"
Cohesion: 0.08
Nodes (13): auto_step(), AutoStepPage, _looks_like_locator(), Wraps a Playwright Page (or Locator) so common actions are automatically recorde, Wrap a Playwright Page (or Locator) so its actions are     automatically recorde, _capture_trace(), configure(), page() (+5 more)

### Community 49 - "ExecUnit Ordering & Requeue"
Cohesion: 0.05
Nodes (26): Namespace, AddoptionError, _check_unknown_hooks(), collect_declarations(), _Declaration, OptionParser, ArgumentParser, ctrlrunner_addoption -- the pytest_addoption equivalent.  A conftest.py may defi (+18 more)

### Community 50 - "Frontend Stats Model"
Cohesion: 0.17
Nodes (23): formatMetaDuration(), HeaderView(), PassRateBadge(), statusTokenActive(), addToStats(), buildModel(), emptyStats(), flakyCount() (+15 more)

### Community 51 - "TypeScript Config"
Cohesion: 0.10
Nodes (20): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+12 more)

### Community 52 - "Grouping Config Backward Compatibility"
Cohesion: 0.05
Nodes (29): assign_worker_groups(), build_units(), _cpu_count(), group_aware_shard(), load_worker_constraints(), _normalized_path(), Worker-count resolution and scoped worker-budget planning.  `num_workers` accept, Posix path used for [ctrlrunner.workers] matching: relative to cwd     when the (+21 more)

### Community 53 - "Fail Annotation Tests"
Cohesion: 0.10
Nodes (3): FailAnnotationTests, SkipFixmeTests, SlowAnnotationTests

### Community 54 - "Migration File Scanner"
Cohesion: 0.17
Nodes (17): expr, pytest -> ctrlrunner source migration.  Usage:     python -m ctrlrunner.migrate, _decorator_dotted_name(), discover_files(), FixtureInfo, IndirectInjection, _is_fixture_decorator(), ProjectIndex (+9 more)

### Community 55 - "Rerun Serial Group Expansion"
Cohesion: 0.12
Nodes (8): open_trace(), PersistentTraceViewer, playwright_cli_available(), Launches Playwright's own trace viewer for a given trace.zip, rather than reimpl, Launches `playwright show-trace <path>` in the background.     Returns False (do, One long-lived `playwright show-trace --stdin` server for a whole     UI Mode se, PersistentTraceViewerTests, TraceViewerTests

### Community 56 - "Local Server Security Helpers"
Cohesion: 0.26
Nodes (12): _artifact_data_uri(), _bundle_trace_viewer(), _has_copied_trace(), _load_static_page(), _process_artifacts(), Path, Static, self-contained HTML report, analogous to Playwright TS's html-reporter p, Copies the trace-viewer web app bundled with the installed Playwright     packag (+4 more)

### Community 57 - "Pytest-Parity Fixes Plan"
Cohesion: 0.16
Nodes (17): build_ctrlrunner_toml(), ConfigMigration, find_pyproject(), _map_addopts(), _marker_names(), migrate_config(), _parse_addopts(), _prefix_hint() (+9 more)

### Community 58 - "Frontend Chip & Icon Components"
Cohesion: 0.20
Nodes (17): AutoChip(), Chip(), BanIcon(), CheckIcon(), ChevronIcon(), ClockIcon(), CopyIcon(), CrossIcon() (+9 more)

### Community 59 - "Pytest Config Migration"
Cohesion: 0.16
Nodes (6): collect_steps(), Called by the worker right after each test attempt to grab the     recorded tree, Plain-text tree rendering, used for JUnit <system-out> since JUnit     has no na, render_text(), Step, StepTests

### Community 60 - "UnifiedResultShapeTests"
Cohesion: 0.17
Nodes (9): THE public serialization of one test Result -- the single source     of truth fo, result_to_public_dict(), Deterministic report order (JUnit + JSON writers): worker     completion timing, _render_steps_text(), result_sort_key(), Pluggable console reporters, modeled on Playwright TS's reporter set. The orches, _resolve_report_chars(), This module promises ONE schema for streaming and reporting.     The test_end ev (+1 more)

### Community 61 - "Advanced Examples Fixtures"
Cohesion: 0.18
Nodes (5): audit_log(), module_resource(), Shared fixtures for every test_*.py under examples/advanced/. Discovered and imp, One instance per test module per worker, not per test. Torn down     when the wo, Runs for every test automatically, even though no test lists it     as a paramet

### Community 62 - "Fixture Resolution Engine"
Cohesion: 0.22
Nodes (6): module_name_for_path(), The sys.modules DICT KEY for `path` -- a hash of its resolved     absolute path,, AncestorConftestImportResolutionTests, DottedNameAliasTests, End-to-end regression: a bare `from conftest import x` in a test     file scoped, The runner imports test files under a hash-of-path     sys.modules key. Without

### Community 63 - "Fail Policy Resolution Tests"
Cohesion: 0.23
Nodes (3): CLI > config > built-in default (0/0/False), same precedence as     everywhere e, resolve_fail_policy(), ResolveFailPolicyTests

### Community 64 - "Migration Dry-Run & Idempotency Tests"
Cohesion: 0.13
Nodes (6): DryRunWriteAndIdempotencyTests, MigrateTestCase, pytest's record_property/record_testsuite_property fixtures now     have direct, RecordPropertyMigrationTests, RuntimeCallTests, TestClassConversionTests

### Community 65 - "Parametrize Helper Tests"
Cohesion: 0.27
Nodes (5): Guards the UI / report servers against being exposed on a network     by acciden, _resolve_bind_host(), _show_report(), BindHostGuardCliTests, _resolve_bind_host is the only thing standing between the     auth-light UI/repo

### Community 67 - "resolve_coverage_config"
Cohesion: 0.12
Nodes (10): Mapping, _CallSpec, Config, item.callspec -- pytest's per-parametrize-combination object.     Only ever atta, The object for ctrlrunner_sessionfinish (full, with results) and     for item.se, The object for ctrlrunner_configure (and item.config /     session.config) -- a, Session, ConfigTests (+2 more)

### Community 68 - "Empty Selection Exit Code Tests"
Cohesion: 0.19
Nodes (3): EmptySelectionExitCodeTests, FailOnFlakyCliTests, A run that selected zero tests must exit     with code 4, not 0 -- a typo'd --ta

### Community 69 - "Worker Config CLI Tests"
Cohesion: 0.06
Nodes (9): AddoptionCliIntegrationTests, CoverageCliIntegrationTests, PositionalNodeIdCliTests, A '::'-suffixed root positional is a pytest-style node id     (path/to/file.py::, ctrlrunner_addoption end to end: declaration in conftest.py,     --help visibili, Startup abort for unsupported hook names in conftest.py, and the     allow_unkno, RerunCliIntegrationTests, UnknownHookCliTests (+1 more)

### Community 70 - "README.md"
Cohesion: 0.17
Nodes (10): Before opening a PR, Contributing, Dev setup, Linting, formatting, type checking, Releasing, Running the test suite, Dev tooling (uv / ruff / ty), Developing ctrlrunner (+2 more)

### Community 71 - "Timeline Gantt Chart"
Cohesion: 0.18
Nodes (17): BarTooltipContent(), formatSeconds(), formatZoomLabel(), GanttChart(), roundZoom(), rowHeight(), trackHeight(), assignLanes() (+9 more)

### Community 72 - "lpt_shard"
Cohesion: 0.29
Nodes (4): HistoryConfig, Historical timing store (storage half; smart sharding is a separate follow-up th, resolve_history_config(), ResolveHistoryConfigTests

### Community 73 - "Static Report Server"
Cohesion: 0.29
Nodes (4): _extract_aria_snapshot(), Path, Splits a Playwright Aria snapshot off the end of a failure     traceback and wri, _safe_test_dir()

### Community 74 - "Contributing"
Cohesion: 0.18
Nodes (7): Result, _custom_status_symbol(), Consults ctrlrunner_report_teststatus for a custom dots/line     symbol -- pytes, _summary_lines(), ReportCharsTests, SummaryLinesConsoleCapturedTests, SummaryLinesFlakyTests

### Community 75 - "Absent-Config Defaults Tests"
Cohesion: 0.39
Nodes (3): load_tag_registry(), Returns None (no validation at all) if `registered_tags` isn't in     config --, LoadTagRegistryTests

### Community 76 - "UI Server HTTP Handling"
Cohesion: 0.21
Nodes (6): _QuietHTTPServer, A page reload tears down the browser's in-flight EventSource     connection (and, QuietHTTPServerTests, A page reload aborts the browser's in-flight EventSource     connection with a T, ServeUICtrlCTests, ThreadingHTTPServer

### Community 77 - "Config Migration Tests"
Cohesion: 0.27
Nodes (3): ConfigMigrationTests, Path, _write_tree()

### Community 79 - "Migration Report Rendering"
Cohesion: 0.12
Nodes (10): Pattern, Best-effort redaction of obvious secrets from captured test logs before they're, Reads [ctrlrunner.log_redaction]. Returns compiled patterns (built-in     defaul, Applies redaction to a worker's per-attempt log list (the shape     log_capture., redact_log_entries(), redact_text(), resolve_redaction_patterns(), RedactLogEntriesTests (+2 more)

### Community 80 - "Runtime Test Context Info"
Cohesion: 0.22
Nodes (8): Dismissing alerts (code-scanning only), Eliminating a false positive instead of just documenting it, Fetching findings, Fixing real findings, GitHub Code Quality & Code Scanning, The GHAS licensing trap (private repos), Triage: read the actual code before trusting the rule description, Triggering / configuring a scan

### Community 81 - "Reproducibility Manifest"
Cohesion: 0.20
Nodes (8): build_manifest(), _ctrlrunner_version(), _git_sha(), A lightweight reproducibility bundle written next to results.json -- ctrlrunner/, Same atomic-write contract as JsonReporter/JUnitReporter: a crash     mid-write, write_manifest(), BuildManifestTests, WriteManifestTests

### Community 82 - "Report Server Host Validation"
Cohesion: 0.20
Nodes (6): host_allowed(), True only if the Host header is one of this server's own loopback     names. A m, A tiny local static file server for viewing a generated HTML report (and any art, SimpleHTTPRequestHandler already strips `..` from URL paths, but     adds two th, _ReportRequestHandler, HostAllowedTests

### Community 84 - "Event Envelope Model"
Cohesion: 0.20
Nodes (9): Artifacts on failure, Auto-recorded actions (`auto_step`), Built-in Playwright fixtures with native trace/screenshot capture, Log/stdout capture, Rich assertion failures, Steps (`test.step()` equivalent), Trace/screenshot for every test, not just failures (`always_capture`), Tracing, artifacts & assertion details (+1 more)

### Community 85 - "Named projects, HTML report, coverage & UI Mode"
Cohesion: 0.29
Nodes (7): Code coverage, Grouping model (HTML report / UI Mode), HTML report, Named projects, HTML report, coverage & UI Mode, Named projects (`--project`), Reports directory, UI Mode

### Community 88 - "Parallelism & Scheduling Docs"
Cohesion: 0.29
Nodes (7): `--list`, Parallelism & scheduling, Parallelism, scheduling & test selection, Scoped worker budgets (`[ctrlrunner.workers]`), Serial classes (`@test_class(serial=True)`), Test selection (replaces `pytest_collection_modifyitems`), Worker isolation contract

### Community 89 - "Pytest Migration Conversion Table"
Cohesion: 0.29
Nodes (7): Fail policies, Fixture and execution profiling, Flaky analytics and quarantine, Historical timing store, Reporters, Reporters, history & flake management, Rerun workflows

### Community 91 - "Frontend App Entry & Dev Fixture"
Cohesion: 0.33
Nodes (6): devFixture, report, root, loadReportData(), Window, ReportData

### Community 92 - "Unified Result Serialization"
Cohesion: 0.53
Nodes (5): main(), Path, Standalone benchmark for ctrlrunner's test discovery/import speed -- NOT part of, _run_one(), _write_suite()

### Community 93 - "Project CLI Integration Tests"
Cohesion: 0.13
Nodes (3): ListProjectScopingTests, ProjectCliIntegrationTests, First CLI-level tests in this project (prior verification was all     manual `py

### Community 94 - "ParamMetadataExecutionTests"
Cohesion: 0.18
Nodes (4): Appends `item` to the registry, raising loudly on a duplicate test     id instea, _register_item(), Takes effect on the next start_run() call -- each run         constructs a fresh, ValueError

### Community 95 - "Security & UI Mode Plan Docs"
Cohesion: 0.25
Nodes (8): Binding a non-loopback address, Captured logs may contain secrets, `--changed-since` and git, On-disk state, Report rendering (XSS), Security model, The local HTTP servers, Threat model

### Community 98 - "Context Info Tests"
Cohesion: 0.20
Nodes (3): ContextInfoTests, pytest's record_property equivalent -- runtime per-test     metadata that lands, RecordPropertyTests

### Community 99 - "Log Capture Tests"
Cohesion: 0.29
Nodes (6): [0.1.0] - 2026-07-15, Added, Added, Changelog, Fixed, [Unreleased]

### Community 100 - "Config file, tags & test metadata reference"
Cohesion: 0.18
Nodes (8): bind_hook_args(), CompatibilityError, A migrated hook touched something ctrlrunner doesn't model. The     message alwa, pluggy-style call-by-parameter-NAME: returns the kwargs for     `hook(**bound)`, BindHookArgsTests, CompatErrorTests, Attributes the compat layer doesn't model FAIL LOUDLY: a     CompatibilityError, pluggy-style call-by-parameter-NAME: each hook impl receives     exactly the nam

### Community 101 - "Parametrize Cartesian Product"
Cohesion: 0.22
Nodes (5): _raise_key_error(), Failure tracebacks start at the user's code -- frames     from inside the ctrlru, TbFilterTests, _user_code_chained(), _user_code_that_raises()

### Community 102 - "test_backward_compatibility.py"
Cohesion: 0.08
Nodes (31): _build_reporters_or_exit(), _build_ui_parser(), _flaky_report(), _guess_root(), main(), _num_workers_arg(), _parse_run_args(), ArgumentParser (+23 more)

### Community 103 - "Origin Validation Tests"
Cohesion: 0.16
Nodes (9): get_option(), get_options(), _normalize(), Per-process store for user-declared run options (ctrlrunner_addoption).  The CLI, Replaces the whole store (None clears it). Called once per     process by the CL, The value of a declared or [ctrlrunner.options]-configured     option. `default`, A copy of the whole store., set_options() (+1 more)

### Community 104 - "Coverage CLI Integration Tests"
Cohesion: 0.17
Nodes (12): Every test needs a `case_id`, Fixtures, Golden rule: decorator order, Imports, Retries, Screenshots/traces on failure, Session & test hooks (`pytest_configure`/`pytest_runtest_*` equivalents), Skill: Writing tests with ctrlrunner (+4 more)

### Community 108 - "ConfigValidationTests"
Cohesion: 0.43
Nodes (3): get_config(), `--headed` used to be a store_true flag defaulting to False --     there was no, UICliHeadedFlagOverrideTests

### Community 109 - "Rerun ID Matching"
Cohesion: 0.22
Nodes (9): Manual conversion recipes, Marker-driven guard fixtures, Migrating from pytest to ctrlrunner, pyproject.toml -> ctrlrunner.toml, Recommended workflow, Semantics to double-check after migration, Usage, What is converted automatically (+1 more)

### Community 110 - "JunitLogsTests"
Cohesion: 0.11
Nodes (9): AttributeError, _Cache, _InvocationParams, _OptionNamespace, Path, config.invocation_params -- pytest's raw-argv snapshot., config.option -- pytest's parsed-args namespace, answered from     the ctrlrunne, config.cache -- pytest's Cache API, implemented for real: a     JSON-backed stor (+1 more)

### Community 111 - "ExecUnit"
Cohesion: 0.04
Nodes (51): Exception, Raised only in strict mode, only from the CLI run path -- see     Orchestrator.r, TagValidationError, Fixture, Decorator to register a fixture. Supports plain-return and     generator (yield-, JobObject, Hard-kills every process currently in the job., discover_modules() (+43 more)

### Community 113 - "Atomic JUnit Write Tests"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 114 - "XmlSanitizationTests"
Cohesion: 0.07
Nodes (35): Fixture dependency resolution. Fixtures are resolved recursively by parameter na, Core test/fixture primitives: registration, dependency injection, steps, runtime, clear_tests(), _collect_parametrized_fixtures(), _fixture_closure(), get_fixtures(), get_tests(), Test/fixture registration. This replaces pytest's collection machinery. No file- (+27 more)

### Community 117 - "Worker Module Import"
Cohesion: 0.16
Nodes (8): Optional tag registry (ctrlrunner.toml `registered_tags`) -- catches typos in @t, Returns the sorted list of unregistered tags found across every     collected te, Separate, always-warning-only check (never blocking, even in     strict mode) fo, validate_tags(), warn_unregistered_cli_tags(), _item(), ValidateTagsTests, WarnUnregisteredCliTagsTests

### Community 118 - "add_marker Migration Tests"
Cohesion: 0.14
Nodes (4): The object for ctrlrunner_runtest_logreport -- pytest TestReport's     commonly-, TestReport, TestReportTests, TestReportWideSurfaceTests

### Community 119 - "Flaky Flag Tests"
Cohesion: 0.33
Nodes (4): Import, ImportFrom, _asname_str(), String value of an import alias's `as` target, if present --     always a plain

### Community 120 - "tb_format.py"
Cohesion: 0.21
Nodes (9): _filter_chain(), format_filtered_exc(), _format_line(), Failure tracebacks shown to test authors should start at THEIR code, not at the, Drops ctrlrunner-internal frames from every link of the exception     chain (__c, --tb=short: keeps only the single frame closest to where the     exception was a, --tb=line: pytest's single-line style, 'file:lineno: ExcType: msg'., traceback.format_exc() with ctrlrunner-internal frames removed     (or reshaped (+1 more)

### Community 121 - "Backward-Compat CLI Tests"
Cohesion: 0.14
Nodes (8): Class-level test metadata (`@test_class`), Config file (`ctrlrunner.toml`), Config file, tags & test metadata reference, Registered tag registry, Runtime annotations: `skip`, `fail`, `fixme`, `slow`, Event model (for reporter/plugin authors), Explicitly not included, Migrating from pytest

### Community 122 - "Multi-Project Duration Tests"
Cohesion: 0.17
Nodes (6): load_config(), ConfigNestingGotchaTests, Regression test for a real gotcha hit during manual verification:     a bare `[g, ConfigTests, NestedGroupingTableTests, Regression test for a real gotcha hit during manual verification:     a bare `[g

### Community 123 - "Multi-Project Line Reporter Tests"
Cohesion: 0.04
Nodes (10): AllSixHooksEndToEndTests, ConfigValidationCliTests, HtmlReportTimelineFieldsTests, ListRiskFlagTests, One conftest.py defining all six pytest-analogue hooks, one real     CLI invocat, ReportCharsFlagTests, ReportTimestampCliOverrideTests, RunManifestCliTests (+2 more)

### Community 124 - "AddMarkerTests"
Cohesion: 0.36
Nodes (3): discover_conftests(), Finds every conftest.py that applies to `root`: every ANCESTOR     directory's c, DiscoverConftestsTests

### Community 125 - "record_property Migration Tests"
Cohesion: 0.17
Nodes (11): 1. Capture becomes default-on, non-forwarding, 2. `-v` / `--verbose` and `-q` / `--quiet`, 3. `-r <chars>` — end-of-run summary control, 4. `--tb=<style>` — traceback detail, 5. Scope boundary, Current state (verified against source), Design, Out of scope (+3 more)

### Community 127 - "match_rerun_ids"
Cohesion: 0.38
Nodes (4): Counter, format_collection_summary(), FormatCollectionSummaryTests, _item()

### Community 129 - "FlakyReportCliTests"
Cohesion: 0.10
Nodes (11): Item, Marker, What Item.get_closest_marker returns -- pytest.Mark's shape.     ctrlrunner tags, The per-test object for ctrlrunner_runtest_setup/teardown --     pytest Item's c, pytest's item.add_report_section -- attaches extra captured         output to th, pytest's marker lookup, answered from the test's tags --         `@test(tags={"m, Adds a tag at runtime -- visible to later get_closest_marker/         iter_marke, (filename, lineno, testname) -- pytest's item.location. (+3 more)

### Community 131 - "AbsentConfigDefaultsToOffTests"
Cohesion: 0.17
Nodes (9): The units of a killed slot, trimmed to the tests actually being     requeued --, _trim_units(), ExecUnit, order_units(), The schedulable atom: an ordered list of test ids that must stay     together in, Reorders ExecUnits -- NEVER the tests inside one -- so a serial     group's memb, Real Orchestrator.run() verification with a genuinely seeded     HistoryStore --, ShardingIntegrationTests (+1 more)

### Community 136 - "Param Metadata Execution Tests"
Cohesion: 0.13
Nodes (15): 1a. `CompatibilityError` for unmodeled attributes, 1b. Unknown-hook detection at startup, 1c. Migrate tool alignment, Already implemented (20, Phases 0–2), Argument status table, Call mechanics: name-based argument binding (Phase 1, blocking), Done — Phase 3: advanced parity (7 hooks + ordering/wrapper mechanics), Part 1 — Policy reversal: fail loudly (Phase 0, do first) (+7 more)

### Community 140 - "import_module_by_path"
Cohesion: 0.11
Nodes (20): Named projects.  A project is a named override bundle over base config -- resolv, Only strict mode needs this early pass -- warning-mode     validation happens fi, Gives every test in a project that never got to start (an     earlier project's, _report_project_not_run(), _validate_all_projects_tags_upfront(), format_unregistered_tags_warning(), Single shared message format for the 'some tags aren't in     registered_tags' w, _apply_ignore_collect() (+12 more)

### Community 142 - "ui_server.py"
Cohesion: 0.40
Nodes (4): The UI Mode frontend.  The page is a prebuilt React app (frontend/src/ui/ in the, Injects the per-launch session token (see localsec.py) into the     served page., render_ui_html(), Local HTTP server exposing RunController over a small JSON API, plus a Server-Se

### Community 144 - "Fixture Session Teardown"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 155 - "Core concepts"
Cohesion: 0.13
Nodes (15): Core concepts, CtrlRunner, Custom options (`pytest_addoption` equivalent), Documentation, `@fixture`, `indirect=` — per-test fixture parametrization, Install, `param()` — per-combination metadata (+7 more)

### Community 158 - "Session & test hooks"
Cohesion: 0.13
Nodes (15): Compatibility limits — fail loudly, with guidance, `ctrlrunner_assertrepr_compare(config, op, left, right)`, `ctrlrunner_fixture_setup` / `ctrlrunner_fixture_post_finalizer`, `ctrlrunner_generate_tests(metafunc)` — dynamic parametrization, `ctrlrunner_make_parametrize_id(config, val, argname)` — custom id text, `ctrlrunner_report_teststatus(report, config)`, `ctrlrunner_warning_recorded(warning_message, when, nodeid, location)`, Dynamic parametrization, fixture/warning/assert/report hooks, and ordering (+7 more)

### Community 159 - "load_projects"
Cohesion: 0.24
Nodes (3): load_projects(), Returns {} if `[ctrlrunner.projects]` is absent entirely. Raises     ValueError, LoadProjectsTests

### Community 161 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 162 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 163 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 166 - "ctrlrunner frontend"
Cohesion: 0.50
Nodes (3): ctrlrunner frontend, Layout, Workflow

### Community 196 - "load_tag_registry"
Cohesion: 0.31
Nodes (12): Lock, compute_buckets(), discover_files(), FileResult, format_summary_table(), main(), parse_summary(), Path (+4 more)

### Community 205 - "localsec.py"
Cohesion: 0.19
Nodes (9): allowed_hosts(), allowed_origins(), new_session_token(), Shared localhost-server hardening for ctrlrunner's two stdlib http.server based, The exact Host header values this loopback server answers to.     Anything else, A fresh, unguessable per-launch token. token_urlsafe(32) is 256     bits of CSPR, Constant-time comparison so a wrong token can't be narrowed down     by response, token_matches() (+1 more)

### Community 206 - "serve_report"
Cohesion: 0.23
Nodes (4): Serves the directory containing `path` (or `path` itself if it's     already a d, serve_report(), NoPortProbeTests, ServeReportTests

### Community 211 - "UIRequestHandler"
Cohesion: 0.31
Nodes (3): BaseHTTPRequestHandler, Serves failure screenshots/other artifacts the frontend         links to (`<a hr, UIRequestHandler

### Community 212 - "_build_run_parser"
Cohesion: 0.24
Nodes (6): _build_run_parser(), The run subcommand's full argparse surface, buildable twice: once     with add_h, argparse type= for --grep/--grep-not: a bad regex fails at parse     time with a, _regex_arg(), NoCaptureFlagTests, TbStyleFlagTests

### Community 214 - "origin_allowed"
Cohesion: 0.36
Nodes (3): origin_allowed(), Defense against a malicious page fetch()ing state-changing     endpoints. Reject, OriginAllowedTests

## Knowledge Gaps
- **272 isolated node(s):** `$schema`, `enabled`, `src/**`, `*.ts`, `index.html` (+267 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **104 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Orchestrator` connect `Test Orchestrator Core` to `compute_near_timeout_test_ids`, `AbsentConfigDefaultsToOffTests`, `Live Run Controller & Event Reporter`, `Worker Count & Project Loading`, `Named Projects & Tag Registry`, `Multi-Project Execution`, `SingleProjectRunUnchangedTests`, `ChunkTests`, `import_module_by_path`, `CLI Entry Point & Argument Parsing`, `Test Grouping Dimensions`, `Fail Policy State Tracking`, `Frontend Build & Metrics Plans`, `load_projects`, `ctrlrunner.toml Config Loading`, `WallClockParallelismTests`, `Coverage Integration Tests`, `UnifiedResultShapeTests`, `Fixture Resolution Engine`, `FlakyFlagTests`, `Grep Filter & Order Seed Tests`, `Worker Reservation Batch Tests`, `HTML Report Artifact Embedding`, `test_backward_compatibility.py`, `ExecUnit`, `XmlSanitizationTests`, `Multi-Project Duration Tests`, `AddMarkerTests`, `Sharding Integration Tests`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `Result` connect `Contributing` to `JobObject & Fixture Core`, `FlakyReportCliTests`, `Historical Timing & Reporter`, `Test Orchestrator Core`, `PlaywrightAndImportTests`, `Worker Count & Project Loading`, `AbsentConfigDefaultsToOffTests`, `Multi-Project Execution`, `CLI History DB Path Tests`, `SingleProjectRunUnchangedTests`, `HTML Report Artifacts`, `Deterministic Report Ordering`, `warn_unregistered_cli_tags`, `Test Grouping Dimensions`, `CLI Entry Point & Argument Parsing`, `Fail Policy State Tracking`, `Log Secret Redaction`, `CtrlRunner`, `Frontend Build & Metrics Plans`, `LineReporter`, `ItemTests`, `JUnit XML Reporter`, `TbFilterTests`, `ctrlrunner.toml Config Loading`, `MultiProjectDurationTests`, `WallClockParallelismTests`, `Migration CST Transformer`, `Coverage Integration Tests`, `Local Server Security Helpers`, `UnifiedResultShapeTests`, `Fixture Resolution Engine`, `Parametrize Helper Tests`, `resolve_coverage_config`, `Empty Selection Exit Code Tests`, `Worker Config CLI Tests`, `GrepCliTests`, `FlakyFlagTests`, `lpt_shard`, `FixtureConversionTests`, `ReportCharsThreadingTests`, `Grep Filter & Order Seed Tests`, `Worker Reservation Batch Tests`, `_build_run_parser`, `Project CLI Integration Tests`, `HTML Report Artifact Embedding`, `HistoryDbPathDerivationTests`, `Config file, tags & test metadata reference`, `CollectionSummaryPrintTests`, `ConfigValidationTests`, `ExecUnit`, `PytestParamConversionTests`, `RunProjectsIntegrationTests`, `add_marker Migration Tests`, `Multi-Project Line Reporter Tests`, `AddMarkerTests`, `Sharding Integration Tests`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `HistoryStore` connect `Historical Timing & Reporter` to `Test Orchestrator Core`, `AbsentConfigDefaultsToOffTests`, `Worker Count & Project Loading`, `Multi-Project Execution`, `SingleProjectRunUnchangedTests`, `warn_unregistered_cli_tags`, `Test Grouping Dimensions`, `CLI Entry Point & Argument Parsing`, `Fail Policy State Tracking`, `CtrlRunner`, `Frontend Build & Metrics Plans`, `LineReporter`, `TbFilterTests`, `ctrlrunner.toml Config Loading`, `MultiProjectDurationTests`, `WallClockParallelismTests`, `Coverage Integration Tests`, `Fixture Resolution Engine`, `Parametrize Helper Tests`, `FlakyFlagTests`, `Empty Selection Exit Code Tests`, `Worker Config CLI Tests`, `GrepCliTests`, `lpt_shard`, `FixtureConversionTests`, `ReportCharsThreadingTests`, `Grep Filter & Order Seed Tests`, `Worker Reservation Batch Tests`, `_build_run_parser`, `Project CLI Integration Tests`, `HTML Report Artifact Embedding`, `HistoryDbPathDerivationTests`, `test_backward_compatibility.py`, `CollectionSummaryPrintTests`, `ConfigValidationTests`, `ExecUnit`, `PytestParamConversionTests`, `RunProjectsIntegrationTests`, `Multi-Project Line Reporter Tests`, `AddMarkerTests`, `Sharding Integration Tests`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Are the 228 inferred relationships involving `Orchestrator` (e.g. with `FailPolicyState` and `JobObject`) actually correct?**
  _`Orchestrator` has 228 INFERRED edges - model-reasoned connections that need verification._
- **Are the 194 inferred relationships involving `Result` (e.g. with `ConsoleReporter` and `DotsReporter`) actually correct?**
  _`Result` has 194 INFERRED edges - model-reasoned connections that need verification._
- **Are the 130 inferred relationships involving `HistoryStore` (e.g. with `ConsoleReporter` and `AddoptionCliIntegrationTests`) actually correct?**
  _`HistoryStore` has 130 INFERRED edges - model-reasoned connections that need verification._
- **Are the 88 inferred relationships involving `TestItem` (e.g. with `Metafunc` and `FormatCollectionSummaryTests`) actually correct?**
  _`TestItem` has 88 INFERRED edges - model-reasoned connections that need verification._