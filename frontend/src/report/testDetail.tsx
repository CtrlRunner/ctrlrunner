import React from 'react';
import { AutoChip } from '../shared/chip';
import { CopyIcon, TraceIcon } from '../shared/icons';
import { StatusIcon } from '../shared/statusIcon';
import type { Artifact, AssertDetails, LogEntry, Step } from '../shared/types';
import { OUTCOME_LABELS } from '../shared/types';
import { LabelsRow } from './labels';
import { Lightbox } from './lightbox';
import { hashFor, Link, useSearchParams, withParam } from './links';
import { testToMarkdown, testToPrompt } from './markdown';
import type { ReportModel } from './model';
import { formatDuration } from './model';

// Same defense-in-depth as the old vanilla renderer (and the Python
// sanitizer): a worker-supplied artifact string must never become a
// javascript:/vbscript: href.
export function safeHref(href: string): string {
  const m = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(href);
  if (!m) return href; // relative/plain path
  if (m[1].length === 1) return href; // Windows drive letter, e.g. "C:\..."
  return ['http', 'https', 'file', 'data'].includes(m[1].toLowerCase()) ? href : '#';
}

function CopyButton({ label, produce }: { label: string; produce: () => string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      className="copy-button"
      title={label === 'MD' ? 'Copy test summary as Markdown' : 'Copy an AI fix-it prompt'}
      onClick={() => {
        navigator.clipboard.writeText(produce()).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 3000);
        });
      }}
    >
      <CopyIcon />
      {copied ? 'Copied ✓' : label}
    </button>
  );
}

function matchesStepFilter(step: Step, needle: string): boolean {
  return step.name.toLowerCase().includes(needle);
}

function subtreeMatches(step: Step, needle: string): boolean {
  if (matchesStepFilter(step, needle)) return true;
  return (step.children || []).some((c) => subtreeMatches(c, needle));
}

function StepNode({ step, needle }: { step: Step; needle: string }) {
  const children = (step.children || []).filter((c) => !needle || subtreeMatches(c, needle));
  // With an active filter, ancestors of matches auto-expand.
  const [openState, setOpen] = React.useState<boolean | null>(null);
  const open = openState ?? (!!needle || step.outcome === 'failed');
  const highlight = needle && matchesStepFilter(step, needle);
  return (
    <li className="step-node">
      <div
        className={`step-line${highlight ? ' step-highlight' : ''}`}
        onClick={() => setOpen(!open)}
      >
        <StatusIcon outcome={step.outcome === 'failed' ? 'failed' : 'passed'} />
        <span className="step-name">{step.name}</span>
        <span className="step-duration">{step.duration}s</span>
      </div>
      {open && step.error ? <pre className="error-pre step-error">{step.error}</pre> : null}
      {open && children.length ? (
        <ul className="steps">
          {(step.children || []).map((c, i) =>
            !needle || subtreeMatches(c, needle) ? (
              // biome-ignore lint/suspicious/noArrayIndexKey: steps have no ids; the full (unfiltered) array is a render-static snapshot, so its indexes are stable
              <StepNode key={i} step={c} needle={needle} />
            ) : null,
          )}
        </ul>
      ) : null}
    </li>
  );
}

function StepsSection({ steps }: { steps: Step[] }) {
  const [filterText, setFilterText] = React.useState('');
  const needle = filterText.trim().toLowerCase();
  const visible = steps.filter((s) => !needle || subtreeMatches(s, needle));
  return (
    <AutoChip
      header="Steps"
      aside={
        <input
          type="search"
          className="step-filter"
          placeholder="Filter steps..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
      }
    >
      <ul className="steps steps-root">
        {steps.map((s, i) =>
          !needle || subtreeMatches(s, needle) ? (
            // biome-ignore lint/suspicious/noArrayIndexKey: steps have no ids; the full (unfiltered) array is a render-static snapshot, so its indexes are stable
            <StepNode key={i} step={s} needle={needle} />
          ) : null,
        )}
      </ul>
      {needle && !visible.length ? <div className="empty-list">No steps match.</div> : null}
    </AutoChip>
  );
}

