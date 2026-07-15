import React from 'react';
import { ChevronIcon } from './icons';

// Collapsible bordered section -- the main layout unit for both the
// group list and the detail-page sections.
export function Chip({
  header,
  aside,
  expanded,
  setExpanded,
  children,
}: {
  header: React.ReactNode;
  aside?: React.ReactNode;
  expanded: boolean;
  setExpanded: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="chip">
      <div className="chip-header" onClick={() => setExpanded(!expanded)}>
        <ChevronIcon open={expanded} />
        <span className="chip-title">{header}</span>
        {aside ? (
          <span className="chip-aside" onClick={(e) => e.stopPropagation()}>
            {aside}
          </span>
        ) : null}
      </div>
      {expanded ? <div className="chip-body">{children}</div> : null}
    </div>
  );
}

// Chip that manages its own expansion state.
export function AutoChip({
  header,
  aside,
  initialExpanded = true,
  children,
}: {
  header: React.ReactNode;
  aside?: React.ReactNode;
  initialExpanded?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = React.useState(initialExpanded);
  return (
    <Chip header={header} aside={aside} expanded={expanded} setExpanded={setExpanded}>
      {children}
    </Chip>
  );
}
