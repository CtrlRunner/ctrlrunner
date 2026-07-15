import React from 'react';
import { cycleTheme, themeSetting } from '../shared/theme';
import type { LiveResult, TestInfo } from './api';
import { apiPost, fetchStatus, fetchTests, subscribeEvents } from './api';
import { buildTree, type TreeCallbacks, TreeView } from './testTree';

export function UiApp() {
  const [allTests, setAllTests] = React.useState<TestInfo[]>([]);
  const [dimensions, setDimensions] = React.useState<string[]>(['module']);
  const [activeDimension, setActiveDimension] = React.useState('module');
  const [resultsById, setResultsById] = React.useState<Record<string, LiveResult>>({});
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [collapsedFolders, setCollapsedFolders] = React.useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = React.useState('');
  const [statusText, setStatusText] = React.useState('Idle');
  const [runInProgress, setRunInProgress] = React.useState(false);
  const [runTotal, setRunTotal] = React.useState(0);
  const [runningIds, setRunningIds] = React.useState<Set<string>>(new Set());
  const [workersValue, setWorkersValue] = React.useState('');
  const [workersTitle, setWorkersTitle] = React.useState('');
  const [traceViewerUrl, setTraceViewerUrl] = React.useState<string | null>(null);
  const [traceStatus, setTraceStatus] = React.useState('No trace loaded');
  const [tracePlaceholder, setTracePlaceholder] = React.useState(
    'Run a test to see its trace here.',
  );
  const [treeWidth, setTreeWidth] = React.useState<number | null>(null);
  const [, forceRender] = React.useReducer((n: number) => n + 1, 0);

  // Which test's trace the panel is pinned to; null = follow the most
  // recent traced test.
  const pinnedTestId = React.useRef<string | null>(null);
  const finishedInRun = React.useRef(0);
  // Mirror runTotal / traceViewerUrl for reads inside the SSE handler:
  // reading them via state updaters would mean side effects in the
  // render phase, which reorders status-text updates.
  const runTotalRef = React.useRef(0);
  const traceViewerUrlRef = React.useRef<string | null>(null);

  const viewTrace = React.useCallback((testId: string, path: string) => {
    pinnedTestId.current = testId;
    setTraceStatus(`Showing: ${testId}`);
    apiPost('/api/view-trace', { path, testId });
  }, []);

  React.useEffect(() => {
    (async () => {
      const data = await fetchTests();
      setAllTests(data.tests);
      const dims = data.dimensions?.length ? data.dimensions : ['module'];
      setDimensions(dims);
      setActiveDimension(dims[0]);
      setResultsById(data.lastResults || {});
      // Show the raw setting ("auto"/"50%"/int); the tooltip carries the
      // resolved concrete worker count.
      setWorkersValue(String(data.numWorkersSetting ?? data.numWorkers));
      setWorkersTitle(`Resolves to ${data.numWorkers} worker(s)`);
      if (data.traceViewerUrl) {
        traceViewerUrlRef.current = data.traceViewerUrl;
        setTraceViewerUrl(data.traceViewerUrl);
        if (data.lastTracedTestId) setTraceStatus(`Showing: ${data.lastTracedTestId}`);
      }
      // Reloaded mid-run: match UI state to reality instead of defaulting
      // to idle until the next SSE event arrives.
      const status = await fetchStatus();
      if (status.status === 'running') setRunInProgress(true);
    })();
  }, []);

  React.useEffect(() => {
    return subscribeEvents((ev) => {
      if (ev.type === 'run_start') {
        runTotalRef.current = ev.total;
        setRunTotal(ev.total);
        setRunInProgress(true);
        finishedInRun.current = 0;
        setRunningIds(new Set());
        setStatusText(`Running 0/${ev.total}`);
        if (ev.traceViewerUrl) {
          traceViewerUrlRef.current = ev.traceViewerUrl;
          setTraceViewerUrl(ev.traceViewerUrl);
        } else if (!traceViewerUrlRef.current) {
          setTracePlaceholder('Trace viewer unavailable -- is the playwright CLI installed?');
        }
      } else if (ev.type === 'test_start') {
        setRunningIds((ids) => new Set(ids).add(ev.id));
        setStatusText(`Running: ${ev.id}`);
      } else if (ev.type === 'test_end') {
        setRunningIds((ids) => {
          const next = new Set(ids);
          next.delete(ev.id);
          return next;
        });
        const { type: _type, ...result } = ev;
        setResultsById((r) => ({ ...r, [ev.id]: result }));
        finishedInRun.current++;
        setStatusText(`Running ${finishedInRun.current}/${runTotalRef.current}`);
        const tracePath = (ev.artifacts || []).find((p) => p.endsWith('.zip'));
        if (tracePath && (pinnedTestId.current === null || pinnedTestId.current === ev.id)) {
          setTraceStatus(`Showing: ${ev.id}`);
          apiPost('/api/view-trace', { path: tracePath, testId: ev.id });
        }
      } else if (ev.type === 'run_end') {
        setRunInProgress(false);
        setStatusText(`${ev.passed} passed, ${ev.failed} failed / ${ev.total} (${ev.duration}s)`);
      }
    });
  }, []);

  const search = searchQuery.trim().toLowerCase();
  const matches = React.useCallback(
    (t: TestInfo) => {
      if (!search) return true;
      return `${t.id} ${t.caseId || ''}`.toLowerCase().includes(search);
    },
    [search],
  );

  const runTests = React.useCallback(
    async (ids: string[]) => {
      // Only clear results for the tests about to (re)run -- other rows'
      // last-known status is still valid info.
      const idsToRun = ids.length ? ids : allTests.map((t) => t.id);
      setResultsById((r) => {
        const next = { ...r };
        for (const id of idsToRun) delete next[id];
        return next;
      });
      const res = await apiPost('/api/run', ids.length ? { testIds: ids } : {});
      if (res.status === 409) setStatusText('A run is already in progress.');
    },
    [allTests],
  );

  const cancelRun = React.useCallback(() => {
    apiPost('/api/cancel', {});
  }, []);

  const updateNumWorkers = async (value: string) => {
    const raw = value.trim();
    let payload: string | number;
    if (raw === 'auto' || /^[1-9][0-9]*%$/.test(raw)) {
      payload = raw;
    } else {
      const n = Number.parseInt(raw, 10);
      if (!Number.isInteger(n) || n < 1 || String(n) !== raw) return;
      payload = n;
    }
    const res = await apiPost('/api/config', { numWorkers: payload });
    if (res.ok) {
      const data = await res.json();
      setWorkersTitle(`Resolves to ${data.numWorkers} worker(s)`);
    }
  };

  const cb: TreeCallbacks = {
    selected,
    toggleSelect: (id) =>
      setSelected((s) => {
        const next = new Set(s);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    setGroupSelected: (ids, checked) =>
      setSelected((s) => {
        const next = new Set(s);
        for (const id of ids) {
          if (checked) next.add(id);
          else next.delete(id);
        }
        return next;
      }),
    expanded,
    toggleExpand: (id) =>
      setExpanded((s) => {
        const next = new Set(s);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    collapsedFolders,
    toggleFolder: (path) =>
      setCollapsedFolders((s) => {
        const next = new Set(s);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      }),
    searchActive: !!search,
    resultsById,
    runningIds,
    runInProgress,
    runTotal,
    runTests,
    cancelRun,
    viewTrace,
  };

  const tree = buildTree(allTests, resultsById, activeDimension, matches);
  const noMatches = search && !allTests.some(matches);
  const themeLabel = { system: 'Auto', light: 'Light', dark: 'Dark' }[themeSetting()];

  const onResizerDown = (e: React.MouseEvent) => {
    e.preventDefault();
    document.body.classList.add('resizing');
    const main = document.getElementById('ui-main');
    const onMove = (me: MouseEvent) => {
      if (!main) return;
      const rect = main.getBoundingClientRect();
      const max = rect.width - 320 - 6;
      setTreeWidth(Math.max(260, Math.min(max, me.clientX - rect.left)));
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.classList.remove('resizing');
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  return (
    <div className="ui-app">
      <div id="toolbar">
        <button
          id="run-all-btn"
          type="button"
          disabled={runInProgress}
          onClick={() => runTests([])}
        >
          Run All
        </button>
        <button
          id="run-selected-btn"
          type="button"
          disabled={runInProgress}
          onClick={() => runTests([...selected])}
        >
          Run Selected
        </button>
        <button id="cancel-btn" type="button" onClick={cancelRun}>
          Cancel
        </button>
        {dimensions.length > 1 ? (
          <select
            className="group-switcher"
            value={activeDimension}
            onChange={(e) => setActiveDimension(e.target.value)}
          >
            {dimensions.map((d) => (
              <option key={d} value={d}>
                Group by: {d}
              </option>
            ))}
          </select>
        ) : null}
        <label className="workers-label">
          Workers:
          <input
            type="text"
            id="num-workers-input"
            inputMode="numeric"
            disabled={runInProgress}
            title={`${workersTitle} -- a number, 'auto' (CPUs - 1), or a percent of CPUs like '50%'`}
            value={workersValue}
            onChange={(e) => setWorkersValue(e.target.value)}
            onBlur={(e) => updateNumWorkers(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') updateNumWorkers((e.target as HTMLInputElement).value);
            }}
          />
        </label>
        <span id="status-text">{statusText}</span>
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
      </div>
      <div id="ui-main">
        <div id="tree-pane" style={treeWidth !== null ? { flex: `0 0 ${treeWidth}px` } : undefined}>
          <div id="tree-search-wrap">
            <input
              type="text"
              id="tree-search"
              placeholder="Filter tests..."
              autoComplete="off"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <div id="tree">
            {noMatches ? (
              <div className="tree-empty">No tests match "{searchQuery.trim()}".</div>
            ) : (
              <TreeView node={tree} cb={cb} />
            )}
          </div>
        </div>
        <div id="resizer" onMouseDown={onResizerDown} />
        <div id="trace-panel">
          <div id="trace-panel-header">
            <span id="trace-panel-status">{traceStatus}</span>
            {traceViewerUrl ? (
              <a id="trace-pop-out" href={traceViewerUrl} target="_blank" rel="noreferrer">
                Open in new tab
              </a>
            ) : null}
          </div>
          <div id="trace-panel-body">
            {traceViewerUrl ? (
              <iframe id="trace-frame" title="Trace viewer" src={traceViewerUrl} />
            ) : (
              <div className="trace-placeholder">{tracePlaceholder}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
