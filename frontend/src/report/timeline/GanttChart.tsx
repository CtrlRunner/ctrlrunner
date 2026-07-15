import React from 'react';
import { OUTCOME_LABELS } from '../../shared/types';
import { Tooltip, type TooltipState } from './Tooltip';
import { generateAxisTicks, type TimelineBar, type TimelineModel } from './timelineData';

function formatSeconds(s: number): string {
  return s >= 10 ? `${Math.round(s)}s` : `${s.toFixed(1)}s`;
}

// Wheel/pinch zoom applies a continuous multiplier (Math.exp of the
// scroll delta), so the raw zoom value quickly picks up float noise
// (e.g. 13.94549127595055) -- round it to something a human can read
// before it ever hits state, not just at display time, so the anchor
// math elsewhere stays consistent with what's shown.
function roundZoom(z: number): number {
  const precision = z < 10 ? 10 : 1;
  return Math.round(z * precision) / precision;
}

function formatZoomLabel(z: number): string {
  return z === 1 ? 'Fit' : `${z}×`;
}

const LANE_HEIGHT = 14;
const LANE_GAP = 4;
const ROW_VPADDING = 5;
const MIN_ROW_HEIGHT = 28;
const AXIS_HEIGHT = 26; // .timeline-axis height (20px) + margin-bottom (6px)

const ZOOM_MIN = 1; // 1x == "fit": the whole run spans exactly the visible width
const ZOOM_MAX = 64;

function trackHeight(laneCount: number): number {
  return laneCount * LANE_HEIGHT + (laneCount - 1) * LANE_GAP;
}

function rowHeight(laneCount: number): number {
  return Math.max(MIN_ROW_HEIGHT, trackHeight(laneCount) + 2 * ROW_VPADDING);
}

function BarTooltipContent({ bar }: { bar: TimelineBar }) {
  return (
    <div>
      <div className="timeline-tooltip-title">{bar.testId}</div>
      <div>
        {OUTCOME_LABELS[bar.outcome] || bar.outcome}
        {bar.flaky ? ' (flaky)' : ''}
      </div>
      <div>Duration: {formatSeconds(bar.durationSeconds)}</div>
      <div>Worker: {bar.workerId}</div>
      {bar.caseId ? <div>Case: {bar.caseId}</div> : null}
      {bar.attempts > 1 ? <div>Attempts: {bar.attempts}</div> : null}
    </div>
  );
}

