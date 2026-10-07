"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { RefreshButton } from "@/components/refresh-button";

const NAV = [
  { href: "/", label: "Pulse", hint: "What changed" },
  { href: "/research", label: "Research", hint: "Ask anything" },
  { href: "/reports", label: "Reports", hint: "Saved deep briefs" },
  { href: "/digests", label: "Digests", hint: "Daily briefs" },
  { href: "/topics", label: "Interests", hint: "Your profile" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface/60 px-3 py-4 md:flex">
        <Link href="/" className="mb-6 flex items-center gap-2 px-2 focus-ring rounded-lg">
          <span className="grid size-7 place-items-center rounded-lg bg-accent text-[13px] font-bold text-white">
            C
          </span>
          <span className="text-sm font-semibold tracking-tight">Cortex</span>
        </Link>

        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group flex items-center justify-between rounded-lg px-2.5 py-2 text-sm transition-colors focus-ring",
                  active
                    ? "bg-surface-3 text-ink"
                    : "text-ink-soft hover:bg-surface-2 hover:text-ink",
                )}
              >
                <span className="font-medium">{item.label}</span>
                <span className="text-[11px] text-ink-faint opacity-0 transition-opacity group-hover:opacity-100">
                  {item.hint}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col gap-3 px-1">
          <RefreshButton />
          <p className="px-1 text-[11px] leading-relaxed text-ink-faint">
            Free sources only — HN, arXiv, blogs, Reddit, GitHub, Product Hunt.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-shell/85 px-4 py-3 backdrop-blur md:hidden">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-[13px] font-bold text-white">
              C
            </span>
            <span className="text-sm font-semibold">Cortex</span>
          </Link>
          <nav className="ml-auto flex gap-3 text-xs">
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="text-ink-soft">
                {item.label}
              </Link>
            ))}
          </nav>
        </header>

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
