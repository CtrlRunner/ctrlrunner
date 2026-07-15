import type React from 'react';

export interface TooltipState {
  x: number;
  y: number;
  align: 'left' | 'right';
  content: React.ReactNode;
}

export function Tooltip({ state }: { state: TooltipState | null }) {
  if (!state) return null;
  const style: React.CSSProperties =
    state.align === 'right'
      ? { right: window.innerWidth - state.x, top: state.y }
      : { left: state.x, top: state.y };
  return (
    <div className="timeline-tooltip" style={style} role="tooltip">
      {state.content}
    </div>
  );
}