export function GanttChart({
  model,
  onSelectTest,
}: {
  model: TimelineModel;
  onSelectTest: (testId: string) => void;
}) {
  const [tooltip, setTooltip] = React.useState<TooltipState | null>(null);
  const [zoom, setZoom] = React.useState(1);
  // Guessed until the ResizeObserver below reports the real width -- avoids
  // a one-frame flash of collapsed (0px) bars on mount.
  const [containerWidth, setContainerWidth] = React.useState(900);
  const scrollAreaRef = React.useRef<HTMLDivElement>(null);
  // Set just before the zoom level changes (by a button, click-centered,
  // or a Cmd/Ctrl+scroll gesture, cursor-centered); consumed by the
  // layout effect below to keep that anchor point visually fixed once
  // the wider/narrower content has actually been laid out.
  const zoomAnchorRef = React.useRef<{ seconds: number; viewportOffset: number } | null>(null);

  const maxSeconds = model.axisMaxSeconds || 1;

  React.useLayoutEffect(() => {
    const el = scrollAreaRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setContainerWidth(width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitPxPerSecond = containerWidth / maxSeconds;
  const pxPerSecond = fitPxPerSecond * zoom;
  const contentWidth = Math.max(containerWidth, maxSeconds * pxPerSecond);

  React.useLayoutEffect(() => {
    const el = scrollAreaRef.current;
    const anchor = zoomAnchorRef.current;
    if (el && anchor) {
      el.scrollLeft = Math.max(0, anchor.seconds * pxPerSecond - anchor.viewportOffset);
      zoomAnchorRef.current = null;
    }
  }, [pxPerSecond]);

  // viewportOffset is where, within the visible scroll area, the anchor
  // point (the seconds value currently under it) should stay pinned --
  // the container's horizontal center for a button click, the cursor's
  // position for a Cmd/Ctrl+scroll or trackpad-pinch gesture.
  const requestZoom = React.useCallback(
    (next: number, viewportOffset: number) => {
      const clamped = roundZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)));
      if (clamped === zoom) return;
      const el = scrollAreaRef.current;
      if (el) {
        zoomAnchorRef.current = {
          seconds: (el.scrollLeft + viewportOffset) / pxPerSecond,
          viewportOffset,
        };
      }
      setZoom(clamped);
    },
    [zoom, pxPerSecond],
  );

  // Cmd (Mac) or Ctrl held while scrolling/pinching zooms instead of
  // scrolling -- addEventListener with {passive:false} rather than
  // React's onWheel, since a passive listener can't preventDefault() and
  // Cmd+scroll would otherwise also zoom the whole browser page. Safari
  // and Chrome both report trackpad pinch gestures as wheel events with
  // ctrlKey=true regardless of whether Control is actually held, so this
  // also covers pinch-to-zoom for free.
  React.useEffect(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const factor = Math.exp(-e.deltaY * 0.01);
      const viewportOffset = e.clientX - el.getBoundingClientRect().left;
      requestZoom(zoom * factor, viewportOffset);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoom, requestZoom]);

  const targetTickCount = Math.max(4, Math.round(contentWidth / 90));
  const ticks = generateAxisTicks(maxSeconds, targetTickCount);

  const TOOLTIP_MAX_WIDTH = 320; // keep in sync with .timeline-tooltip's max-width in app.css

  const showTooltip = (e: React.MouseEvent<HTMLDivElement>, bar: TimelineBar) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const overflowsRight = rect.left + TOOLTIP_MAX_WIDTH > window.innerWidth;
    setTooltip({
      x: overflowsRight ? rect.right : rect.left,
      y: rect.bottom + 6,
      align: overflowsRight ? 'right' : 'left',
      content: <BarTooltipContent bar={bar} />,
    });
  };

  return (
    <div className="timeline-gantt">
      <div className="timeline-zoom-controls">
        <button
          type="button"
          disabled={zoom <= ZOOM_MIN}
          onClick={() => requestZoom(zoom / 2, containerWidth / 2)}
          aria-label="Zoom out"
        >
          &minus;
        </button>
        <span className="timeline-zoom-label">{formatZoomLabel(zoom)}</span>
        <button
          type="button"
          disabled={zoom >= ZOOM_MAX}
          onClick={() => requestZoom(zoom * 2, containerWidth / 2)}
          aria-label="Zoom in"
        >
          +
        </button>
        {zoom !== 1 ? (
          <button
            type="button"
            className="timeline-zoom-reset"
            onClick={() => requestZoom(1, containerWidth / 2)}
          >
            Reset
          </button>
        ) : null}
        <span className="timeline-zoom-hint">Cmd/Ctrl+scroll to zoom</span>
      </div>
      <div className="timeline-body">
        <div className="timeline-labels-col">
          <div className="timeline-axis-spacer" />
          {model.rows.map((row) => (
            <div
              className="timeline-row-label"
              key={row.workerId}
              style={{ height: rowHeight(row.laneCount) }}
            >
              Worker {row.workerId}
            </div>
          ))}
        </div>
        <div className="timeline-scroll-area" ref={scrollAreaRef}>
          <div className="timeline-scroll-content" style={{ width: contentWidth }}>
            <div className="timeline-axis" style={{ height: AXIS_HEIGHT }}>
              {ticks.map((t) => (
                <span key={t} className="timeline-axis-tick" style={{ left: t * pxPerSecond }}>
                  {formatSeconds(t)}
                </span>
              ))}
            </div>
            {model.rows.map((row) => (
              <div
                className="timeline-row-track"
                key={row.workerId}
                style={{ height: rowHeight(row.laneCount) }}
              >
                {row.bars.map((bar) => (
                  <div
                    key={bar.testId}
                    className={`timeline-bar status-${bar.outcome}${bar.flaky ? ' timeline-bar-flaky' : ''}`}
                    style={{
                      left: bar.offsetSeconds * pxPerSecond,
                      width: bar.durationSeconds * pxPerSecond,
                      top: ROW_VPADDING + bar.lane * (LANE_HEIGHT + LANE_GAP),
                      height: LANE_HEIGHT,
                    }}
                    onMouseEnter={(e) => showTooltip(e, bar)}
                    onMouseLeave={() => setTooltip(null)}
                    onClick={() => onSelectTest(bar.testId)}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
      <Tooltip state={tooltip} />
    </div>
  );
}
