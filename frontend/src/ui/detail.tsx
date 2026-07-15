import type { Step } from '../shared/types';
import type { LiveResult } from './api';

function TimelineRows({
  steps,
  totalDuration,
  depth,
}: {
  steps: Step[];
  totalDuration: number;
  depth: number;
}) {
  const maxDur = Math.max(totalDuration, 0.001);
  return (
    <>
      {steps.map((s, i) => {
        const pct = Math.max(2, Math.min(100, (s.duration / maxDur) * 100));
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: steps have no ids; the list is a render-static snapshot
          <div key={i} style={depth ? { paddingLeft: depth * 14 } : undefined}>
            <div className="timeline-row">
              <span className="timeline-label mono" title={s.name}>
                {s.name}
              </span>
              <div className="timeline-bar-track">
                <div
                  className={`timeline-bar${s.outcome === 'failed' ? ' failed' : ''}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="timeline-dur">{s.duration}s</span>
            </div>
            {s.children?.length ? (
              <TimelineRows steps={s.children} totalDuration={totalDuration} depth={depth + 1} />
            ) : null}
          </div>
        );
      })}
    </>
  );
}

export function TestDetail({
  test,
  status,
  onViewTrace,
}: {
  test: { id: string };
  status: LiveResult | undefined;
  onViewTrace: (testId: string, path: string) => void;
}) {
  if (!status) {
    return (
      <div className="detail open">
        <div className="detail-empty">Not run yet.</div>
      </div>
    );
  }
  return (
    <div className="detail open">
      {status.error ? <pre className="error-pre">{status.error}</pre> : null}
      {status.steps?.length ? (
        <div>
          <div className="detail-caption">Timeline:</div>
          <TimelineRows steps={status.steps} totalDuration={status.duration} depth={0} />
        </div>
      ) : null}
      {status.artifacts?.length ? (
        <div>
          <div className="detail-caption">Artifacts:</div>
          {status.artifacts.map((path) => (
            <div className="artifact-row" key={path}>
              <a href={path} target="_blank" rel="noreferrer">
                {path.split('/').pop()}
              </a>
              {path.endsWith('.zip') ? (
                <button
                  type="button"
                  className="trace-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewTrace(test.id, path);
                  }}
                >
                  View Trace
                </button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
