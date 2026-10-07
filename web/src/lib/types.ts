/** Types mirroring the FastAPI contracts in api/routes/watch.py. */

export type SourceKey =
  | "hackernews"
  | "arxiv"
  | "rss"
  | "reddit"
  | "github"
  | "producthunt";

export interface Item {
  id: string;
  source: SourceKey | string;
  source_label: string;
  title: string;
  url: string;
  author: string;
  published_at: string;
  first_seen_at: string;
  raw_text: string;
  metrics: Record<string, string | number | string[] | null>;
  relevance: number | null;
  rationale: string;
  tags: string[];
  bookmarked: boolean;
  cluster_key: string;
  cluster_size: number;
  cluster_sources: string[];
}

export interface FeedResponse {
  items: Item[];
  count: number;
  total: number;
  stats: Stats;
}

export interface Stats {
  total_items: number;
  by_source: Record<string, number>;
  scored_items: number;
  bookmarks: number;
  last_ingest_at: string | null;
  sources?: SourceInfo[];
}

export interface SourceInfo {
  key: string;
  label: string;
  enabled: boolean;
  items: number;
}

export interface ItemDetail {
  item: Item;
  also_covered_by: Item[];
}

export interface Profile {
  name: string;
  interests: string[];
  stack: string[];
  goals: string[];
  boost: string[];
  mute: string[];
  arxiv_keywords: string[];
  version: string;
}

export interface Job {
  id: string;
  kind: string;
  status: "pending" | "running" | "done" | "failed";
  progress: Record<string, unknown>;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface FeedParams {
  source?: string;
  window?: "today" | "week" | "month" | "all";
  min_score?: number;
  q?: string;
  bookmarked?: boolean;
  order?: "newest" | "relevance";
  limit?: number;
  offset?: number;
}

/* ── Deep research (mirrors api/routes/research.py + schemas/report.py) ── */

export type Depth = "brief" | "standard" | "deep";
export type Confidence = "high" | "medium" | "low";

export interface ReportSource {
  id: string;
  title: string;
  url: string;
  kind: string;
  published_at: string | null;
  quote: string;
}

export interface KeyDevelopment {
  claim: string;
  evidence: string;
  sources: string[];
  confidence: Confidence;
}

export interface TimelineEntry {
  when: string;
  what: string;
  source_id: string | null;
}

export interface ComparisonTable {
  columns: string[];
  rows: string[][];
}

export interface FaqItem {
  question: string;
  answer: string;
}

export interface GlossaryTerm {
  term: string;
  definition: string;
}

export interface UnsupportedClaim {
  claim: string;
  reason: string;
  action: "flagged" | "softened" | "removed";
}

export interface Verification {
  checked: number;
  supported: number;
  unsupported: number;
  unsupported_claims: UnsupportedClaim[];
  notes: string;
}

export interface ModelCall {
  model: string;
  label: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface Report {
  query: string;
  title: string;
  depth: Depth;
  tldr: string[];
  executive_summary: string;
  background_primer: string;
  key_developments: KeyDevelopment[];
  technical_explainer: string;
  timeline: TimelineEntry[];
  comparison_table: ComparisonTable | null;
  implications: string;
  risks_and_uncertainty: string;
  what_to_watch_next: string[];
  faq: FaqItem[];
  glossary: GlossaryTerm[];
  open_questions: string[];
  sources: ReportSource[];
  verification: Verification;
  reading_time_min: number;
  model_trace: ModelCall[];
  cost_usd: number;
  created_at: string;
}

export interface VerificationSummary {
  checked: number;
  supported: number;
  unsupported: number;
}

export interface ReportSummary {
  id: string;
  query: string;
  status: "running" | "done" | "error" | string;
  item_id: string | null;
  title: string;
  tldr: string[];
  depth: Depth;
  reading_time_min: number;
  source_count: number;
  verification: VerificationSummary;
  cost_usd: number;
  created_at: string;
  finished_at: string | null;
}

export interface ReportDetail {
  id: string;
  query: string;
  status: string;
  item_id: string | null;
  created_at: string;
  finished_at: string | null;
  report: Report | Record<string, never>;
  markdown: string;
}

export interface RunStarted {
  job_id: string;
  brief_id: string;
  status: string;
}

/** One streaming event from the pipeline (SSE). */
export interface RunEvent {
  type: string;
  job_id?: string;
  ts?: number;
  label?: string;
  pct?: number;
  stage?: string;
  plan?: {
    title?: string;
    scope?: string;
    sub_questions?: { question: string; why?: string; search_queries?: string[] }[];
  };
  sources?: ReportSource[];
  verification?: Verification;
  report?: Report;
  brief_id?: string | null;
  count?: number;
  duration_s?: number;
  cost_usd?: number;
  message?: string;
  [key: string]: unknown;
}

export interface RunSnapshot {
  job_id: string;
  kind: string;
  status: "pending" | "running" | "done" | "error" | string;
  brief_id: string | null;
  pct: number;
  events: RunEvent[];
}

/* ── Digests ── */

export interface DigestSummary {
  id: string;
  created_at: string;
  story_count: number;
  delivered: string[];
  preview: string;
}

export interface DigestDetail {
  id: string;
  created_at: string;
  item_ids: string[];
  delivered: string[];
  markdown: string;
}

export interface DigestDelta {
  new_clusters: number;
  reheated: { title: string; url: string; gained_sources: number; score_gain: number }[];
  previously_covered: number;
}

export interface DigestPreview {
  markdown: string;
  story_count: number;
  delta: DigestDelta;
  since: string;
}

export interface DeltaStarted {
  job_id: string;
  brief_id: string;
  query: string;
}

/* ── Library search (/search) ── */

export interface SearchHit {
  ref_id: string;
  kind: "item" | "brief" | string;
  title: string;
  url: string;
  snippet: string;
  source: string;
  published_at: string;
  score: number;
  relevance: number | null;
  brief_id: string | null;
}

export interface GraphAnswer {
  available: boolean;
  answer: string;
  reason: string;
}

export interface MemoryHit {
  text: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchHit[];
  graph: GraphAnswer | null;
  memory: MemoryHit[];
  flags: { graph_rag: boolean; supermemory: boolean };
}
