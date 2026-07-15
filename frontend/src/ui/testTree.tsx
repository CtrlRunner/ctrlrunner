import React from 'react';
import type { LiveResult, TestInfo } from './api';
import { TestDetail } from './detail';

// Splits each test's group label on "." into folder segments (e.g.
// "examples.advanced.test_x" -> examples/advanced/test_x); labels
// without a "." just become a single folder -- same behavior as the old
// vanilla tree.
type TreeNode = {
  children: Map<string, TreeNode>;
  tests: TestInfo[];
  path: string;
};

export function buildTree(
  tests: TestInfo[],
  resultsById: Record<string, LiveResult>,
  activeDimension: string,
  matches: (t: TestInfo) => boolean,
): TreeNode {
  const root: TreeNode = { children: new Map(), tests: [], path: '' };
  for (const t of tests) {
    if (!matches(t)) continue;
    // Prefer the live result's groups (present once a test has run),
    // falling back to the static list's -- both come from the same
    // compute_groups() call server-side, just at different times.
    const groups = resultsById[t.id]?.groups || t.groups || {};
    const label = groups[activeDimension] || 'ungrouped';
    let node = root;
    for (const seg of label.split('.')) {
      let child = node.children.get(seg);
      if (!child) {
        child = { children: new Map(), tests: [], path: node.path ? `${node.path}.${seg}` : seg };
        node.children.set(seg, child);
      }
      node = child;
    }
    node.tests.push(t);
  }
  return root;
}

function collectIds(node: TreeNode): string[] {
  let ids = node.tests.map((t) => t.id);
  for (const child of node.children.values()) ids = ids.concat(collectIds(child));
  return ids;
}

export type TreeCallbacks = {
  selected: Set<string>;
  toggleSelect: (id: string) => void;
  setGroupSelected: (ids: string[], checked: boolean) => void;
  expanded: Set<string>;
  toggleExpand: (id: string) => void;
  collapsedFolders: Set<string>;
  toggleFolder: (path: string) => void;
  searchActive: boolean;
  resultsById: Record<string, LiveResult>;
  runningIds: Set<string>;
  runInProgress: boolean;
  runTotal: number;
  runTests: (ids: string[]) => void;
  cancelRun: () => void;
  viewTrace: (testId: string, path: string) => void;
};

function TestRow({ test, cb }: { test: TestInfo; cb: TreeCallbacks }) {
  const status = cb.resultsById[test.id];
  const isRunning = cb.runningIds.has(test.id);
  const dotClass = isRunning ? ' dot-running' : status ? ` dot-${status.outcome}` : '';
  // The folders above already show where the test lives, so the row
  // only needs the part after "::".
  const shortName = test.id.includes('::') ? test.id.split('::').slice(1).join('::') : test.id;
  const rowLabel = shortName + (test.caseId ? `  [${test.caseId}]` : '');
  const tracePath = status?.artifacts?.find((p) => p.endsWith('.zip'));
  return (
    <>
      <div className="row" onClick={() => cb.toggleExpand(test.id)}>
        <input
          type="checkbox"
          checked={cb.selected.has(test.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => cb.toggleSelect(test.id)}
        />
        <span className={`dot${dotClass}`} />
        <span className="name" title={rowLabel}>
          {rowLabel}
        </span>
        {status?.quarantined ? (
          <span className="flag" title={status.quarantineReason || 'no reason given'}>
            quarantined
          </span>
        ) : null}
        {status?.nearTimeout ? (
          <span className="flag" title="Finished at or above 80% of its configured timeout">
            near timeout
          </span>
        ) : null}
        {tracePath ? (
          <span
            className="flag flag-trace trace-flag-click"
            title="This test has a trace -- click to view"
            onClick={(e) => {
              e.stopPropagation();
              cb.viewTrace(test.id, tracePath);
            }}
          >
            trace
          </span>
        ) : null}
        {!cb.runInProgress ? (
          <button
            type="button"
            className="run-row-btn"
            onClick={(e) => {
              e.stopPropagation();
              cb.runTests([test.id]);
            }}
          >
            Run
          </button>
        ) : cb.runTotal === 1 && isRunning ? (
          <button
            type="button"
            className="run-row-btn stop"
            onClick={(e) => {
              e.stopPropagation();
              cb.cancelRun();
            }}
          >
            Stop
          </button>
        ) : null}
      </div>
      {cb.expanded.has(test.id) ? (
        <TestDetail test={test} status={status} onViewTrace={cb.viewTrace} />
      ) : null}
    </>
  );
}

function FolderCheckbox({ ids, cb }: { ids: string[]; cb: TreeCallbacks }) {
  const selectedCount = ids.filter((id) => cb.selected.has(id)).length;
  const ref = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = selectedCount > 0 && selectedCount < ids.length;
  });
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={ids.length > 0 && selectedCount === ids.length}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => cb.setGroupSelected(ids, e.target.checked)}
    />
  );
}

export function TreeView({ node, cb }: { node: TreeNode; cb: TreeCallbacks }) {
  return (
    <>
      {node.tests.map((t) => (
        <TestRow key={t.id} test={t} cb={cb} />
      ))}
      {[...node.children.entries()].map(([seg, child]) => {
        const ids = collectIds(child);
        const isCollapsed = !cb.searchActive && cb.collapsedFolders.has(child.path);
        return (
          <React.Fragment key={child.path}>
            <div className="tree-folder-header" onClick={() => cb.toggleFolder(child.path)}>
              <span className="tree-toggle">{isCollapsed ? '▶' : '▼'}</span>
              <FolderCheckbox ids={ids} cb={cb} />
              <span className="tree-folder-name">{seg}</span>
            </div>
            {!isCollapsed ? (
              <div className="tree-children">
                <TreeView node={child} cb={cb} />
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
    </>
  );
}
