"""Structured contracts for every agent hand-off.

These are the `output_schema` targets on the ADK LlmAgents — no agent in the
pipeline is allowed to answer in free text.

A note on the verdict vocabulary. `ISSUE` / `ESCALATE` / `REJECT` are the
decision the auditor reaches about the monitoring system's fraud alert:
uphold it and act against the account, send it to a human, or dismiss it and
let the transaction stand. The action layer renders these as BLOCK / REVIEW /
ALLOW, which is how a fraud-operations analyst says the same three things.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FraudType = Literal[
    "card_testing",
    "account_takeover",
    "stolen_card_use",
    "impossible_travel",
    "merchant_anomaly",
    "structuring",
    "none",
]

VerdictType = Literal["ISSUE", "REJECT", "ESCALATE"]

Language = Literal["en", "hi", "kn", "ta"]


# --------------------------------------------------------------------------- #
# Core schemas
# --------------------------------------------------------------------------- #
class TxnEvent(BaseModel):
    """One transaction in the case file — flagged or surrounding history."""

    event_id: str
    ts: str = Field(description="ISO-8601 authorisation time")
    amount: float
    currency: str = "INR"
    merchant: str = ""
    category: str = Field(default="uncategorised", description="Merchant category")
    channel: str = Field(default="ecom", description="card_present | ecom | atm | transfer")
    device_id: str = ""
    city: str = ""
    country: str = "IN"
    status: str = "approved"
    is_flagged: bool = False


class RiskSignal(BaseModel):
    """What fraud pattern the perception stage believes it is looking at."""

    fraud_type: FraudType
    evidence_summary: str = Field(
        description="Which transactions support the call, and what makes them suspicious"
    )
    raw_confidence: float = Field(ge=0.0, le=1.0)
    event_ref: str = Field(description="Which event(s) evidence the call")


class AttributionRead(BaseModel):
    """Can this be attributed to someone other than the genuine customer?

    The direct analogue of a plate read in automated enforcement: the pattern
    may be real while the attribution is not, and acting on an unreliable
    attribution is how an innocent customer loses access to their money.
    """

    account_ref: str
    indicators: list[str] = Field(
        default_factory=list, description="Behavioural indicators actually checked"
    )
    per_indicator_confidence: list[float] = Field(default_factory=list)
    min_confidence: float = Field(
        ge=0.0, le=1.0, description="Weakest indicator — governs whether we may act"
    )
    matches_known_behaviour: bool = Field(
        default=False, description="True when this looks like the customer's own pattern"
    )
    ambiguous: bool = False


class VerdictChecks(BaseModel):
    pattern_confirmed: bool
    attribution_reliable: bool
    duplicate: bool
    rule_applies: bool
    context_ok: bool


class Verdict(BaseModel):
    verdict: VerdictType
    trust_score: float = Field(ge=0.0, le=1.0, description="Calibrated, not raw")
    reasoning: str = Field(description="Customer-facing plain English")
    checks: VerdictChecks


class EvidencePacket(BaseModel):
    challan_id: str
    account_ref: str
    customer_masked: str
    fraud_type: str
    merchant: str
    ts: str
    trust_score: float
    reasoning: str
    rule_citation: str
    events: list[str] = Field(default_factory=list)
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
    """Result of the semantic near-duplicate sweep over recent alerts."""

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
    """One row in the live agent trace shown in the analyst console."""

    agent: str
    status: Literal["pending", "running", "done", "skipped", "error"]
    label: str
    detail: str = ""
    output: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class NaiveComparison(BaseModel):
    """What a score-threshold-only engine would have done. Demo drama."""

    would_issue: bool
    basis: str
    amount_held: float = 0.0


class AuditResult(BaseModel):
    challan_id: str
    mode: str
    verdict: Verdict
    signal: RiskSignal
    attribution: AttributionRead
    events: list[TxnEvent] = Field(default_factory=list)
    duplicate: DuplicateCheck
    rule: RuleCitation | None = None
    evidence: EvidencePacket | None = None
    ledger_id: str = ""
    ledger_hash: str = ""
    events_sha256: str = ""
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
    fraud_label: str
    trust_score: float
    verdict: VerdictType
    account_ref: str
    customer_masked: str
    merchant: str
    ts: str
    rule_citation: str
    rule_text: str = ""
    auditor_reasoning: str
    checks: VerdictChecks
    events: list[TxnEvent] = Field(default_factory=list)
    ledger_hash: str
    amount_held: float = 0.0
    disputable: bool = True
    dispute_status: str | None = None


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)
    language: Language = "en"


class ReviewDecision(BaseModel):
    """An analyst closing an escalated case.

    `note` is required and has a floor, because a decision with no stated
    reason is the failure mode this queue exists to prevent.
    """

    decision: Literal["ISSUE", "REJECT"]
    officer: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=10, max_length=4000)


class ReviewOutcome(BaseModel):
    review_id: str
    challan_id: str
    decision: Literal["ISSUE", "REJECT"]
    officer: str
    note: str
    decided_at: str
    ledger_id: str
    ledger_hash: str


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
        description="Share of alerts the auditor stopped before the account was blocked"
    )
    avg_trust: float = 0.0


class BiasDashboard(BaseModel):
    generated_at: str
    total_events: int
    issued: int
    rejected: int
    escalated: int
    wrongful_blocks_prevented: int
    prevention_rate: float
    amount_protected: float = 0.0
    by_region: list[BiasSlice] = Field(default_factory=list)
    by_segment: list[BiasSlice] = Field(default_factory=list)
    by_fraud_type: list[BiasSlice] = Field(default_factory=list)
    by_hour: list[BiasSlice] = Field(default_factory=list)
    over_time: list[dict] = Field(default_factory=list)
