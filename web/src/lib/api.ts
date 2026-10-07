/**
 * Typed API client.
 *
 * All calls go through /api/*, which next.config.ts rewrites to the FastAPI
 * engine — so there is no CORS surface and no API URL in client code.
 */

import type {
  DeltaStarted,
  Depth,
  DigestDetail,
  DigestPreview,
  DigestSummary,
  FeedParams,
  FeedResponse,
  Item,
  ItemDetail,
  Job,
  Profile,
  ReportDetail,
  ReportSummary,
  RunSnapshot,
  RunStarted,
  Stats,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }

  return (await res.json()) as T;
}

function query(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  feed: (params: FeedParams = {}) =>
    request<FeedResponse>(`/watch/feed${query({ ...params } as Record<string, unknown>)}`),

  stats: () => request<Stats>("/watch/stats"),

  item: (id: string) => request<ItemDetail>(`/watch/items/${id}`),

  bookmark: (id: string, note = "") =>
    request<Item>(`/watch/items/${id}/bookmark`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),

  unbookmark: (id: string) =>
    request<Item>(`/watch/items/${id}/bookmark`, { method: "DELETE" }),

  profile: () => request<Profile>("/watch/profile"),

  saveProfile: (profile: Omit<Profile, "version">) =>
    request<Profile>("/watch/profile", { method: "PUT", body: JSON.stringify(profile) }),

  refresh: (body: { ingest?: boolean; score?: boolean; sources?: string[] } = {}) =>
    request<Job>("/watch/refresh", { method: "POST", body: JSON.stringify(body) }),

  job: (id: string) => request<Job>(`/watch/jobs/${id}`),

  /* ── Deep research ── */

  startResearch: (body: { query: string; depth?: Depth; item_id?: string | null }) =>
    request<RunStarted>("/research/start", { method: "POST", body: JSON.stringify(body) }),

  itemBrief: (itemId: string, depth: Depth = "standard") =>
    request<RunStarted>(`/research/items/${itemId}/brief${query({ depth })}`, { method: "POST" }),

  run: (jobId: string) => request<RunSnapshot>(`/research/jobs/${jobId}`),

  reports: (params: { limit?: number; item_id?: string } = {}) =>
    request<ReportSummary[]>(`/research/reports${query({ ...params } as Record<string, unknown>)}`),

  report: (id: string) => request<ReportDetail>(`/research/reports/${id}`),

  deleteReport: (id: string) =>
    request<{ deleted: string }>(`/research/reports/${id}`, { method: "DELETE" }),

  health: () => request<{ status: string; version: string }>("/health"),
};

/** URL for SSE streams (EventSource cannot send custom headers). */
export const streamUrl = (path: string) => `${BASE}${path}`;

export const runStreamUrl = (jobId: string) => streamUrl(`/research/jobs/${jobId}/stream`);

/** Download URL for a saved report (browser handles the save dialog). */
export const exportUrl = (id: string, format: "md" | "json" = "md") =>
  `${BASE}/research/reports/${id}/export?format=${format}`;

/* Digest endpoints (appended — kept separate from the core client for review clarity). */
export const digestsApi = {
  list: () => request<DigestSummary[]>("/digests"),

  get: (id: string) => request<DigestDetail>(`/digests/${id}`),

  preview: (params: { window_hours?: number; min_score?: number } = {}) =>
    request<DigestPreview>(`/digests/preview${query(params as Record<string, unknown>)}`, {
      method: "GET",
    }),

  run: () => request<DigestSummary>("/digests/run", { method: "POST" }),

  deltaBrief: (topic: string, since?: string) =>
    request<DeltaStarted>("/digests/delta", {
      method: "POST",
      body: JSON.stringify({ topic, since: since ?? null }),
    }),
};
