"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/common";

const LINKS = [
  { href: "/sim", label: "Simulator" },
  { href: "/lab", label: "Pilot Lab" },
  { href: "/audit", label: "World audit" },
  { href: "/reports", label: "Reports" },
];

/** Links between the tools. Compact enough to sit in the simulator's header too. */
export function ToolLinks({ className = "" }: { className?: string }) {
  const path = usePathname();
  return (
    <nav aria-label="Tools" className={`flex items-center gap-1 text-sm ${className}`}>
      {LINKS.map((l) => {
        const on = path === l.href || path.startsWith(l.href + "/");
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={on ? "page" : undefined}
            className={`whitespace-nowrap rounded-md px-2.5 py-1.5 transition ${on ? "bg-surface-2 text-ink" : "text-muted hover:text-ink"}`}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function ToolHeader({ badge }: { badge: string }) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4">
        <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Lucid home">
          <Logo />
          <span className="hidden rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted sm:inline">{badge}</span>
        </Link>
        <ToolLinks className="-mr-2 min-w-0 overflow-x-auto" />
      </div>
    </header>
  );
}
