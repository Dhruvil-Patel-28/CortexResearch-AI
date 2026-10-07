"use client";

/**
 * The report reader — a calm, light editorial surface.
 *
 * Every section of Report Schema v2 gets an explicit treatment: citations
 * become inline links to the source list, confidence becomes a badge, the
 * verification verdict is shown rather than hidden, and the reading controls
 * (TOC, export, copy) sit beside the article instead of on top of it.
 */

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Check,
  Clipboard,
  Copy,
  Download,
  Gauge,
  HelpCircle,
  ListOrdered,
  Sparkles,
  Table2,
} from "lucide-react";
import type { Confidence, Report, ReportSource } from "@/lib/types";
import { cn } from "@/lib/utils";

const CONFIDENCE_META: Record<Confidence, { label: string; className: string }> = {
  high: { label: "High confidence", className: "border-positive/30 bg-positive/10 text-positive" },
  medium: { label: "Medium confidence", className: "border-warning/30 bg-warning/10 text-warning" },
  low: { label: "Low confidence", className: "border-danger/30 bg-danger/10 text-danger" },
};

interface Section {
  id: string;
  label: string;
}

function sectionsOf(report: Report): Section[] {
  const out: Section[] = [];
  if (report.tldr.length) out.push({ id: "tldr", label: "TL;DR" });
  if (report.executive_summary) out.push({ id: "summary", label: "Executive summary" });
  if (report.background_primer) out.push({ id: "background", label: "Background primer" });
  if (report.key_developments.length) out.push({ id: "developments", label: "Key developments" });
  if (report.technical_explainer) out.push({ id: "technical", label: "How it works" });
  if (report.timeline.length) out.push({ id: "timeline", label: "Timeline" });
  if (report.comparison_table?.columns.length) out.push({ id: "comparison", label: "Comparison" });
  if (report.implications) out.push({ id: "implications", label: "Why this matters" });
  if (report.risks_and_uncertainty) out.push({ id: "risks", label: "Risks & uncertainty" });
  if (report.what_to_watch_next.length) out.push({ id: "watch", label: "What to watch next" });
  if (report.faq.length) out.push({ id: "faq", label: "FAQ" });
  if (report.glossary.length) out.push({ id: "glossary", label: "Glossary" });
  if (report.open_questions.length) out.push({ id: "open", label: "Open questions" });
  if (report.sources.length) out.push({ id: "sources", label: "Sources" });
  out.push({ id: "verification", label: "Verification" });
  return out;
}

function Paragraphs({ text, className }: { text: string; className?: string }) {
  const blocks = (text ?? "").split(/\n{2,}/).filter((b) => b.trim());
  return (
    <div className={className}>
      {blocks.map((block, i) => {
        const bulletLines = block
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => /^[-*]\s+/.test(l));

        if (bulletLines.length > 1) {
          return (
            <ul key={i} className="my-3 list-disc pl-5">
              {bulletLines.map((line, li) => (
                <li key={li} dangerouslySetInnerHTML={{ __html: inline(line.replace(/^[-*]\s+/, "")) }} />
              ))}
            </ul>
          );
        }
        return (
          <p
            key={i}
            className="my-3 leading-[1.8] text-paper-ink-soft"
            dangerouslySetInnerHTML={{ __html: inline(block) }}
          />
        );
      })}
    </div>
  );
}

/** Minimal inline markdown (bold, italics, links, code) — reports are plain text from the model. */
function inline(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>',
    );
}

function CitationLinks({
  ids,
  sources,
}: {
  ids: string[];
  sources: Map<string, ReportSource>;
}) {
  if (ids.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1 align-middle">
      {ids.map((id) => {
        const source = sources.get(id);
        if (!source?.url) {
          return (
            <span key={id} className="rounded bg-paper-2 px-1 font-mono text-[10px] text-paper-ink-faint">
              {id}
            </span>
          );
        }
        return (
          <a
            key={id}
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            title={source.title}
            className="rounded bg-paper-2 px-1 font-mono text-[10px] text-[#4a3ec9] no-underline transition-colors hover:bg-accent/15"
          >
            {id}
          </a>
        );
      })}
    </span>
  );
}

