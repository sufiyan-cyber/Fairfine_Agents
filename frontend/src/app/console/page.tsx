"use client";

import {
  ArrowRight,
  FileVideo,
  Loader2,
  RotateCcw,
  Upload,
  Zap,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { AgentTrace, TraceLegend } from "@/components/agent-trace";
import { SiteFooter, SiteNav } from "@/components/site-nav";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  Eyebrow,
  buttonVariants,
} from "@/components/ui/primitives";
import {
  AttributionDisplay,
  ChecksList,
  TrustMeter,
  TxnLedger,
  VerdictBadge,
} from "@/components/verdict";
import { api, streamAudit } from "@/lib/api";
import { VERDICT_META, formatPercent, formatRupees, titleCase, truncateHash } from "@/lib/format";
import type { AuditResult, AuditTrace } from "@/lib/types";
import { cn } from "@/lib/utils";

const IDLE_TRACE: AuditTrace[] = [
  ["IngestAgent", "Parsing alert + account history"],
  ["SignalAgent", "Classifying fraud pattern"],
  ["AttributionAgent", "Scoring attribution confidence"],
  ["MemoryAgent", "Duplicate sweep + rulebook retrieval"],
  ["AuditorAgent", "Adversarial review"],
  ["VerdictRouter", "Routing on verdict"],
  ["LedgerAgent", "Appending to hash chain"],
].map(([agent, label]) => ({
  agent,
  label,
  status: "pending" as const,
  detail: "",
  output: null,
  started_at: null,
  finished_at: null,
  duration_ms: null,
}));

