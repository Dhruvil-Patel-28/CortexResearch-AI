"use client";

/**
 * Live run view — `/research/[jobId]`.
 *
 * Shows the agents working: the plan they produced, the sources they pulled
 * (streaming in as they are registered), the verification verdict and, on
 * completion, a jump straight into the report.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ArrowRight, CircleSlash, FileText, Loader2, RefreshCw } from "lucide-react";
import { ReportReader } from "@/components/report-reader";
import { RunActivity, RunPipeline, SourceStream, lastEvent } from "@/components/run-pipeline";
import { useRunStream } from "@/lib/use-run-stream";
import type { Report, ReportSource, Verification } from "@/lib/types";
import { cn } from "@/lib/utils";

const PHASE_COPY: Record<string, string> = {
  connecting: "Connecting to the run…",
  live: "Research in progress",
  finished: "Run finished",
  lost: "Live stream lost — showing what was recorded",
};

export default function RunPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;
  const { events, phase, pct, snapshot, error } = useRunStream(jobId);

  const [showReport, setShowReport] = useState(false);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const startedAt = events[0]?.ts ?? null;
  const live = phase === "live" || phase === "connecting";

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [live]);

  const elapsed = startedAt ? Math.max(0, Math.round(now - startedAt)) : 0;

  const planEvent = lastEvent(events, "plan");
  const sources = (lastEvent(events, "sources")?.sources ?? []) as ReportSource[];
  const verification = lastEvent(events, "verification")?.verification as Verification | undefined;
  const doneEvent = lastEvent(events, "done");
  const runCompleted = lastEvent(events, "run_completed");
  const failed = error ?? (lastEvent(events, "error")?.message as string | undefined);

  const report = (doneEvent?.report ?? null) as Report | null;
  const briefId = (doneEvent?.brief_id ?? snapshot?.brief_id ?? "") as string;
  const query = (events.find((e) => e.type === "run_started")?.query ??
    snapshot?.events.find((e) => e.type === "run_started")?.query ??
    "") as string;
  const depth = (events.find((e) => e.type === "run_started")?.depth ??
    snapshot?.events.find((e) => e.type === "run_started")?.depth ??
    "standard") as string;

  const duration = Math.round(Number(doneEvent?.duration_s ?? runCompleted?.duration_s ?? elapsed));
  const cost = Number(doneEvent?.cost_usd ?? runCompleted?.cost_usd ?? 0);

  if (showReport && report) {
    return (
      <div>
        <div className="border-b border-line bg-surface/60 px-4 py-2.5 lg:px-8">
          <button
            onClick={() => setShowReport(false)}
            className="inline-flex items-center gap-1.5 text-xs text-ink-faint transition-colors hover:text-ink-soft focus-ring rounded"
          >
            <ArrowLeft className="size-3" />
            Back to the run
          </button>
        </div>
        <ReportReader report={report} reportId={briefId} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <Link
        href="/research"
        className="inline-flex items-center gap-1.5 text-xs text-ink-faint transition-colors hover:text-ink-soft focus-ring rounded"
      >
        <ArrowLeft className="size-3" />
        Research
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5",
              failed
                ? "border-danger/40 bg-danger/10 text-danger"
                : phase === "finished"
                  ? "border-positive/40 bg-positive/10 text-positive"
                  : "border-accent/40 bg-accent/10 text-accent-soft",
            )}
          >
            {live && <Loader2 className="size-3 animate-spin" />}
            {failed ? "Failed" : PHASE_COPY[phase]}
          </span>
          <span className="capitalize">{depth} depth</span>
          <span>{duration}s</span>
          {cost > 0 && <span>${cost.toFixed(4)}</span>}
          <span className="font-mono">{jobId}</span>
        </div>

        {query && (
          <h1 className="mt-3 text-lg font-semibold leading-snug tracking-tight">
            {query.split("\n")[0]}
          </h1>
        )}
        {planEvent?.plan?.title && (
          <p className="mt-1 text-xs text-ink-soft">Working title: {planEvent.plan.title}</p>
        )}
      </header>

      {/* Progress */}
      <div className="mt-5">
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-700 ease-out",
              failed ? "bg-danger" : phase === "finished" ? "bg-positive" : "bg-accent",
            )}
            style={{ width: `${failed ? 100 : Math.max(pct, 2)}%` }}
          />
        </div>
        <p className="mt-1.5 text-[11px] text-ink-faint">
          {failed ?? (doneEvent?.label ?? events[events.length - 1]?.label ?? PHASE_COPY[phase])}
        </p>
      </div>

      {failed && (
        <div className="card mt-5 border-danger/30 p-4">
          <p className="flex items-center gap-2 text-sm text-danger">
            <CircleSlash className="size-4" />
            The run stopped early
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">{failed}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-xs text-ink-soft transition-colors hover:text-ink focus-ring"
          >
            <RefreshCw className="size-3" />
            Reload
          </button>
        </div>
      )}

      {report && (
        <div className="card mt-5 border-positive/25 p-4">
          <p className="text-sm font-medium text-positive">Report ready</p>
          <p className="mt-1 text-xs leading-relaxed text-ink-soft">
            {report.title} · {report.reading_time_min} min read · {report.sources.length} sources
            {verification ? ` · ${verification.supported}/${verification.checked} claims verified` : ""}
          </p>
          {report.tldr.length > 0 && (
            <ul className="mt-2.5 flex flex-col gap-1">
              {report.tldr.slice(0, 3).map((point, i) => (
                <li key={i} className="text-xs leading-relaxed text-ink-soft">
                  · {point}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => setShowReport(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 focus-ring"
            >
              Read the full report
              <ArrowRight className="size-3.5" />
            </button>
            {briefId && (
              <Link
                href={`/reports/${briefId}`}
                className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-soft transition-colors hover:text-ink focus-ring"
              >
                <FileText className="size-3.5" />
                Open saved report
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="mt-5 flex flex-col gap-4">
        <RunPipeline events={events} phase={phase} />
        <SourceStream sources={sources} />
        <RunActivity events={events} />
      </div>
    </div>
  );
}
