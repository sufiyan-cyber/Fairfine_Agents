"""Structured contracts for every agent hand-off.

These are the `output_schema` targets on the ADK LlmAgents — no agent in the
pipeline is allowed to answer in free text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ViolationType = Literal[
    "red_light_jump",
    "no_helmet",
    "wrong_side",
    "triple_riding",
    "no_seatbelt",
    "phone_use",
    "none",
]

VerdictType = Literal["ISSUE", "REJECT", "ESCALATE"]

Language = Literal["en", "hi", "kn", "ta"]


# --------------------------------------------------------------------------- #
# PRD §5 core schemas
# --------------------------------------------------------------------------- #
class Frame(BaseModel):
    path: str
    ts: str = Field(description="ISO-8601 capture time")
    camera_id: str
    location: str = Field(description="'lat,lng' or a named junction")


class Detection(BaseModel):
    violation_type: ViolationType
    region_description: str = Field(
        description="Where in the frame the violation appears, in plain words"
    )
    raw_confidence: float = Field(ge=0.0, le=1.0)
    frame_ref: str = Field(description="Which frame(s) evidence the call")


class PlateRead(BaseModel):
    plate: str
    per_char_confidence: list[float] = Field(default_factory=list)
    min_confidence: float = Field(ge=0.0, le=1.0)
    occluded: bool = False


class VerdictChecks(BaseModel):
    visually_confirmed: bool
    plate_reliable: bool
    duplicate: bool
    rule_applies: bool
    environment_ok: bool


class Verdict(BaseModel):
    verdict: VerdictType
    trust_score: float = Field(ge=0.0, le=1.0, description="Calibrated, not raw")
    reasoning: str = Field(description="Citizen-facing plain English")
    checks: VerdictChecks


class EvidencePacket(BaseModel):
    challan_id: str
    plate: str
    owner_masked: str
    violation_type: str
    location: str
    ts: str
    trust_score: float
    reasoning: str
    rule_citation: str
    frames: list[str] = Field(default_factory=list)
    ledger_hash: str


class LedgerRecord(BaseModel):
    id: str
    prev_hash: str
    payload: dict
    hash: str
    ts: str


# --------------------------------------------------------------------------- #
# Supporting contracts
# --------------------------------------------------------------------------- #
class DuplicateCheck(BaseModel):
    """Result of the Qdrant near-duplicate sweep."""

    is_duplicate: bool = False
    similarity: float = 0.0
    matched_challan_id: str | None = None
    matched_ts: str | None = None
    seconds_apart: float | None = None
    note: str = ""


class RuleCitation(BaseModel):
    section: str
    title: str
    text: str
    penalty: str = ""
    relevance: float = 0.0


class AuditTrace(BaseModel):
    """One row in the live agent trace shown in the officer console."""

    agent: str
    status: Literal["pending", "running", "done", "skipped", "error"]
    label: str
    detail: str = ""
    output: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class NaiveComparison(BaseModel):
    """What a confidence-threshold-only system would have done. Demo drama."""

    would_issue: bool
    basis: str
    fine_amount: int = 0


class AuditResult(BaseModel):
    challan_id: str
    mode: str
    verdict: Verdict
    detection: Detection
    plate: PlateRead
    frames: list[Frame] = Field(default_factory=list)
    duplicate: DuplicateCheck
    rule: RuleCitation | None = None
    evidence: EvidencePacket | None = None
    ledger_id: str = ""
    ledger_hash: str = ""
    frames_sha256: str = ""
    trace: list[AuditTrace] = Field(default_factory=list)
    naive: NaiveComparison | None = None
    created_at: str = ""


class CitizenView(BaseModel):
    challan_id: str
    language: Language
    headline: str
    explanation: str
    what_this_means: str
    your_options: list[str] = Field(default_factory=list)
    violation_label: str
    trust_score: float
    verdict: VerdictType
    plate: str
    owner_masked: str
    location: str
    ts: str
    rule_citation: str
    rule_text: str = ""
    auditor_reasoning: str
    checks: VerdictChecks
    frames: list[str] = Field(default_factory=list)
    ledger_hash: str
    fine_amount: int = 0
    disputable: bool = True
    dispute_status: str | None = None


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)
    language: Language = "en"


class DisputeOutcome(BaseModel):
    challan_id: str
    original_verdict: VerdictType
    new_verdict: VerdictType
    changed: bool
    trust_score: float
    reasoning: str
    checks: VerdictChecks
    ledger_hash: str
    ledger_id: str
    reviewed_at: str


class LedgerVerification(BaseModel):
    valid: bool
    records_checked: int
    broken_at: str | None = None
    reason: str | None = None
    head_hash: str | None = None


class BiasSlice(BaseModel):
    key: str
    total: int
    issued: int
    rejected: int
    escalated: int
    false_positive_rate: float = Field(
        description="Share of AI-flagged events the auditor stopped before a fine"
    )
    avg_trust: float = 0.0


class BiasDashboard(BaseModel):
    generated_at: str
    total_events: int
    issued: int
    rejected: int
    escalated: int
    wrongful_fines_prevented: int
    prevention_rate: float
    by_area: list[BiasSlice] = Field(default_factory=list)
    by_vehicle_type: list[BiasSlice] = Field(default_factory=list)
    by_violation_type: list[BiasSlice] = Field(default_factory=list)
    by_hour: list[BiasSlice] = Field(default_factory=list)
    over_time: list[dict] = Field(default_factory=list)
