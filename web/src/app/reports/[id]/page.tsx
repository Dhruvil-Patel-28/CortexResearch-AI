"use client";

/**
 * Report reader page — `/reports/[id]`.
 *
 * Editorial light surface (the one place in the app that is not dark), with a
 * sticky table of contents, inline citations and export actions.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, FileWarning, Loader2 } from "lucide-react";
import { ExportButtons, ReportReader } from "@/components/report-reader";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Report } from "@/lib/types";
import { relativeTime } from "@/lib/utils";

/** A stored report is only renderable if it has the v2 shape. */
function asReport(value: unknown): Report | null {
  const candidate = value as Partial<Report> | null;
  if (!candidate || typeof candidate !== "object") return null;
  if (typeof candidate.title !== "string" || !Array.isArray(candidate.tldr)) return null;
  return {
    ...(candidate as Report),
    key_developments: candidate.key_developments ?? [],
    timeline: candidate.timeline ?? [],
    faq: candidate.faq ?? [],
    glossary: candidate.glossary ?? [],
    open_questions: candidate.open_questions ?? [],
    what_to_watch_next: candidate.what_to_watch_next ?? [],
    sources: candidate.sources ?? [],
    model_trace: candidate.model_trace ?? [],
    verification: candidate.verification ?? {
      checked: 0,
      supported: 0,
      unsupported: 0,
      unsupported_claims: [],
      notes: "",
    },
  };
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const detail = useAsync(() => api.report(id), [id]);

  if (detail.loading && !detail.data) {
    return (
      <div className="grid place-items-center py-32">
        <Loader2 className="size-5 animate-spin text-ink-faint" />
      </div>
    );
  }

  if (detail.error || !detail.data) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-24 text-center">
        <FileWarning className="mx-auto size-6 text-ink-faint" />
        <p className="mt-3 text-sm text-ink-soft">{detail.error ?? "Report not found"}</p>
        <Link href="/reports" className="mt-3 inline-block text-xs text-accent-soft hover:underline">
          Back to reports
        </Link>
      </div>
    );
  }

  const { data } = detail;
  const report = asReport(data.report);

  return (
    <div>
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pt-6 lg:px-8">
        <Link
          href="/reports"
          className="inline-flex items-center gap-1.5 text-xs text-ink-faint transition-colors hover:text-ink-soft focus-ring rounded"
        >
          <ArrowLeft className="size-3" />
          Reports
        </Link>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-ink-faint">
            {data.status} · {relativeTime(data.finished_at ?? data.created_at)}
          </span>
          <ExportButtons id={data.id} />
        </div>
      </div>

      {report ? (
        <ReportReader report={report} reportId={data.id} />
      ) : (
        <div className="mx-auto max-w-2xl px-4 py-16 text-center">
          <AlertTriangle className="mx-auto size-6 text-warning" />
          <p className="mt-3 text-sm text-ink-soft">
            This stored report could not be rendered — it may come from an earlier schema version.
          </p>
          {data.markdown && (
            <pre className="mt-4 max-h-96 overflow-auto rounded-xl border border-line bg-surface p-4 text-left text-xs leading-relaxed text-ink-soft">
              {data.markdown.slice(0, 4000)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
