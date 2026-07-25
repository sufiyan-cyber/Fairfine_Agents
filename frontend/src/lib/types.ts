export type VerdictType = "ISSUE" | "REJECT" | "ESCALATE";
export type Language = "en" | "hi" | "kn" | "ta";
export type TraceStatus = "pending" | "running" | "done" | "skipped" | "error";

export interface Frame {
  path: string;
  ts: string;
  camera_id: string;
  location: string;
}

export interface Detection {
  violation_type: string;
  region_description: string;
  raw_confidence: number;
  frame_ref: string;
}

export interface PlateRead {
  plate: string;
  per_char_confidence: number[];
  min_confidence: number;
  occluded: boolean;
}

export interface VerdictChecks {
  visually_confirmed: boolean;
  plate_reliable: boolean;
  duplicate: boolean;
  rule_applies: boolean;
  environment_ok: boolean;
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
  fine_amount: number;
}

export interface EvidencePacket {
  challan_id: string;
  plate: string;
  owner_masked: string;
  violation_type: string;
  location: string;
  ts: string;
  trust_score: number;
  reasoning: string;
  rule_citation: string;
  frames: string[];
  ledger_hash: string;
}

export interface AuditResult {
  challan_id: string;
  mode: string;
  verdict: Verdict;
  detection: Detection;
  plate: PlateRead;
  frames: Frame[];
  duplicate: DuplicateCheck;
  rule: RuleCitation | null;
  evidence: EvidencePacket | null;
  ledger_id: string;
  ledger_hash: string;
  trace: AuditTrace[];
  naive: NaiveComparison | null;
  created_at: string;
  frame_uris?: string[];
  fine_amount?: number;
  registry?: Record<string, unknown> & { owner_masked?: string };
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
  violation_label: string;
  trust_score: number;
  verdict: VerdictType;
  plate: string;
  owner_masked: string;
  location: string;
  ts: string;
  rule_citation: string;
  rule_text: string;
  auditor_reasoning: string;
  checks: VerdictChecks;
  frames: string[];
  ledger_hash: string;
  fine_amount: number;
  disputable: boolean;
  dispute_status: string | null;
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
  wrongful_fines_prevented: number;
  prevention_rate: number;
  by_area: BiasSlice[];
  by_vehicle_type: BiasSlice[];
  by_violation_type: BiasSlice[];
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
  violation_type: string;
  violation_label: string;
  plate: string;
  location: string;
  area: string;
  vehicle_type: string;
  event_ts: string;
  ledger_hash: string;
  created_at: string;
  fine_amount: number;
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
    plate_confidence_floor: number;
    duplicate_window_seconds: number;
  };
}

export interface Health {
  status: string;
  mode: string;
  capabilities: Record<string, string>;
}
