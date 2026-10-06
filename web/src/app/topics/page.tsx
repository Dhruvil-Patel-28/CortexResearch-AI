"use client";

import { useState } from "react";
import { Check, Loader2, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Profile } from "@/lib/types";

type ListField = "interests" | "stack" | "goals" | "boost" | "mute" | "arxiv_keywords";

const SECTIONS: { field: ListField; title: string; hint: string; placeholder: string }[] = [
  {
    field: "interests",
    title: "Interests",
    hint: "Broad areas you want to stay on top of.",
    placeholder: "e.g. AI agents and agentic workflows",
  },
  {
    field: "stack",
    title: "Your stack",
    hint: "Things you build with — items you can act on score higher.",
    placeholder: "e.g. Python",
  },
  {
    field: "goals",
    title: "Current goals",
    hint: "What you're working towards right now.",
    placeholder: "e.g. ship a standout portfolio project",
  },
  {
    field: "boost",
    title: "Always interesting",
    hint: "Keywords that always deserve a second look.",
    placeholder: "e.g. evaluation",
  },
  {
    field: "arxiv_keywords",
    title: "arXiv search terms",
    hint: "Used to query arXiv; falls back to 'Always interesting' when empty.",
    placeholder: "e.g. retrieval augmented generation",
  },
  {
    field: "mute",
    title: "Never show me",
    hint: "Case-insensitive substrings that hide an item completely.",
    placeholder: "e.g. crypto",
  },
];

export default function TopicsPage() {
  const profile = useAsync(() => api.profile(), []);
  // Edits are layered over the server value instead of copied into an effect,
  // so there is no state sync in an effect.
  const [edits, setEdits] = useState<Partial<Profile>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const draft: Profile | null = profile.data ? { ...profile.data, ...edits } : null;

  const update = (field: ListField, values: string[]) =>
    setEdits((prev) => ({ ...prev, [field]: values }));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.saveProfile({
        name: draft.name,
        interests: draft.interests,
        stack: draft.stack,
        goals: draft.goals,
        boost: draft.boost,
        mute: draft.mute,
        arxiv_keywords: draft.arxiv_keywords,
      });
      setEdits({});
      profile.reload();
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } finally {
      setSaving(false);
    }
  };

  if (!draft) {
    return (
      <div className="grid place-items-center py-24">
        <Loader2 className="size-5 animate-spin text-ink-faint" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <header className="mb-6">
        <h1 className="text-lg font-semibold tracking-tight">Your interests</h1>
        <p className="mt-1 max-w-xl text-xs leading-relaxed text-ink-soft">
          This profile is the whole point of the radar: every story is scored against it, and the
          &ldquo;why this matters to you&rdquo; line is written from it. Editing it invalidates
          cached scores, so the next refresh re-ranks new items.
        </p>
      </header>

      <div className="card mb-5 p-4">
        <label className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
          What should the agent call you?
        </label>
        <input
          value={draft.name}
          onChange={(e) => setEdits((prev) => ({ ...prev, name: e.target.value }))}
          className="mt-2 w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink focus:border-line-strong focus:outline-none focus-ring"
          placeholder="Your name"
        />
      </div>

      <div className="flex flex-col gap-5">
        {SECTIONS.map((section) => (
          <TagSection
            key={section.field}
            title={section.title}
            hint={section.hint}
            placeholder={section.placeholder}
            values={draft[section.field]}
            onChange={(values) => update(section.field, values)}
            tone={section.field === "mute" ? "danger" : "default"}
          />
        ))}
      </div>

      <div className="sticky bottom-4 mt-6 flex items-center justify-end gap-3 rounded-xl border border-line bg-surface/95 px-4 py-3 backdrop-blur">
        <span className="mr-auto text-[11px] text-ink-faint">
          profile version {draft.version || "unsaved"}
        </span>
        <button
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-ring"
        >
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
          {saved ? "Saved" : "Save profile"}
        </button>
      </div>
    </div>
  );
}

function TagSection({
  title,
  hint,
  placeholder,
  values,
  onChange,
  tone = "default",
}: {
  title: string;
  hint: string;
  placeholder: string;
  values: string[];
  onChange: (values: string[]) => void;
  tone?: "default" | "danger";
}) {
  const [input, setInput] = useState("");

  const add = () => {
    const value = input.trim();
    if (!value || values.includes(value)) {
      setInput("");
      return;
    }
    onChange([...values, value]);
    setInput("");
  };

  return (
    <section className="card p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="text-[11px] text-ink-faint">{hint}</p>
      </div>

      {values.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className={
                tone === "danger"
                  ? "chip !border-danger/30 !bg-danger/10 !text-danger"
                  : "chip !text-ink-soft"
              }
            >
              {value}
              <button
                onClick={() => onChange(values.filter((v) => v !== value))}
                className="ml-0.5 rounded p-0.5 hover:bg-surface-3 focus-ring"
                aria-label={`Remove ${value}`}
              >
                <X className="size-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint focus:border-line-strong focus:outline-none focus-ring"
        />
        <button
          onClick={add}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-ink-soft transition-colors hover:border-line-strong hover:text-ink focus-ring"
        >
          <Plus className="size-3" />
          Add
        </button>
      </div>
    </section>
  );
}
