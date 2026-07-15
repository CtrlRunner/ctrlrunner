import React from 'react';
import type { ReportData } from '../shared/types';
import { filterWithToken } from './filter';
import { HeaderView } from './headerView';
import { navigate, useSearchParams, withParam } from './links';
import type { SortMode } from './model';
import { buildModel } from './model';
import { TestDetailView } from './testDetail';
import { TestListView } from './testList';
import { TimelinePanel } from './timeline/TimelinePanel';

function isTypingTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
}

export function ReportApp({ report }: { report: ReportData }) {
  const params = useSearchParams();
  const q = params.get('q') || '';
  const testId = params.get('testId');
  const panel = params.get('panel');
  const sortParam = params.get('sort') as SortMode | null;
  const model = React.useMemo(
    () => buildModel(report, q, params.get('d'), sortParam || undefined),
    [report, q, params, sortParam],
  );

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'Escape' && panel === 'timeline') {
        navigate(withParam(params, 'panel', null));
        return;
      }
      if (e.key === 'a') {
        navigate(withParam(withParam(params, 'q', null), 'testId', null));
      } else if (e.key === 'p' || e.key === 'f') {
        const token = e.key === 'p' ? 's:passed' : 's:failed';
        const nextQ = filterWithToken(q, token, false);
        navigate(withParam(withParam(params, 'q', nextQ), 'testId', null));
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        if (!testId) return;
        const order = model.visibleTests;
        const idx = order.findIndex((t) => t.id === testId);
        if (idx === -1) return;
        const target = e.key === 'ArrowLeft' ? order[idx - 1] : order[idx + 1];
        if (target) navigate(withParam(params, 'testId', target.id));
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [params, q, testId, panel, model]);

  return (
    <div className="report-app">
      <HeaderView model={model} />
      {testId ? <TestDetailView model={model} testId={testId} /> : <TestListView model={model} />}
      {panel === 'timeline' ? <TimelinePanel report={report} /> : null}
    </div>
  );
}
