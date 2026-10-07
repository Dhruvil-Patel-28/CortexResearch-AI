"use client";

/**
 * Live pipeline view.
 *
 * Renders the run from its event trace rather than from a timer, so what the
 * user sees is what the agents actually did: the plan they produced, how many
 * sources each channel returned, which pages were read in full, and the
 * claim-level verification result.
 */

import { Check, Circle, Loader2, Radio, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReportSource, RunEvent, Verification } from "@/lib/types";
import { cn, hostOf } from "@/lib/utils";

interface Step {
  key: string;
  label: string;
  detail?: string;
  items?: string[];
  state: "pending" | "active" | "done" | "failed";
}

const STAGE_LABELS: Record<string, string> = {
  starting: "Starting the team",
  planning: "Planning the research",
  gathering: "Searching the sources",
  reading: "Reading pages in full",
  gap_fill: "Filling a coverage gap",
  writing: "Writing the report",
  written: "Draft complete",
  verifying: "Verifying every claim",
  revising: "Repairing unsupported claims",
  verified: "Verification complete",
};

function lastEvent(events: RunEvent[], type: string): RunEvent | undefined {
  return [...events].reverse().find((e) => e.type === type);
}

function eventsOf(events: RunEvent[], type: string): RunEvent[] {
  return events.filter((e) => e.type === type);
}

function buildSteps(events: RunEvent[], phase: string): Step[] {
  const plan = lastEvent(events, "plan");
  const tools = lastEvent(events, "tools");
  const reading = [...events].reverse().find((e) => e.stage === "reading");
  const written = [...events].reverse().find((e) => e.stage === "written");
  const verification = lastEvent(events, "verification");
  const revised = [...events].reverse().find((e) => e.stage === "revising");
  const done = lastEvent(events, "done");
  const failed = lastEvent(events, "error");

  const stageOrder = ["planning", "gathering", "reading", "writing", "verifying", "revising"];
  const currentStage = [...events].reverse().find((e) => e.stage)?.stage ?? "starting";
  const currentIndex = stageOrder.indexOf(currentStage);
  const isOver = phase === "finished";

  /** A step is done once a later stage has started; active while it is current. */
  const stateFor = (index: number, evidence: unknown): Step["state"] => {
    if (failed && index === Math.max(currentIndex, 0)) return "failed";
    if (evidence) return "done";
    if (isOver) return "done";
    if (currentIndex === -1) return index === 0 ? "active" : "pending";
    if (index < currentIndex) return "done";
    if (index === currentIndex) return "active";
    return "pending";
  };

  const subQuestions = plan?.plan?.sub_questions ?? [];

  return [
    {
      key: "planner",
      label: "Planner",
      detail: plan?.label ?? (currentStage === "planning" ? "Decomposing the question…" : undefined),
      items: subQuestions.map((q) => q.question).filter(Boolean),
      state: stateFor(0, plan),
    },
    {
      key: "researcher",
      label: "Researcher",
      detail: tools
        ? `${tools.radar_store ?? 0} radar items · ${tools.knowledge_base ?? 0} knowledge-base chunks · ${tools.web_search ?? 0} web hits`
        : undefined,
      state: stateFor(1, tools),
    },
    {
      key: "reader",
      label: "Page reader",
      detail: reading?.label,
      state: stateFor(2, reading),
    },
    {
      key: "writer",
      label: "Writer",
      detail: written?.label ?? (currentStage === "writing" ? "Drafting the report…" : undefined),
      state: stateFor(3, written),
    },
    {
      key: "verifier",
      label: "Verifier",
      detail: verification?.label,
      state: stateFor(4, verification),
    },
    {
      key: "reviser",
      label: "Reviser",
      detail: revised?.label ?? (done ? "No revision needed" : undefined),
      state: revised ? "done" : currentStage === "revising" ? "active" : done || isOver ? "done" : "pending",
    },
  ];
}

function StepIcon({ state }: { state: Step["state"] }) {
  if (state === "done") return <Check className="size-3.5 text-positive" />;
  if (state === "active") return <Loader2 className="size-3.5 animate-spin text-accent-soft" />;
  if (state === "failed") return <TriangleAlert className="size-3.5 text-danger" />;
  return <Circle className="size-3 text-line-strong" />;
}

