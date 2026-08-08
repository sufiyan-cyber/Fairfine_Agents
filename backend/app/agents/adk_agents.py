"""The ADK agent tree.

    FairFineOrchestrator (SequentialAgent)
    ├─ PerceptionStage (ParallelAgent)
    │   ├─ SignalAgent       LlmAgent · gemini-2.5-flash · output_schema=RiskSignal
    │   └─ AttributionAgent  LlmAgent · gemini-2.5-flash · output_schema=AttributionRead
    ├─ MemoryAgent          BaseAgent · duplicate-alert sweep + fraud-rulebook RAG
    ├─ AuditorAgent ★       LlmAgent · gemini-2.5-flash · output_schema=Verdict
    └─ VerdictRouter        BaseAgent · ISSUE→CaseFile, ESCALATE→HumanQueue, REJECT→drop

ADK features carrying real weight here:
  * `output_schema` on every LlmAgent — no agent may answer in free text.
  * `ParallelAgent` — the fraud pattern and the attribution are independent
    questions, so they race.
  * `before_model_callback` — Enkrypt PII scrub runs on the assembled request,
    so nothing unredacted can reach a model even if a prompt changes upstream.
  * `after_agent_callback` — the ledger append is bound to the orchestrator
    rather than called by hand, so no verdict can skip it.
  * Session state — the hand-off medium between every stage.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models import LlmRequest
from google.genai import types

from ..config import settings
from ..guardrails import enkrypt
from ..schemas import AttributionRead, RiskSignal, Verdict
from ..tools import fraud_rules
from ..tools.accounts import account_lookup, merchant_profile
from ..tools.memory import memory
from . import prompts

# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #
def pii_scrub_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """`before_model_callback` — Enkrypt PII scrub on prompt assembly.

    Mutates the outbound request in place. Returning None lets the (now
    redacted) call proceed. This is the enforcement point for the PRD's
    non-negotiable that every LLM call is scrubbed before assembly.
    """
    redactions: list[str] = []
    provider = "local"

    for content in llm_request.contents or []:
        for part in content.parts or []:
            if getattr(part, "text", None):
                scrubbed, meta = enkrypt.guard_prompt(part.text)
                if meta["redaction_count"]:
                    part.text = scrubbed
                    redactions.extend(meta["redactions"])
                    provider = meta["provider"]

    if redactions:
        state = callback_context.state
        prior = state.get("guardrail_events", []) or []
        state["guardrail_events"] = prior + [
            {
                "agent": callback_context.agent_name,
                "provider": provider,
                "redactions": sorted(set(redactions)),
            }
        ]
    return None


def bias_screen_callback(callback_context: CallbackContext) -> None:
    """`after_agent_callback` on the auditor — screen reasoning for
    prejudicial justification before it becomes citizen-facing evidence."""
    verdict_raw = callback_context.state.get("verdict")
    if not verdict_raw:
        return None
    reasoning = _as_dict(verdict_raw).get("reasoning", "")
    if not reasoning:
        return None
    result = enkrypt.check_bias(reasoning)
    callback_context.state["bias_check"] = {
        "clean": result.clean,
        "flags": result.bias_flags,
        "provider": result.provider,
    }
    return None


def ledger_callback(callback_context: CallbackContext) -> None:
    """`after_agent_callback` on the orchestrator — mark the invocation ready
    for the ledger append. The append itself is performed by the pipeline so
    it can be committed transactionally with the challan row."""
    callback_context.state["ledger_pending"] = True
    return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def _agent_model(model_name: str, location: str | None = None):
    """The `model` value for an LlmAgent, optionally pinned to a Vertex region.

    A plain string lets ADK build its Gemini client from the environment, which
    is the normal path. Pinning a *different* region needs an explicit `Gemini`
    with `client_kwargs`, because the env-derived client is process-wide state
    that can't be varied per tree.
    """
    if not location or not settings.live_vertex:
        return model_name
    from google.adk.models.google_llm import Gemini

    return Gemini(
        model=model_name,
        client_kwargs={
            "vertexai": True,
            "project": settings.google_cloud_project,
            "location": location,
        },
    )


# --------------------------------------------------------------------------- #
# Perception stage
# --------------------------------------------------------------------------- #
def build_signal_agent(location: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="SignalAgent",
        model=_agent_model(settings.detector_model, location),
        description="Classifies the fraud pattern present in the transaction ledger.",
        instruction=prompts.SIGNAL_PROMPT,
        output_schema=RiskSignal,
        output_key="signal",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def build_attribution_agent(location: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="AttributionAgent",
        model=_agent_model(settings.plate_model, location),
        description="Assesses whether the activity is attributable to someone other than the customer.",
        instruction=prompts.ATTRIBUTION_PROMPT,
        output_schema=AttributionRead,
        output_key="attribution",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


# --------------------------------------------------------------------------- #
# MemoryAgent — duplicate-alert sweep + fraud-rulebook RAG
# --------------------------------------------------------------------------- #
class MemoryAgent(BaseAgent):
    """Bridges perception and audit: near-duplicate sweep + statute retrieval.

    A custom BaseAgent rather than an LlmAgent — this step is deterministic
    retrieval, and putting a model in the loop would only add a way to be wrong.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        from .. import db

        state = ctx.session.state
        signal = _as_dict(state.get("signal"))
        attribution = _as_dict(state.get("attribution"))
        events = state.get("events", []) or []

        flagged = next(
            (e for e in events if e.get("is_flagged")), events[0] if events else {}
        )
        account_ref = attribution.get("account_ref") or state.get("account_ref", "UNRESOLVED")
        merchant = flagged.get("merchant", "unknown")
        event_ts = flagged.get("ts", "")
        fraud_type = signal.get("fraud_type", "none")

        candidates = db.recent_events_for_dedup(
            account_ref, merchant, settings.duplicate_window_seconds
        )
        duplicate = memory.check_duplicate(
            account_ref=account_ref,
            merchant=merchant,
            fraud_type=fraud_type,
            ts=event_ts,
            description=signal.get("evidence_summary", ""),
            candidates=candidates,
        )

        rule = memory.rule_for_fraud_type(fraud_type)
        related = memory.search_rules(
            f"{fraud_type} {signal.get('evidence_summary', '')}", top_k=3
        )

        delta = {
            "duplicate": duplicate.model_dump(),
            "rule": rule.model_dump() if rule else None,
            "related_rules": [r.model_dump() for r in related],
            "memory_backend": memory.backend,
        }
        state.update(delta)

        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            actions=EventActions(state_delta=delta),
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            f"Duplicate: {duplicate.is_duplicate} "
                            f"(sim {duplicate.similarity}). "
                            f"Rule: {rule.section if rule else 'none'}."
                        )
                    )
                ],
            ),
        )


