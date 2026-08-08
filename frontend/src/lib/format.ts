import type { VerdictType } from "./types";

/**
 * Verdict presentation, read from the customer's side.
 *
 * The internal vocabulary is ISSUE / ESCALATE / REJECT — the auditor's ruling
 * on the monitoring system's alert. What an analyst says out loud is BLOCK /
 * REVIEW / ALLOW, so that is what the interface shows. REJECT is the good
 * outcome: a wrongful block was prevented.
 */
export const VERDICT_META: Record<
  VerdictType,
  {
    label: string;
    short: string;
    tone: "good" | "warn" | "danger";
    text: string;
    bg: string;
    border: string;
    dot: string;
    description: string;
  }
> = {
  ISSUE: {
    label: "Transaction blocked",
    short: "BLOCK",
    tone: "danger",
    text: "text-danger",
    bg: "bg-danger/10",
    border: "border-danger/35",
    dot: "bg-danger",
    description: "Evidence cleared every check and the trust threshold.",
  },
  ESCALATE: {
    label: "Held for human review",
    short: "REVIEW",
    tone: "warn",
    text: "text-warn",
    bg: "bg-warn/10",
    border: "border-warn/35",
    dot: "bg-warn",
    description: "Genuine doubt remains. Nothing is held until a person decides.",
  },
  REJECT: {
    label: "Allowed — alert dismissed",
    short: "ALLOW",
    tone: "good",
    text: "text-good",
    bg: "bg-good/10",
    border: "border-good/35",
    dot: "bg-good",
    description: "A check failed. A wrongful block was prevented.",
  },
};

export const LANGUAGES: Array<{ code: "en" | "hi" | "kn" | "ta"; label: string; native: string }> = [
  { code: "en", label: "English", native: "English" },
  { code: "hi", label: "Hindi", native: "हिन्दी" },
  { code: "kn", label: "Kannada", native: "ಕನ್ನಡ" },
  { code: "ta", label: "Tamil", native: "தமிழ்" },
];

export const CHECK_LABELS: Record<string, { label: string; goodWhen: boolean; help: string }> = {
  pattern_confirmed: {
    label: "Fraud pattern confirmed",
    goodWhen: true,
    help: "The pattern is real in the ledger — not a batch-settlement artifact or a truncated history.",
  },
  attribution_reliable: {
    label: "Attribution reliable",
    goodWhen: true,
    help: "Every indicator cleared the 85% floor required before acting against an account.",
  },
  duplicate: {
    label: "Not a duplicate",
    goodWhen: false,
    help: "No near-identical alert on this account at this merchant in the last 60 seconds.",
  },
  rule_applies: {
    label: "Cited rule applies",
    goodWhen: true,
    help: "The rulebook section actually governs the pattern that was found.",
  },
  context_ok: {
    label: "Account context supports it",
    goodWhen: true,
    help: "Tenure, prior wrongful blocks and merchant base rates do not undermine the case.",
  },
};

export function checkPassed(key: string, value: boolean): boolean {
  const meta = CHECK_LABELS[key];
  return meta ? value === meta.goodWhen : Boolean(value);
}

export function formatPercent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatRupees(amount: number): string {
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

export function formatDateTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function truncateHash(hash: string, head = 10, tail = 6): string {
  if (!hash) return "—";
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** Colour ramp for a 0..1 confidence value, used on per-indicator scores. */
export function confidenceTone(value: number, floor = 0.85): string {
  if (value >= floor) return "text-good border-good/40 bg-good/10";
  if (value >= 0.6) return "text-warn border-warn/40 bg-warn/10";
  return "text-danger border-danger/40 bg-danger/10";
}
