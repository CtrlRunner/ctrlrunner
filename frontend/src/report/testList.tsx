import React from 'react';
import { Chip } from '../shared/chip';
import { ImageIcon, TraceIcon } from '../shared/icons';
import { StatusIcon } from '../shared/statusIcon';
import type { TestData } from '../shared/types';
import { filterWithToken } from './filter';
import { LabelsRow } from './labels';
import { hashFor, Link, useSearchParams, withParam } from './links';
import type { Group, ReportModel, SortMode } from './model';
import {
  DEFAULT_SORT_MODE,
  formatDuration,
  formatPassRate,
  passRate,
  SORT_MODE_LABELS,
} from './model';

const AUTO_EXPAND_LIMIT = 200;

function DimensionSwitcher({ model }: { model: ReportModel }) {
  const params = useSearchParams();
  const dims = model.report.dimensions;
  if (dims.length < 2) return null;
  return (
    <select
      className="dimension-switcher"
      value={model.activeDimension}
      onChange={(e) => {
        const next = withParam(params, 'd', e.target.value === dims[0] ? null : e.target.value);
        window.history.pushState({}, '', hashFor(next));
        window.dispatchEvent(new PopStateEvent('popstate'));
      }}
    >
      {dims.map((d) => (
        <option key={d} value={d}>
          Group by: {d}
        </option>
      ))}
    </select>
  );
}

function SortSelector({ sortMode }: { sortMode: SortMode }) {
  const params = useSearchParams();
  return (
    <select
      className="dimension-switcher"
      value={sortMode}
      onChange={(e) => {
        const value = e.target.value as SortMode;
        const next = withParam(params, 'sort', value === DEFAULT_SORT_MODE ? null : value);
        window.history.pushState({}, '', hashFor(next));
        window.dispatchEvent(new PopStateEvent('popstate'));
      }}
    >
      {(Object.keys(SORT_MODE_LABELS) as SortMode[]).map((mode) => (
        <option key={mode} value={mode}>
          Sort: {SORT_MODE_LABELS[mode]}
        </option>
      ))}
    </select>
  );
}

function passRateClass(rate: number | null): string {
  if (rate === null) return 'cell-zero';
  if (rate >= 1) return 'cell-passed';
  if (rate < 0.5) return 'cell-failed';
  return 'cell-quarantined';
}

