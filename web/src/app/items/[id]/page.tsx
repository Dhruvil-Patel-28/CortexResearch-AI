"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Bookmark, BookmarkCheck, ExternalLink, Layers, Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { ScoreBadge } from "@/components/score-badge";
import { cn, formatNumber, hostOf, relativeTime, SOURCE_META } from "@/lib/utils";

export default function ItemPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const detail = useAsync(() => api.item(id), [id]);
  const item = detail.data?.item;

  const toggle = async () => {
    if (!item) return;
    if (item.bookmarked) await api.unbookmark(item.id);
    else await api.bookmark(item.id);
    detail.reload();
  };

  if (detail.loading && !detail.data) {
    return (
      <div className="mx-auto grid max-w-3xl place-items-center px-4 py-24">
        <Loader2 className="size-5 animate-spin text-ink-faint" />
      </div>
    );
  }

  if (detail.error || !item) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <p className="text-sm text-ink-soft">{detail.error ?? "Item not found"}</p>
        <Link href="/" className="mt-3 inline-block text-xs text-accent-soft hover:underline">
          Back to pulse
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-xs text-ink-faint transition-colors hover:text-ink-soft focus-ring rounded"
      >
        <ArrowLeft className="size-3" />
        Pulse
      </Link>

      <article className="card mt-4 p-6">
        <div className="flex items-start gap-4">
          <ScoreBadge score={item.relevance} size="lg" />
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold leading-snug tracking-tight">{item.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-faint">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="size-1.5 rounded-full"
                  style={{ background: SOURCE_META[item.source]?.tone }}
                />
                {item.source_label || SOURCE_META[item.source]?.label || item.source}
              </span>
              {item.author && <span>by {item.author}</span>}
              {item.published_at && <span>{relativeTime(item.published_at)}</span>}
              {hostOf(item.url) && <span>{hostOf(item.url)}</span>}
              {typeof item.metrics.score === "number" && (
                <span>{formatNumber(Number(item.metrics.score))} points</span>
              )}
              {typeof item.metrics.stars === "number" && (
                <span>{formatNumber(Number(item.metrics.stars))} stars</span>
              )}
            </div>
          </div>
        </div>

        {item.rationale && (
          <div className="mt-5 rounded-xl border border-accent/25 bg-accent/8 p-4">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-accent-soft">
              <Sparkles className="size-3" />
              Why this matters to you
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{item.rationale}</p>
          </div>
        )}

        {item.raw_text && (
          <div className="mt-5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              Excerpt
            </p>
            <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-ink-soft">
              {item.raw_text.slice(0, 1600)}
            </p>
          </div>
        )}

        {item.tags.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-1.5">
            {item.tags.map((t) => (
              <span key={t} className="chip !text-ink-faint">
                #{t}
              </span>
            ))}
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 focus-ring"
            >
              <ExternalLink className="size-3.5" />
              Open original
            </a>
          )}
          <Link
            href={`/research?item=${item.id}`}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs font-medium text-ink-soft transition-colors hover:border-line-strong hover:text-ink focus-ring"
          >
            <Sparkles className="size-3.5" />
            Deep brief
          </Link>
          <button
            onClick={toggle}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors focus-ring",
              item.bookmarked
                ? "border-accent/40 bg-accent/10 text-accent-soft"
                : "border-line bg-surface-2 text-ink-soft hover:text-ink",
            )}
          >
            {item.bookmarked ? (
              <BookmarkCheck className="size-3.5" />
            ) : (
              <Bookmark className="size-3.5" />
            )}
            {item.bookmarked ? "Saved" : "Save"}
          </button>
        </div>
      </article>

      {(detail.data?.also_covered_by.length ?? 0) > 0 && (
        <section className="mt-6">
          <h2 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
            <Layers className="size-3" />
            Also covered by
          </h2>
          <ul className="mt-2 flex flex-col divide-y divide-line overflow-hidden rounded-xl border border-line">
            {detail.data?.also_covered_by.map((other) => (
              <li key={other.id} className="bg-surface/60">
                <a
                  href={other.url || "#"}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs transition-colors hover:bg-surface-2"
                >
                  <span className="truncate text-ink-soft">{other.title}</span>
                  <span className="shrink-0 text-ink-faint">
                    {SOURCE_META[other.source]?.short ?? other.source}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