export function ReportReader({ report, reportId }: { report: Report; reportId: string }) {
  const sections = useMemo(() => sectionsOf(report), [report]);
  const sources = useMemo(
    () => new Map(report.sources.map((s) => [s.id, s])),
    [report.sources],
  );

  const [active, setActive] = useState(sections[0]?.id ?? "");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible?.target.id) setActive(visible.target.id);
      },
      { rootMargin: "-15% 0px -70% 0px", threshold: [0, 1] },
    );
    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [sections]);

  const copyMarkdown = async () => {
    const text = buildMarkdown(report);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — the download button still works */
    }
  };

  const verification = report.verification;

  return (
    <div className="mx-auto flex max-w-6xl gap-10 px-4 py-8 lg:px-8">
      {/* Contents rail */}
      <aside className="sticky top-8 hidden h-fit w-56 shrink-0 lg:block">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Contents</p>
        <nav className="mt-2 flex flex-col gap-0.5 border-l border-line">
          {sections.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              className={cn(
                "border-l-2 py-1 pl-3 text-xs transition-colors",
                active === section.id
                  ? "border-accent text-ink"
                  : "border-transparent text-ink-faint hover:text-ink-soft",
              )}
            >
              {section.label}
            </a>
          ))}
        </nav>

        <div className="mt-5 flex flex-col gap-2">
          <button
            onClick={copyMarkdown}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] text-ink-soft transition-colors hover:text-ink focus-ring"
          >
            {copied ? <Check className="size-3" /> : <Clipboard className="size-3" />}
            {copied ? "Copied" : "Copy markdown"}
          </button>
          <a
            href={exportPath(reportId, "md")}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] text-ink-soft transition-colors hover:text-ink focus-ring"
          >
            <Download className="size-3" />
            Markdown
          </a>
          <a
            href={exportPath(reportId, "json")}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] text-ink-soft transition-colors hover:text-ink focus-ring"
          >
            <Download className="size-3" />
            JSON
          </a>
        </div>
      </aside>

      {/* Article */}
      <article className="prose-report min-w-0 flex-1 rounded-2xl border border-paper-line bg-paper px-6 py-8 shadow-[0_1px_0_rgba(0,0,0,0.03)] sm:px-10">
        <header className="border-b border-paper-line pb-6">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-paper-ink-faint">
            <span className="rounded-full border border-paper-line bg-paper-2 px-2 py-0.5 capitalize">
              {report.depth} brief
            </span>
            <span className="inline-flex items-center gap-1">
              <BookOpen className="size-3" />
              {report.reading_time_min} min read
            </span>
            <span className="inline-flex items-center gap-1">
              <ListOrdered className="size-3" />
              {report.sources.length} sources
            </span>
            <span className="inline-flex items-center gap-1">
              <Gauge className="size-3" />
              {report.verification.supported}/{report.verification.checked} claims verified
            </span>
            {report.created_at && (
              <span>{new Date(report.created_at).toLocaleString()}</span>
            )}
          </div>

          <h1 className="mt-3 font-serif text-[2rem] leading-tight tracking-tight text-paper-ink">
            {report.title}
          </h1>

          {report.query && (
            <p className="mt-2 text-sm italic leading-relaxed text-paper-ink-faint">
              {report.query.split("\n")[0]}
            </p>
          )}
        </header>

        {report.tldr.length > 0 && (
          <section id="tldr" className="scroll-mt-8">
            <h2>TL;DR</h2>
            <ul className="!mt-2 list-none !pl-0">
              {report.tldr.map((point, i) => (
                <li key={i} className="flex gap-2.5 py-1">
                  <span className="mt-[0.35rem] size-1.5 shrink-0 rounded-full bg-accent" />
                  <span dangerouslySetInnerHTML={{ __html: inline(point) }} />
                </li>
              ))}
            </ul>
          </section>
        )}

        {report.executive_summary && (
          <section id="summary" className="scroll-mt-8">
            <h2>Executive summary</h2>
            <Paragraphs text={report.executive_summary} />
          </section>
        )}

        {report.background_primer && (
          <section id="background" className="scroll-mt-8">
            <h2>Background primer</h2>
            <Paragraphs text={report.background_primer} />
          </section>
        )}

        {report.key_developments.length > 0 && (
          <section id="developments" className="scroll-mt-8">
            <h2>Key developments</h2>
            <div className="mt-3 flex flex-col gap-5">
              {report.key_developments.map((dev, i) => (
                <div key={i} className="border-l-2 border-paper-line pl-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                        CONFIDENCE_META[dev.confidence].className,
                      )}
                    >
                      {CONFIDENCE_META[dev.confidence].label}
                    </span>
                    <CitationLinks ids={dev.sources} sources={sources} />
                  </div>
                  <h3 className="!mt-2 !mb-1 !text-[1.15rem]">
                    <span dangerouslySetInnerHTML={{ __html: inline(dev.claim) }} />
                  </h3>
                  {dev.evidence && <Paragraphs text={dev.evidence} />}
                </div>
              ))}
            </div>
          </section>
        )}

        {report.technical_explainer && (
          <section id="technical" className="scroll-mt-8">
            <h2>How it works</h2>
            <Paragraphs text={report.technical_explainer} />
          </section>
        )}

        {report.timeline.length > 0 && (
          <section id="timeline" className="scroll-mt-8">
            <h2>Timeline</h2>
            <ol className="!mt-3 list-none !pl-0">
              {report.timeline.map((entry, i) => (
                <li key={i} className="flex gap-3 py-1.5">
                  <span className="w-24 shrink-0 text-xs font-medium text-paper-ink-faint">
                    {entry.when}
                  </span>
                  <span className="flex-1">
                    <span dangerouslySetInnerHTML={{ __html: inline(entry.what) }} />
                    {entry.source_id && (
                      <span className="ml-1.5">
                        <CitationLinks ids={[entry.source_id]} sources={sources} />
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {report.comparison_table && report.comparison_table.columns.length > 0 && (
          <section id="comparison" className="scroll-mt-8">
            <h2 className="flex items-center gap-2">
              <Table2 className="size-4" />
              Comparison
            </h2>
            <div className="overflow-x-auto">
              <table>
                <thead>
                  <tr>
                    {report.comparison_table.columns.map((c, i) => (
                      <th key={i}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.comparison_table.rows.map((row, ri) => (
                    <tr key={ri}>
                      {report.comparison_table?.columns.map((_, ci) => (
                        <td
                          key={ci}
                          dangerouslySetInnerHTML={{ __html: inline(row[ci] ?? "") }}
                        />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {report.implications && (
          <section id="implications" className="scroll-mt-8">
            <h2 className="flex items-center gap-2">
              <Sparkles className="size-4 text-accent" />
              Why this matters to you
            </h2>
            <div className="rounded-xl border border-accent/20 bg-accent/5 px-4">
              <Paragraphs text={report.implications} className="[&_p]:text-paper-ink" />
            </div>
          </section>
        )}

        {report.risks_and_uncertainty && (
          <section id="risks" className="scroll-mt-8">
            <h2 className="flex items-center gap-2">
              <AlertTriangle className="size-4" />
              Risks &amp; uncertainty
            </h2>
            <Paragraphs text={report.risks_and_uncertainty} />
          </section>
        )}

        {report.what_to_watch_next.length > 0 && (
          <section id="watch" className="scroll-mt-8">
            <h2>What to watch next</h2>
            <ul>
              {report.what_to_watch_next.map((item, i) => (
                <li key={i} dangerouslySetInnerHTML={{ __html: inline(item) }} />
              ))}
            </ul>
          </section>
        )}

        {report.faq.length > 0 && (
          <section id="faq" className="scroll-mt-8">
            <h2 className="flex items-center gap-2">
              <HelpCircle className="size-4" />
              FAQ
            </h2>
            <div className="mt-2 flex flex-col gap-3">
              {report.faq.map((item, i) => (
                <details key={i} className="group rounded-lg border border-paper-line bg-paper-2/60 px-4 py-2">
                  <summary className="cursor-pointer list-none text-[0.95rem] font-semibold text-paper-ink">
                    <span dangerouslySetInnerHTML={{ __html: inline(item.question) }} />
                  </summary>
                  <Paragraphs text={item.answer} />
                </details>
              ))}
            </div>
          </section>
        )}

        {report.glossary.length > 0 && (
          <section id="glossary" className="scroll-mt-8">
            <h2>Glossary</h2>
            <dl className="mt-2">
              {report.glossary.map((term, i) => (
                <div key={i} className="border-b border-paper-line py-2 last:border-0">
                  <dt className="text-sm font-semibold text-paper-ink">{term.term}</dt>
                  <dd className="text-sm text-paper-ink-soft">{term.definition}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {report.open_questions.length > 0 && (
          <section id="open" className="scroll-mt-8">
            <h2>Open questions</h2>
            <ul>
              {report.open_questions.map((item, i) => (
                <li key={i} dangerouslySetInnerHTML={{ __html: inline(item) }} />
              ))}
            </ul>
          </section>
        )}

        {report.sources.length > 0 && (
          <section id="sources" className="scroll-mt-8">
            <h2>Sources</h2>
            <ol className="!mt-2 list-none !pl-0">
              {report.sources.map((source) => (
                <li key={source.id} className="flex gap-2.5 border-b border-paper-line py-2 last:border-0">
                  <span className="mt-0.5 shrink-0 font-mono text-[10px] text-paper-ink-faint">
                    {source.id}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-1.5 text-sm">
                      {source.url ? (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="!no-underline hover:!underline"
                        >
                          {source.title}
                          <ArrowUpRight className="ml-1 inline size-3" />
                        </a>
                      ) : (
                        <span className="text-paper-ink">{source.title}</span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-paper-ink-faint">
                      {source.kind}
                      {source.published_at ? ` · ${source.published_at.slice(0, 10)}` : ""}
                    </span>
                    {source.quote && (
                      <span className="mt-1 block border-l border-paper-line pl-2 text-[12px] italic leading-relaxed text-paper-ink-faint">
                        {source.quote.slice(0, 260)}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        )}

        <section id="verification" className="scroll-mt-8">
          <h2>Verification</h2>
          <p className="!text-paper-ink-soft">
            {verification.supported}/{verification.checked} load-bearing claims were checked against
            the exact snippets of the sources they cite.
          </p>
          {verification.notes && <p className="!text-paper-ink-faint">{verification.notes}</p>}
          {verification.unsupported_claims.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              {verification.unsupported_claims.map((claim, i) => (
                <div key={i} className="rounded-lg border border-paper-line bg-paper-2 px-3 py-2">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-paper-ink-faint">
                    {claim.action === "removed"
                      ? "Removed after review"
                      : claim.action === "softened"
                        ? "Softened after review"
                        : "Flagged as unsupported"}
                  </p>
                  <p className="mt-1 text-sm text-paper-ink">{claim.claim}</p>
                  <p className="text-xs text-paper-ink-faint">{claim.reason}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        <footer className="mt-8 border-t border-paper-line pt-4 text-[11px] text-paper-ink-faint">
          Generated by CortexResearch · {report.cost_usd.toFixed(4)} USD
          {report.model_trace.length > 0 && (
            <>
              {" · "}
              {Array.from(new Set(report.model_trace.map((c) => c.model))).join(", ")}
            </>
          )}
        </footer>
      </article>
    </div>
  );
}

export function ExportButtons({ id }: { id: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <a
        href={exportPath(id, "md")}
        className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 focus-ring"
      >
        <Download className="size-3.5" />
        Download Markdown
      </a>
      <a
        href={exportPath(id, "json")}
        className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs font-medium text-ink-soft transition-colors hover:text-ink focus-ring"
      >
        <Copy className="size-3.5" />
        Download JSON
      </a>
    </div>
  );
}

const exportPath = (id: string, format: "md" | "json") =>
  `/api/research/reports/${id}/export?format=${format}`;

/** Client-side markdown build, used by "Copy markdown" (no extra round trip). */
function buildMarkdown(report: Report): string {
  const lines: string[] = [`# ${report.title}`, "", `> ${report.query}`, ""];
  if (report.tldr.length) {
    lines.push("## TL;DR", "", ...report.tldr.map((t) => `- ${t}`), "");
  }
  if (report.executive_summary) lines.push("## Executive summary", "", report.executive_summary, "");
  if (report.background_primer) lines.push("## Background primer", "", report.background_primer, "");
  if (report.key_developments.length) {
    lines.push("## Key developments", "");
    report.key_developments.forEach((d) => {
      lines.push(`### ${d.claim}`, "", `_${d.confidence} confidence · ${d.sources.join(", ")}_`, "");
      if (d.evidence) lines.push(d.evidence, "");
    });
  }
  if (report.technical_explainer) lines.push("## How it works", "", report.technical_explainer, "");
  if (report.implications) lines.push("## Why this matters", "", report.implications, "");
  if (report.risks_and_uncertainty) lines.push("## Risks and uncertainty", "", report.risks_and_uncertainty, "");
  if (report.what_to_watch_next.length) {
    lines.push("## What to watch next", "", ...report.what_to_watch_next.map((w) => `- ${w}`), "");
  }
  if (report.sources.length) {
    lines.push("## Sources", "");
    report.sources.forEach((s) => lines.push(`- \`${s.id}\` [${s.title}](${s.url}) — *${s.kind}*`));
    lines.push("");
  }
  return lines.join("\n");
}