function AssertDetailsView({ d }: { d: AssertDetails }) {
  return (
    <div className="assert-details">
      <div className="assert-expr mono">assert {d.expr}</div>
      {d.left && d.right ? (
        <div className="assert-compare mono">
          {d.op ? <div>op:&nbsp;&nbsp;&nbsp;&nbsp;{d.op}</div> : null}
          <div>
            left:&nbsp;&nbsp;{d.left.repr}&nbsp;&nbsp;({d.left.type})
          </div>
          <div>
            right:&nbsp;{d.right.repr}&nbsp;&nbsp;({d.right.type})
          </div>
        </div>
      ) : null}
      {typeof d.diff === 'string' ? (
        <pre className="assert-diff">{d.diff}</pre>
      ) : d.diff ? (
        <div className="assert-diff-struct mono">
          {d.diff.missing?.length ? <div>missing: {d.diff.missing.join(', ')}</div> : null}
          {d.diff.extra?.length ? <div>extra: {d.diff.extra.join(', ')}</div> : null}
        </div>
      ) : null}
      {d.names ? (
        <div className="assert-names mono">
          <div className="assert-names-title">Values</div>
          {Object.entries(d.names).map(([k, v]) => (
            <div key={k}>
              {k} = {v}
            </div>
          ))}
        </div>
      ) : null}
      {d.truncated ? <div className="assert-truncated">(truncated)</div> : null}
    </div>
  );
}

