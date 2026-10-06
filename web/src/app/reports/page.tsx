import Link from "next/link";
import { FileText } from "lucide-react";

export default function ReportsPage() {
  return (
    <div className="mx-auto grid max-w-3xl place-items-center px-4 py-24 text-center">
      <FileText className="size-6 text-accent-soft" />
      <h1 className="mt-3 text-lg font-semibold tracking-tight">Reports</h1>
      <p className="mt-1 max-w-md text-xs leading-relaxed text-ink-soft">
        Saved deep briefs will appear here — full reports with TL;DR, background, key developments,
        implications, risks, FAQ and citation-verified sources.
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
