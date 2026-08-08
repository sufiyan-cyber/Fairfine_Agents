"use client";

import { Menu, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/console", label: "Audit Console" },
  { href: "/review", label: "Human Review" },
  { href: "/ledger", label: "Ledger" },
  { href: "/dashboard", label: "Bias Dashboard" },
];

export function SiteNav() {
  const pathname = usePathname();
  const [mode, setMode] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    api
      .health()
      .then((health) => setMode(health.mode))
      .catch(() => setMode("offline"));
  }, []);

  // Close the mobile sheet on navigation.
  React.useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="sticky top-0 z-40 border-b border-edge bg-void/85 backdrop-blur-md">
      <nav
        className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8"
        aria-label="Main"
      >
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-md transition-opacity hover:opacity-85"
        >
          <span className="flex size-8 items-center justify-center rounded-lg border border-signal/35 bg-signal/12">
            <ShieldCheck className="size-[18px] text-signal" aria-hidden="true" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">FairFine</span>
        </Link>

        <div className="ml-auto hidden items-center gap-1 md:flex">
          {LINKS.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2 text-[13.5px] transition-colors duration-200",
                  active
                    ? "bg-panel-2 font-medium text-ink"
                    : "text-ink-dim hover:bg-panel-2/70 hover:text-ink",
                )}
              >
                {link.label}
              </Link>
            );
          })}
          <ModePill mode={mode} className="ml-2" />
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          className="ml-auto flex size-11 items-center justify-center rounded-lg text-ink-dim transition-colors hover:bg-panel-2 hover:text-ink md:hidden"
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </nav>

      {open ? (
        <div id="mobile-nav" className="border-t border-edge bg-panel px-4 py-3 md:hidden">
          <div className="flex flex-col gap-1">
            {LINKS.map((link) => {
              const active = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center rounded-lg px-3 text-sm transition-colors",
                    active ? "bg-panel-2 font-medium text-ink" : "text-ink-dim hover:text-ink",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
            <ModePill mode={mode} className="mt-2 self-start" />
          </div>
        </div>
      ) : null}
    </header>
  );
}

/**
 * Shows whether the pipeline is running live Gemini inference or the
 * deterministic simulator. Surfaced everywhere rather than hidden — claiming
 * live inference while simulating would undermine the entire premise.
 */
export function ModePill({ mode, className }: { mode: string | null; className?: string }) {
  if (!mode) return null;

  const config = {
    live: { label: "live inference", tone: "border-good/35 bg-good/10 text-good" },
    simulation: { label: "simulation mode", tone: "border-warn/35 bg-warn/10 text-warn" },
    offline: { label: "api offline", tone: "border-danger/35 bg-danger/10 text-danger" },
  }[mode] ?? { label: mode, tone: "border-edge-strong bg-panel-2 text-ink-dim" };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[10.5px] uppercase tracking-wider",
        config.tone,
        className,
      )}
      title={
        mode === "simulation"
          ? "No GEMINI_API_KEY is set — a deterministic rule engine is standing in for the models."
          : mode === "offline"
            ? "The FairFine API is not reachable."
            : "Running live Gemini inference through the ADK pipeline."
      }
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          mode === "live" ? "bg-good" : mode === "simulation" ? "bg-warn" : "bg-danger",
        )}
        aria-hidden="true"
      />
      {config.label}
    </span>
  );
}

export function SiteFooter() {
  return (
    <footer className="relative z-10 border-t border-edge bg-void">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[12.5px] leading-relaxed text-ink-faint">
            FairFine is decision support with a human in the loop for ambiguous cases.
            It does not replace a fraud-operations team.
          </p>
          <p className="font-mono text-[11px] text-ink-faint">
            Demo build · mocked core banking · synthetic transactions
          </p>
        </div>
      </div>
    </footer>
  );
}
