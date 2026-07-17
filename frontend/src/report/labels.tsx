import React from 'react';
import type { TestData } from '../shared/types';
import { filterWithToken } from './filter';
import { navigate, useSearchParams, withParam } from './links';

// Deterministic color slot for a label: same string -> same hue in every
// report, no coordination needed.
export function labelColorIndex(label: string): number {
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) | 0;
  return Math.abs(hash) % 6;
}

// Clicking a pill drives the filter query: plain click replaces any token
// of the same kind, Ctrl/Cmd-click toggles it on/off (so several tags can
// be combined). Clicking from a detail page drops back to the list.
function useApplyToken() {
  const params = useSearchParams();
  return (token: string, append: boolean) => {
    const q = filterWithToken(params.get('q') || '', token, append);
    let next = withParam(params, 'q', q || null);
    next = withParam(next, 'testId', null);
    navigate(next);
  };
}

export function TagLabel({ tag, colorIndex }: { tag: string; colorIndex?: number }) {
  const applyToken = useApplyToken();
  return (
    <span
      className={`label label-${colorIndex ?? labelColorIndex(tag)}`}
      title={`Filter by @${tag} (Ctrl/Cmd-click to combine)`}
      onClick={(e) => {
        e.stopPropagation();
        applyToken(`@${tag}`, e.metaKey || e.ctrlKey);
      }}
    >
      {tag}
    </span>
  );
}

export function GroupLabel({ dimension, value }: { dimension: string; value: string }) {
  const applyToken = useApplyToken();
  return (
    <span
      className={`label label-wrap label-${labelColorIndex(`${dimension}=${value}`)}`}
      title={`Filter by ${dimension}=${value} (Ctrl/Cmd-click to combine)`}
      onClick={(e) => {
        e.stopPropagation();
        applyToken(`g:${dimension}=${value}`, e.metaKey || e.ctrlKey);
      }}
    >
      {value}
    </span>
  );
}

export function LabelsRow({
  test,
  activeDimension,
  showGroup,
}: {
  test: TestData;
  activeDimension?: string;
  showGroup?: boolean;
}) {
  const tags = [...test.tags].sort();
  const groupValue = activeDimension ? test.groups[activeDimension] : undefined;
  if (!tags.length && !(showGroup && groupValue)) return null;
  return (
    <span className="label-row">
      {showGroup && groupValue && activeDimension ? (
        <GroupLabel dimension={activeDimension} value={groupValue} />
      ) : null}
      {tags.map((tag) => (
        <TagLabel key={tag} tag={tag} />
      ))}
    </span>
  );
}

export function LabelsRowStatic({ tags }: { tags: string[] }) {
  // Non-interactive variant (used where navigation would be a trap).
  return (
    <span className="label-row">
      {tags.map((tag) => (
        <span key={tag} className={`label label-${labelColorIndex(tag)}`}>
          {tag}
        </span>
      ))}
    </span>
  );
}

export const LabelsContext = React.createContext<null>(null);
