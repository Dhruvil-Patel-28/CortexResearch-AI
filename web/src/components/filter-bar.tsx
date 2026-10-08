"use client";

import { Bookmark, ChevronDown, Search, X } from "lucide-react";
import { cn, SOURCE_META } from "@/lib/utils";
import type { FeedParams } from "@/lib/types";

const WINDOWS: { key: NonNullable<FeedParams["window"]>; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "month", label: "Month" },
  { key: "all", label: "All" },
];

const SCORE_STEPS: { value: number | undefined; label: string }[] = [
  { value: undefined, label: "Any score" },
  { value: 5, label: "5+" },
  { value: 7, label: "7+" },
  { value: 8.5, label: "Must read" },
];

export interface FilterState {
  window: NonNullable<FeedParams["window"]>;
  source?: string;
  minScore?: number;
  order: NonNullable<FeedParams["order"]>;
  bookmarkedOnly: boolean;
}

/**
 * Sticky filter deck. Laid out narrow-first: window + sort + saved on one row,
 * search on its own full-width row, then the source / score chips wrap below so
 * nothing hides behind a horizontal scroll on small screens.
 */
export function FilterBar({
  state,
  query,
  onQueryChange,
  onChange,
  counts,
  total,
}: {
  state: FilterState;
  query: string;
  onQueryChange: (q: string) => void;
  onChange: (next: Partial<FilterState>) => void;
  counts: Record<string, number>;
  total: number;
}) {
  return (
    <div className="glass border-b md:sticky md:top-0 md:z-10">
      <div className="mx-auto flex max-w-4xl flex-col gap-2.5 px-4 py-3">
        <div className="flex items-center gap-2">
          <div
            role="group"
            aria-label="Time window"
            className="scrollbar-none flex flex-1 gap-0.5 overflow-x-auto rounded-lg border border-line bg-surface p-0.5"
          >
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                onClick={() => onChange({ window: w.key })}
                aria-pressed={state.window === w.key}
                className={cn(
                  "flex-1 whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-ring",
                  state.window === w.key
                    ? "bg-accent/15 text-accent-soft"
                    : "text-ink-faint hover:text-ink-soft",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>

          <div className="relative shrink-0">
            <select
              value={state.order}
              onChange={(e) => onChange({ order: e.target.value as FilterState["order"] })}
              aria-label="Sort order"
              className="appearance-none rounded-lg border border-line bg-surface py-1.5 pl-2.5 pr-7 text-xs text-ink-soft transition-colors hover:text-ink focus-ring"
            >
              <option value="relevance">Best match</option>
              <option value="newest">Newest</option>
            </select>
            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
          </div>

          <button
            onClick={() => onChange({ bookmarkedOnly: !state.bookmarkedOnly })}
            aria-pressed={state.bookmarkedOnly}
            title="Show saved only"
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus-ring",
              state.bookmarkedOnly
                ? "border-accent/40 bg-accent/10 text-accent-soft"
                : "border-line bg-surface text-ink-faint hover:text-ink-soft",
            )}
          >
            <Bookmark className="size-3" />
            <span className="hidden sm:inline">Saved</span>
          </button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search titles and text…"
            aria-label="Search stories"
            className="w-full rounded-lg border border-line bg-surface py-1.5 pl-8 pr-8 text-xs text-ink placeholder:text-ink-faint focus:border-line-strong focus:outline-none focus-ring"
          />
          {query && (
            <button
              onClick={() => onQueryChange("")}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded text-ink-faint transition-colors hover:text-ink focus-ring"
            >
              <X className="size-3" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => onChange({ source: undefined })}
            aria-pressed={!state.source}
            className={cn(
              "chip transition-colors focus-ring",
              !state.source && "!border-accent/40 !bg-accent/10 !text-accent-soft",
            )}
          >
            All sources
            <span className="text-ink-faint">{total}</span>
          </button>
          {Object.entries(SOURCE_META).map(([key, meta]) => (
            <button
              key={key}
              onClick={() => onChange({ source: state.source === key ? undefined : key })}
              aria-pressed={state.source === key}
              className={cn(
                "chip transition-colors focus-ring",
                state.source === key && "!border-accent/40 !bg-accent/10 !text-accent-soft",
              )}
            >
              <span className="size-1.5 rounded-full" style={{ background: meta.tone }} />
              {meta.short}
              <span className="text-ink-faint">{counts[key] ?? 0}</span>
            </button>
          ))}

          <span className="mx-1 hidden h-4 w-px bg-line sm:block" />

          {SCORE_STEPS.map((step) => (
            <button
              key={step.label}
              onClick={() => onChange({ minScore: step.value })}
              aria-pressed={state.minScore === step.value}
              className={cn(
                "chip transition-colors focus-ring",
                state.minScore === step.value && "!border-accent/40 !bg-accent/10 !text-accent-soft",
              )}
            >
              {step.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
