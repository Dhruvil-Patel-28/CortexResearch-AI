<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Cortex web (Next.js 16 + Tailwind v4)

Design language: **"signal observatory"** — dark product shell for app pages, calm
light editorial surface for report reading. Amber accent, mono micro-labels,
glass sticky chrome. Every page is a client component that talks to the FastAPI
engine at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) through
`src/lib/api.ts`; types come from `src/lib/types.ts`.

## Shell and sticky chrome (do not regress)

Two sticky bars previously stacked at `top-0` on narrow viewports and hid content
behind each other. The rule now is: **the mobile header is the only pinned bar.**

- `src/components/app-shell.tsx` — `aside` is `sticky top-0 h-screen` from `md` up.
  The mobile `header` is `glass sticky top-0 z-30 md:hidden` and holds three rows:
  compact `Logo`, a `live` pulse dot, and `<RefreshButton compact />`, then
  `MobileNav` — a horizontal pill rail (`scrollbar-none ... overflow-x-auto`) that
  bleeds edge-to-edge. Six sections must stay reachable there; never wrap labels.
- `src/components/filter-bar.tsx` — must stay `md:sticky md:top-0 md:z-10` with
  **no** base `sticky`. Below `md` it scrolls away with the content so it cannot
  slide under the pinned header. If you ever re-pin it on mobile, offset it below
  the header instead of stacking at `top-0`.
- `src/components/report-reader.tsx` uses `sticky top-8 lg:block` for the TOC —
  desktop only, unaffected by the rule above.

## Components worth knowing

- `RefreshButton` (`src/components/refresh-button.tsx`) — one component, two
  shapes: `compact` renders an icon-only square (status moves into `title` /
  `aria-label`), default renders the full "Refresh feed" button used in the
  sidebar. Both share the poll/`onDone` behavior.
- `FilterBar` + `FilterState` (`src/components/filter-bar.tsx`) — narrow-first
  layout: window segments + sort select + Saved toggle on one row, search on its
  own full-width row, then source/score chips that wrap. Chips use the global
  `.chip` class and override with `!border-…`/`!bg-…` when active. Avoid turning
  any of these rows back into a horizontal scroll where filters can hide.
- `PulsePage` (`src/app/page.tsx`) — masthead, a `Stat` tile grid
  (`In radar` / `Ranked` / `In view` / `Saved`) built from `FeedResponse.stats`,
  error/empty/skeleton states, then the staggered `ItemCard` list. `WINDOW_LABEL`
  maps the active window to human copy.
- `run-pipeline.tsx` + `use-run-stream.ts` render live agent runs from the SSE
  job stream; `item-card.tsx`, `score-badge.tsx` are the pulse atoms.

## Tailwind v4 notes

- Custom utilities live in `src/app/globals.css` under `@utility`:
  `scrollbar-none` (hide the track on edge-to-edge scrollers such as the mobile
  nav and filter rows), `masthead-tick` (amber tick above page titles), plus the
  theme tokens (`--color-ink*`, `--color-line*`, `--color-accent*`, `--color-surface*`).
  Use these tokens instead of raw hex so dark/light surfaces stay consistent.
- Prefer the existing helpers in `src/lib/utils.ts` (`cn`, `relativeTime`,
  `formatNumber`, `SOURCE_META`) over new one-off formatting.

## Verification before you call it done

`npx tsc --noEmit`, `npx eslint .`, `npm run build`. The dev server runs on port
3001 (`npm run dev -- -p 3001`) and expects the API on port 8000
(`uvicorn api.main:app --port 8000`). The live preview viewport is ~543 px wide:
check any layout change there for horizontal overflow and pinned-bar overlap.
