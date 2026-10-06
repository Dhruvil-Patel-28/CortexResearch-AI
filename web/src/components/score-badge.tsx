import { cn, scoreTone } from "@/lib/utils";

/** Circular relevance indicator (0-10) with a tone derived from the score. */
export function ScoreBadge({ score, size = "md" }: { score: number | null; size?: "sm" | "md" | "lg" }) {
  const tone = scoreTone(score);
  const dimension = size === "lg" ? "size-14" : size === "sm" ? "size-8" : "size-10";
  const font = size === "lg" ? "text-lg" : size === "sm" ? "text-[11px]" : "text-sm";

  const value = score ?? null;
  const pct = value === null ? 0 : Math.min(100, (value / 10) * 100);

  return (
    <div
      className={cn("relative grid shrink-0 place-items-center rounded-full", dimension)}
      style={{
        background: `conic-gradient(${tone.ring} ${pct}%, var(--color-surface-3) ${pct}% 100%)`,
      }}
      title={value === null ? "Not scored yet" : `${value.toFixed(1)} / 10 — ${tone.label}`}
    >
      <div className="absolute inset-[2px] rounded-full bg-surface" />
      <span className={cn("relative font-semibold tabular-nums", font, tone.text)}>
        {value === null ? "–" : value.toFixed(1)}
      </span>
    </div>
  );
}
