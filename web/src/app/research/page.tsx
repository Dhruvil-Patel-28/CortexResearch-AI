"use client";

/**
 * Ask page — start a deep-research run, optionally about one pulse item.
 *
 * `?item=<id>` switches the page into "brief this story" mode: it shows the
 * item being briefed and the personalized rationale, so the report that comes
 * back is an answer to a question the user actually asked.
 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, FileText, Loader2, Sparkles, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Depth, Item } from "@/lib/types";
import { cn, relativeTime, sourceLabel } from "@/lib/utils";

const DEPTHS: { key: Depth; label: string; hint: string }[] = [
  { key: "brief", label: "Brief", hint: "~700 words · 3 threads · fastest" },
  { key: "standard", label: "Standard", hint: "~2000 words · 5 threads · balanced" },
  { key: "deep", label: "Deep", hint: "~3000 words · 7 threads · exhaustive" },
];

const EXAMPLES = [
  "What changed in LLM inference pricing this quarter, and what should I do about it?",
  "Which vector database should I pick in 2026 for a local RAG app, and why?",
  "What is the current state of AI coding agents, and how do they differ in practice?",
];

function ResearchContent() {
  const router = useRouter();
  const params = useSearchParams();
  const itemId = params.get("item");

  const [query, setQuery] = useState("");
  const [depth, setDepth] = useState<Depth>("standard");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const item = useAsync(() => (itemId ? api.item(itemId) : Promise.resolve(null)), [itemId]);
  const recent = useAsync(() => api.reports({ limit: 8 }), []);

  useEffect(() => {
    if (itemId) return;
    textarea.current?.focus();
  }, [itemId]);

  const start = async (payload?: { query?: string; itemBrief?: boolean }) => {
    setError(null);
    const text = (payload?.query ?? query).trim();
    if (!payload?.itemBrief && text.length < 8) {
      setError("Describe what you want researched (at least a few words).");
      return;
    }
    setStarting(true);
    try {
      const started = payload?.itemBrief && itemId
        ? await api.itemBrief(itemId, depth)
        : await api.startResearch({ query: text, depth, item_id: itemId });
      router.push(`/research/${started.job_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the run");
      setStarting(false);
    }
  };

  const briefedItem: Item | undefined = item.data?.item;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Deep research</h1>
        <p className="mt-1 text-xs leading-relaxed text-ink-soft">
          A research team plans the question, reads the sources it finds, verifies every claim against
          what it actually read, and writes a report you should not have to follow up on.
        </p>
      </header>

      {itemId && (
        <div className="card mt-5 p-4">
          {item.loading && !briefedItem ? (
            <p className="flex items-center gap-2 text-xs text-ink-faint">
              <Loader2 className="size-3 animate-spin" /> Loading story…
            </p>
          ) : briefedItem ? (
            <>
              <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
                Briefing this story
              </p>
              <h2 className="mt-1.5 text-sm font-medium leading-snug">{briefedItem.title}</h2>
              <p className="mt-1 text-[11px] text-ink-faint">
                {sourceLabel(briefedItem.source)} · {relativeTime(briefedItem.published_at)}
              </p>
              {briefedItem.rationale && (
                <p className="mt-2.5 rounded-lg border border-accent/25 bg-accent/8 p-3 text-xs leading-relaxed text-ink-soft">
                  {briefedItem.rationale}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => start({ itemBrief: true })}
                  disabled={starting}
                  className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-ring"
                >
                  {starting ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                  Generate deep brief
                </button>
                <button
                  onClick={() => router.push("/research")}
                  className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-soft transition-colors hover:text-ink focus-ring"
                >
                  Ask something else
                </button>
              </div>
            </>
          ) : (
            <p className="text-xs text-ink-faint">That story no longer exists.</p>
          )}
        </div>
      )}

      {!itemId && (
        <>
          <div className="card mt-5 p-4">
            <label htmlFor="query" className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              Research question
            </label>
            <textarea
              id="query"
              ref={textarea}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void start();
              }}
              rows={3}
              placeholder="e.g. What changed in open-weight LLMs this quarter, and which one should I actually use?"
              className="mt-2 w-full resize-none rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-accent/50 focus:outline-none"
            />

            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {DEPTHS.map((d) => (
                <button
                  key={d.key}
                  onClick={() => setDepth(d.key)}
                  title={d.hint}
                  className={cn(
                    "rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus-ring",
                    depth === d.key
                      ? "border-accent/40 bg-accent/12 text-accent-soft"
                      : "border-line bg-surface-2 text-ink-soft hover:text-ink",
                  )}
                >
                  {d.label}
                </button>
              ))}
              <span className="ml-1 hidden text-[11px] text-ink-faint sm:inline">
                {DEPTHS.find((d) => d.key === depth)?.hint}
              </span>
            </div>

            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => void start()}
                disabled={starting}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-ring"
              >
                {starting ? <Loader2 className="size-3.5 animate-spin" /> : <Zap className="size-3.5" />}
                {starting ? "Starting…" : "Start research"}
              </button>
              <span className="text-[11px] text-ink-faint">⌘↵ to run</span>
            </div>

            {error && <p className="mt-2 text-xs text-danger">{error}</p>}
          </div>

          <div className="mt-3 flex flex-col gap-1.5">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  setQuery(example);
                  textarea.current?.focus();
                }}
                className="flex items-center gap-2 rounded-lg border border-line/60 bg-surface/60 px-3 py-2 text-left text-xs text-ink-faint transition-colors hover:border-line-strong hover:text-ink-soft focus-ring"
              >
                <ArrowRight className="size-3 shrink-0" />
                {example}
              </button>
            ))}
          </div>
        </>
      )}

      {(recent.data?.length ?? 0) > 0 && (
        <section className="mt-8">
          <h2 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
            <FileText className="size-3" />
            Recent reports
          </h2>
          <ul className="mt-2 flex flex-col divide-y divide-line overflow-hidden rounded-xl border border-line">
            {recent.data?.map((report) => (
              <li key={report.id} className="bg-surface/60">
                <Link
                  href={`/reports/${report.id}`}
                  className="flex items-start justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink">
                      {report.title || report.query}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-faint">
                      {report.depth} · {report.source_count} sources ·{" "}
                      {report.verification.supported}/{report.verification.checked} verified ·{" "}
                      {relativeTime(report.created_at)}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] text-ink-faint">${report.cost_usd.toFixed(3)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export default function ResearchPage() {
  return (
    <Suspense>
      <ResearchContent />
    </Suspense>
  );
}
