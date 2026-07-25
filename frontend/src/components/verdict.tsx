import { Check, Minus, X } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import {
  CHECK_LABELS,
  VERDICT_META,
  checkPassed,
  confidenceTone,
  formatPercent,
} from "@/lib/format";
import type { PlateRead, VerdictChecks, VerdictType } from "@/lib/types";
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
            {formatPercent(escalateFloor)} escalate · {formatPercent(issueThreshold)} issue
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
/*  Plate display — per-character confidence is the point, so show it          */
/* -------------------------------------------------------------------------- */
export function PlateDisplay({
  plate,
  floor = 0.85,
  showChars = true,
}: {
  plate: PlateRead;
  floor?: number;
  showChars?: boolean;
}) {
  const characters = plate.plate.split("");
  const confidences = plate.per_char_confidence;
  const hasPerChar = confidences.length === characters.length;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        {characters.map((character, index) => {
          const confidence = hasPerChar ? confidences[index] : plate.min_confidence;
          return (
            <span
              key={`${character}-${index}`}
              className={cn(
                "flex min-w-[26px] flex-col items-center rounded border px-1.5 py-1 font-mono",
                showChars ? confidenceTone(confidence, floor) : "border-edge bg-panel-2 text-ink",
              )}
              title={`Character '${character}' read at ${formatPercent(confidence)} confidence`}
            >
              <span className="text-sm font-semibold leading-none">{character}</span>
              {showChars ? (
                <span className="mt-1 text-[9px] leading-none tabular opacity-80">
                  {Math.round(confidence * 100)}
                </span>
              ) : null}
            </span>
          );
        })}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Badge variant={plate.min_confidence >= floor ? "good" : "danger"}>
          weakest character {formatPercent(plate.min_confidence)}
        </Badge>
        <span className="text-[11px] text-ink-faint">
          floor to charge anyone: {formatPercent(floor)}
        </span>
        {plate.occluded ? (
          <Badge variant="warn">
            <Minus className="size-3" />
            occluded
          </Badge>
        ) : null}
      </div>
    </div>
  );
}
