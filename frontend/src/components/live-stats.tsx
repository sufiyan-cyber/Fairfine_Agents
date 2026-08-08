"use client";

import { ShieldCheck, ShieldX } from "lucide-react";
import * as React from "react";

import { Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { BiasDashboard, LedgerVerification } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Live counters on the landing page. The "Real-Time / Operations" pattern
 * calls for status-as-proof above the fold — these read from the running
 * system rather than being hard-coded marketing numbers.
 */
export function LiveStats() {
  const [dashboard, setDashboard] = React.useState<BiasDashboard | null>(null);
  const [ledger, setLedger] = React.useState<LedgerVerification | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    Promise.all([api.dashboard(), api.verifyLedger()])
      .then(([dash, verification]) => {
        if (cancelled) return;
        setDashboard(dash);
        setLedger(verification);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <p className="text-[13px] text-ink-faint">
        Live figures unavailable — the FairFine API is not reachable from this browser.
      </p>
    );
  }

  if (!dashboard || !ledger) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[86px]" />
        ))}
      </div>
    );
  }

  const stats = [
    {
      value: dashboard.total_events.toLocaleString("en-IN"),
      label: "alerts audited",
      tone: "text-ink",
    },
    {
      value: dashboard.wrongful_blocks_prevented.toLocaleString("en-IN"),
      label: "blocks stopped before the money moved",
      tone: "text-good",
    },
    {
      value: formatPercent(dashboard.prevention_rate),
      label: "of AI alerts did not survive audit",
      tone: "text-warn",
    },
    {
      value: ledger.records_checked.toLocaleString("en-IN"),
      label: "ledger records, chain verified",
      tone: ledger.valid ? "text-signal" : "text-danger",
      icon: ledger.valid ? ShieldCheck : ShieldX,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <div
            key={stat.label}
            className="rounded-xl border border-edge bg-panel/70 p-4 backdrop-blur-sm"
          >
            <div className="flex items-center gap-1.5">
              <p className={cn("font-mono text-2xl font-semibold tabular", stat.tone)}>
                {stat.value}
              </p>
              {Icon ? <Icon className={cn("size-4", stat.tone)} aria-hidden="true" /> : null}
            </div>
            <p className="mt-1.5 text-[12px] leading-snug text-ink-dim">{stat.label}</p>
          </div>
        );
      })}
    </div>
  );
}
