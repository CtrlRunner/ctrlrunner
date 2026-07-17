# Graph Report - pyrunner  (2026-07-17)

## Corpus Check
- 170 files · ~155,717 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3168 nodes · 6997 edges · 221 communities (124 shown, 97 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 2269 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d8a4f0ef`
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
- cli.py
- AbsentConfigDefaultsToOffTests
- PlaywrightAndImportTests
- IndirectParametrizeTests
- Fixture Conversion Migration Tests
- origin_allowed
- Param Metadata Execution Tests
- SingleProjectRunUnchangedTests
- ChunkTests
- SingleProjectRunUnchangedTests
- test_reporter.py
- AddoptionMigrationTests
- ui_server.py
- Config Package Docstring
- Fixture Session Teardown
- Core Package Docstring
- Execution Package Docstring
- Playwright Package Docstring
- Reporting Package Docstring
- UI Package Docstring
- Project Package Metadata
- ProfilingIntegrationTests
- CtrlRunner
- Core concepts
- cli.py
- MultiProjectDurationTests
- ._make_coverage_test_dir
- load_projects
- ReportTimestampCliOverrideTests
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- _result_to_event
- TagNotCliTests
- ctrlrunner frontend
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
- pytest -> ctrlrunner automatic conversion table
- ctrlrunner.migrate (pytest -> ctrlrunner migration tool)
- Local HTTP server defenses (Host allowlist, origin validation, session token)
- Captured log secret redaction
- After src/ changes, npm run build + commit regenerated bundles (staleness cannot be auto-detected)
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
- test_example.py

## God Nodes (most connected - your core abstractions)
1. `Orchestrator` - 222 edges
2. `Result` - 145 edges
3. `HistoryStore` - 127 edges
4. `TestItem` - 93 edges
5. `FailPolicyState` - 90 edges
6. `TagRegistry` - 88 edges
7. `ProjectConfig` - 84 edges
8. `QuarantineConfig` - 77 edges
9. `CoverageConfig` - 74 edges
10. `GroupingDimension` - 73 edges

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

## Communities (221 total, 97 thin omitted)

### Community 0 - "JobObject & Fixture Core"
Cohesion: 0.27
Nodes (5): Guards the UI / report servers against being exposed on a network     by acciden, _resolve_bind_host(), _show_report(), BindHostGuardCliTests, _resolve_bind_host is the only thing standing between the     auth-light UI/repo

### Community 2 - "Historical Timing & Reporter"
Cohesion: 0.09
Nodes (11): compute_near_timeout_test_ids(), HistoryStore, `CREATE TABLE IF NOT EXISTS` in _SCHEMA is a no-op against a         table that, Most recent `window` durations for a test, newest first --         the direct in, Most recent `window` (outcome, attempts, retries_configured)         rows for a, Every distinct test_id with at least one recorded run,         scoped by project, Section 4.8's hang-risk heuristic: flags a test_id whose median     historical d, ComputeNearTimeoutTestIdsTests (+3 more)

### Community 3 - "Worker Budget & Sharding Units"
Cohesion: 0.31
Nodes (3): Separate, always-warning-only check (never blocking, even in     strict mode) fo, warn_unregistered_cli_tags(), WarnUnregisteredCliTagsTests

### Community 5 - "Worker Count & Project Loading"
Cohesion: 0.13
Nodes (8): EventEnvelope, EventSubscriber, A versioned, serializable event envelope -- the stable public shape for anything, The stable, envelope-based observation interface -- what hooks     and reporter-, EventEnvelopeTests, EventSubscriberTests, CustomOptionsEndToEndTests, The options dict passed to Orchestrator reaches get_option() in     a spawned wo

### Community 6 - "Named Projects & Tag Registry"
Cohesion: 0.19
Nodes (5): load_tag_registry(), Returns None (no validation at all) if `registered_tags` isn't in     config --, AbsentConfigDefaultsToOffTests, Every opt-in [ctrlrunner.*] section, when absent entirely, must     resolve to i, LoadTagRegistryTests

### Community 7 - "Multi-Project Execution"
Cohesion: 0.06
Nodes (30): ProjectConfig, Named projects.  A project is a named override bundle over base config -- resolv, Runs each named project as its own Orchestrator.run() within this     process, m, Only strict mode needs this early pass -- warning-mode     validation happens fi, Gives every test in a project that never got to start (an     earlier project's, Validates every requested name exists; raises ValueError listing     what IS ava, _report_project_not_run(), resolve_project_names() (+22 more)

### Community 8 - "Flaky Test Analytics"
Cohesion: 0.13
Nodes (12): compute_flake_score(), compute_flaky_report(), FlakyStats, format_flaky_report(), Flaky analytics.  "Flaky" is already latent in existing history data: a run wher, outcome_rows: HistoryStore.get_outcomes()'s own shape. Returns     (flake_score,, One row per test_id with history, sorted most-flaky-first (an     unknown/no-sam, ComputeFlakeScoreTests (+4 more)

### Community 9 - "CLI History DB Path Tests"
Cohesion: 0.23
Nodes (8): Result, DotsReporter, One character per test: '.' pass, 'F' fail, 's' skip, 'f' fixme,     'x' expecte, _summary_lines(), DotsReporterTests, _results_with_annotations(), SummaryLinesFlakyTests, SummaryLinesModuleBreakdownTests

### Community 10 - "Assert Details & Event Integration Tests"
Cohesion: 0.22
Nodes (8): _cartesian(), param, parametrize(), Any, Stacks parametrization metadata onto the function; @test expands it     into one, Renders one parametrize value for the test id suffix. Plain str/     int/bool/et, One @parametrize entry with per-entry metadata -- ctrlrunner's     equivalent of, _stable_param_str()

### Community 11 - "Coverage.py Integration"
Cohesion: 0.27
Nodes (3): Mirrors resolve_fail_policy()/resolve_quarantine_config(): reads     config["cov, resolve_coverage_config(), ResolveCoverageConfigTests

### Community 12 - "Playwright Fixture Config Tests"
Cohesion: 0.05
Nodes (14): ClosableFakeContext, ConfigureTests, ContextFixtureTeardownTests, ContextSetupTracingDecisionTests, CrashingPage, FakeBrowser, FakeContext, FakePage (+6 more)

### Community 13 - "HTML Report Artifacts"
Cohesion: 0.13
Nodes (5): report_dir: where artifacts get copied to (as <report_dir>/artifacts/).     If N, render_html(), ArtifactModeTests, _extract_embedded_data(), HtmlReportTests

### Community 15 - "Deterministic Report Ordering"
Cohesion: 0.22
Nodes (6): build_reporters(), _load_custom_reporter(), Loads a user-supplied reporter from a 'module.path:ClassName'     spec (--report, BuildReportersTests, CustomReporterLoaderTests, --reporter accepts 'module.path:ClassName'     specs -- the class is imported an

### Community 16 - "Fixture Dependency Resolution"
Cohesion: 0.05
Nodes (19): ExitStack, FixtureResolver, Tears down module- and session-scoped fixtures. Call once when         the worke, Call before running each test. Tears down module-scoped         fixtures when th, Returns (values, resolved_all).          `values` has one entry per name in `nam, DiTests, FixtureProfilingStepTests, IndirectOverrideResolutionTests (+11 more)

### Community 18 - "Test Grouping Dimensions"
Cohesion: 0.22
Nodes (6): compute_groups(), GroupingDimension, ComputeGroupsTests, _item(), GroupingIntegrationTests, Verifies grouping is computed through a real Orchestrator.run(),     not just th

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
Cohesion: 0.12
Nodes (10): Pattern, Best-effort redaction of obvious secrets from captured test logs before they're, Reads [ctrlrunner.log_redaction]. Returns compiled patterns (built-in     defaul, Applies redaction to a worker's per-attempt log list (the shape     log_capture., redact_log_entries(), redact_text(), resolve_redaction_patterns(), RedactLogEntriesTests (+2 more)

### Community 26 - "LPT Sharding Algorithm"
Cohesion: 0.11
Nodes (14): duration_weights(), lookup_median_durations(), lpt_shard(), _lpt_shard_weighted(), Longest-processing-time-first (LPT) greedy bin-packing across workers, using eac, Generic LPT greedy bin-packer over (item, weight) pairs. With     all-equal weig, (key, weight) pairs for _lpt_shard_weighted: a known median is     used as-is; N, durations: test_id -> known median duration, or None/absent for a     test with (+6 more)

### Community 27 - "Frontend Build & Metrics Plans"
Cohesion: 0.05
Nodes (20): Orchestrator, Reporting + requeue decision for a hard-killed slot. Returns         the ExecUni, Crossing a fail-policy threshold reuses the exact same         cancel_event/hard, Returns (effective_outcome, is_quarantined, reason).          A quarantined test, Builds an EventEnvelope and hands it to every registered         EventSubscriber, Runs one ConsoleReporter method call, catching any         exception so a broken, A cancelled/not_run/hard-killed/crashed test_end can fire         for a test tha, Safety belt for the exactly-once result contract: every         selected test mu (+12 more)

### Community 28 - "Report Directory Resolution"
Cohesion: 0.14
Nodes (9): find_latest_report_dir(), _prune_old_reports(), Path, Resolves where a managed HTML report directory lives, and prunes old timestamped, Read-only counterpart to resolve_report_dir(), for --last-failed     (section 4., Keeps only the `keep - 1` most recent '<report_name>-<timestamp>'     directorie, resolve_report_dir(), FindLatestReportDirTests (+1 more)

### Community 29 - "--list Output Formatting"
Cohesion: 0.21
Nodes (4): format_list(), fmt: "text" | "json" | "md". `fields` only affects text/md --     json always in, FormatListTests, _item()

### Community 30 - "JUnit XML Reporter"
Cohesion: 0.05
Nodes (21): JUnitReporter, multi_project=True wraps output in <testsuites> with one         <testsuite> per, Emits standard JUnit XML so the existing JUnit-XML-to-Teams pipeline     keeps w, _render_steps_text(), _sanitize_xml_text(), AtomicWriteTests, DeterministicOrderTests, JUnitGoldenBytesTests (+13 more)

### Community 31 - "Migration Import Rewriting Tests"
Cohesion: 0.12
Nodes (4): AddMarkerTests, PytestParamConversionTests, Returns (report, {relative_name: new_source})., TestFunctionConversionTests

### Community 32 - "Migration AST Transformer Core"
Cohesion: 0.14
Nodes (13): BaseExpression, EmptyLine, _dotted(), _has_todo(), _PytestParamConverter, Pass 2 of the migration: the libcst rewrite of one file.  What gets converted au, request.node.add_marker(pytest.mark.<case-id-marker>(x)) ->         record_prope, pytest.skip/fail/xfail as a standalone statement. (+5 more)

### Community 33 - "graphify Skill Reference Docs"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 34 - "ctrlrunner.toml Config Loading"
Cohesion: 0.17
Nodes (12): CoverageConfig, CoverageSummary, finalize_coverage(), Coverage.py integration support: config resolution and per-run data-dir lifecycl, Combine every worker's data file in coverage_config.data_dir,     generate the o, Resolved, run-scoped coverage configuration. The SAME instance is     passed to, FinalizeCoverageTests, Runs real coverage.py instrumentation against a scratch module,         saving a (+4 more)

### Community 35 - "Step Tree Recording"
Cohesion: 0.07
Nodes (15): _BoundedBuffer, capture_logs(), _CaptureHandler, Buffered stdout/stderr + logging capture for one test attempt, used by worker.py, Captures stdout, stderr, and Python logging records for the     duration of the, A tail-keeping, byte-capped text buffer -- a chatty test must     not OOM the wo, Writes to both the bounded buffer and the original stream, so     worker output, Appends one dict per log record to a plain list. Never raises:     record.getMes (+7 more)

### Community 36 - "Migration Function Plan Builder"
Cohesion: 0.16
Nodes (9): Arg, ClassDef, Decorator, FunctionDef, _code(), MigrationTransformer, Value of a positional-or-keyword argument, or None., @pytest.mark.<case-id-marker>("7412675") -> @test(case_id="7412675").         Th (+1 more)

### Community 37 - "Assert Introspection Tests"
Cohesion: 0.07
Nodes (23): Assert, AssertionError, AST, Module, _build(), build_assert_details(), _collect_names(), _contains_forbidden() (+15 more)

### Community 39 - "Selftest Fakes & Fixtures"
Cohesion: 0.11
Nodes (6): # NOTE: decorators apply bottom-up, so @parametrize must sit closer to the, test_fail_non_strict_allows_unexpected_pass(), test_fail_strict_flags_unexpected_pass(), test_fail_strict_reports_expected_failure(), fail(), Marks the rest of this test as expected to fail (pytest's xfail,     named after

### Community 40 - "Test Selection Filters"
Cohesion: 0.07
Nodes (5): All filters are AND-ed together; each accepts multiple values (OR     within tha, select_tests(), ParamHelperTests, _item(), SelectionTests

### Community 42 - "Migration CLI Entry Point"
Cohesion: 0.12
Nodes (19): Counter, pytest -> ctrlrunner source migration.  Usage:     python -m ctrlrunner.migrate, FileReport, MigrationReport, Migration report model + rendering (console and markdown)., _alias_local_name(), fix_imports(), _import_module_name() (+11 more)

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
Cohesion: 0.15
Nodes (6): TagRegistry, EventOrderingTests, NearTimeoutPerAttemptTests, near_timeout must compare a SINGLE attempt's own duration to     its own per-att, test_end for a test a worker was killed/crashed over must     precede that worke, TagRegistryTests

### Community 47 - "Playwright Auto-Step Tests"
Cohesion: 0.19
Nodes (5): Quarantine.  A config-driven allowlist, populated by a human after reviewing `ct, Returns None if [ctrlrunner.quarantine] is absent entirely -- zero     behavior, resolve_quarantine_config(), QuarantineConfigTests, ResolveQuarantineConfigTests

### Community 48 - "JSON Reporter"
Cohesion: 0.17
Nodes (5): auto_step(), Wrap a Playwright Page (or Locator) so its actions are     automatically recorde, AutoStepTests, FakeLocator, FakePage

### Community 49 - "ExecUnit Ordering & Requeue"
Cohesion: 0.09
Nodes (14): Namespace, AddoptionError, _Declaration, OptionParser, ArgumentParser, ctrlrunner_addoption -- the pytest_addoption equivalent.  A conftest.py may defi, argparse's dest rule, for use before apply_to has run:         explicit dest= wi, declared defaults <- [ctrlrunner.options], WITHOUT any CLI         layer (the ba (+6 more)

### Community 50 - "Frontend Stats Model"
Cohesion: 0.16
Nodes (24): formatMetaDuration(), HeaderView(), PassRateBadge(), statusTokenActive(), addToStats(), buildModel(), emptyStats(), flakyCount() (+16 more)

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
Cohesion: 0.19
Nodes (16): expr, _decorator_dotted_name(), discover_files(), FixtureInfo, IndirectInjection, _is_fixture_decorator(), ProjectIndex, Path (+8 more)

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
Cohesion: 0.28
Nodes (14): BanIcon(), CheckIcon(), ChevronIcon(), ClockIcon(), CopyIcon(), CrossIcon(), IconProps, ImageIcon() (+6 more)

### Community 59 - "Pytest Config Migration"
Cohesion: 0.16
Nodes (5): load_grouping_dimensions(), Returns DEFAULT_DIMENSIONS (just "module") if `[grouping]` is     absent from co, ConfigNestingGotchaTests, Regression test for a real gotcha hit during manual verification:     a bare `[g, LoadGroupingDimensionsTests

### Community 60 - "UnifiedResultShapeTests"
Cohesion: 0.21
Nodes (7): THE public serialization of one test Result -- the single source     of truth fo, result_to_public_dict(), Deterministic report order (JUnit + JSON writers): worker     completion timing, result_sort_key(), Pluggable console reporters, modeled on Playwright TS's reporter set. The orches, This module promises ONE schema for streaming and reporting.     The test_end ev, UnifiedResultShapeTests

### Community 61 - "Advanced Examples Fixtures"
Cohesion: 0.18
Nodes (5): audit_log(), module_resource(), Shared fixtures for every test_*.py under examples/advanced/. Discovered and imp, One instance per test module per worker, not per test. Torn down     when the wo, Runs for every test automatically, even though no test lists it     as a paramet

### Community 62 - "Fixture Resolution Engine"
Cohesion: 0.15
Nodes (13): discover_and_import(), discover_and_import_multi(), discover_conftests(), discover_modules(), _dotted_module_name(), Path, root may be a directory (globbed for test_*.py) or a single file     (pytest-sty, The human-readable dotted name (e.g. "suite.test_a") a file gets     as its modu (+5 more)

### Community 63 - "Fail Policy Resolution Tests"
Cohesion: 0.19
Nodes (4): Fail policies.  A single mutable FailPolicyState is shared across every Orchestr, CLI > config > built-in default (0/0/False), same precedence as     everywhere e, resolve_fail_policy(), ResolveFailPolicyTests

### Community 64 - "Migration Dry-Run & Idempotency Tests"
Cohesion: 0.11
Nodes (6): DryRunWriteAndIdempotencyTests, FixtureConversionTests, HookAndAsyncTests, MigrateTestCase, RuntimeCallTests, TestClassConversionTests

### Community 65 - "Parametrize Helper Tests"
Cohesion: 0.16
Nodes (5): QuarantineConfig, IndirectParametrizeEndToEndTests, QuarantineIntegrationTests, Real Orchestrator.run() verification for section 4.9's     quarantine mechanism, @parametrize(..., indirect=...) through the real worker path:     a stateful gen

### Community 67 - "resolve_coverage_config"
Cohesion: 0.33
Nodes (4): format_collection_summary(), A one-line "what did we collect" summary printed before a real run starts, regar, FormatCollectionSummaryTests, _item()

### Community 68 - "Empty Selection Exit Code Tests"
Cohesion: 0.19
Nodes (3): EmptySelectionExitCodeTests, FailOnFlakyCliTests, A run that selected zero tests must exit     with code 4, not 0 -- a typo'd --ta

### Community 69 - "Worker Config CLI Tests"
Cohesion: 0.08
Nodes (5): AddoptionCliIntegrationTests, CoverageCliIntegrationTests, ctrlrunner_addoption end to end: declaration in conftest.py,     --help visibili, RerunCliIntegrationTests, WorkerConfigCliTests

### Community 70 - "README.md"
Cohesion: 0.16
Nodes (7): Dev tooling (uv / ruff / ty), Developing ctrlrunner, Project layout, Running ctrlrunner's own test suite, Event model (for reporter/hook/plugin authors), Explicitly not included, Migrating from pytest

### Community 71 - "Timeline Gantt Chart"
Cohesion: 0.18
Nodes (17): BarTooltipContent(), formatSeconds(), formatZoomLabel(), GanttChart(), roundZoom(), rowHeight(), trackHeight(), assignLanes() (+9 more)

### Community 72 - "lpt_shard"
Cohesion: 0.11
Nodes (9): HistoryConfig, HistoryReporter, Historical timing store (storage half; smart sharding is a separate follow-up th, Writes one `runs` row plus one `test_runs` row per result, all         in a sing, Records one run's results to a HistoryStore on_run_end. Safe to     reuse the sa, resolve_history_config(), HistoryWriteProcessBoundaryTests, This is worth a dedicated     assertion, not just an implicit consequence' -- Hi (+1 more)

### Community 73 - "Static Report Server"
Cohesion: 0.06
Nodes (40): format_unregistered_tags_warning(), Optional tag registry (ctrlrunner.toml `registered_tags`) -- catches typos in @t, Single shared message format for the 'some tags aren't in     registered_tags' w, FixtureRequest, Fixture dependency resolution. Fixtures are resolved recursively by parameter na, Passed to fixtures that declare a `request` parameter, so a     parametrized fix, clear_tests(), _collect_parametrized_fixtures() (+32 more)

### Community 74 - "Contributing"
Cohesion: 0.33
Nodes (6): Before opening a PR, Contributing, Dev setup, Linting, formatting, type checking, Releasing, Running the test suite

### Community 75 - "Absent-Config Defaults Tests"
Cohesion: 0.18
Nodes (6): CSTNode, _FnPlan, Drop statements from body by identity (the exact node objects         stashed ea, Everything decided about one function before rebuilding it., Classify and collect every decision; None -> leave untouched., If a request.node.add_marker(<case-id-marker>(x)) call was         stashed by _r

### Community 76 - "UI Server HTTP Handling"
Cohesion: 0.21
Nodes (6): _QuietHTTPServer, A page reload tears down the browser's in-flight EventSource     connection (and, QuietHTTPServerTests, A page reload aborts the browser's in-flight EventSource     connection with a T, ServeUICtrlCTests, ThreadingHTTPServer

### Community 77 - "Config Migration Tests"
Cohesion: 0.27
Nodes (3): ConfigMigrationTests, Path, _write_tree()

### Community 79 - "Migration Report Rendering"
Cohesion: 0.16
Nodes (11): test_fixme_marks_known_broken(), test_skipped_via_runtime_condition(), begin_test(), fixme(), FixmeTest, Exception, Called by the worker before each test attempt., Stops the test immediately; reported as 'skipped', not a failure.     Nothing af (+3 more)

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
Cohesion: 0.25
Nodes (7): `--list`, Parallelism & scheduling, Parallelism, scheduling & test selection, Scoped worker budgets (`[ctrlrunner.workers]`), Serial classes (`@test_class(serial=True)`), Test selection (replaces `pytest_collection_modifyitems`), Worker isolation contract

### Community 89 - "Pytest Migration Conversion Table"
Cohesion: 0.29
Nodes (7): Fail policies, Fixture and execution profiling, Flaky analytics and quarantine, Historical timing store, Reporters, Reporters, history & flake management, Rerun workflows

### Community 91 - "Frontend App Entry & Dev Fixture"
Cohesion: 0.24
Nodes (9): devFixture, Window, Artifact, AssertDetails, AssertSide, CoverageSummary, LogRecord, Outcome (+1 more)

### Community 92 - "Unified Result Serialization"
Cohesion: 0.53
Nodes (5): main(), Path, Standalone benchmark for ctrlrunner's test discovery/import speed -- NOT part of, _run_one(), _write_suite()

### Community 93 - "Project CLI Integration Tests"
Cohesion: 0.13
Nodes (3): ListProjectScopingTests, ProjectCliIntegrationTests, First CLI-level tests in this project (prior verification was all     manual `py

### Community 94 - "ParamMetadataExecutionTests"
Cohesion: 0.19
Nodes (9): allowed_hosts(), allowed_origins(), new_session_token(), Shared localhost-server hardening for ctrlrunner's two stdlib http.server based, The exact Host header values this loopback server answers to.     Anything else, A fresh, unguessable per-launch token. token_urlsafe(32) is 256     bits of CSPR, Constant-time comparison so a wrong token can't be narrowed down     by response, token_matches() (+1 more)

### Community 95 - "Security & UI Mode Plan Docs"
Cohesion: 0.25
Nodes (8): Binding a non-loopback address, Captured logs may contain secrets, `--changed-since` and git, On-disk state, Report rendering (XSS), Security model, The local HTTP servers, Threat model

### Community 96 - "Playwright Fixture Definitions"
Cohesion: 0.10
Nodes (6): Takes effect on the next start_run() call -- each run         constructs a fresh, Returns False (does nothing) if a run is already in progress., Test helper: blocks until the current run finishes or timeout         elapses. R, RunController, LastResultsThreadSafetyTests, _last_results is written from the background run thread and     read from last_r

### Community 98 - "Context Info Tests"
Cohesion: 0.20
Nodes (3): ContextInfoTests, pytest's record_property equivalent -- runtime per-test     metadata that lands, RecordPropertyTests

### Community 99 - "Log Capture Tests"
Cohesion: 0.29
Nodes (6): [0.1.0] - 2026-07-15, Added, Added, Changelog, Fixed, [Unreleased]

### Community 100 - "Config file, tags & test metadata reference"
Cohesion: 0.29
Nodes (5): Class-level test metadata (`@test_class`), Config file (`ctrlrunner.toml`), Config file, tags & test metadata reference, Registered tag registry, Runtime annotations: `skip`, `fail`, `fixme`, `slow`

### Community 101 - "Parametrize Cartesian Product"
Cohesion: 0.33
Nodes (4): Import, ImportFrom, _asname_str(), String value of an import alias's `as` target, if present --     always a plain

### Community 102 - "test_backward_compatibility.py"
Cohesion: 0.09
Nodes (30): _build_reporters_or_exit(), _build_run_parser(), _build_ui_parser(), _flaky_report(), _guess_root(), main(), _num_workers_arg(), _parse_run_args() (+22 more)

### Community 103 - "Origin Validation Tests"
Cohesion: 0.19
Nodes (9): get_option(), get_options(), _normalize(), Per-process store for user-declared run options (ctrlrunner_addoption).  The CLI, Replaces the whole store (None clears it). Called once per     process by the CL, The value of a declared or [ctrlrunner.options]-configured     option. `default`, A copy of the whole store., set_options() (+1 more)

### Community 104 - "Coverage CLI Integration Tests"
Cohesion: 0.17
Nodes (11): Every test needs a `case_id`, Fixtures, Golden rule: decorator order, Imports, Retries, Screenshots/traces on failure, Skill: Writing tests with ctrlrunner, Skip / fail / fixme / slow (+3 more)

### Community 105 - "Case-ID Marker Migration Tests"
Cohesion: 0.13
Nodes (7): CliEndToEndBackwardCompatibilityTests, NoHistoryStoreRoundRobinUnchangedTests, Dedicated backward-compatibility suite. This is the single most important test c, Same guarantees as SingleProjectRunUnchangedTests, verified     through the real, A single-project or no-project run must keep today's exact     unprefixed test_i, Orchestrator without a history_store still runs every test to     completion --, SingleProjectRunUnchangedTests

### Community 109 - "Rerun ID Matching"
Cohesion: 0.22
Nodes (9): Manual conversion recipes, Marker-driven guard fixtures, Migrating from pytest to ctrlrunner, pyproject.toml -> ctrlrunner.toml, Recommended workflow, Semantics to double-check after migration, Usage, What is converted automatically (+1 more)

### Community 111 - "ExecUnit"
Cohesion: 0.04
Nodes (45): Fixture, Decorator to register a fixture. Supports plain-return and     generator (yield-, JobObject, Hard-kills every process currently in the job., One live worker process and everything the scheduler needs to     supervise it:, _WorkerSlot, Batch, One worker process's workload: an ordered list of ExecUnits.     `group`/`dedica (+37 more)

### Community 113 - "Atomic JUnit Write Tests"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 114 - "XmlSanitizationTests"
Cohesion: 0.23
Nodes (4): Serves the directory containing `path` (or `path` itself if it's     already a d, serve_report(), NoPortProbeTests, ServeReportTests

### Community 115 - "PytestParamConversionTests"
Cohesion: 0.12
Nodes (12): test_slow_extends_timeout(), Extends this test's timeout by `factor` for this run. Call before     the slow p, pytest-record_testsuite_property equivalent: run-level     metadata (environment, record_suite_property(), slow(), Exposes the current test's id/attempt number to fixture code, so built-in Playwr, pytest-record_property equivalent: call from a test     body or fixture to attac, record_property() (+4 more)

### Community 116 - "RunProjectsIntegrationTests"
Cohesion: 0.20
Nodes (5): _capture_trace(), configure(), page(), Built-in Playwright fixtures with trace/screenshot capture controlled entirely b, Registered with always_capture=True so this always runs, then     decides for it

### Community 117 - "Worker Module Import"
Cohesion: 0.22
Nodes (6): Returns the sorted list of unregistered tags found across every     collected te, validate_tags(), Imports test/conftest modules once at startup so list_tests()         works befo, FormatUnregisteredTagsWarningTests, _item(), ValidateTagsTests

### Community 119 - "Flaky Flag Tests"
Cohesion: 0.31
Nodes (3): BaseHTTPRequestHandler, Serves failure screenshots/other artifacts the frontend         links to (`<a hr, UIRequestHandler

### Community 120 - "tb_format.py"
Cohesion: 0.33
Nodes (5): _filter_chain(), format_filtered_exc(), Failure tracebacks shown to test authors should start at THEIR code, not at the, Drops ctrlrunner-internal frames from every link of the exception     chain (__c, traceback.format_exc() with ctrlrunner-internal frames removed.     Call from an

### Community 121 - "Backward-Compat CLI Tests"
Cohesion: 0.36
Nodes (3): origin_allowed(), Defense against a malicious page fetch()ing state-changing     endpoints. Reject, OriginAllowedTests

### Community 122 - "Multi-Project Duration Tests"
Cohesion: 0.13
Nodes (7): load_config(), Optional ctrlrunner.toml config file. CLI flags always take precedence over it;, ConfigTests, ConfigValidationTests, NestedGroupingTableTests, A typo'd key or mis-nested table used to be silently     ignored -- the run proc, Regression test for a real gotcha hit during manual verification:     a bare `[g

### Community 123 - "Multi-Project Line Reporter Tests"
Cohesion: 0.06
Nodes (8): GrepCliTests, HistoryDbPathDerivationTests, HtmlReportTimelineFieldsTests, MultiProjectLineReporterResetTests, OrderSeedCliTests, LineReporter._seen accumulates unique test_ids across an     entire multi-projec, RunManifestCliTests, UnknownReporterCliTests

### Community 124 - "AddMarkerTests"
Cohesion: 0.19
Nodes (8): _extract_aria_snapshot(), import_module_by_path(), module_name_for_path(), Path, Splits a Playwright Aria snapshot off the end of a failure     traceback and wri, The sys.modules DICT KEY for `path` -- a hash of its resolved     absolute path,, Imports the file at `path`, giving the resulting module object a     human-reada, _safe_test_dir()

### Community 126 - "Sharding Integration Tests"
Cohesion: 0.16
Nodes (7): ExecUnit, order_units(), The schedulable atom: an ordered list of test ids that must stay     together in, Reorders ExecUnits -- NEVER the tests inside one -- so a serial     group's memb, Result.worker_id should be populated from the slot that     produced it on every, WorkerIdOnResultTests, OrderUnitsTests

### Community 127 - "match_rerun_ids"
Cohesion: 0.19
Nodes (4): LineReporter, Overwrites a single progress line as tests run, printing failures     as they ha, Clears per-run progress state. The reporter instance is         reused across pr, LineReporterTests

### Community 130 - "cli.py"
Cohesion: 0.27
Nodes (9): TestItem, _group_by_module(), _group_by_path(), _group_by_property(), _group_by_tag_prefix(), A generic grouping strategy system for the HTML report / UI Mode, replacing the, _format_scalar(), --list output formatting. A pure view over already-selected TestItems: never a s (+1 more)

### Community 131 - "AbsentConfigDefaultsToOffTests"
Cohesion: 0.24
Nodes (4): prepare_data_dir(), Purge and recreate the per-run data directory. Call once, before     any worker, PrepareDataDirTests, ValueError

### Community 139 - "SingleProjectRunUnchangedTests"
Cohesion: 0.27
Nodes (3): AutoStepPage, _looks_like_locator(), Wraps a Playwright Page (or Locator) so common actions are automatically recorde

### Community 142 - "ui_server.py"
Cohesion: 0.40
Nodes (4): The UI Mode frontend.  The page is a prebuilt React app (frontend/src/ui/ in the, Injects the per-launch session token (see localsec.py) into the     served page., render_ui_html(), Local HTTP server exposing RunController over a small JSON API, plus a Server-Se

### Community 144 - "Fixture Session Teardown"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 154 - "CtrlRunner"
Cohesion: 0.29
Nodes (7): CtrlRunner, Documentation, Install, Quick start, Table of contents, Timeout & hard-kill model, Why this exists

### Community 155 - "Core concepts"
Cohesion: 0.25
Nodes (8): Core concepts, Custom options (`pytest_addoption` equivalent), `@fixture`, `indirect=` — per-test fixture parametrization, `param()` — per-combination metadata, `@parametrize`, Shared fixtures (`conftest.py`), `@test`

### Community 156 - "cli.py"
Cohesion: 0.43
Nodes (5): build_parser(), main(), ArgumentParser, CLI: python -m ctrlrunner.migrate <paths> [--write] [--no-diff] [--report FILE], render_diffs()

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

### Community 164 - "_result_to_event"
Cohesion: 0.40
Nodes (3): Every test's most recent result keyed by test id, accumulated         across run, Shared shape between the live `test_end` SSE event and     RunController.last_re, _result_to_event()

### Community 166 - "ctrlrunner frontend"
Cohesion: 0.50
Nodes (3): ctrlrunner frontend, Layout, Workflow

## Knowledge Gaps
- **239 isolated node(s):** `$schema`, `enabled`, `src/**`, `*.ts`, `index.html` (+234 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **97 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_config()` connect `Multi-Project Duration Tests` to `Pytest Config Migration`, `AbsentConfigDefaultsToOffTests`, `Config Migration Tests`, `test_backward_compatibility.py`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Why does `Orchestrator` connect `Frontend Build & Metrics Plans` to `Test Orchestrator Core`, `Worker Count & Project Loading`, `Named Projects & Tag Registry`, `Multi-Project Execution`, `Fixture Conversion Migration Tests`, `SingleProjectRunUnchangedTests`, `ChunkTests`, `Test Grouping Dimensions`, `Fail Policy State Tracking`, `ProfilingIntegrationTests`, `load_projects`, `ctrlrunner.toml Config Loading`, `Coverage Integration Tests`, `Pytest Config Migration`, `UnifiedResultShapeTests`, `Fixture Resolution Engine`, `Parametrize Helper Tests`, `FlakyFlagTests`, `Static Report Server`, `Grep Filter & Order Seed Tests`, `Worker Reservation Batch Tests`, `Playwright Fixture Definitions`, `HTML Report Artifact Embedding`, `test_backward_compatibility.py`, `Case-ID Marker Migration Tests`, `CollectionSummaryPrintTests`, `ConfigValidationTests`, `ExecUnit`, `add_marker Migration Tests`, `Sharding Integration Tests`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `select_tests()` connect `Test Selection Filters` to `Static Report Server`, `cli.py`, `Frontend Build & Metrics Plans`, `test_backward_compatibility.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 194 inferred relationships involving `Orchestrator` (e.g. with `FailPolicyState` and `JobObject`) actually correct?**
  _`Orchestrator` has 194 INFERRED edges - model-reasoned connections that need verification._
- **Are the 135 inferred relationships involving `Result` (e.g. with `ConsoleReporter` and `DotsReporter`) actually correct?**
  _`Result` has 135 INFERRED edges - model-reasoned connections that need verification._
- **Are the 112 inferred relationships involving `HistoryStore` (e.g. with `ConsoleReporter` and `AddoptionCliIntegrationTests`) actually correct?**
  _`HistoryStore` has 112 INFERRED edges - model-reasoned connections that need verification._
- **Are the 81 inferred relationships involving `TestItem` (e.g. with `FormatCollectionSummaryTests` and `_item()`) actually correct?**
  _`TestItem` has 81 INFERRED edges - model-reasoned connections that need verification._