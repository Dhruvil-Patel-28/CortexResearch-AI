"use client";

/**
 * Digests — the daily briefing history.
 *
 * The digest itself is Markdown rendered with a small inline renderer (the
 * digest format is small and controlled: headings, lists, blockquotes, links,
 * bold — nothing else), plus a manual "build now" action and per-topic delta
 * briefs that hand off to the live research view.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, ChevronRight, Loader2, Mail, Plus, Radio } from "lucide-react";
import { digestsApi } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { DigestDetail } from "@/lib/types";
import { relativeTime } from "@/lib/utils";

/** Render the controlled digest markdown subset. Escapes HTML first. */
function DigestMarkdown({ markdown }: { markdown: string }) {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');

  const lines = markdown.split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  let quote: string[] = [];

  const flushList = () => {
    if (list.length) {
      out.push(
        <ul key={`ul-${out.length}`} className="my-3 list-disc pl-5">
          {list.map((item, i) => (
            <li key={i} dangerouslySetInnerHTML={{ __html: inline(item) }} />
          ))}
        </ul>,
      );
      list = [];
    }
  };
  const flushQuote = () => {
    if (quote.length) {
      out.push(
        <blockquote
          key={`q-${out.length}`}
          className="my-3 border-l-2 border-paper-line pl-3 text-sm italic text-paper-ink-soft"
          dangerouslySetInnerHTML={{ __html: inline(quote.join(" ")) }}
        />,
      );
      quote = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^###\s+/.test(line)) {
      flushList();
      flushQuote();
      out.push(
        <h3 key={out.length} className="mt-5 text-base font-semibold text-paper-ink">
          <span dangerouslySetInnerHTML={{ __html: inline(line.replace(/^###\s+/, "")) }} />
        </h3>,
      );
    } else if (/^##\s+/.test(line)) {
      flushList();
      flushQuote();
      out.push(
        <h2 key={out.length} className="mt-7 border-b border-paper-line pb-1 text-lg font-semibold text-paper-ink">
          <span dangerouslySetInnerHTML={{ __html: inline(line.replace(/^##\s+/, "")) }} />
        </h2>,
      );
    } else if (/^#\s+/.test(line)) {
      flushList();
      flushQuote();
      out.push(
        <h1 key={out.length} className="text-xl font-semibold tracking-tight text-paper-ink">
          <span dangerouslySetInnerHTML={{ __html: inline(line.replace(/^#\s+/, "")) }} />
        </h1>,
      );
    } else if (/^>\s?/.test(line)) {
      flushList();
      quote.push(line.replace(/^>\s?/, ""));
    } else if (/^[-*]\s+/.test(line)) {
      flushQuote();
      list.push(line.replace(/^[-*]\s+/, ""));
    } else if (/^---+$/.test(line)) {
      flushList();
      flushQuote();
      out.push(<hr key={out.length} className="my-5 border-paper-line" />);
    } else if (line.trim() === "") {
      flushList();
      flushQuote();
    } else {
      flushList();
      flushQuote();
      out.push(
        <p
          key={out.length}
          className="my-2 text-sm leading-relaxed text-paper-ink-soft"
          dangerouslySetInnerHTML={{ __html: inline(line) }}
        />,
      );
    }
  }
  flushList();
  flushQuote();

  return <div className="prose-digest">{out}</div>;
}

export default function DigestsPage() {
  const router = useRouter();
  const digests = useAsync(() => digestsApi.list(), []);
  const [open, setOpen] = useState<DigestDetail | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [topic, setTopic] = useState("");
  const [deltaBusy, setDeltaBusy] = useState(false);
  const [deltaError, setDeltaError] = useState<string | null>(null);

  const openDigest = async (id: string) => {
    setLoadingId(id);
    try {
      setOpen(await digestsApi.get(id));
    } finally {
      setLoadingId(null);
    }
  };

  const buildNow = async () => {
    setBuilding(true);
    try {
      await digestsApi.run();
      digests.reload();
    } finally {
      setBuilding(false);
    }
  };

  const startDelta = async () => {
    const value = topic.trim();
    if (!value) return;
    setDeltaBusy(true);
    setDeltaError(null);
    try {
      const started = await digestsApi.deltaBrief(value);
      router.push(`/research/${started.job_id}`);
    } catch (e) {
      setDeltaError(e instanceof Error ? e.message : "Could not start the delta brief");
      setDeltaBusy(false);
    }
  };

  const items = digests.data ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Digests</h1>
          <p className="mt-1 text-xs text-ink-soft">
            Daily briefs assembled from your ranked pulse — with an honest “what changed since last
            time” section.
          </p>
        </div>
        <button
          onClick={() => void buildNow()}
          disabled={building}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-ring"
        >
          {building ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
          {building ? "Building…" : "Build digest now"}
        </button>
      </header>

      {/* Delta brief launcher */}
      <div className="card mt-5 p-4">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
          Delta brief — what changed in a topic you follow
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void startDelta()}
            placeholder="e.g. AI coding agents, local LLMs, vector databases"
            className="flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent/50 focus:outline-none"
          />
          <button
            onClick={() => void startDelta()}
            disabled={deltaBusy || !topic.trim()}
            className="inline-flex items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs font-medium text-accent-soft transition-colors hover:bg-accent/15 disabled:opacity-50 focus-ring"
          >
            {deltaBusy ? <Loader2 className="size-3.5 animate-spin" /> : <Radio className="size-3.5" />}
            Research delta
          </button>
        </div>
        {deltaError && <p className="mt-2 text-xs text-danger">{deltaError}</p>}
      </div>

      {digests.loading && !digests.data && (
        <p className="mt-8 flex items-center gap-2 text-xs text-ink-faint">
          <Loader2 className="size-3 animate-spin" />
          Loading digests…
        </p>
      )}

      {!digests.loading && items.length === 0 && !digests.error && (
        <div className="card mt-6 grid place-items-center px-4 py-16 text-center">
          <CalendarClock className="size-6 text-accent-soft" />
          <p className="mt-3 text-sm font-medium">No digests yet</p>
          <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-soft">
            Build one now, or let the scheduler do it daily — it ranks everything new since the last
            digest and writes it here (and to <code>data/digests/</code>).
          </p>
        </div>
      )}

      <ul className="mt-5 flex flex-col gap-3">
        {items.map((digest) => (
          <li key={digest.id} className="card p-4">
            <button
              onClick={() => void openDigest(digest.id)}
              className="flex w-full items-start justify-between gap-3 text-left focus-ring rounded-lg"
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-ink">
                    {relativeTime(digest.created_at)}
                  </span>
                  <span className="text-[11px] text-ink-faint">
                    {digest.story_count} stories
                  </span>
                  {digest.delivered.map((channel) => (
                    <span
                      key={channel}
                      className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-ink-faint"
                    >
                      {channel === "file" ? <Mail className="size-2.5" /> : null}
                      {channel}
                    </span>
                  ))}
                </span>
                <span className="mt-1 line-clamp-2 block text-xs leading-relaxed text-ink-faint">
                  {digest.preview.replace(/[#>*\n]/g, " ").trim()}
                </span>
              </span>
              <span className="mt-1 shrink-0 text-ink-faint">
                {loadingId === digest.id ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ChevronRight className="size-4" />
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {open && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => setOpen(null)}
          role="presentation"
        >
          <div
            className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-paper-line bg-paper px-6 py-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Digest preview"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-wide text-paper-ink-faint">
                Digest · {relativeTime(open.created_at)}
              </span>
              <button
                onClick={() => setOpen(null)}
                className="rounded-lg border border-paper-line bg-paper-2 px-2.5 py-1 text-[11px] text-paper-ink-soft transition-colors hover:text-paper-ink focus-ring"
              >
                Close
              </button>
            </div>
            <DigestMarkdown markdown={open.markdown} />
          </div>
        </div>
      )}
    </div>
  );
}
