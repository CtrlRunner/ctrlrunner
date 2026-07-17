import type { ReportData } from '../../shared/types';
import { navigate, useSearchParams, withParam } from '../links';
import { GanttChart } from './GanttChart';
import { buildTimelineModel } from './timelineData';

function closePanel(params: URLSearchParams) {
  navigate(withParam(params, 'panel', null));
}

export function TimelinePanel({ report }: { report: ReportData }) {
  const params = useSearchParams();
  const model = buildTimelineModel(report);

  const onSelectTest = (testId: string) => {
    let next = withParam(params, 'testId', testId);
    next = withParam(next, 'panel', null);
    navigate(next);
  };

  return (
    <>
      <div className="timeline-backdrop" onClick={() => closePanel(params)} role="presentation" />
      <div className="timeline-panel">
        <div className="timeline-panel-header">
          <h2>Timeline</h2>
          {report.numWorkers != null ? (
            <span className="timeline-panel-meta">{report.numWorkers} workers</span>
          ) : null}
          <button
            type="button"
            className="timeline-panel-close"
            onClick={() => closePanel(params)}
            aria-label="Close timeline"
          >
            ×
          </button>
        </div>
        {model.isEmpty ? (
          <div className="timeline-empty-state">
            Timeline data isn't available for this report — rerun with a newer ctrlrunner build to
            see worker activity over time.
          </div>
        ) : (
          <GanttChart model={model} onSelectTest={onSelectTest} />
        )}
      </div>
    </>
  );
}
