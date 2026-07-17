import type { ReportData, TestData } from '../shared/types';
import { Filter } from './filter';

export type Stats = {
  total: number;
  passed: number;
  failed: number;
  skipped: number; // skipped + fixme
  expectedFailure: number;
  quarantined: number;
  cancelled: number;
  notRun: number;
  duration: number;
};

export function emptyStats(): Stats {
  return {
    total: 0,
    passed: 0,
    failed: 0,
    skipped: 0,
    expectedFailure: 0,
    quarantined: 0,
    cancelled: 0,
    notRun: 0,
    duration: 0,
  };
}

export function addToStats(stats: Stats, test: TestData): void {
  stats.total++;
  stats.duration += test.duration;
  switch (test.outcome) {
    case 'passed':
      stats.passed++;
      break;
    case 'failed':
      stats.failed++;
      break;
    case 'skipped':
    case 'fixme':
      stats.skipped++;
      break;
    case 'expected_failure':
      stats.expectedFailure++;
      break;
    case 'quarantined_failure':
      stats.quarantined++;
      break;
    case 'cancelled':
      stats.cancelled++;
      break;
    default:
      stats.notRun++;
  }
}

export type Group = {
  label: string;
  tests: TestData[];
  stats: Stats;
};

export type ReportModel = {
  report: ReportData;
  activeDimension: string;
  sortMode: SortMode;
  filter: Filter;
  // Tests matching the filter, in display order (failed groups first,
  // failures first within a group) -- also the prev/next ordering.
  visibleTests: TestData[];
  groups: Group[];
  filteredStats: Stats;
  totalStats: Stats;
};

const UNGROUPED = 'ungrouped';

function outcomeWeight(test: TestData): number {
  if (test.outcome === 'failed') return 2;
  if (test.outcome === 'quarantined_failure') return 1;
  return 0;
}

export type SortMode =
  | 'failures'
  | 'file-asc'
  | 'file-desc'
  | 'duration-desc'
  | 'duration-asc'
  | 'flaky-first'
  | 'near-timeout-first';

export const DEFAULT_SORT_MODE: SortMode = 'failures';

export const SORT_MODE_LABELS: Record<SortMode, string> = {
  failures: 'Failures first',
  'file-asc': 'File (A→Z)',
  'file-desc': 'File (Z→A)',
  'duration-desc': 'Duration (slowest first)',
  'duration-asc': 'Duration (fastest first)',
  'flaky-first': 'Flaky first',
  'near-timeout-first': 'Near timeout first',
};

function flakyCount(group: Group): number {
  return group.tests.filter((t) => t.flaky).length;
}

function nearTimeoutCount(group: Group): number {
  return group.tests.filter((t) => t.nearTimeout).length;
}

function sortGroups(groups: Group[], sortMode: SortMode): Group[] {
  const sorted = [...groups];
  switch (sortMode) {
    case 'file-asc':
      sorted.sort((a, b) => a.label.localeCompare(b.label));
      break;
    case 'file-desc':
      sorted.sort((a, b) => b.label.localeCompare(a.label));
      break;
    case 'duration-desc':
      sorted.sort((a, b) => b.stats.duration - a.stats.duration);
      break;
    case 'duration-asc':
      sorted.sort((a, b) => a.stats.duration - b.stats.duration);
      break;
    case 'flaky-first':
      sorted.sort((a, b) => flakyCount(b) - flakyCount(a));
      break;
    case 'near-timeout-first':
      sorted.sort((a, b) => nearTimeoutCount(b) - nearTimeoutCount(a));
      break;
    default:
      sorted.sort(
        (a, b) => b.stats.failed + b.stats.quarantined - (a.stats.failed + a.stats.quarantined),
      );
  }
  return sorted;
}

export function buildModel(
  report: ReportData,
  query: string,
  requestedDimension: string | null,
  sortMode: SortMode = DEFAULT_SORT_MODE,
): ReportModel {
  const activeDimension =
    requestedDimension && report.dimensions.includes(requestedDimension)
      ? requestedDimension
      : report.dimensions[0] || 'file';

  const filter = new Filter(query);
  const totalStats = emptyStats();
  for (const test of report.tests) addToStats(totalStats, test);

  const byLabel = new Map<string, Group>();
  for (const test of report.tests) {
    if (!filter.matches(test)) continue;
    const label = test.groups?.[activeDimension] || UNGROUPED;
    let group = byLabel.get(label);
    if (!group) {
      group = { label, tests: [], stats: emptyStats() };
      byLabel.set(label, group);
    }
    group.tests.push(test);
    addToStats(group.stats, test);
  }

  const groups = sortGroups([...byLabel.values()], sortMode);
  const durationSort = sortMode === 'duration-desc' || sortMode === 'duration-asc';
  for (const group of groups) {
    group.tests = durationSort
      ? [...group.tests].sort((a, b) =>
          sortMode === 'duration-desc' ? b.duration - a.duration : a.duration - b.duration,
        )
      : [...group.tests].sort((a, b) => outcomeWeight(b) - outcomeWeight(a));
  }

  const visibleTests = groups.flatMap((g) => g.tests);
  const filteredStats = emptyStats();
  for (const test of visibleTests) addToStats(filteredStats, test);

  return {
    report,
    activeDimension,
    sortMode,
    filter,
    visibleTests,
    groups,
    filteredStats,
    totalStats,
  };
}

// Share of passed tests among those that actually ran to a verdict
// (skipped/fixme/cancelled/not-run don't count against the rate;
// expected failures count as passing outcomes). null = nothing ran.
export function passRate(stats: Stats): number | null {
  const executed = stats.total - stats.skipped - stats.cancelled - stats.notRun;
  if (executed <= 0) return null;
  return (stats.passed + stats.expectedFailure) / executed;
}

export function formatPassRate(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 1000) / 10}%`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 0) return '';
  if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
