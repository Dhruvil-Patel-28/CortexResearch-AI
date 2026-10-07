"use client";

/**
 * Library — hybrid search over everything you have: saved sources and
 * published reports, ranked by BM25 + embeddings (with optional GraphRAG
 * and Supermemory results when those flags are enabled in the backend).
 */

import { useState } from "react";
import Link from "next/link";
import { Loader2, Network, Search, Sparkles } from "lucide-react";
import { searchApi } from "@/lib/api";
import type { SearchHit, SearchResponse } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";

const KINDS = [
  { value: undefined as "item" | "brief" | undefined, label: "Everything" },
  { value: "item" as const, label: "Sources" },
  { value: "brief" as const, label: "Reports" },
];

function HitCard({ hit }: { hit: SearchHit }) {
  const meta = [
    hit.kind === "brief" ? "report" : hit.source || "source",
    hit.relevance != null ? `relevance ${hit.relevance.toFixed(1)}/10` : null,
    hit.published_at ? relativeTime(hit.published_at) : null,
  ].filter(Boolean);

  const href =
    hit.kind === "brief" ? `/reports/${hit.ref_id}` : `/items/${hit.ref_id}`;

  return (
    <li className="card p-4 transition-colors hover:border-line-strong">
      <Link href={href} className="block rounded-lg focus-ring">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-sm font-medium leading-snug text-ink">{hit.title}</h2>
          <span className="shrink-0 font-mono text-[11px] text-ink-faint">
            {hit.score.toFixed(2)}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-soft">
          {hit.snippet}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-faint">
          {meta.map((bit, i) => (
            <span key={i} className="capitalize">
              {bit}
            </span>
          ))}
        </div>
      </Link>
    </li>
  );
}

export default function LibraryPage() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"item" | "brief" | undefined>(undefined);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const run = async (q: string, k: "item" | "brief" | undefined) => {
    if (!q.trim()) return;
    setLoading(true);
    setError("");
    try {
      setResult(await searchApi.search(q.trim(), k ? { kind: k } : {}));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <header className="masthead-tick pt-2">
        <h1 className="text-xl font-bold tracking-tight">Library</h1>
        <p className="mt-1 text-xs text-ink-soft">
          Search everything you have saved — sources and reports, ranked by hybrid
          retrieval. Ask connections and the graph layer can answer multi-hop questions.
        </p>
      </header>

      <form
        className="mt-5 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(query, kind);
        }}
      >
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search your sources and reports…"
            aria-label="Search the library"
            className="w-full rounded-lg border border-line bg-surface-2 py-2 pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus-ring"
          />
        </div>
        <div className="flex rounded-lg border border-line bg-surface-2 p-0.5" role="group" aria-label="Result type">
          {KINDS.map((option) => (
            <button
              key={option.label}
              type="button"
              onClick={() => {
                setKind(option.value);
                if (query.trim()) void run(query, option.value);
              }}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors focus-ring",
                kind === option.value ? "bg-accent text-white" : "text-ink-soft hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </form>

      {loading && (
        <p className="mt-8 flex items-center gap-2 text-xs text-ink-faint">
          <Loader2 className="size-3 animate-spin" /> Searching…
        </p>
      )}
      {error && <p className="mt-8 text-xs text-danger">{error}</p>}

      {result && !loading && (
        <>
          {result.graph && (
            <div
              className={cn(
                "card mt-5 p-4",
                result.graph.available && "border-accent-soft/40",
              )}
            >
              <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
                <Network className="size-3.5" /> Graph answer
              </p>
              {result.graph.available ? (
                <p className="mt-2 text-xs leading-relaxed text-ink-soft">{result.graph.answer}</p>
              ) : (
                <p className="mt-2 text-xs leading-relaxed text-ink-faint">{result.graph.reason}</p>
              )}
            </div>
          )}

          {result.memory.length > 0 && (
            <div className="card mt-3 p-4">
              <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
                <Sparkles className="size-3.5" /> From your memory
              </p>
              <ul className="mt-2 flex flex-col gap-1.5">
                {result.memory.map((m, i) => (
                  <li key={i} className="text-xs leading-relaxed text-ink-soft">
                    {m.text}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-5 text-[11px] text-ink-faint">
            {result.results.length} result{result.results.length === 1 ? "" : "s"} for
            “{result.query}”
          </p>
          <ul className="mt-2 flex flex-col gap-3">
            {result.results.map((hit) => (
              <HitCard key={`${hit.kind}-${hit.ref_id}`} hit={hit} />
            ))}
          </ul>
          {result.results.length === 0 && (
            <div className="card mt-3 grid place-items-center px-4 py-14 text-center">
              <p className="text-sm font-medium">Nothing matched</p>
              <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-soft">
                Try broader keywords — or research the topic on the pulse page and the
                findings will be searchable here afterwards.
              </p>
            </div>
          )}
        </>
      )}

      {!result && !loading && !error && (
        <div className="card mt-6 grid place-items-center px-4 py-16 text-center">
          <Search className="size-6 text-accent-soft" />
          <p className="mt-3 text-sm font-medium">Search your whole library</p>
          <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-soft">
            Every ingested source and every published report is indexed — BM25 keyword
            matching fused with semantic embeddings, reranked for relevance.
          </p>
        </div>
      )}
    </div>
  );
}
