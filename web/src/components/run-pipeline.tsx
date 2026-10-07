"use client";

/**
 * Live pipeline view.
 *
 * Renders the run from its event trace rather than from a timer, so what the
 * user sees is what the agents actually did: the plan they produced, how many
 * sources each channel returned, which pages were read in full, and the
 * claim-level verification result.
 */

import { Check, Circle, Loader2, Network, Radio, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReportSource, RunEvent, Verification } from "@/lib/types";
import { cn, hostOf } from "@/lib/utils";

interface Step {
  key: string;
  label: string;
  detail?: string;
  items?: string[];
  lanes?: Lane[];
  state: "pending" | "active" | "done" | "failed";
}

/** Live progress of one parallel sub-question retrieval thread. */
interface Lane {
  index: number;
  question: string;
  done: number;
  tasks: number;
  /** Retrieval channel of the most recently finished task ("store"|"rag"|"web"). */
  lastKind?: string;
}

/** Fold every `subq` event into the latest state per sub-question. */
function subqLanes(events: RunEvent[]): Lane[] {
  const byIndex = new Map<number, Lane>();
  for (const e of events) {
    if (e.type !== "subq" || typeof e.index !== "number") continue;
    byIndex.set(e.index, {
      index: e.index,
      question: e.question ?? "",
      done: e.done ?? 0,
      tasks: e.tasks ?? 0,
      lastKind: e.kind ?? byIndex.get(e.index)?.lastKind,
    });
  }
  return [...byIndex.values()].sort((a, b) => a.index - b.index);
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
  const gathering = [...events].reverse().find((e) => e.stage === "gathering");
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
  const lanes = subqLanes(events);

  // S1/S2 routing summary for the Verifier step: how many claim checks the
  // reflex handled vs escalated to the chat tier, and which backend served them.
  const routeEvents = events.filter((e) => e.type === "route" && e.task === "claim_support");
  const escalations = routeEvents.filter((e) => e.escalated).length;
  const s1Backends = [...new Set(routeEvents.filter((e) => !e.escalated).map((e) => e.backend))].filter(Boolean);
  const routingSuffix = routeEvents.length
    ? `S1 reflex${s1Backends.length ? ` (${s1Backends.join(", ")})` : ""} · ${escalations} escalation${escalations === 1 ? "" : "s"}`
    : undefined;

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
        : gathering?.label ??
          (currentStage === "gathering" ? "Running parallel retrieval threads…" : undefined),
      lanes: lanes.length > 0 ? lanes : undefined,
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
      detail: [verification?.label, routingSuffix].filter(Boolean).join(" — ") || undefined,
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

/** Source channels the researcher fans out to, in graph bottom-row order. */
const GRAPH_CHANNELS = [
  { key: "store", label: "Radar store", countKey: "radar_store", x: 20 },
  { key: "rag", label: "Knowledge base", countKey: "knowledge_base", x: 50 },
  { key: "web", label: "Web search", countKey: "web_search", x: 80 },
] as const;

/**
 * Live retrieval graph: planner node fanning out to one node per
 * sub-question, each reaching down to the three source channels. Edges flow
 * (animated dashes) while that thread is still working, so the parallel
 * fan-out is something you watch, not something you are told about.
 */
function ResearchGraph({ lanes, tools, live }: { lanes: Lane[]; tools?: RunEvent; live: boolean }) {
  if (lanes.length === 0) return null;

  const n = lanes.length;
  const subqX = (i: number) => ((i + 1) * 100) / (n + 1);
  const PLANNER = { x: 50, y: 7 };
  const SQ_Y = 26;
  const CH_Y = 45;
  const R = 2.2;

  const channelCounts = Object.fromEntries(
    GRAPH_CHANNELS.map((c) => {
      const v = tools?.[c.countKey];
      return [c.key, typeof v === "number" ? v : null];
    }),
  ) as Record<string, number | null>;
  const gatheringDone = GRAPH_CHANNELS.every((c) => channelCounts[c.key] !== null);

  const laneActive = (lane: Lane) => live && lane.done < lane.tasks;
  const channelHot = (key: string) =>
    live && !gatheringDone && lanes.some((l) => l.done < l.tasks && l.lastKind === key);

  const plannerColor = "var(--color-positive)";
  const sqColor = (lane: Lane) =>
    lane.done >= lane.tasks
      ? "var(--color-positive)"
      : laneActive(lane)
        ? "var(--color-accent-soft)"
        : "var(--color-ink-faint)";

  return (
    <svg
      viewBox="0 0 100 54"
      className="mt-2.5 w-full"
      role="img"
      aria-label="Live retrieval graph: planner fanning out to sub-questions and source channels"
    >
      {/* planner → sub-question edges */}
      {lanes.map((lane) => {
        const x = subqX(lanes.indexOf(lane));
        const active = laneActive(lane);
        return (
          <line
            key={`p${lane.index}`}
            x1={PLANNER.x}
            y1={PLANNER.y + R}
            x2={x}
            y2={SQ_Y - R}
            stroke={active ? "var(--color-accent-soft)" : "var(--color-line-strong)"}
            strokeWidth={active ? 0.45 : 0.3}
            className={active ? "edge-flow" : undefined}
            opacity={active ? 0.9 : 0.5}
          />
        );
      })}

      {/* sub-question → channel edges */}
      {lanes.map((lane) =>
        GRAPH_CHANNELS.map((ch) => {
          const x = subqX(lanes.indexOf(lane));
          const hot = channelHot(ch.key);
          return (
            <line
              key={`s${lane.index}-${ch.key}`}
              x1={x}
              y1={SQ_Y + R}
              x2={ch.x}
              y2={CH_Y - 3}
              stroke={hot ? "var(--color-accent-soft)" : "var(--color-line-strong)"}
              strokeWidth={hot ? 0.4 : 0.22}
              className={hot ? "edge-flow" : undefined}
              opacity={hot ? 0.85 : lane.done >= lane.tasks ? 0.35 : 0.15}
            />
          );
        }),
      )}

      {/* planner node */}
      <circle cx={PLANNER.x} cy={PLANNER.y} r={R} fill="var(--color-surface-3)" stroke={plannerColor} strokeWidth={0.4} />
      <path
        d={`M ${PLANNER.x - 0.9} ${PLANNER.y} l 0.6 0.7 l 1.2 -1.4`}
        fill="none"
        stroke={plannerColor}
        strokeWidth={0.35}
        strokeLinecap="round"
      />
      <text x={PLANNER.x} y={PLANNER.y - R - 1} textAnchor="middle" fontSize={2.4} fill="var(--color-ink-soft)">
        Planner
      </text>

      {/* sub-question nodes */}
      {lanes.map((lane) => {
        const x = subqX(lanes.indexOf(lane));
        const active = laneActive(lane);
        const done = lane.done >= lane.tasks;
        return (
          <g key={`sq${lane.index}`}>
            {active && (
              <circle cx={x} cy={SQ_Y} r={R + 1.1} fill="none" stroke="var(--color-accent-soft)" strokeWidth={0.25} className="node-pulse" />
            )}
            <circle cx={x} cy={SQ_Y} r={R} fill="var(--color-surface-3)" stroke={sqColor(lane)} strokeWidth={0.4} />
            <text x={x} y={SQ_Y - R - 1.1} textAnchor="middle" fontSize={2.2} fill={done ? "var(--color-positive)" : "var(--color-ink-soft)"}>
              SQ{lane.index + 1}
            </text>
            <text x={x} y={SQ_Y + R + 2.8} textAnchor="middle" fontSize={2} className="font-mono" fill={done ? "var(--color-positive)" : "var(--color-ink-faint)"}>
              {lane.done}/{lane.tasks}
            </text>
            <title>{lane.question}</title>
          </g>
        );
      })}

      {/* channel nodes */}
      {GRAPH_CHANNELS.map((ch) => {
        const hot = channelHot(ch.key);
        const count = channelCounts[ch.key];
        const complete = count !== null;
        return (
          <g key={ch.key}>
            <rect
              x={ch.x - 11}
              y={CH_Y - 3}
              width={22}
              height={6}
              rx={1.6}
              fill="var(--color-surface-3)"
              stroke={hot ? "var(--color-accent-soft)" : complete ? "var(--color-positive)" : "var(--color-line-strong)"}
              strokeWidth={hot ? 0.4 : 0.3}
              className={hot ? "node-pulse" : undefined}
            />
            <text x={ch.x} y={CH_Y - 0.4} textAnchor="middle" fontSize={2.2} fill={complete ? "var(--color-ink)" : "var(--color-ink-soft)"}>
              {ch.label}
            </text>
            <text x={ch.x} y={CH_Y + 2.4} textAnchor="middle" fontSize={1.9} className="font-mono" fill={complete ? "var(--color-positive)" : "var(--color-ink-faint)"}>
              {complete ? `${count} hits` : "searching…"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function LaneRow({ lane, running }: { lane: Lane; running: boolean }) {
  const complete = lane.done >= lane.tasks;
  const pct = Math.round((lane.done / Math.max(lane.tasks, 1)) * 100);
  return (
    <div className="flex items-center gap-2">
      {complete ? (
        <Check className="size-3 shrink-0 text-positive" />
      ) : running ? (
        <Loader2 className="size-3 shrink-0 animate-spin text-accent-soft" />
      ) : (
        <Circle className="size-3 shrink-0 text-line-strong" />
      )}
      <span
        className={cn(
          "min-w-0 flex-1 truncate text-xs",
          complete ? "text-ink-soft" : "text-ink",
        )}
        title={lane.question}
      >
        {lane.question}
      </span>
      <span className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-line">
        <span
          className={cn(
            "block h-full rounded-full transition-all duration-500",
            complete ? "bg-positive/70" : "bg-accent-soft",
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="w-8 shrink-0 text-right font-mono text-[10px] text-ink-faint">
        {lane.done}/{lane.tasks}
      </span>
    </div>
  );
}

/** Latest per-source hit counts, from the most recent `subq` event carrying one. */
function foundSources(events: RunEvent[]): Record<string, number> {
  const last = [...events].reverse().find((e) => e.type === "subq" && e.found);
  return (last?.found as Record<string, number>) ?? {};
}

/** Compact pills showing what the fan-out actually brought back, live. */
function SourcePills({ found }: { found: Record<string, number> }) {
  const entries = Object.entries(found).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-ink-faint">Pulled from</span>
      {entries.map(([label, count]) => (
        <span
          key={`${label}-${count}`}
          className="rise-in inline-flex items-center gap-1 rounded-full border border-line bg-surface-3 px-2 py-0.5 text-[10px] text-ink-soft"
        >
          {label}
          <span className="font-mono text-[9px] text-accent-soft">{count}</span>
        </span>
      ))}
    </div>
  );
}

export function RunPipeline({ events, phase }: { events: RunEvent[]; phase: string }) {
  const steps = buildSteps(events, phase);
  const plan = lastEvent(events, "plan");
  const verification = lastEvent(events, "verification")?.verification as Verification | undefined;
  const live = phase === "live" || phase === "connecting";
  const toolsEvent = lastEvent(events, "tools");

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
                {step.lanes && step.lanes.length > 0 && (
                  <div className="mt-2.5 flex flex-col gap-2 rounded-lg border border-line bg-surface-2/60 p-2.5">
                    <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
                      <Network className="size-3" />
                      {live && step.state === "active" ? "Live retrieval graph" : "Retrieval graph"}
                    </p>
                    <ResearchGraph lanes={step.lanes} tools={toolsEvent} live={live} />
                    <SourcePills found={foundSources(events)} />
                    {step.lanes.map((lane) => (
                      <LaneRow key={lane.index} lane={lane} running={step.state === "active"} />
                    ))}
                  </div>
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
