// SPDX-License-Identifier: AGPL-3.0-or-later
// Line icons from the V4 prototype, drawn with currentColor.

const PATHS = {
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.8" />
      <path d="m16 16 5 5" />
    </>
  ),
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  spark: (
    <path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" />
  ),
  bookmark: <path d="M6 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18l-6-4-6 4V4Z" />,
  settings: (
    <>
      <path d="M4 8h16M4 16h16M9 4v8M15 12v8" />
      <circle cx="9" cy="8" r="2" className="icon-knob" />
      <circle cx="15" cy="16" r="2" className="icon-knob" />
    </>
  ),
  close: <path d="M5 5 19 19M19 5 5 19" />,
  chevron: <path d="m6 9 6 6 6-6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  up: <path d="m6 15 6-6 6 6" />,
  down: <path d="m6 9 6 6 6-6" />,
  candle: <path d="M6 2v20M18 2v20M3 7h6v9H3zM15 10h6v7h-6z" />,
  indicators: <path d="M3 17c3-1 4-8 7-8s3 6 6 6 4-9 5-11M3 21h18" />,
  pen: <path d="M4 20l4-1 11-11-3-3L5 16l-1 4zM14 6l3 3" />,
  line: <path d="m2 16 5-5 5 3 4-8 6 4" />,
  doc: (
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8" />
  ),
  trash: <path d="M4 7h16M10 4h4M7 7l1 14h8l1-14M10 10v8M14 10v8" />,
  layers: <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" />,
  bell: <path d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />,
  star: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2-5.5-2.9-5.5 2.9 1-6.2L3 9.6l6.2-.9L12 3Z" />,
  chart: <path d="M3 3v18h18M6.5 15.5l4.2-4.2 3.5 2.2L20 6" />,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, filled = false }: { name: IconName; filled?: boolean }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" data-filled={filled || undefined}>
      {PATHS[name]}
    </svg>
  );
}
