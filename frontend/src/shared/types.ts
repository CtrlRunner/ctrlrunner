// Mirrors ctrlrunner/reporting/html_report.py::_result_to_dict exactly.
// The Python side is the source of truth for this contract.

export type Outcome =
  | 'passed'
  | 'failed'
  | 'skipped'
  | 'fixme'
  | 'expected_failure'
  | 'quarantined_failure'
  | 'cancelled'
  | 'not_run';

export type Step = {
  name: string;
  outcome: string;
  duration: number;
  error?: string | null;
  children?: Step[];
};

export type LogRecord = {
  level: string;
  name: string;
  message: string;
};

export type LogEntry = {
  attempt: number;
  stdout?: string;
  stderr?: string;
  records: LogRecord[];
  truncated?: boolean;
};

export type AssertSide = { repr: string; type: string };

export type AssertDetails = {
  expr: string;
  op?: string;
  left?: AssertSide;
  right?: AssertSide;
  diff?: string | { missing?: string[]; extra?: string[] };
  names?: Record<string, string>;
  truncated?: boolean;
};

export type Artifact = {
  label: string;
  href: string;
  embedded: boolean;
};

export type TestData = {
  id: string;
  caseId: string | null;
  tags: string[];
  outcome: Outcome;
  duration: number;
  attempts: number;
  error: string | null;
  artifacts: Artifact[];
  steps: Step[];
  properties: Record<string, unknown>;
  groups: Record<string, string>;
  quarantined: boolean;
  quarantineReason: string | null;
  nearTimeout: boolean;
  workerRestartOverhead: number | null;
  assertDetails: AssertDetails | null;
  logs: LogEntry[];
  workerId: number | null;
  startedAt: number | null;
  flaky: boolean;
};

export type CoverageSummary = {
  percent: number;
  htmlDir?: string;
};

export type ReportData = {
  suiteName: string;
  tests: TestData[];
  dimensions: string[];
  coverage?: CoverageSummary | null;
  generatedAt?: string;
  totalDuration?: number;
  runStartedAt?: number | null;
  runDuration?: number | null;
  numWorkers?: number | null;
};

export const OUTCOME_LABELS: Record<string, string> = {
  passed: 'Passed',
  failed: 'Failed',
  skipped: 'Skipped',
  fixme: 'Fixme',
  expected_failure: 'Expected failure',
  quarantined_failure: 'Quarantined',
  cancelled: 'Cancelled',
  not_run: 'Not run',
};
