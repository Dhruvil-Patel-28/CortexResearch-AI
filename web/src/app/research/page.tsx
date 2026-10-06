import Link from "next/link";
import { Sparkles } from "lucide-react";

export default function ResearchPage() {
  return (
    <div className="mx-auto grid max-w-3xl place-items-center px-4 py-24 text-center">
      <Sparkles className="size-6 text-accent-soft" />
      <h1 className="mt-3 text-lg font-semibold tracking-tight">Deep research</h1>
      <p className="mt-1 max-w-md text-xs leading-relaxed text-ink-soft">
        The live research workbench — ask anything, watch the agent plan, search and verify in real
        time, and get a report with citations — lands in the next step of this build.
      </p>
      <Link
        href="/"
        className="mt-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-soft transition-colors hover:text-ink"
      >
        Back to pulse
      </Link>
    </div>
  );
}
