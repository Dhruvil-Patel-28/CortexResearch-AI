import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** "3h ago", "2d ago" — compact relative time for feed metadata. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);

  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

export function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Relevance 0-10 → colour + label used by the score ring/chip. */
export function scoreTone(score: number | null | undefined) {
  if (score === null || score === undefined) {
    return { text: "text-ink-faint", ring: "var(--color-line-strong)", label: "unscored" };
  }
  if (score >= 8.5) return { text: "text-positive", ring: "var(--color-positive)", label: "must read" };
  if (score >= 7) return { text: "text-accent-soft", ring: "var(--color-accent)", label: "relevant" };
  if (score >= 5) return { text: "text-warning", ring: "var(--color-warning)", label: "worth a look" };
  return { text: "text-ink-faint", ring: "var(--color-line-strong)", label: "low signal" };
}

export const SOURCE_META: Record<string, { label: string; short: string; tone: string }> = {
  hackernews: { label: "Hacker News", short: "HN", tone: "#ff8b3d" },
  arxiv: { label: "arXiv", short: "arXiv", tone: "#e2554f" },
  rss: { label: "Blogs & RSS", short: "RSS", tone: "#4fa8e2" },
  reddit: { label: "Reddit", short: "Reddit", tone: "#f2555a" },
  github: { label: "GitHub", short: "GitHub", tone: "#a99cff" },
  producthunt: { label: "Product Hunt", short: "PH", tone: "#da552f" },
};

export function sourceLabel(key: string): string {
  return SOURCE_META[key]?.label ?? key;
}

export function pluck<T>(arr: T[] | undefined | null, key: keyof T): string {
  return (arr ?? []).map((v) => String(v[key])).join(", ");
}