// Aggregated per-group results for the active dimension. Row click
// narrows the list to that group (g: token).
function GroupSummaryTable({ model }: { model: ReportModel }) {
  const params = useSearchParams();
  const [open, setOpen] = React.useState(false);
  if (model.groups.length < 2) return null;
  const q = params.get('q') || '';
  return (
    <div className="group-summary">
      <button className="group-summary-toggle" type="button" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Show'} summary by {model.activeDimension}
      </button>
      {open ? (
        <table className="group-summary-table">
          <thead>
            <tr>
              <th>{model.activeDimension}</th>
              <th>Total</th>
              <th>Passed</th>
              <th>Failed</th>
              <th>Skipped</th>
              <th>Expected failure</th>
              <th>Quarantined</th>
              <th>Pass rate</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {model.groups.map((g) => {
              const token = `g:${model.activeDimension}=${g.label}`;
              const href = hashFor(withParam(params, 'q', filterWithToken(q, token, false)));
              return (
                <tr key={g.label}>
                  <td>
                    <Link href={href}>{g.label}</Link>
                  </td>
                  <td>{g.stats.total}</td>
                  <td className={g.stats.passed ? 'cell-passed' : 'cell-zero'}>{g.stats.passed}</td>
                  <td className={g.stats.failed ? 'cell-failed' : 'cell-zero'}>{g.stats.failed}</td>
                  <td className={g.stats.skipped ? '' : 'cell-zero'}>{g.stats.skipped}</td>
                  <td className={g.stats.expectedFailure ? '' : 'cell-zero'}>
                    {g.stats.expectedFailure}
                  </td>
                  <td className={g.stats.quarantined ? 'cell-quarantined' : 'cell-zero'}>
                    {g.stats.quarantined}
                  </td>
                  <td className={passRateClass(passRate(g.stats))}>
                    {formatPassRate(passRate(g.stats))}
                  </td>
                  <td>{formatDuration(g.stats.duration)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td>{model.filteredStats.total}</td>
              <td className={model.filteredStats.passed ? 'cell-passed' : 'cell-zero'}>
                {model.filteredStats.passed}
              </td>
              <td className={model.filteredStats.failed ? 'cell-failed' : 'cell-zero'}>
                {model.filteredStats.failed}
              </td>
              <td className={model.filteredStats.skipped ? '' : 'cell-zero'}>
                {model.filteredStats.skipped}
              </td>
              <td className={model.filteredStats.expectedFailure ? '' : 'cell-zero'}>
                {model.filteredStats.expectedFailure}
              </td>
              <td className={model.filteredStats.quarantined ? 'cell-quarantined' : 'cell-zero'}>
                {model.filteredStats.quarantined}
              </td>
              <td className={passRateClass(passRate(model.filteredStats))}>
                {formatPassRate(passRate(model.filteredStats))}
              </td>
              <td>{formatDuration(model.filteredStats.duration)}</td>
            </tr>
          </tfoot>
        </table>
      ) : null}
    </div>
  );
}

function TestRow({ test }: { test: TestData }) {
  const params = useSearchParams();
  const detailHref = hashFor(withParam(params, 'testId', test.id));
  const hasImage = test.artifacts?.some(
    (a) => a.href.startsWith('data:image/') || /\.(png|jpe?g|gif|webp)$/i.test(a.label),
  );
  const hasTrace = test.artifacts?.some((a) => a.label.endsWith('.zip'));
  const hasSubRow =
    test.caseId ||
    test.tags.length > 0 ||
    test.quarantined ||
    test.nearTimeout ||
    hasImage ||
    hasTrace ||
    test.attempts > 1;
  return (
    <div className="test-row">
      <div className="test-row-main">
        <StatusIcon outcome={test.outcome} />
        <Link className="test-row-title mono" href={detailHref}>
          {test.id}
        </Link>
        <span className="test-row-duration">{formatDuration(test.duration)}</span>
      </div>
      {hasSubRow ? (
        <div className="test-row-sub">
          {test.caseId ? <span className="test-row-case mono">{test.caseId}</span> : null}
          <LabelsRow test={test} />
          {test.quarantined ? (
            <span className="flag" title={test.quarantineReason || 'no reason given'}>
              quarantined
            </span>
          ) : null}
          {test.nearTimeout ? (
            <span className="flag" title="Finished at or above 80% of its configured timeout">
              near timeout
            </span>
          ) : null}
          {hasImage ? <ImageIcon className="row-media" title="Has screenshots" /> : null}
          {hasTrace ? <TraceIcon className="row-media" title="Has a trace" /> : null}
          {test.attempts > 1 ? (
            <span className="flag flag-info" title="Number of attempts">
              ×{test.attempts}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function GroupChip({
  group,
  expanded,
  setExpanded,
}: {
  group: Group;
  expanded: boolean;
  setExpanded: (v: boolean) => void;
}) {
  const s = group.stats;
  const counters: string[] = [];
  if (s.passed) counters.push(`${s.passed} passed`);
  if (s.failed) counters.push(`${s.failed} failed`);
  if (s.skipped) counters.push(`${s.skipped} skipped`);
  if (s.expectedFailure) counters.push(`${s.expectedFailure} expected`);
  if (s.quarantined) counters.push(`${s.quarantined} quarantined`);
  return (
    <Chip
      header={<span className="group-label mono">{group.label}</span>}
      aside={
        <>
          <span className={`group-counters${s.failed ? ' group-counters-failed' : ''}`}>
            {counters.join(', ')}
          </span>
          <span>{formatDuration(s.duration)}</span>
        </>
      }
      expanded={expanded}
      setExpanded={setExpanded}
    >
      {group.tests.map((t) => (
        <TestRow key={t.id} test={t} />
      ))}
    </Chip>
  );
}

export function TestListView({ model }: { model: ReportModel }) {
  // Groups auto-expand until the cumulative test count passes the limit;
  // manual toggles win over the default.
  const [overrides, setOverrides] = React.useState<Map<string, boolean>>(new Map());
  // Manual expand/collapse choices are scoped to a dimension: switching
  // the grouping resets them (adjust-state-during-render idiom).
  const [prevDimension, setPrevDimension] = React.useState(model.activeDimension);
  if (prevDimension !== model.activeDimension) {
    setPrevDimension(model.activeDimension);
    setOverrides(new Map());
  }

  let cumulative = 0;
  const defaults = new Map<string, boolean>();
  for (const g of model.groups) {
    defaults.set(g.label, cumulative < AUTO_EXPAND_LIMIT);
    cumulative += g.tests.length;
  }

  if (!model.groups.length)
    return <div className="empty-list">No tests match the current filter.</div>;

  return (
    <div className="test-list">
      <div className="list-controls">
        <DimensionSwitcher model={model} />
        <SortSelector sortMode={model.sortMode} />
      </div>
      <GroupSummaryTable model={model} />
      {model.groups.map((g) => (
        <GroupChip
          key={g.label}
          group={g}
          expanded={overrides.get(g.label) ?? defaults.get(g.label) ?? true}
          setExpanded={(v) => setOverrides(new Map(overrides).set(g.label, v))}
        />
      ))}
    </div>
  );
}
