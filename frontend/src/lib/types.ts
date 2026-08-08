export type VerdictType = "ISSUE" | "REJECT" | "ESCALATE";
export type Language = "en" | "hi" | "kn" | "ta";
export type TraceStatus = "pending" | "running" | "done" | "skipped" | "error";

export interface TxnEvent {
  event_id: string;
  ts: string;
  amount: number;
  currency: string;
  merchant: string;
  category: string;
  channel: string;
  device_id: string;
  city: string;
  country: string;
  status: string;
  is_flagged: boolean;
}

export interface RiskSignal {
  fraud_type: string;
  evidence_summary: string;
  raw_confidence: number;
  event_ref: string;
}

export interface AttributionRead {
  account_ref: string;
  indicators: string[];
  per_indicator_confidence: number[];
  min_confidence: number;
  matches_known_behaviour: boolean;
  ambiguous: boolean;
}

export interface VerdictChecks {
  pattern_confirmed: boolean;
  attribution_reliable: boolean;
  duplicate: boolean;
  rule_applies: boolean;
  context_ok: boolean;
}

export interface Verdict {
  verdict: VerdictType;
  trust_score: number;
  reasoning: string;
  checks: VerdictChecks;
}

export interface DuplicateCheck {
  is_duplicate: boolean;
  similarity: number;
  matched_challan_id: string | null;
  matched_ts: string | null;
  seconds_apart: number | null;
  note: string;
}

export interface RuleCitation {
  section: string;
  title: string;
  text: string;
  penalty: string;
  relevance: number;
}

export interface AuditTrace {
  agent: string;
  status: TraceStatus;
  label: string;
  detail: string;
  output: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface NaiveComparison {
  would_issue: boolean;
  basis: string;
  amount_held: number;
}

export interface EvidencePacket {
  challan_id: string;
  account_ref: string;
  customer_masked: string;
  fraud_type: string;
  merchant: string;
  ts: string;
  trust_score: number;
  reasoning: string;
  rule_citation: string;
  events: string[];
  ledger_hash: string;
}

export interface AuditResult {
  challan_id: string;
  mode: string;
  verdict: Verdict;
  signal: RiskSignal;
  attribution: AttributionRead;
  events: TxnEvent[];
  duplicate: DuplicateCheck;
  rule: RuleCitation | null;
  evidence: EvidencePacket | null;
  ledger_id: string;
  ledger_hash: string;
  events_sha256?: string;
  trace: AuditTrace[];
  naive: NaiveComparison | null;
  created_at: string;
  amount_held?: number;
  flagged_amount?: number;
  account?: Record<string, unknown> & { customer_masked?: string };
  merchant_profile?: Record<string, unknown>;
  scenario?: string;
  review_id?: string | null;
}

export interface CitizenView {
  challan_id: string;
  language: Language;
  headline: string;
  explanation: string;
  what_this_means: string;
  your_options: string[];
  fraud_label: string;
  trust_score: number;
  verdict: VerdictType;
  account_ref: string;
  customer_masked: string;
  merchant: string;
  ts: string;
  rule_citation: string;
  rule_text: string;
  auditor_reasoning: string;
  checks: VerdictChecks;
  events: TxnEvent[];
  ledger_hash: string;
  amount_held: number;
  disputable: boolean;
  dispute_status: string | null;
}

export interface PendingReview {
  id: string;
  challan_id: string;
  uncertainty: string;
  trust_score: number;
  status: string;
  decision: string;
  officer: string;
  note: string;
  decided_at: string;
  created_at: string;
}

export interface ReviewOutcome {
  review_id: string;
  challan_id: string;
  decision: "ISSUE" | "REJECT";
  officer: string;
  note: string;
  decided_at: string;
  ledger_id: string;
  ledger_hash: string;
}

export interface DisputeOutcome {
  challan_id: string;
  original_verdict: VerdictType;
  new_verdict: VerdictType;
  changed: boolean;
  trust_score: number;
  reasoning: string;
  checks: VerdictChecks;
  ledger_hash: string;
  ledger_id: string;
  reviewed_at: string;
}

export interface LedgerRecord {
  seq: number;
  id: string;
  prev_hash: string;
  payload: Record<string, unknown>;
  hash: string;
  ts: string;
}

export interface LedgerVerification {
  valid: boolean;
  records_checked: number;
  broken_at: string | null;
  reason: string | null;
  head_hash: string | null;
}

export interface BiasSlice {
  key: string;
  total: number;
  issued: number;
  rejected: number;
  escalated: number;
  false_positive_rate: number;
  avg_trust: number;
}

export interface BiasDashboard {
  generated_at: string;
  total_events: number;
  issued: number;
  rejected: number;
  escalated: number;
  wrongful_blocks_prevented: number;
  prevention_rate: number;
  amount_protected: number;
  by_region: BiasSlice[];
  by_segment: BiasSlice[];
  by_fraud_type: BiasSlice[];
  by_hour: BiasSlice[];
  over_time: Array<{
    index: number;
    challan_id: string;
    ts: string;
    verdict: VerdictType;
    trust_score: number;
    prevention_rate: number;
  }>;
}

export interface ChallanSummary {
  challan_id: string;
  verdict: VerdictType;
  trust_score: number;
  fraud_type: string;
  fraud_label: string;
  account_ref: string;
  merchant: string;
  region: string;
  segment: string;
  event_ts: string;
  ledger_hash: string;
  created_at: string;
  amount_held: number;
}

export interface AgentNode {
  name: string;
  type: string;
  model: string | null;
  role: string;
  output_schema?: string;
  starred?: boolean;
  children?: AgentNode[];
}

export interface Architecture {
  root: string;
  type: string;
  adk_version: string;
  mode: string;
  stages: AgentNode[];
  separate_entrypoints: AgentNode[];
  adk_features: string[];
  capabilities: Record<string, string>;
  thresholds: {
    issue_trust_threshold: number;
    escalate_trust_floor: number;
    attribution_confidence_floor: number;
    duplicate_window_seconds: number;
  };
}

export interface Health {
  status: string;
  mode: string;
  capabilities: Record<string, string>;
}
