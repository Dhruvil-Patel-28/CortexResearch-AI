"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Job } from "@/lib/types";

type Stage = { stage?: string; ingest?: { new?: number }; score?: { scored?: number } };

/**
 * Triggers a background ingest + score run and reports live progress while it
 * polls the job.
 */
export function RefreshButton({
  onDone,
  compact = false,
}: {
  onDone?: () => void;
  /** Icon-only variant for the narrow-viewport header. */
  compact?: boolean;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const busy = job?.status === "pending" || job?.status === "running";

  useEffect(() => {
    if (!busy || !job) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.job(job.id);
        setJob(next);
        if (next.status === "done" || next.status === "failed") {
          clearInterval(timer);
          onDone?.();
          setTimeout(() => setJob(null), 2500);
        }
      } catch {
        clearInterval(timer);
        setJob(null);
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [busy, job, onDone]);

  const start = async () => {
    try {
      setJob(await api.refresh({ ingest: true, score: true }));
    } catch {
      setJob(null);
    }
  };

  const progress = (job?.progress ?? {}) as Stage;
  const stage = progress.stage;
  const label = !job
    ? "Refresh feed"
    : job.status === "done"
      ? `+${progress.ingest?.new ?? 0} new · ${progress.score?.scored ?? 0} scored`
      : job.status === "failed"
        ? "Refresh failed"
        : stage?.startsWith("score")
          ? `Scoring… (${progress.score?.scored ?? 0})`
          : "Fetching sources…";

  if (compact) {
    return (
      <button
        onClick={start}
        disabled={busy}
        title={label}
        aria-label={label}
        className={cn(
          "grid size-9 shrink-0 place-items-center rounded-lg border transition-colors focus-ring",
          busy
            ? "border-line bg-surface-2 text-ink-faint"
            : "border-accent/40 bg-accent/15 text-accent-soft hover:bg-accent/25",
        )}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
      </button>
    );
  }

  return (
    <button
      onClick={start}
      disabled={busy}
      className={cn(
        "flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all focus-ring",
        busy
          ? "bg-surface-3 text-ink-faint"
          : "bg-gradient-to-b from-accent-soft to-accent text-shell shadow-[0_2px_12px_-4px] shadow-accent/50 hover:brightness-105 active:brightness-95",
      )}
    >
      {busy ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : (
        <RefreshCw className="size-3.5" />
      )}
      <span className="truncate">{label}</span>
    </button>
  );
}
