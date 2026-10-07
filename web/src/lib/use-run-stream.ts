"use client";

/**
 * Live run stream.
 *
 * The engine emits named SSE events (`stage`, `plan`, `tools`, `sources`,
 * `verification`, `done`, `error`), and EventSource only routes those to
 * per-type listeners — so we subscribe to each known type rather than relying
 * on `onmessage`.
 *
 * Reconnection is deliberate, not accidental: if the stream closes while the
 * run is still going (dev-server restart, laptop sleep), we reconnect with
 * backoff and the server replays the trace from the start.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, runStreamUrl } from "./api";
import type { RunEvent, RunSnapshot } from "./types";

const EVENT_TYPES = [
  "queued",
  "run_started",
  "stage",
  "plan",
  "subq",
  "tools",
  "sources",
  "verification",
  "run_completed",
  "done",
  "error",
  "closed",
] as const;

export type RunPhase = "connecting" | "live" | "finished" | "lost";

export interface RunStreamState {
  events: RunEvent[];
  phase: RunPhase;
  pct: number;
  snapshot: RunSnapshot | null;
  error: string | null;
}

const MAX_EVENTS = 300;

export function useRunStream(jobId: string | null, enabled = true) {
  const [state, setState] = useState<RunStreamState>({
    events: [],
    phase: "connecting",
    pct: 0,
    snapshot: null,
    error: null,
  });

  const eventsRef = useRef<RunEvent[]>([]);
  const attemptsRef = useRef(0);
  const closedRef = useRef(false);

  const push = useCallback((event: RunEvent) => {
    const last = eventsRef.current[eventsRef.current.length - 1];
    // The replay after a reconnect re-sends events we already hold; drop dupes.
    if (
      last &&
      last.type === event.type &&
      last.label === event.label &&
      last.pct === event.pct &&
      last.ts === event.ts
    ) {
      return;
    }
    const next = [...eventsRef.current, event];
    eventsRef.current = next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
    setState((prev) => ({
      ...prev,
      events: eventsRef.current,
      pct: Math.max(prev.pct, typeof event.pct === "number" ? event.pct : 0),
      error: event.type === "error" ? (event.message ?? event.label ?? "Run failed") : prev.error,
    }));
  }, []);

  const refreshSnapshot = useCallback(async () => {
    if (!jobId) return;
    try {
      const snapshot = await api.run(jobId);
      setState((prev) => ({
        ...prev,
        snapshot,
        pct: Math.max(prev.pct, snapshot.pct),
        // A stored snapshot may hold events from a previous process.
        events: prev.events.length ? prev.events : snapshot.events,
      }));
      return snapshot;
    } catch {
      return null;
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId || !enabled) return;

    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const settle = async () => {
      const snapshot = await refreshSnapshot();
      if (disposed) return;
      const finished = snapshot?.status === "done" || snapshot?.status === "error";
      setState((prev) => ({ ...prev, phase: finished ? "finished" : "lost" }));
    };

    const connect = () => {
      if (disposed) return;
      source = new EventSource(runStreamUrl(jobId));

      source.onopen = () => {
        attemptsRef.current = 0;
        setState((prev) => ({ ...prev, phase: prev.phase === "finished" ? prev.phase : "live" }));
      };

      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (raw) => {
          let payload: RunEvent;
          try {
            payload = JSON.parse((raw as MessageEvent).data) as RunEvent;
          } catch {
            return;
          }
          push(payload);

          if (payload.type === "done") {
            closedRef.current = true;
            setState((prev) => ({ ...prev, phase: "finished", pct: 100 }));
            source?.close();
            void refreshSnapshot();
          } else if (payload.type === "error") {
            closedRef.current = true;
            setState((prev) => ({ ...prev, phase: "finished" }));
            source?.close();
            void refreshSnapshot();
          } else if (payload.type === "closed") {
            closedRef.current = true;
            source?.close();
            void settle();
          }
        });
      }

      source.onerror = () => {
        source?.close();
        if (disposed || closedRef.current) return;
        attemptsRef.current += 1;
        if (attemptsRef.current > 4) {
          void settle();
          return;
        }
        setState((prev) => ({ ...prev, phase: "connecting" }));
        retry = setTimeout(connect, Math.min(1000 * attemptsRef.current, 5000));
      };
    };

    // The stream replays the stored trace on connect, so the initial state
    // comes from the events themselves — the API is only consulted when the
    // stream reports that the run is no longer live.
    connect();

    return () => {
      disposed = true;
      if (retry) clearTimeout(retry);
      source?.close();
    };
  }, [jobId, enabled, push, refreshSnapshot]);

  return state;
}
