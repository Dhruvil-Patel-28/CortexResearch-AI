"use client";

/**
 * Report library — every saved deep brief.
 */

import { useState } from "react";
import Link from "next/link";
import { FileText, Loader2, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn, relativeTime } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  done: "text-positive",
  running: "text-accent-soft",
  error: "text-danger",
};

export default function ReportsPage() {
  const reports = useAsync(() => api.reports({ limit: 100 }), []);
  const [removing, setRemoving] = useState<string | null>(null);

  const remove = async (id: string) => {
    setRemoving(id);
    try {
      await api.deleteReport(id);
      reports.reload();
    } finally {
      setRemoving(null);
    }
  };

  const items = reports.data ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <header className="masthead-tick flex flex-wrap items-end justify-between gap-3 pt-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Reports</h1>
          <p className="mt-1 text-xs text-ink-soft">
            {items.length
              ? `${items.length} saved deep brief${items.length === 1 ? "" : "s"} — cited, verified and exportable.`
              : "Deep briefs you generate will be saved here."}
          </p>
        </div>
        <Link
          href="/research"
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 focus-ring"
        >
          <Plus className="size-3.5" />
          New research
        </Link>
      </header>

      {reports.loading && !reports.data && (
        <p className="mt-8 flex items-center gap-2 text-xs text-ink-faint">
          <Loader2 className="size-3 animate-spin" />
          Loading reports…
        </p>
      )}

      {reports.error && <p className="mt-8 text-xs text-danger">{reports.error}</p>}

      {!reports.loading && items.length === 0 && !reports.error && (
        <div className="card mt-6 grid place-items-center px-4 py-16 text-center">
          <FileText className="size-6 text-accent-soft" />
          <p className="mt-3 text-sm font-medium">No reports yet</p>
          <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-soft">
            Ask a question on the research page, or hit “Deep brief” on any story in the pulse — the
            finished report lands here with its sources and verification.
          </p>
          <Link
            href="/research"
            className="mt-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-soft transition-colors hover:text-ink focus-ring"
          >
            Research something
          </Link>
        </div>
      )}

      <ul className="mt-5 flex flex-col gap-3">
        {items.map((report) => (
          <li key={report.id} className="card group relative p-4 transition-colors hover:border-line-strong">
            <Link href={`/reports/${report.id}`} className="block focus-ring rounded-lg">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-medium leading-snug text-ink">
                    {report.title || report.query}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-faint">
                    <span className={cn("capitalize", STATUS_TONE[report.status])}>{report.status}</span>
                    <span>{report.depth === "brief" ? "quick brief" : `${report.depth} brief`}</span>
                    <span>{report.reading_time_min} min read</span>
                    <span>{report.source_count} sources</span>
                    <span className="inline-flex items-center gap-1">
                      <ShieldCheck className="size-3" />
                      {report.verification.supported}/{report.verification.checked} claims verified
                    </span>
                    <span>{relativeTime(report.created_at)}</span>
                  </div>
                </div>
                <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                  ${report.cost_usd.toFixed(3)}
                </span>
              </div>

              {report.tldr.length > 0 && (
                <ul className="mt-2.5 flex flex-col gap-1 border-l border-line pl-3">
                  {report.tldr.slice(0, 3).map((point, i) => (
                    <li key={i} className="truncate text-xs leading-relaxed text-ink-soft">
                      {point}
                    </li>
                  ))}
                </ul>
              )}
            </Link>

            <button
              onClick={() => void remove(report.id)}
              aria-label="Delete report"
              className="absolute right-3 top-3 rounded-md border border-line bg-surface-2 p-1.5 text-ink-faint opacity-0 transition-opacity hover:text-danger focus-ring group-hover:opacity-100"
            >
              {removing === report.id ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Trash2 className="size-3" />
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
