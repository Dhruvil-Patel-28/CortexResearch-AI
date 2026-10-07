"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  Library,
  Newspaper,
  Radar,
  SlidersHorizontal,
  Telescope,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { RefreshButton } from "@/components/refresh-button";

const NAV = [
  { href: "/", label: "Pulse", hint: "What changed", icon: Radar },
  { href: "/research", label: "Research", hint: "Ask anything", icon: Telescope },
  { href: "/reports", label: "Reports", hint: "Saved deep briefs", icon: FileText },
  { href: "/digests", label: "Digests", hint: "Daily briefs", icon: Newspaper },
  { href: "/library", label: "Library", hint: "Search everything", icon: Library },
  { href: "/topics", label: "Interests", hint: "Your profile", icon: SlidersHorizontal },
];

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-2.5 rounded-lg px-1 py-1 focus-ring">
      <span className="relative grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-accent to-warning text-shell shadow-[0_0_16px_-4px] shadow-accent/60 transition-shadow group-hover:shadow-accent/90">
        <Radar className="size-4" strokeWidth={2.4} />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-bold tracking-tight text-ink">Cortex</span>
        <span className="block font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
          signal observatory
        </span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      <aside className="glass sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r px-3 py-4 md:flex">
        <div className="mb-7 px-1">
          <Logo />
        </div>

        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors focus-ring",
                  active
                    ? "bg-accent/10 text-ink"
                    : "text-ink-soft hover:bg-surface-2 hover:text-ink",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent transition-all",
                    active ? "opacity-100 shadow-[0_0_8px] shadow-accent/70" : "opacity-0",
                  )}
                />
                <Icon
                  className={cn(
                    "size-4 transition-colors",
                    active ? "text-accent" : "text-ink-faint group-hover:text-ink-soft",
                  )}
                  strokeWidth={2}
                />
                <span className="font-medium">{item.label}</span>
                <span className="ml-auto text-[10px] text-ink-faint opacity-0 transition-opacity group-hover:opacity-100">
                  {item.hint}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col gap-3 px-1">
          <RefreshButton />
          <div className="flex items-center gap-2 px-1 text-[11px] text-ink-faint">
            <span className="relative flex size-1.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-positive opacity-60" />
              <span className="relative inline-flex size-1.5 rounded-full bg-positive" />
            </span>
            radar nominal — free sources only
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-20 flex items-center gap-3 border-b px-4 py-3 md:hidden">
          <Logo />
          <nav className="ml-auto flex gap-3 text-xs">
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="text-ink-soft transition-colors hover:text-ink">
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
