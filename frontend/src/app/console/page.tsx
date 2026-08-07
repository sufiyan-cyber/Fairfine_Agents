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
  EmptyState,
  ErrorState,
  Eyebrow,
  buttonVariants,
} from "@/components/ui/primitives";
import { ChecksList, PlateDisplay, TrustMeter, VerdictBadge } from "@/components/verdict";
import { api, streamAudit } from "@/lib/api";
import { VERDICT_META, formatPercent, formatRupees, titleCase, truncateHash } from "@/lib/format";
import type { AuditResult, AuditTrace } from "@/lib/types";
import { cn } from "@/lib/utils";

const IDLE_TRACE: AuditTrace[] = [
  ["IngestAgent", "Sampling frames + metadata"],
  ["DetectorAgent", "Classifying violation"],
  ["PlateAgent", "Reading plate + per-char confidence"],
  ["MemoryAgent", "Duplicate sweep + MV Act retrieval"],
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
          <Eyebrow>Officer console</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Audit an AI-flagged violation
          </h1>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-dim">
            Upload a clip or still from any CCTV/ANPR feed. Every agent&rsquo;s output is
            shown as it runs, and the decision is written to the ledger before it is
            displayed.
          </p>
        </header>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
          {/* ------------------------------------------------------------ */}
          {/* Left rail: upload + trace                                     */}
          {/* ------------------------------------------------------------ */}
          <div className="space-y-5">
            <Card>
              <CardHeader>
                <CardTitle>Evidence clip</CardTitle>
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
                    accept="video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm,image/jpeg,image/png,image/webp"
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
                        Drop a clip here, or choose a file
                      </p>
                      <p className="text-[11.5px] text-ink-faint">
                        mp4 · mov · avi · mkv · jpg · png — up to 200 MB
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
                    Live inference — Gemini reads the frames from your upload directly.
                    Nothing about the outcome is pre-set.
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
          {/* Right: verdict                                                */}
          {/* ------------------------------------------------------------ */}
          <div className="space-y-5">
            {error ? (
              <ErrorState
                title="Audit failed"
                message={error}
                onRetry={file ? () => start(file) : undefined}
              />
            ) : null}

            {!result && !error ? (
              <Card className="min-h-[420px]">
                <EmptyState
                  icon={<Zap className="size-8" />}
                  title={running ? "Agents are running" : "No audit yet"}
                >
                  {running
                    ? "Watch the trace on the left — each agent reports its structured output as it finishes."
                    : "Upload a clip and run the audit. The verdict, the evidence, and what a threshold-only system would have done all appear here."}
                </EmptyState>
              </Card>
            ) : null}

            {result ? <VerdictPanel result={result} /> : null}
          </div>
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
  const fine = result.fine_amount ?? 0;

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
            <Eyebrow>Auditor&rsquo;s reasoning · shown to the citizen verbatim</Eyebrow>
            <p className="mt-2.5 text-[13.5px] leading-relaxed text-ink">
              {result.verdict.reasoning}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {fine > 0 ? (
              <Badge variant="danger">fine {formatRupees(fine)}</Badge>
            ) : (
              <Badge variant="good">no amount charged</Badge>
            )}
            {result.rule ? <Badge variant="neutral">{result.rule.section}</Badge> : null}
            <Badge variant="neutral">{titleCase(result.detection.violation_type)}</Badge>
            {result.review_id ? (
              <Badge variant="warn">queued · {result.review_id}</Badge>
            ) : null}
          </div>

          <Link
            href={`/challan/${encodeURIComponent(result.challan_id)}`}
            className={buttonVariants({ variant: "primary", className: "w-full" })}
          >
            Open the citizen&rsquo;s view of this decision
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>

      {/* Naive comparison — the demo's pivot */}
      {result.naive ? (
        <Card>
          <CardHeader>
            <CardTitle>What a threshold-only system would have done</CardTitle>
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
                <Eyebrow>Naive system</Eyebrow>
                <p
                  className={cn(
                    "mt-2 font-mono text-sm font-semibold",
                    result.naive.would_issue ? "text-danger" : "text-ink-dim",
                  )}
                >
                  {result.naive.would_issue
                    ? `ISSUE · ${formatRupees(result.naive.fine_amount)}`
                    : "NO ACTION"}
                </p>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-dim">
                  {result.naive.basis}
                </p>
              </div>

              <div className={cn("rounded-lg border p-4", meta.border, meta.bg)}>
                <Eyebrow>FairFine</Eyebrow>
                <p className={cn("mt-2 font-mono text-sm font-semibold", meta.text)}>
                  {meta.short} · {fine > 0 ? formatRupees(fine) : "₹0"}
                </p>
                <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-dim">
                  {meta.description} Trust {formatPercent(result.verdict.trust_score)} against
                  a 90% bar.
                </p>
              </div>
            </div>

            {result.naive.would_issue && result.verdict.verdict !== "ISSUE" ? (
              <p className="mt-4 rounded-lg border border-good/30 bg-good/[0.07] px-4 py-3 text-[13px] leading-relaxed text-good">
                A wrongful fine of {formatRupees(result.naive.fine_amount)} was prevented on
                this event.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Checks + plate */}
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
            <CardTitle>Plate read</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <PlateDisplay plate={result.plate} />
            <div className="space-y-1.5 border-t border-edge pt-3 text-[12px] text-ink-dim">
              <Row label="Detector confidence" value={formatPercent(result.detection.raw_confidence)} />
              <Row label="Duplicate" value={result.duplicate.is_duplicate ? "yes" : "no"} />
              {result.duplicate.matched_challan_id ? (
                <Row label="Matched" value={result.duplicate.matched_challan_id} mono />
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Evidence frames */}
      {result.frame_uris?.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Sampled frames</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {result.frame_uris.map((uri, index) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={index}
                  src={uri}
                  alt={`Evidence frame ${index + 1} of ${result.frame_uris?.length}, ${result.detection.region_description.slice(0, 90)}`}
                  className="aspect-video w-full rounded-lg border border-edge object-cover"
                  loading="lazy"
                />
              ))}
            </div>
            <p className="mt-3 text-[12.5px] leading-relaxed text-ink-dim">
              {result.detection.region_description}
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
          <Row label="Camera" value={result.frames[0]?.camera_id ?? "—"} mono />
          <Row label="Location" value={result.frames[0]?.location ?? "—"} />
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
