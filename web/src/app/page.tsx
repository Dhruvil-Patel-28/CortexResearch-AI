"use client";

import { useMemo, useState } from "react";
import { Inbox, Loader2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { FilterBar, type FilterState } from "@/components/filter-bar";
import { ItemCard } from "@/components/item-card";
import type { Item } from "@/lib/types";
import { formatNumber, relativeTime } from "@/lib/utils";

const WINDOW_LABEL: Record<FilterState["window"], string> = {
  today: "today",
  week: "this week",
  month: "this month",
  all: "all time",
};

/** Compact metric tile used in the pulse header strip. */
function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 px-3 py-2">
      <p className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-ink-faint">{label}</p>
      <p className="mt-0.5 flex items-baseline gap-1.5">
        <span className="text-base font-semibold tabular-nums text-ink">{value}</span>
        <span className="truncate text-[10px] text-ink-faint">{hint}</span>
      </p>
    </div>
  );
}

export default function PulsePage() {
  const [filters, setFilters] = useState<FilterState>({
    window: "week",
    order: "relevance",
    bookmarkedOnly: false,
    minScore: undefined,
  });
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounced(query, 300);
  const [optimistic, setOptimistic] = useState<Record<string, boolean>>({});

  const feed = useAsync(
    () =>
      api.feed({
        window: filters.window,
        source: filters.source,
        min_score: filters.minScore || undefined,
        order: filters.order,
        bookmarked: filters.bookmarkedOnly || undefined,
        q: debouncedQuery || undefined,
        limit: 100,
      }),
    [
      filters.window,
      filters.source,
      filters.minScore,
      filters.order,
      filters.bookmarkedOnly,
      debouncedQuery,
    ],
  );

  const items = useMemo<Item[]>(() => {
    return (feed.data?.items ?? []).map((item) =>
      item.id in optimistic ? { ...item, bookmarked: optimistic[item.id] } : item,
    );
  }, [feed.data, optimistic]);

  const toggleBookmark = async (item: Item) => {
    const next = !item.bookmarked;
    setOptimistic((prev) => ({ ...prev, [item.id]: next }));
    try {
      if (next) await api.bookmark(item.id);
      else await api.unbookmark(item.id);
      feed.reload();
    } catch {
      setOptimistic((prev) => ({ ...prev, [item.id]: !next }));
    }
  };

  const counts = feed.data?.stats.by_source ?? {};
  const stats = feed.data?.stats;
  const lastIngest = stats?.last_ingest_at;

  return (
    <>
      <FilterBar
        state={filters}
        query={query}
        onQueryChange={setQuery}
        onChange={(next) => setFilters((prev) => ({ ...prev, ...next }))}
        counts={counts}
        total={stats?.total_items ?? 0}
      />

      <div className="mx-auto max-w-4xl px-4 py-5">
        <header className="masthead-tick flex flex-wrap items-end justify-between gap-x-4 gap-y-2 pt-2">
          <div>
            <h1 className="text-xl font-bold tracking-tight">Market pulse</h1>
            <p className="mt-0.5 text-xs text-ink-faint">
              {feed.loading && !feed.data
                ? "Loading your radar…"
                : `Ranked against your profile${
                    lastIngest ? ` · sources last checked ${relativeTime(lastIngest)}` : ""
                  }`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {feed.loading && feed.data && (
              <Loader2 className="size-3.5 animate-spin text-ink-faint" />
            )}
            {!feed.loading && (feed.data?.count ?? 0) > 0 && (
              <span className="chip !border-positive/30 !bg-positive/10 !text-positive">
                <span className="size-1.5 rounded-full bg-positive" />
                live feed
              </span>
            )}
          </div>
        </header>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat
            label="In radar"
            value={stats ? formatNumber(stats.total_items) : "—"}
            hint="all sources"
          />
          <Stat
            label="Ranked"
            value={stats ? formatNumber(stats.scored_items) : "—"}
            hint="scored for you"
          />
          <Stat
            label="In view"
            value={feed.data ? formatNumber(feed.data.count) : "—"}
            hint={WINDOW_LABEL[filters.window]}
          />
          <Stat
            label="Saved"
            value={stats ? String(stats.bookmarks) : "—"}
            hint="bookmarks"
          />
        </div>

        {feed.error && (
          <div className="card mt-5 flex items-start gap-3 border-danger/40 p-4 text-sm">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-danger" />
            <div>
              <p className="font-medium text-ink">Could not reach the research engine</p>
              <p className="mt-1 text-xs text-ink-soft">
                {feed.error}. Start it with{" "}
                <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[11px]">
                  uvicorn api.main:app --port 8000
                </code>
                .
              </p>
            </div>
          </div>
        )}

        {!feed.error && feed.loading && !feed.data && (
          <div className="mt-5 flex flex-col gap-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="card h-28 animate-pulse bg-surface-2" />
            ))}
          </div>
        )}

        {!feed.error && !feed.loading && items.length === 0 && (
          <div className="card mt-5 flex flex-col items-center gap-3 px-6 py-14 text-center">
            <Inbox className="size-6 text-ink-faint" />
            <div>
              <p className="text-sm font-medium">Nothing here yet</p>
              <p className="mt-1 max-w-sm text-xs text-ink-soft">
                Use <strong className="text-ink-soft">Refresh feed</strong> to pull the latest from
                Hacker News, arXiv, blogs, Reddit, GitHub and Product Hunt.
              </p>
            </div>
          </div>
        )}

        <div className="stagger mt-5 flex flex-col gap-3">
          {items.map((item) => (
            <ItemCard
              key={item.cluster_key || item.id}
              item={item}
              onToggleBookmark={toggleBookmark}
            />
          ))}
        </div>
      </div>
    </>
  );
}