export function RunPipeline({ events, phase }: { events: RunEvent[]; phase: string }) {
  const steps = buildSteps(events, phase);
  const plan = lastEvent(events, "plan");
  const verification = lastEvent(events, "verification")?.verification as Verification | undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-4">
        <ol className="flex flex-col">
          {steps.map((step, i) => (
            <li key={step.key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className="mt-0.5 grid size-5 place-items-center rounded-full border border-line bg-surface-2">
                  <StepIcon state={step.state} />
                </span>
                {i < steps.length - 1 && (
                  <span
                    className={cn(
                      "my-1 w-px flex-1",
                      step.state === "done" ? "bg-positive/30" : "bg-line",
                    )}
                  />
                )}
              </div>
              <div className="min-w-0 flex-1 pb-4">
                <p
                  className={cn(
                    "text-sm font-medium",
                    step.state === "pending" ? "text-ink-faint" : "text-ink",
                  )}
                >
                  {step.label}
                </p>
                {step.detail && (
                  <p className="mt-0.5 text-xs leading-relaxed text-ink-soft">{step.detail}</p>
                )}
                {step.items && step.items.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1 border-l border-line pl-3">
                    {step.items.map((q, qi) => (
                      <li key={qi} className="text-xs leading-relaxed text-ink-faint">
                        {q}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>

      {plan?.plan?.scope && (
        <div className="card p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Scope</p>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">{plan.plan.scope}</p>
        </div>
      )}

      {verification && <VerificationPanel verification={verification} />}
    </div>
  );
}

export function VerificationPanel({ verification }: { verification: Verification }) {
  const { checked, supported, unsupported, unsupported_claims, notes } = verification;
  const tone = unsupported === 0 ? "text-positive" : unsupported / Math.max(checked, 1) > 0.3 ? "text-danger" : "text-warning";

  return (
    <div className="card p-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className={cn("size-4", tone)} />
        <p className="text-sm font-medium">
          <span className={tone}>{supported}</span>
          <span className="text-ink-faint">/{checked} claims supported by their cited sources</span>
        </p>
      </div>
      {notes && <p className="mt-2 text-xs leading-relaxed text-ink-soft">{notes}</p>}
      {unsupported_claims.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {unsupported_claims.map((claim, i) => (
            <li key={i} className="rounded-lg border border-warning/25 bg-warning/8 p-2.5">
              <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-warning">
                {claim.action === "removed" ? "Removed after review" : "Flagged"}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-ink-soft">{claim.claim}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">{claim.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SourceStream({ sources }: { sources: ReportSource[] }) {
  if (sources.length === 0) return null;

  return (
    <div className="card p-4">
      <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        <Search className="size-3" />
        Evidence gathered ({sources.length})
      </p>
      <ul className="mt-2.5 flex flex-col gap-1">
        {sources.map((s) => (
          <li key={s.id} className="flex items-baseline gap-2 text-xs">
            <span className="shrink-0 font-mono text-[10px] text-ink-faint">{s.id}</span>
            {s.url ? (
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer noopener"
                className="truncate text-ink-soft transition-colors hover:text-ink hover:underline"
              >
                {s.title}
              </a>
            ) : (
              <span className="truncate text-ink-soft">{s.title}</span>
            )}
            <span className="ml-auto shrink-0 text-[10px] text-ink-faint">
              {hostOf(s.url) || s.kind}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One-line event feed, so the run never looks stalled while a model thinks. */
export function RunActivity({ events }: { events: RunEvent[] }) {
  const lines = events
    .filter((e) => e.label || e.type === "run_started")
    .slice(-6)
    .reverse();

  if (lines.length === 0) return null;

  return (
    <div className="card p-4">
      <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        <Radio className="size-3" />
        Activity
      </p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {lines.map((e, i) => (
          <li key={i} className="flex items-baseline gap-2 text-xs">
            <span className="text-ink-faint">{STAGE_LABELS[e.stage ?? ""] ?? e.type}</span>
            <span className="truncate text-ink-soft">{e.label}</span>
            {typeof e.pct === "number" && e.pct > 0 && (
              <span className="ml-auto shrink-0 font-mono text-[10px] text-ink-faint">{e.pct}%</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export { eventsOf, lastEvent };
export const STAGE_LABEL_MAP = STAGE_LABELS;
