"use client";

import Link from "next/link";
import { Bookmark, BookmarkCheck, ExternalLink, Layers, Sparkles } from "lucide-react";
import type { Item } from "@/lib/types";
import { cn, formatNumber, hostOf, relativeTime, SOURCE_META } from "@/lib/utils";
import { ScoreBadge } from "@/components/score-badge";

/** Compact source pill with the source's accent colour. */
export function SourceChip({ source, label }: { source: string; label?: string }) {
  const meta = SOURCE_META[source];
  return (
    <span className="chip">
      <span
        className="size-1.5 rounded-full"
        style={{ background: meta?.tone ?? "var(--color-ink-faint)" }}
      />
      {label ?? meta?.label ?? source}
    </span>
  );
}

/** Human summary of an item's metrics (HN points, stars, subreddit, feed). */
function metricSummary(item: Item): string[] {
  const m = item.metrics ?? {};
  const bits: string[] = [];
  if (typeof m.score === "number") bits.push(`${formatNumber(m.score)} pts`);
  if (typeof m.comments === "number" && m.comments > 0) bits.push(`${formatNumber(m.comments)} comments`);
  if (typeof m.stars === "number") bits.push(`${formatNumber(m.stars)} stars`);
  if (typeof m.subreddit === "string") bits.push(`r/${m.subreddit}`);
  if (typeof m.feed === "string" && m.feed) bits.push(String(m.feed));
  if (typeof m.language === "string" && m.language) bits.push(String(m.language));
  return bits;
}

export function ItemCard({
  item,
  onToggleBookmark,
}: {
  item: Item;
  onToggleBookmark?: (item: Item) => void;
}) {
  const meta = SOURCE_META[item.source];
  const bits = metricSummary(item);
  const others = item.cluster_sources.filter((s) => s !== item.source);

  return (
    <article
      className={cn(
        "card card-hover group relative p-4",
        item.bookmarked && "border-accent/40",
      )}
    >
      <div className="flex gap-4">
        <ScoreBadge score={item.relevance} />

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-[15px] font-medium leading-snug text-ink">
              <Link
                href={`/items/${item.id}`}
                className="transition-colors hover:text-accent-soft focus-ring rounded"
              >
                {item.title}
              </Link>
            </h3>

            <div className="flex shrink-0 items-center gap-1">
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="rounded-md p-1.5 text-ink-faint opacity-0 transition-all hover:bg-surface-3 hover:text-ink group-hover:opacity-100 focus-ring"
                  title="Open original"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              )}
              <button
                onClick={() => onToggleBookmark?.(item)}
                className={cn(
                  "rounded-md p-1.5 transition-all focus-ring",
                  item.bookmarked
                    ? "text-accent-soft"
                    : "text-ink-faint opacity-0 hover:bg-surface-3 hover:text-ink group-hover:opacity-100",
                )}
                title={item.bookmarked ? "Remove bookmark" : "Save for later"}
              >
                {item.bookmarked ? (
                  <BookmarkCheck className="size-3.5" />
                ) : (
                  <Bookmark className="size-3.5" />
                )}
              </button>
            </div>
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-faint">
            <span className="inline-flex items-center gap-1.5">
              <span
                className="size-1.5 rounded-full"
                style={{ background: meta?.tone ?? "var(--color-ink-faint)" }}
              />
              {item.source_label || meta?.label || item.source}
            </span>
            {bits.slice(0, 3).map((b) => (
              <span key={b} className="before:mr-2 before:text-line-strong before:content-['·']">
                {b}
              </span>
            ))}
            {item.published_at && (
              <span className="before:mr-2 before:text-line-strong before:content-['·']">
                {relativeTime(item.published_at)}
              </span>
            )}
            {hostOf(item.url) && (
              <span className="before:mr-2 before:text-line-strong before:content-['·']">
                {hostOf(item.url)}
              </span>
            )}
            {others.length > 0 && (
              <span className="chip !border-accent/30 !bg-accent/10 !text-accent-soft">
                <Layers className="size-2.5" />
                also on {others.map((s) => SOURCE_META[s]?.short ?? s).join(", ")}
              </span>
            )}
          </div>

          {item.rationale ? (
            <p className="mt-3 border-l-2 border-accent/50 pl-3 text-[13px] leading-relaxed text-ink-soft">
              <Sparkles className="mr-1.5 -mt-0.5 inline size-3 text-accent-soft" />
              {item.rationale}
            </p>
          ) : (
            <p className="mt-3 text-[12px] italic text-ink-faint">
              Not scored yet — hit Refresh to rank this with your profile.
            </p>
          )}

          {item.tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {item.tags.map((tag) => (
                <span key={tag} className="chip !text-[10px] !text-ink-faint">
                  #{tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
