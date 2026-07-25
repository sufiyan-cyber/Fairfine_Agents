"use client";

import {
  ChevronRight,
  Link2,
  Loader2,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SiteFooter, SiteNav } from "@/components/site-nav";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Eyebrow,
  Skeleton,
  buttonVariants,
} from "@/components/ui/primitives";
import { VerdictBadge } from "@/components/verdict";
import { api } from "@/lib/api";
import { formatPercent, formatTime, truncateHash } from "@/lib/format";
import type { LedgerRecord, LedgerVerification, VerdictType } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function LedgerPage() {
  const [records, setRecords] = React.useState<LedgerRecord[]>([]);
  const [total, setTotal] = React.useState(0);
  const [verification, setVerification] = React.useState<LedgerVerification | null>(null);
  const [verifying, setVerifying] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<LedgerRecord | null>(null);

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.ledger(100), api.verifyLedger()])
      .then(([page, check]) => {
        setRecords(page.items);
        setTotal(page.total);
        setVerification(check);
        setSelected((current) => current ?? page.items[0] ?? null);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(load, [load]);

  const runVerify = async () => {
    setVerifying(true);
    try {
      setVerification(await api.verifyLedger());
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <>
      <SiteNav />

      <main id="main" className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-7">
          <Eyebrow>Public record</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Ledger explorer
          </h1>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-dim">
            Every decision — issued, rejected and escalated alike — appended in order. Each
            record&rsquo;s hash covers the one before it, so history cannot be rewritten
            without the chain visibly breaking.
          </p>
        </header>

        {/* Verification banner */}
        {verification ? (
          <Card
            className={cn(
              "mb-5",
              verification.valid ? "border-good/30 bg-good/[0.05]" : "border-danger/35 bg-danger/[0.07]",
            )}
          >
            <CardContent className="flex flex-col gap-4 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                {verification.valid ? (
                  <ShieldCheck className="mt-0.5 size-5 shrink-0 text-good" aria-hidden="true" />
                ) : (
                  <ShieldAlert className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden="true" />
                )}
                <div>
                  <p
                    className={cn(
                      "text-[14px] font-semibold",
                      verification.valid ? "text-good" : "text-danger",
                    )}
                  >
                    {verification.valid
                      ? `Chain verified — ${verification.records_checked} records intact`
                      : "Chain broken — tampering detected"}
                  </p>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-ink-dim">
                    {verification.valid
                      ? "Every hash was recomputed from genesis as SHA-256 over the previous hash, the canonical payload, and the timestamp."
                      : verification.reason}
                  </p>
                  {verification.broken_at ? (
                    <p className="mt-1 font-mono text-[11.5px] text-danger">
                      first bad record: {verification.broken_at}
                    </p>
                  ) : null}
                </div>
              </div>

              <Button variant="secondary" onClick={runVerify} disabled={verifying} className="shrink-0">
                {verifying ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                    Recomputing…
                  </>
                ) : (
                  "Re-verify now"
                )}
              </Button>
            </CardContent>
          </Card>
        ) : null}

        {error ? <ErrorState message={error} onRetry={load} /> : null}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
          {/* Record list */}
          <Card className="overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Records</CardTitle>
              <span className="font-mono text-[11.5px] text-ink-faint tabular">
                {total} total
              </span>
            </CardHeader>

            {loading && !records.length ? (
              <CardContent className="space-y-2">
                {Array.from({ length: 8 }).map((_, index) => (
                  <Skeleton key={index} className="h-14 w-full" />
                ))}
              </CardContent>
            ) : !records.length ? (
              <EmptyState
                icon={<Link2 className="size-8" />}
                title="The ledger is empty"
                action={
                  <Link href="/console" className={buttonVariants({ variant: "primary", size: "sm" })}>
                    Run the first audit
                  </Link>
                }
              >
                Every audit you run appends a record here.
              </EmptyState>
            ) : (
              <div className="max-h-[640px] overflow-y-auto">
                <ul className="divide-y divide-edge">
                  {records.map((record) => {
                    const payload = record.payload as Record<string, unknown>;
                    const verdict = String(payload.verdict ?? "") as VerdictType;
                    const isReaudit = payload.event === "REAUDIT";
                    const active = selected?.id === record.id;

                    return (
                      <li key={record.id}>
                        <button
                          type="button"
                          onClick={() => setSelected(record)}
                          aria-current={active ? "true" : undefined}
                          className={cn(
                            "flex w-full items-center gap-3 px-5 py-3 text-left transition-colors duration-150 cursor-pointer",
                            active ? "bg-signal/[0.08]" : "hover:bg-panel-2/60",
                          )}
                        >
                          <span className="w-9 shrink-0 font-mono text-[11px] text-ink-faint tabular">
                            #{record.seq}
                          </span>

                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-1.5">
                              {verdict ? <VerdictBadge verdict={verdict} size="sm" showLabel={false} /> : null}
                              {isReaudit ? <Badge variant="signal">re-audit</Badge> : null}
                              <span className="font-mono text-[11.5px] text-ink-dim">
                                {String(payload.challan_id ?? "")}
                              </span>
                            </span>
                            <span className="mt-1 block truncate font-mono text-[10.5px] text-ink-faint">
                              {truncateHash(record.hash, 14, 8)}
                            </span>
                          </span>

                          <span className="shrink-0 text-right">
                            <span className="block font-mono text-[11px] text-ink-dim tabular">
                              {formatTime(record.ts)}
                            </span>
                            {typeof payload.trust_score === "number" ? (
                              <span className="mt-0.5 block font-mono text-[10.5px] text-ink-faint tabular">
                                {formatPercent(payload.trust_score as number)}
                              </span>
                            ) : null}
                          </span>

                          <ChevronRight className="size-4 shrink-0 text-ink-faint" aria-hidden="true" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </Card>

          {/* Detail */}
          <div className="lg:sticky lg:top-24 lg:self-start">
            {selected ? <RecordDetail record={selected} /> : null}
          </div>
        </div>
      </main>

      <SiteFooter />
    </>
  );
}

function RecordDetail({ record }: { record: LedgerRecord }) {
  const payload = record.payload as Record<string, unknown>;
  const challanId = String(payload.challan_id ?? "");
  const verdict = String(payload.verdict ?? "") as VerdictType;

  return (
    <Card className="animate-fade-up">
      <CardHeader>
        <CardTitle>Record #{record.seq}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {verdict ? <VerdictBadge verdict={verdict} /> : null}

        <div className="space-y-2.5">
          <HashRow label="This hash" value={record.hash} tone="text-signal" />
          <HashRow label="Previous hash" value={record.prev_hash} tone="text-ink-dim" />
          <div className="flex items-baseline justify-between gap-3 text-[12px]">
            <span className="text-ink-faint">Timestamp</span>
            <span className="font-mono text-ink tabular">{record.ts}</span>
          </div>
        </div>

        <div>
          <Eyebrow className="mb-2">Payload — hashed exactly as shown</Eyebrow>
          <pre className="max-h-80 overflow-auto rounded-lg border border-edge bg-void/70 p-3 font-mono text-[11px] leading-relaxed text-ink-dim">
            {JSON.stringify(record.payload, null, 2)}
          </pre>
        </div>

        {challanId ? (
          <Link
            href={`/challan/${encodeURIComponent(challanId)}`}
            className={buttonVariants({ variant: "secondary", size: "sm", className: "w-full" })}
          >
            Open the citizen&rsquo;s view
          </Link>
        ) : null}
      </CardContent>
    </Card>
  );
}

function HashRow({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div>
      <p className="text-[11.5px] text-ink-faint">{label}</p>
      <p className={cn("mt-0.5 break-all font-mono text-[11px] leading-relaxed", tone)}>
        {value}
      </p>
    </div>
  );
}