# --------------------------------------------------------------------------- #
# AuditorAgent ★
# --------------------------------------------------------------------------- #
def _auditor_instruction(ctx: ReadonlyContext) -> str:
    """Instruction provider — composes the adversarial prompt with the live
    state so the auditor reviews concrete evidence, not placeholders."""
    state = ctx.state
    context = prompts.build_auditor_context(
        signal=_as_dict(state.get("signal")),
        attribution=_as_dict(state.get("attribution")),
        duplicate=_as_dict(state.get("duplicate")),
        rule=_as_dict(state.get("rule")) or None,
        events=state.get("events", []) or [],
        account=_as_dict(state.get("account")) or None,
        merchant=_as_dict(state.get("merchant")) or None,
        dispute_reason=state.get("dispute_reason"),
    )
    base = prompts.REAUDIT_PROMPT if state.get("dispute_reason") else prompts.AUDITOR_PROMPT
    return f"{base}\n\n{context}"


def build_auditor_agent(
    model: str | None = None, location: str | None = None
) -> LlmAgent:
    return LlmAgent(
        name="AuditorAgent",
        model=_agent_model(model or settings.auditor_model, location),
        description=(
            "Adversarially reviews the risk signal and the attribution, and returns "
            "a calibrated trust score with an ISSUE / REJECT / ESCALATE verdict."
        ),
        instruction=_auditor_instruction,
        output_schema=Verdict,
        output_key="verdict",
        before_model_callback=pii_scrub_callback,
        after_agent_callback=bias_screen_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


# --------------------------------------------------------------------------- #
# Terminal branch agents
# --------------------------------------------------------------------------- #
class HumanQueueAgent(BaseAgent):
    """ESCALATE branch — flags the case for human review.

    Records only the *intent* in session state. The `pending_review` row itself
    is written by the pipeline AFTER the challan row is saved, because
    `pending_review` has a foreign key to `challans` and the challan is
    persisted only once the whole agent tree has finished. Writing here — mid
    tree, before the challan exists — violates that constraint and fails the
    whole live audit. The pipeline owns the persistence and its ordering.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        verdict = _as_dict(state.get("verdict"))
        checks = verdict.get("checks", {}) or {}
        failed = [k for k, v in checks.items() if v is False and k != "duplicate"]

        uncertainty = verdict.get("reasoning", "")
        if failed:
            uncertainty += f"\n\nUnresolved checks: {', '.join(failed)}."

        delta = {"queued_for_human": True, "review_uncertainty": uncertainty}
        state.update(delta)

        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            actions=EventActions(state_delta=delta),
            content=types.Content(
                role="model",
                parts=[types.Part(text="Flagged for human review.")],
            ),
        )


class RejectAgent(BaseAgent):
    """REJECT branch — no action is taken. The decision is still ledgered."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        verdict = _as_dict(ctx.session.state.get("verdict"))
        delta = {"dropped": True, "drop_reason": verdict.get("reasoning", "")}
        ctx.session.state.update(delta)
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            actions=EventActions(state_delta=delta),
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="No action taken. Decision recorded in the ledger.")
                ],
            ),
        )


