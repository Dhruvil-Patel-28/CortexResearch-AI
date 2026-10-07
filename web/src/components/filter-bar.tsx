"use client";

import { Bookmark, Search } from "lucide-react";
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
    <div className="glass sticky top-0 z-10 border-b">
      <div className="mx-auto flex max-w-4xl flex-col gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-line bg-surface p-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                onClick={() => onChange({ window: w.key })}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-ring",
                  state.window === w.key
                    ? "bg-accent/15 text-accent-soft"
                    : "text-ink-faint hover:text-ink-soft",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>

          <div className="relative min-w-[180px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
            <input
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Search titles and text…"
              className="w-full rounded-lg border border-line bg-surface py-1.5 pl-8 pr-3 text-xs text-ink placeholder:text-ink-faint focus:border-line-strong focus:outline-none focus-ring"
            />
          </div>

          <select
            value={state.order}
            onChange={(e) => onChange({ order: e.target.value as FilterState["order"] })}
            className="rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-ink-soft focus-ring"
          >
            <option value="relevance">Best match</option>
            <option value="newest">Newest</option>
          </select>

          <button
            onClick={() => onChange({ bookmarkedOnly: !state.bookmarkedOnly })}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus-ring",
              state.bookmarkedOnly
                ? "border-accent/40 bg-accent/10 text-accent-soft"
                : "border-line bg-surface text-ink-faint hover:text-ink-soft",
            )}
          >
            <Bookmark className="size-3" />
            Saved
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => onChange({ source: undefined })}
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

          <span className="mx-1 h-4 w-px bg-line" />

          {SCORE_STEPS.map((step) => (
            <button
              key={step.label}
              onClick={() => onChange({ minScore: step.value })}
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