export default function ConsolePage() {
  const [file, setFile] = React.useState<File | null>(null);
  const [trace, setTrace] = React.useState<AuditTrace[]>(IDLE_TRACE);
  const [result, setResult] = React.useState<AuditResult | null>(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);
  const [scenarios, setScenarios] = React.useState<
    Array<{ id: string; label: string; expected_verdict: string }>
  >([]);
  const [scenario, setScenario] = React.useState("");
  // The scenario override only influences the deterministic simulator. In live
  // mode only the video frames reach Gemini, so the control would do nothing —
  // we hide it entirely rather than show a dead input.
  const [mode, setMode] = React.useState<string | null>(null);
  const abortRef = React.useRef<(() => void) | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    api
      .scenarios()
      .then((data) => {
        setScenarios(data.scenarios);
        setMode(data.mode);
      })
      .catch(() => setScenarios([]));
    return () => abortRef.current?.();
  }, []);

  const showScenarioPicker = mode === "simulation" && scenarios.length > 0;
  const showVerdictColumn = Boolean(result || error);

  const start = React.useCallback(
    (target: File) => {
      setRunning(true);
      setError(null);
      setResult(null);
      setTrace(IDLE_TRACE);

      abortRef.current = streamAudit(
        target,
        {
          onTrace: setTrace,
          onResult: setResult,
          onError: (message) => setError(message),
          onDone: () => setRunning(false),
        },
        // Only forward the scenario when the picker is actually shown; in live
        // mode it is meaningless and must not leak into the request.
        { scenario: showScenarioPicker ? scenario || undefined : undefined },
      );
    },
    [scenario, showScenarioPicker],
  );

  const onSelect = (selected: File | null) => {
    if (!selected) return;
    setFile(selected);
    setResult(null);
    setError(null);
    setTrace(IDLE_TRACE);
  };

  const reset = () => {
    abortRef.current?.();
    setFile(null);
    setResult(null);
    setError(null);
    setTrace(IDLE_TRACE);
    setRunning(false);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <>
      <SiteNav />

      <main id="main" className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-7">
          <Eyebrow>Fraud operations console</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Audit an AI-flagged transaction
          </h1>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-dim">
            Upload a fraud alert exported from any monitoring system. Every agent&rsquo;s
            output is shown as it runs, and the decision is written to the ledger before
            it is displayed.
          </p>
        </header>

        <div
          className={cn(
            "grid items-start gap-5",
            // Until there is a verdict (or an error) the right column has
            // nothing to say, and an empty panel beside a narrow rail reads
            // as a broken page. So idle and running audits spread the upload
            // and the pipeline across the full width, and the rail layout
            // only appears together with the content that justifies it.
            showVerdictColumn
              ? "lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]"
              : "lg:grid-cols-2",
          )}
        >
          {/* ------------------------------------------------------------ */}
          {/* Upload + trace: a left rail once a verdict is shown,          */}
          {/* two full-width columns before that (lg:contents dissolves     */}
          {/* the wrapper so both cards become grid children).              */}
          {/* ------------------------------------------------------------ */}
          <div className={cn("space-y-5", !showVerdictColumn && "lg:contents")}>
            <Card>
              <CardHeader>
                <CardTitle>Alert case file</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    onSelect(event.dataTransfer.files?.[0] ?? null);
                  }}
                  className={cn(
                    "rounded-xl border-2 border-dashed p-6 text-center transition-colors duration-200",
                    dragging
                      ? "border-signal bg-signal/[0.07]"
                      : "border-edge-strong bg-panel-2/40",
                  )}
                >
                  <input
                    ref={inputRef}
                    id="clip"
                    type="file"
                    accept="application/json,.json"
                    className="sr-only"
                    onChange={(event) => onSelect(event.target.files?.[0] ?? null)}
                    disabled={running}
                  />

                  {file ? (
                    <div className="flex flex-col items-center gap-2">
                      <FileVideo className="size-7 text-signal" aria-hidden="true" />
                      <p className="max-w-full truncate text-[13px] font-medium text-ink">
                        {file.name}
                      </p>
                      <p className="font-mono text-[11px] text-ink-faint tabular">
                        {file.size < 1024 * 1024
                          ? `${(file.size / 1024).toFixed(0)} KB`
                          : `${(file.size / 1024 / 1024).toFixed(2)} MB`}
                      </p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2">
                      <Upload className="size-7 text-ink-faint" aria-hidden="true" />
                      <p className="text-[13px] text-ink-dim">
                        Drop an alert here, or choose a file
                      </p>
                      <p className="text-[11.5px] text-ink-faint">
                        JSON case file — flagged transaction + account history
                      </p>
                    </div>
                  )}

                  <label
                    htmlFor="clip"
                    className={cn(
                      buttonVariants({ variant: "secondary", size: "sm" }),
                      "mt-4",
                      running && "pointer-events-none opacity-45",
                    )}
                  >
                    {file ? "Choose a different file" : "Choose file"}
                  </label>
                </div>

                {showScenarioPicker ? (
                  <div>
                    <label
                      htmlFor="scenario"
                      className="mb-1.5 block text-[12.5px] font-medium text-ink"
                    >
                      Perception scenario{" "}
                      <span className="font-normal text-ink-faint">(optional)</span>
                    </label>
                    <select
                      id="scenario"
                      value={scenario}
                      onChange={(event) => setScenario(event.target.value)}
                      disabled={running}
                      className="h-11 w-full rounded-lg border border-edge-strong bg-panel-2 px-3 text-[13px] text-ink transition-colors hover:border-signal/40 disabled:opacity-45"
                    >
                      <option value="">Infer from the filename</option>
                      {scenarios.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label} → {item.expected_verdict}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1.5 text-[11.5px] leading-snug text-ink-faint">
                      Forces a known perception result so a specific decision boundary can
                      be demonstrated. The audit itself still runs for real.
                    </p>
                  </div>
                ) : mode === "live" ? (
                  <p className="rounded-lg border border-edge bg-panel-2/40 px-3 py-2 text-[11.5px] leading-snug text-ink-faint">
                    Live inference — Gemini reads the transactions from your upload
                    directly. Nothing about the outcome is pre-set.
                  </p>
                ) : null}

                <div className="flex gap-2">
                  <Button
                    variant="primary"
                    className="flex-1"
                    disabled={!file || running}
                    onClick={() => file && start(file)}
                  >
                    {running ? (
                      <>
                        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                        Auditing…
                      </>
                    ) : (
                      <>
                        <Zap className="size-4" aria-hidden="true" />
                        Run audit
                      </>
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={reset}
                    disabled={running}
                    aria-label="Reset the console"
                    title="Reset"
                  >
                    <RotateCcw className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <TraceLegend />
              </CardHeader>
              <CardContent>
                <AgentTrace trace={trace} />
              </CardContent>
            </Card>
          </div>

          {/* ------------------------------------------------------------ */}
          {/* Right: verdict — only mounted once there is something to show */}
          {/* ------------------------------------------------------------ */}
          {showVerdictColumn ? (
            <div className="space-y-5">
              {error ? (
                <ErrorState
                  title="Audit failed"
                  message={error}
                  onRetry={file ? () => start(file) : undefined}
                />
              ) : null}

              {result ? <VerdictPanel result={result} /> : null}
            </div>
          ) : null}
        </div>
      </main>

      <SiteFooter />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Verdict panel                                                              */
/* -------------------------------------------------------------------------- */
function VerdictPanel({ result }: { result: AuditResult }) {
  const meta = VERDICT_META[result.verdict.verdict];
  const held = result.amount_held ?? 0;

  return (
    <div className="animate-fade-up space-y-5">
      {/* Verdict headline */}
      <Card className={cn("overflow-hidden", meta.border)}>
        <div className={cn("border-b px-5 py-4", meta.bg, meta.border)}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <VerdictBadge verdict={result.verdict.verdict} size="lg" />
            <span className="font-mono text-[11.5px] text-ink-dim">
              {result.challan_id}
            </span>
          </div>
        </div>

        <CardContent className="space-y-5 pt-5">
          <div>
            <Eyebrow>Calibrated trust score</Eyebrow>
            <div className="mt-2 flex items-baseline gap-3">
              <span className={cn("font-mono text-3xl font-semibold tabular", meta.text)}>
                {formatPercent(result.verdict.trust_score, 1)}
              </span>
              <span className="text-[13px] text-ink-dim">{meta.description}</span>
            </div>
            <TrustMeter score={result.verdict.trust_score} className="mt-3" />
          </div>

          <div className="rounded-lg border border-edge bg-panel-2/60 p-4">
            <Eyebrow>Auditor&rsquo;s reasoning · shown to the customer verbatim</Eyebrow>
            <p className="mt-2.5 text-[13.5px] leading-relaxed text-ink">
              {result.verdict.reasoning}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {held > 0 ? (
              <Badge variant="danger">held {formatRupees(held)}</Badge>
            ) : (
              <Badge variant="good">nothing held</Badge>
            )}
            {result.rule ? <Badge variant="neutral">{result.rule.section}</Badge> : null}
            <Badge variant="neutral">{titleCase(result.signal.fraud_type)}</Badge>
            {result.review_id ? (
              <Badge variant="warn">queued · {result.review_id}</Badge>
            ) : null}
          </div>

          <Link
            href={`/challan/${encodeURIComponent(result.challan_id)}`}
            className={buttonVariants({ variant: "primary", className: "w-full" })}
          >
            Open the customer&rsquo;s view of this decision
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>

      {/* Naive comparison — the demo's pivot */}
      {result.naive ? (
        <Card>
          <CardHeader>
            <CardTitle>What the bank&rsquo;s existing engine would have done</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2">
              <div
                className={cn(
                  "rounded-lg border p-4",
                  result.naive.would_issue
                    ? "border-danger/30 bg-danger/[0.06]"
                    : "border-edge bg-panel-2/50",
                )}
              >
                <Eyebrow>Threshold-only engine</Eyebrow>
                <p
                  className={cn(
                    "mt-2 font-mono text-sm font-semibold",
                    result.naive.would_issue ? "text-danger" : "text-ink-dim",
                  )}
                >
                  {result.naive.would_issue
                    ? `BLOCK · ${formatRupees(result.naive.amount_held)}`
                    : "NO ACTION"}
                </p>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-dim">
                  {result.naive.basis}
                </p>
              </div>

              <div className={cn("rounded-lg border p-4", meta.border, meta.bg)}>
                <Eyebrow>FairFine</Eyebrow>
                <p className={cn("mt-2 font-mono text-sm font-semibold", meta.text)}>
                  {meta.short} · {held > 0 ? formatRupees(held) : "₹0"}
                </p>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-dim">
                  {meta.description} Trust {formatPercent(result.verdict.trust_score)} against
                  a 90% bar.
                </p>
              </div>
            </div>

            {result.naive.would_issue && result.verdict.verdict !== "ISSUE" ? (
              <p className="mt-4 rounded-lg border border-good/30 bg-good/[0.07] px-4 py-3 text-[13px] leading-relaxed text-good">
                A wrongful block of {formatRupees(result.naive.amount_held)} was prevented on
                this account.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Checks + attribution */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Checks performed</CardTitle>
          </CardHeader>
          <CardContent>
            <ChecksList checks={result.verdict.checks} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Attribution</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <AttributionDisplay attribution={result.attribution} />
            <div className="space-y-1.5 border-t border-edge pt-3 text-[12px] text-ink-dim">
              <Row label="Signal confidence" value={formatPercent(result.signal.raw_confidence)} />
              <Row label="Duplicate" value={result.duplicate.is_duplicate ? "yes" : "no"} />
              {result.duplicate.matched_challan_id ? (
                <Row label="Matched" value={result.duplicate.matched_challan_id} mono />
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* The evidence itself */}
      {result.events?.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Transaction ledger reviewed</CardTitle>
          </CardHeader>
          <CardContent>
            <TxnLedger events={result.events} />
            <p className="mt-3 text-[12.5px] leading-relaxed text-ink-dim">
              {result.signal.evidence_summary}
            </p>
          </CardContent>
        </Card>
      ) : null}

      {/* Ledger */}
      <Card>
        <CardHeader>
          <CardTitle>Ledger record</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5 text-[12px]">
          <Row label="Record" value={result.ledger_id} mono />
          <Row label="Hash" value={truncateHash(result.ledger_hash, 18, 10)} mono />
          <Row label="Account" value={result.attribution.account_ref} mono />
          <Row
            label="Merchant"
            value={result.events.find((e) => e.is_flagged)?.merchant ?? "—"}
          />
          <Link
            href="/ledger"
            className={buttonVariants({ variant: "outline", size: "sm", className: "mt-4 w-full" })}
          >
            Verify the chain
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="shrink-0 text-ink-faint">{label}</span>
      <span className={cn("truncate text-right text-ink", mono && "font-mono tabular")}>
        {value}
      </span>
    </div>
  );
}