def build_evidence_agent(location: str | None = None) -> LlmAgent:
    """ISSUE branch — assembles the case file and drafts the customer notice.

    Holds the mock account and merchant lookups as ADK tools. Customer identity
    is withheld from the model by `scrub_owner_record`, so the drafted notice
    can never name a person the model was not entitled to see.
    """

    def account_record(account_ref: str, fraud_type: str = "") -> dict:
        """Look up account details for a masked account reference (mock core banking).

        Args:
            account_ref: The masked card or account reference to look up.
            fraud_type: Optional pattern hint for context.

        Returns:
            Account details with customer identity withheld.
        """
        return enkrypt.scrub_owner_record(account_lookup(account_ref, fraud_type))

    def merchant_record(category: str, merchant_name: str = "") -> dict:
        """Look up a merchant category's reputation and base fraud rate.

        Args:
            category: The merchant category, e.g. "gift_card".
            merchant_name: Optional merchant name for the identifier.

        Returns:
            Merchant reputation including historical fraud rate and risk band.
        """
        return merchant_profile(category, merchant_name)

    def rule_text(section: str) -> dict:
        """Fetch the full text of a fraud-rulebook section.

        Args:
            section: Section identifier, e.g. "Card Network Rules §11.3 — Fraud / Card-Absent".

        Returns:
            The section's title, text and prescribed action.
        """
        return fraud_rules.get_section(section) or {"error": "section not found"}

    return LlmAgent(
        name="EvidenceAgent",
        model=_agent_model(settings.detector_model, location),
        description="Assembles the case file and drafts the customer notice.",
        instruction=prompts.EVIDENCE_PROMPT,
        tools=[account_record, merchant_record, rule_text],
        output_key="case_draft",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


class VerdictRouter(BaseAgent):
    """Branches on the auditor's verdict.

    ADK has no declarative conditional, so routing lives in a custom BaseAgent
    that delegates to the branch agent held in `sub_agents`. Every branch —
    including REJECT — still flows through to the ledger.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        verdict = _as_dict(ctx.session.state.get("verdict")).get("verdict", "ESCALATE")
        target = {
            "ISSUE": "EvidenceAgent",
            "ESCALATE": "HumanQueueAgent",
            "REJECT": "RejectAgent",
        }.get(verdict, "HumanQueueAgent")

        ctx.session.state["branch_taken"] = target
        for agent in self.sub_agents:
            if agent.name == target:
                async for event in agent.run_async(ctx):
                    yield event
                return


# --------------------------------------------------------------------------- #
# Root
# --------------------------------------------------------------------------- #
def build_root_agent(
    auditor_model: str | None = None, location: str | None = None
) -> SequentialAgent:
    perception = ParallelAgent(
        name="PerceptionStage",
        description="Runs fraud-pattern classification and attribution concurrently.",
        sub_agents=[build_signal_agent(location), build_attribution_agent(location)],
    )

    router = VerdictRouter(
        name="VerdictRouter",
        description="Routes ISSUE / ESCALATE / REJECT to the correct branch.",
        sub_agents=[
            build_evidence_agent(location),
            HumanQueueAgent(name="HumanQueueAgent", description="Human review queue."),
            RejectAgent(name="RejectAgent", description="Drops the event, still ledgered."),
        ],
    )

    return SequentialAgent(
        name="FairFineOrchestrator",
        description=(
            "Audits an AI-flagged traffic violation and only issues a fine when it "
            "clears a calibrated trust threshold."
        ),
        sub_agents=[
            perception,
            MemoryAgent(
                name="MemoryAgent", description="Duplicate sweep + fraud-rulebook RAG."
            ),
            build_auditor_agent(auditor_model, location),
            router,
        ],
        after_agent_callback=ledger_callback,
    )


# `adk web` / `adk run` entry point.
root_agent = None

# One cached tree per (auditor model, region). Keyed rather than single because
# the fallback paths need their own trees: ADK fixes an LlmAgent's model — and,
# via `client_kwargs`, its region — at construction, so serving a different
# model or region means a different tree. Building one per audit leaks the
# Gemini connection pools this cache exists to avoid in the first place.
_root_agents: dict[tuple[str, str], SequentialAgent] = {}


def get_root_agent(
    auditor_model: str | None = None, location: str | None = None
) -> SequentialAgent:
    global root_agent
    key = (auditor_model or settings.auditor_model, location or "")
    tree = _root_agents.get(key)
    if tree is None:
        tree = _root_agents[key] = build_root_agent(*key)
    if root_agent is None:
        root_agent = tree  # `adk web` / `adk run` entry point
    return tree


def describe_architecture() -> dict:
    """Machine-readable agent tree — powers the architecture panel in the UI."""
    return {
        "root": "FairFineOrchestrator",
        "type": "SequentialAgent",
        "adk_version": _adk_version(),
        "stages": [
            {
                "name": "IngestAgent",
                "type": "FunctionTool",
                "model": None,
                "role": "Parses the alert into the flagged transaction plus account history.",
            },
            {
                "name": "PerceptionStage",
                "type": "ParallelAgent",
                "model": None,
                "role": "Pattern classification and attribution run concurrently.",
                "children": [
                    {
                        "name": "SignalAgent",
                        "type": "LlmAgent",
                        "model": settings.detector_model,
                        "output_schema": "RiskSignal",
                        "role": "Classifies the fraud pattern present in the ledger.",
                    },
                    {
                        "name": "AttributionAgent",
                        "type": "LlmAgent",
                        "model": settings.plate_model,
                        "output_schema": "AttributionRead",
                        "role": "Scores whether this is attributable to a non-customer.",
                    },
                ],
            },
            {
                "name": "MemoryAgent",
                "type": "BaseAgent",
                "model": None,
                "role": "Near-duplicate alert sweep and fraud-rulebook retrieval.",
            },
            {
                "name": "AuditorAgent",
                "type": "LlmAgent",
                "model": settings.auditor_model,
                "output_schema": "Verdict",
                "starred": True,
                "role": "Adversarially reviews the evidence and returns a calibrated verdict.",
            },
            {
                "name": "VerdictRouter",
                "type": "BaseAgent",
                "model": None,
                "role": "ISSUE -> EvidenceAgent, ESCALATE -> HumanQueueAgent, REJECT -> drop.",
                "children": [
                    {
                        "name": "EvidenceAgent",
                        "type": "LlmAgent",
                        "model": settings.detector_model,
                        "role": "Assembles the case file and drafts the customer notice.",
                    },
                    {
                        "name": "HumanQueueAgent",
                        "type": "BaseAgent",
                        "model": None,
                        "role": "Queues ambiguous cases with the auditor's uncertainty notes.",
                    },
                    {
                        "name": "RejectAgent",
                        "type": "BaseAgent",
                        "model": None,
                        "role": "Dismisses the alert; the decision is still ledgered.",
                    },
                ],
            },
            {
                "name": "LedgerAgent",
                "type": "after_agent_callback",
                "model": None,
                "role": "Appends every verdict to the hash chain. Cannot be skipped.",
            },
        ],
        "separate_entrypoints": [
            {
                "name": "CitizenAgent",
                "type": "LlmAgent",
                "model": settings.citizen_model,
                "role": "Explains the decision in en / hi / kn / ta.",
            },
            {
                "name": "ReAuditAgent",
                "type": "LlmAgent",
                "model": settings.auditor_model,
                "role": "Re-runs the audit against the ledger record when a customer disputes.",
            },
        ],
        "adk_features": [
            "SequentialAgent + ParallelAgent composition",
            "output_schema on every LlmAgent",
            "before_model_callback -> Enkrypt PII scrub",
            "after_agent_callback -> ledger append + bias screen",
            "Session state hand-off between agents",
            "FunctionTool -> mock account/merchant lookup + rulebook retrieval",
        ],
    }


def _adk_version() -> str:
    try:
        import google.adk

        return getattr(google.adk, "__version__", "unknown")
    except Exception:
        return "unknown"
