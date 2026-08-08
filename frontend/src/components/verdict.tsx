import { Check, Minus, X } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import {
  CHECK_LABELS,
  VERDICT_META,
  checkPassed,
  confidenceTone,
  formatDateTime,
  formatPercent,
  formatRupees,
} from "@/lib/format";
import type {
  AttributionRead,
  TxnEvent,
  VerdictChecks,
  VerdictType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  Verdict badge — colour is never the only signal; the label always shows.   */
/* -------------------------------------------------------------------------- */
export function VerdictBadge({
  verdict,
  size = "md",
  showLabel = true,
}: {
  verdict: VerdictType;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}) {
  const meta = VERDICT_META[verdict];
  const sizing = {
    sm: "px-2 py-0.5 text-[11px]",
    md: "px-2.5 py-1 text-xs",
    lg: "px-3.5 py-1.5 text-sm",
  }[size];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md border font-mono font-semibold tracking-wide",
        meta.bg,
        meta.border,
        meta.text,
        sizing,
      )}
    >
      <span className={cn("size-1.5 rounded-full", meta.dot)} aria-hidden="true" />
      {meta.short}
      {showLabel ? (
        <span className="font-sans font-normal opacity-80">· {meta.label}</span>
      ) : null}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  Trust meter                                                                */
/* -------------------------------------------------------------------------- */
export function TrustMeter({
  score,
  issueThreshold = 0.9,
  escalateFloor = 0.6,
  showScale = true,
  className,
}: {
  score: number;
  issueThreshold?: number;
  escalateFloor?: number;
  showScale?: boolean;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, score));
  const tone =
    pct >= issueThreshold ? "bg-danger" : pct >= escalateFloor ? "bg-warn" : "bg-good";

  return (
    <div className={cn("w-full", className)}>
      <div
        className="relative h-2.5 w-full overflow-hidden rounded-full bg-panel-3"
        role="meter"
        aria-valuenow={Math.round(pct * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Calibrated trust score ${formatPercent(pct)}`}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500 ease-out", tone)}
          style={{ width: `${pct * 100}%` }}
        />
        {/* Threshold markers — the decision boundaries, made visible */}
        <span
          className="absolute top-0 h-full w-px bg-ink/45"
          style={{ left: `${escalateFloor * 100}%` }}
          aria-hidden="true"
        />
        <span
          className="absolute top-0 h-full w-px bg-ink/70"
          style={{ left: `${issueThreshold * 100}%` }}
          aria-hidden="true"
        />
      </div>
      {showScale ? (
        <div className="mt-1.5 flex justify-between font-mono text-[10px] text-ink-faint tabular">
          <span>0%</span>
          <span>
            {formatPercent(escalateFloor)} review · {formatPercent(issueThreshold)} block
          </span>
          <span>100%</span>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Checks list                                                                */
/* -------------------------------------------------------------------------- */
export function ChecksList({
  checks,
  compact = false,
}: {
  checks: VerdictChecks;
  compact?: boolean;
}) {
  const entries = Object.entries(checks) as Array<[keyof VerdictChecks, boolean]>;

  return (
    <ul className={cn("space-y-2", compact && "space-y-1.5")}>
      {entries.map(([key, value]) => {
        const meta = CHECK_LABELS[key];
        const passed = checkPassed(key, value);
        return (
          <li key={key} className="flex items-start gap-2.5">
            <span
              className={cn(
                "mt-px flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border",
                passed
                  ? "border-good/40 bg-good/10 text-good"
                  : "border-danger/40 bg-danger/10 text-danger",
              )}
              aria-hidden="true"
            >
              {passed ? <Check className="size-3" /> : <X className="size-3" />}
            </span>
            <div className="min-w-0">
              <p
                className={cn(
                  "text-[13px] leading-tight",
                  passed ? "text-ink" : "font-medium text-danger",
                )}
              >
                {meta?.label ?? key}
                <span className="sr-only">{passed ? " — passed" : " — failed"}</span>
              </p>
              {!compact && meta ? (
                <p className="mt-0.5 text-[11.5px] leading-snug text-ink-faint">{meta.help}</p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/*  Transaction ledger — the evidence, with the flagged row called out         */
/* -------------------------------------------------------------------------- */
export function TxnLedger({ events, limit }: { events: TxnEvent[]; limit?: number }) {
  if (!events?.length) {
    return <p className="text-[12.5px] text-ink-faint">No transaction events recorded.</p>;
  }

  // The surrounding history is the argument, so show the flagged row in
  // context rather than on its own — trimming from the top keeps it visible.
  const shown = limit ? events.slice(-limit) : events;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[12px]">
        <thead>
          <tr className="border-b border-edge text-left text-ink-faint">
            <th className="py-1.5 pr-3 font-medium">Time</th>
            <th className="py-1.5 pr-3 text-right font-medium">Amount</th>
            <th className="py-1.5 pr-3 font-medium">Merchant</th>
            <th className="py-1.5 pr-3 font-medium">Channel</th>
            <th className="py-1.5 pr-3 font-medium">City</th>
            <th className="py-1.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((event) => (
            <tr
              key={event.event_id}
              className={cn(
                "border-b border-edge/50 last:border-0",
                event.is_flagged && "bg-danger/[0.07] font-medium text-ink",
              )}
            >
              <td className="whitespace-nowrap py-1.5 pr-3 font-mono tabular text-ink-dim">
                {event.is_flagged ? "▶ " : ""}
                {formatDateTime(event.ts)}
              </td>
              <td className="whitespace-nowrap py-1.5 pr-3 text-right font-mono tabular">
                {formatRupees(event.amount)}
              </td>
              <td className="max-w-[200px] truncate py-1.5 pr-3">{event.merchant}</td>
              <td className="whitespace-nowrap py-1.5 pr-3 text-ink-dim">{event.channel}</td>
              <td className="whitespace-nowrap py-1.5 pr-3 text-ink-dim">{event.city || "—"}</td>
              <td className="whitespace-nowrap py-1.5">
                <span
                  className={cn(
                    event.status === "declined" ? "text-danger" : "text-ink-dim",
                  )}
                >
                  {event.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Attribution display — the weakest indicator governs, so show every one     */
/* -------------------------------------------------------------------------- */
export function AttributionDisplay({
  attribution,
  floor = 0.85,
}: {
  attribution: AttributionRead;
  floor?: number;
}) {
  const { indicators, per_indicator_confidence: confidences } = attribution;
  const hasPerIndicator = confidences.length === indicators.length;

  return (
    <div>
      <p className="font-mono text-sm font-semibold text-ink">{attribution.account_ref}</p>

      <ul className="mt-3 space-y-1.5">
        {indicators.map((indicator, index) => {
          const confidence = hasPerIndicator
            ? confidences[index]
            : attribution.min_confidence;
          return (
            <li
              key={`${indicator}-${index}`}
              className="flex items-center justify-between gap-3 text-[12.5px]"
            >
              <span className="min-w-0 flex-1 truncate text-ink-dim">{indicator}</span>
              <span
                className={cn(
                  "shrink-0 rounded border px-1.5 py-0.5 font-mono text-[11px] tabular",
                  confidenceTone(confidence, floor),
                )}
                title={`This indicator points to a non-customer with ${formatPercent(confidence)} confidence`}
              >
                {Math.round(confidence * 100)}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-edge pt-3">
        <Badge variant={attribution.min_confidence >= floor ? "good" : "danger"}>
          weakest indicator {formatPercent(attribution.min_confidence)}
        </Badge>
        <span className="text-[11px] text-ink-faint">
          floor to act on an account: {formatPercent(floor)}
        </span>
        {attribution.matches_known_behaviour ? (
          <Badge variant="warn">
            <Minus className="size-3" />
            matches the customer&rsquo;s own pattern
          </Badge>
        ) : null}
      </div>
    </div>
  );
}
