import React from 'react';
import { ClockIcon, SearchIcon } from '../shared/icons';
import { cycleTheme, themeSetting } from '../shared/theme';
import type { ReportData } from '../shared/types';
import { filterWithToken } from './filter';
import { hashFor, Link, navigate, useSearchParams, withParam } from './links';
import type { ReportModel } from './model';
import { formatDuration, formatPassRate, passRate } from './model';

// `wall` (report.runDuration) is real elapsed time; `sequential`
// (report.totalDuration) is the sum of every test's own duration --
// what the suite would've cost with no parallelism. Showing both
// (plus the ratio) is what makes the wall-clock speedup legible
// instead of reading as a mysteriously smaller "total".
function formatMetaDuration(report: ReportData): string {
  const wall = report.runDuration;
  const seq = report.totalDuration;
  if (wall != null && seq !== undefined) {
    const speedup = wall > 0 ? ` (${(seq / wall).toFixed(1)}×)` : '';
    return ` · wall ${formatDuration(wall)} · sequential ${formatDuration(seq)}${speedup}`;
  }
  if (wall != null) return ` · wall ${formatDuration(wall)}`;
  if (seq !== undefined) return ` · total ${formatDuration(seq)}`;
  return '';
}

function StatNav({
  label,
  count,
  token,
  active,
}: {
  label: string;
  count: number;
  token: string | null;
  active: boolean;
}) {
  const params = useSearchParams();
  const q = params.get('q') || '';
  const makeHash = (append: boolean) => {
    let next = withParam(params, 'testId', null);
    if (token === null) next = withParam(next, 'q', null);
    else next = withParam(next, 'q', filterWithToken(q, token, append) || null);
    return hashFor(next);
  };
  return (
    <Link
      className={`stat-nav${active ? ' stat-nav-active' : ''}`}
      href={makeHash(false)}
      ctrlHref={token ? makeHash(true) : undefined}
    >
      {label} <span className="stat-count">{count}</span>
    </Link>
  );
}

function PassRateBadge({ rate }: { rate: number | null }) {
  if (rate === null) return null;
  const tone = rate >= 1 ? 'good' : rate < 0.5 ? 'bad' : 'warn';
  return (
    <span
      className={`pass-rate-badge pass-rate-${tone}`}
      title="Passed (incl. expected failures) / tests that ran to a verdict"
    >
      {formatPassRate(rate)} passed
    </span>
  );
}

function statusTokenActive(q: string, token: string): boolean {
  return q.split(/\s+/).includes(token);
}

export function HeaderView({ model }: { model: ReportModel }) {
  const params = useSearchParams();
  const q = params.get('q') || '';
  const [searchText, setSearchText] = React.useState(q);
  React.useEffect(() => setSearchText(q), [q]);
  const [, forceRender] = React.useReducer((n: number) => n + 1, 0);

  const stats = model.totalStats;
  const report = model.report;

  const navs: { label: string; count: number; token: string | null }[] = [
    { label: 'All', count: stats.total, token: null },
    { label: 'Passed', count: stats.passed, token: 's:passed' },
    { label: 'Failed', count: stats.failed, token: 's:failed' },
    { label: 'Skipped', count: stats.skipped, token: 's:skipped' },
  ];
  if (stats.expectedFailure)
    navs.push({
      label: 'Expected failure',
      count: stats.expectedFailure,
      token: 's:expected_failure',
    });
  if (stats.quarantined)
    navs.push({ label: 'Quarantined', count: stats.quarantined, token: 's:quarantined_failure' });
  if (stats.cancelled)
    navs.push({ label: 'Cancelled', count: stats.cancelled, token: 's:cancelled' });
  if (stats.notRun) navs.push({ label: 'Not run', count: stats.notRun, token: 's:not_run' });

  const themeLabel = { system: 'Auto', light: 'Light', dark: 'Dark' }[themeSetting()];

  return (
    <header className="report-header">
      <div className="report-title-row">
        <h1 className="report-title">{report.suiteName}</h1>
        <PassRateBadge rate={passRate(stats)} />
        <span className="report-meta">
          {report.generatedAt ? new Date(report.generatedAt).toLocaleString() : ''}
          {formatMetaDuration(report)}
        </span>
        <button
          className="theme-toggle"
          type="button"
          title="Cycle theme: auto / light / dark"
          onClick={() => {
            cycleTheme();
            forceRender();
          }}
        >
          Theme: {themeLabel}
        </button>
        <button
          className="timeline-toggle-btn"
          type="button"
          title="Show worker timeline"
          onClick={() => {
            const isOpen = params.get('panel') === 'timeline';
            navigate(withParam(params, 'panel', isOpen ? null : 'timeline'));
          }}
        >
          <ClockIcon />
          Timeline
        </button>
      </div>
      {report.coverage ? (
        <div className="coverage-summary">
          Coverage: {report.coverage.percent.toFixed(1)}%
          {report.coverage.htmlDir ? ` (full report: ${report.coverage.htmlDir})` : ''}
        </div>
      ) : null}
      <form
        className="search-row"
        onSubmit={(e) => {
          e.preventDefault();
          let next = withParam(params, 'q', searchText.trim() || null);
          next = withParam(next, 'testId', null);
          navigate(next);
        }}
      >
        <SearchIcon className="search-icon" />
        <input
          type="search"
          className="search-input"
          spellCheck={false}
          placeholder="Search: text  s:failed  @tag  g:module=api  case:C123  !token"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />
      </form>
      <nav className="stats-nav">
        {navs.map((n) => (
          <StatNav
            key={n.label}
            label={n.label}
            count={n.count}
            token={n.token}
            active={n.token === null ? !q : statusTokenActive(q, n.token)}
          />
        ))}
        {!model.filter.empty ? (
          <span className="filtered-readout">
            Filtered: {model.filteredStats.total} ({formatDuration(model.filteredStats.duration)})
          </span>
        ) : null}
      </nav>
    </header>
  );
}