function LogsSection({ logs }: { logs: LogEntry[] }) {
  const [attempt, setAttempt] = React.useState(logs[logs.length - 1]?.attempt);
  const entry = logs.find((l) => l.attempt === attempt) || logs[0];
  return (
    <AutoChip header="Logs" initialExpanded={false}>
      <div className="test-logs">
        {logs.length > 1 ? (
          <div className="attempt-tabs">
            {logs.map((l) => (
              <button
                key={l.attempt}
                type="button"
                className={`attempt-tab${l.attempt === entry.attempt ? ' attempt-tab-active' : ''}`}
                onClick={() => setAttempt(l.attempt)}
              >
                Attempt {l.attempt}
              </button>
            ))}
          </div>
        ) : null}
        {entry ? (
          <div className="log-entry">
            {entry.truncated ? <div className="assert-truncated">(truncated)</div> : null}
            {entry.stdout ? (
              <>
                <div className="log-title">stdout</div>
                <pre className="log-pre">{entry.stdout}</pre>
              </>
            ) : null}
            {entry.stderr ? (
              <>
                <div className="log-title">stderr</div>
                <pre className="log-pre">{entry.stderr}</pre>
              </>
            ) : null}
            {entry.records.length ? (
              <>
                <div className="log-title">log records</div>
                <div className="log-records mono">
                  {entry.records.map((r, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: log records are a render-static, append-only snapshot
                    <div key={i} className="log-record">
                      <span className="log-record-level">[{r.level}]</span> {r.name}: {r.message}
                    </div>
                  ))}
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </AutoChip>
  );
}

function ArtifactView({
  artifact,
  onImageClick,
}: {
  artifact: Artifact;
  onImageClick: (src: string, alt: string) => void;
}) {
  const href = safeHref(artifact.href);
  const isImage = href.startsWith('data:image/') || /\.(png|jpe?g|gif|webp)$/i.test(artifact.label);
  // Only file-copied artifacts (href like "artifacts/...") live at a path the
  // bundled trace viewer -- itself copied to <report_dir>/trace/ -- can reach
  // with a relative "../" path. Anything else (missing file, embedded, no
  // report_dir) falls back to a plain download link below.
  const isTrace = artifact.label.endsWith('.zip') && artifact.href.startsWith('artifacts/');

  if (isImage) {
    return (
      <div className="artifact">
        <button
          type="button"
          className="artifact-thumb"
          onClick={() => onImageClick(href, artifact.label)}
        >
          <img className="artifact-image" src={href} alt={artifact.label} />
        </button>
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          download={artifact.embedded ? artifact.label : undefined}
        >
          {artifact.label}
        </a>
      </div>
    );
  }

  if (isTrace) {
    return (
      <div className="artifact">
        <a className="artifact-trace" href={`trace/index.html?trace=../${artifact.href}`}>
          <TraceIcon />
          View trace
        </a>
        <a className="artifact-trace-download" href={href} download={artifact.label}>
          {artifact.label}
        </a>
      </div>
    );
  }

  return (
    <div className="artifact">
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        download={artifact.embedded ? artifact.label : undefined}
      >
        {artifact.label}
      </a>
      {artifact.label.endsWith('.zip') ? <span className="flag flag-trace">trace</span> : null}
    </div>
  );
}

export function TestDetailView({ model, testId }: { model: ReportModel; testId: string }) {
  const params = useSearchParams();
  const [lightbox, setLightbox] = React.useState<{ src: string; alt: string } | null>(null);
  const openLightbox = (src: string, alt: string) => setLightbox({ src, alt });
  const test = model.report.tests.find((t) => t.id === testId);
  const order = model.visibleTests;
  const idx = order.findIndex((t) => t.id === testId);
  const prev = idx > 0 ? order[idx - 1] : null;
  const next = idx >= 0 && idx < order.length - 1 ? order[idx + 1] : null;

  if (!test)
    return (
      <div className="test-detail">
        <Link href={hashFor(withParam(params, 'testId', null))}>← Back to list</Link>
        <div className="empty-list">Test not found: {testId}</div>
      </div>
    );

  const propEntries = Object.entries(test.properties || {});

  return (
    <div className="test-detail">
      <div className="detail-nav">
        <Link href={hashFor(withParam(params, 'testId', null))}>← Back to list</Link>
        <span className="detail-nav-spacer" />
        {prev ? (
          <Link href={hashFor(withParam(params, 'testId', prev.id))}>« previous</Link>
        ) : (
          <span className="dim">« previous</span>
        )}
        {next ? (
          <Link href={hashFor(withParam(params, 'testId', next.id))}>next »</Link>
        ) : (
          <span className="dim">next »</span>
        )}
      </div>

      <div className="detail-header">
        <StatusIcon outcome={test.outcome} />
        <h2 className="detail-title mono">{test.id}</h2>
      </div>
      <div className="detail-meta">
        <span className={`outcome-badge outcome-${test.outcome}`}>
          {OUTCOME_LABELS[test.outcome] || test.outcome}
        </span>
        {test.caseId ? <span className="mono">{test.caseId}</span> : null}
        <span>{formatDuration(test.duration)}</span>
        {test.attempts > 1 ? <span>attempts: {test.attempts}</span> : null}
        {test.quarantined ? (
          <span className="flag" title={test.quarantineReason || 'no reason given'}>
            quarantined{test.quarantineReason ? `: ${test.quarantineReason}` : ''}
          </span>
        ) : null}
        {test.nearTimeout ? (
          <span className="flag" title="Finished at or above 80% of its configured timeout">
            near timeout
          </span>
        ) : null}
        <LabelsRow test={test} />
      </div>

      {test.error || test.assertDetails ? (
        <AutoChip
          header="Errors"
          aside={
            <>
              <CopyButton label="Copy prompt" produce={() => testToPrompt(test)} />
              <CopyButton label="MD" produce={() => testToMarkdown(test)} />
            </>
          }
        >
          <div className="detail-section">
            {test.error ? <pre className="error-pre">{test.error}</pre> : null}
            {test.assertDetails ? <AssertDetailsView d={test.assertDetails} /> : null}
          </div>
        </AutoChip>
      ) : (
        <div className="detail-copy-row">
          <CopyButton label="Copy prompt" produce={() => testToPrompt(test)} />
          <CopyButton label="MD" produce={() => testToMarkdown(test)} />
        </div>
      )}

      {test.steps?.length ? <StepsSection steps={test.steps} /> : null}
      {test.logs?.length ? <LogsSection logs={test.logs} /> : null}

      {test.artifacts?.length ? (
        <AutoChip header="Artifacts">
          <div className="detail-section">
            {test.artifacts.map((a, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: artifact list is a render-static snapshot; hrefs may collide so the index is the only reliable key
              <ArtifactView key={i} artifact={a} onImageClick={openLightbox} />
            ))}
          </div>
        </AutoChip>
      ) : null}

      {lightbox ? (
        <Lightbox src={lightbox.src} alt={lightbox.alt} onClose={() => setLightbox(null)} />
      ) : null}

      {propEntries.length ? (
        <AutoChip header="Properties" initialExpanded={false}>
          <div className="detail-section mono props">
            {propEntries.map(([k, v]) => (
              <div key={k} className="prop">
                {k}: {String(v)}
              </div>
            ))}
          </div>
        </AutoChip>
      ) : null}
    </div>
  );
}
