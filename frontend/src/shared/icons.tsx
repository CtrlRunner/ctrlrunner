// Hand-drawn minimal SVG glyphs (16x16 viewBox), intentionally our own
// shapes -- no icon-set files are copied into this repo.
import type React from 'react';

type IconProps = { className?: string; title?: string };

function svg(props: IconProps, children: React.ReactNode, filled = false) {
  const shared = {
    className: `icon ${props.className || ''}`,
    viewBox: '0 0 16 16',
    width: 14,
    height: 14,
    fill: filled ? 'currentColor' : 'none',
    stroke: filled ? 'none' : 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  } as const;
  if (props.title) {
    return (
      <svg {...shared} role="img" aria-label={props.title}>
        <title>{props.title}</title>
        {children}
      </svg>
    );
  }
  return (
    <svg {...shared} aria-hidden="true">
      {children}
    </svg>
  );
}

export const CheckIcon = (p: IconProps) => svg(p, <path d="M3 8.5l3.5 3.5L13 4.5" />);

export const CrossIcon = (p: IconProps) => svg(p, <path d="M4 4l8 8M12 4l-8 8" />);

export const SkipIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M5.5 8h5" />
    </>,
  );

export const WarnIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <path d="M8 2.2L14.7 13.5H1.3L8 2.2z" />
      <path d="M8 6.5v3.2" />
      <path d="M8 11.6v.4" />
    </>,
  );

export const ClockIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.8V8l2.4 1.6" />
    </>,
  );

export const BanIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M3.8 3.8l8.4 8.4" />
    </>,
  );

export const TubeIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <path d="M6 2h4" />
      <path d="M7 2v5l-3.6 6a1.4 1.4 0 0 0 1.2 2.2h6.8a1.4 1.4 0 0 0 1.2-2.2L9 7V2" />
    </>,
  );

export const ChevronIcon = (p: IconProps & { open?: boolean }) =>
  svg(
    { ...p, className: (p.className || '') + (p.open ? ' chevron-open' : ' chevron') },
    <path d="M6 4l4 4-4 4" />,
  );

export const CopyIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
    </>,
  );

export const SearchIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </>,
  );

export const ImageIcon = (p: IconProps) =>
  svg(
    p,
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <circle cx="5.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
      <path d="M2.5 11.5l3.5-3 3 2.5 2.5-2 2 2" />
    </>,
  );

export const TraceIcon = (p: IconProps) => svg(p, <path d="M2 8h3l2-4 2 8 2-4h3" />);
