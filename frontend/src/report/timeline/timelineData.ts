import type { ReportData, TestData } from '../../shared/types';

export interface TimelineBar {
  testId: string;
  outcome: TestData['outcome'];
  offsetSeconds: number;
  durationSeconds: number;
  workerId: number;
  caseId: string | null;
  attempts: number;
  flaky: boolean;
  lane: number;
}

export interface TimelineRow {
  workerId: number;
  bars: TimelineBar[];
  laneCount: number;
}

export interface TimelineModel {
  rows: TimelineRow[];
  axisMaxSeconds: number;
  isEmpty: boolean;
}

function hasTimelineData(t: TestData): boolean {
  return t.workerId != null && t.startedAt != null;
}

// Bars whose real duration renders to sub-pixel width (near-simultaneous
// fast tests) would otherwise sit invisibly under/behind a later,
// longer-running bar on the same row. Treat every bar as occupying at
// least this fraction of the axis range for OVERLAP DETECTION ONLY
// (rendered width still reflects the real duration) so near-coincident
// bars get pushed into separate lanes instead of visually merging.
const MIN_VISUAL_OVERLAP_FRACTION = 0.006;

// Greedy interval-stacking (same idea as calendar event layout): sorted
// bars each claim the first lane whose last-placed bar has already
// "ended" (real duration, floored to MIN_VISUAL_OVERLAP_FRACTION of the
// axis range so near-zero-duration bars still count as occupying visible
// space); otherwise a new lane opens. Mutates `lane` on each bar and
// returns the number of lanes used.
function assignLanes(bars: TimelineBar[], axisMaxSeconds: number): number {
  const minSpan = axisMaxSeconds > 0 ? axisMaxSeconds * MIN_VISUAL_OVERLAP_FRACTION : 0;
  const laneEnds: number[] = [];
  for (const bar of bars) {
    const effectiveEnd = bar.offsetSeconds + Math.max(bar.durationSeconds, minSpan);
    let lane = laneEnds.findIndex((end) => end <= bar.offsetSeconds);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(effectiveEnd);
    } else {
      laneEnds[lane] = effectiveEnd;
    }
    bar.lane = lane;
  }
  return laneEnds.length || 1;
}

export function buildTimelineModel(report: ReportData): TimelineModel {
  const runStart = report.runStartedAt;
  const positioned = report.tests.filter(hasTimelineData);

  if (runStart == null || positioned.length === 0) {
    return { rows: [], axisMaxSeconds: 0, isEmpty: true };
  }

  const rowCount =
    report.numWorkers != null
      ? report.numWorkers
      : Math.max(...positioned.map((t) => t.workerId as number)) + 1;

  const rowsByWorker = new Map<number, TimelineBar[]>();
  for (let w = 1; w <= rowCount; w++) rowsByWorker.set(w, []);

  let axisMaxSeconds = report.runDuration ?? 0;

  for (const t of positioned) {
    const workerId = t.workerId as number;
    const offsetSeconds = (t.startedAt as number) - runStart;
    const bar: TimelineBar = {
      testId: t.id,
      outcome: t.outcome,
      offsetSeconds,
      durationSeconds: t.duration,
      workerId,
      caseId: t.caseId,
      attempts: t.attempts,
      flaky: t.flaky,
      lane: 0, // filled in by assignLanes() once axisMaxSeconds is final
    };
    const bucket = rowsByWorker.get(workerId);
    if (!bucket) continue; // workerId outside 1..numWorkers -- drop rather than manufacture a row
    bucket.push(bar);
    axisMaxSeconds = Math.max(axisMaxSeconds, offsetSeconds + t.duration);
  }

  const rows: TimelineRow[] = Array.from(rowsByWorker.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([workerId, bars]) => {
      const sorted = bars.sort((a, b) => a.offsetSeconds - b.offsetSeconds);
      const laneCount = assignLanes(sorted, axisMaxSeconds);
      return { workerId, bars: sorted, laneCount };
    });

  return { rows, axisMaxSeconds, isEmpty: false };
}

export function generateAxisTicks(maxSeconds: number, targetTickCount = 6): number[] {
  if (maxSeconds <= 0) return [0];
  const rawStep = maxSeconds / targetTickCount;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const niceStep =
    (normalized >= 5 ? 10 : normalized >= 2 ? 5 : normalized >= 1 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  for (let t = 0; t <= maxSeconds; t += niceStep) ticks.push(Math.round(t * 100) / 100);
  return ticks;
}
