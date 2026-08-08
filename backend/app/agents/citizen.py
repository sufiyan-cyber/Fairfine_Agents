"""CitizenAgent + ReAuditAgent — the two separate entrypoints.

CitizenAgent turns a stored verdict into an explanation the affected person can
actually act on, in their own language. ReAuditAgent re-decides a contested case
against the stored evidence, and whatever it concludes is appended to the chain
next to the original — so a reversal is permanently visible rather than quietly
replacing history.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from .. import db
from ..config import settings
from ..guardrails import enkrypt
from ..retry import with_retry
from ..schemas import (
    AttributionRead,
    CitizenView,
    DisputeOutcome,
    DuplicateCheck,
    RiskSignal,
    Verdict,
)
from ..tools import fraud_rules
from ..tools.memory import memory
from . import prompts, simulator
from .adk_agents import _as_dict, pii_scrub_callback


class CitizenExplanation(BaseModel):
    """`output_schema` for the CitizenAgent."""

    headline: str = Field(description="One short line, under 12 words")
    explanation: str = Field(description="2-4 sentences on what was seen and decided")
    what_this_means: str = Field(description="1-2 sentences on the practical consequence")
    your_options: list[str] = Field(description="Concrete actions, in the reader's language")


def build_citizen_agent():
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name="CitizenAgent",
        model=settings.citizen_model,
        description="Explains an enforcement decision to the citizen it affects.",
        instruction=prompts.CITIZEN_PROMPT,
        output_schema=CitizenExplanation,
        output_key="citizen_explanation",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


async def _run_single_agent(agent, context: str, session_id: str) -> dict:
    """Run one LlmAgent to completion and return its structured output.

    Retried on transient Gemini failures — this path serves the citizen
    explanation and the dispute re-audit, the two screens a citizen is looking
    at when they are already unhappy.
    """
    return await with_retry(
        lambda: _run_single_agent_once(agent, context, session_id),
        label=agent.name,
    )


async def _run_single_agent_once(agent, context: str, session_id: str) -> dict:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="fairfine", user_id="citizen", session_id=session_id, state={}
    )
    runner = Runner(app_name="fairfine", agent=agent, session_service=session_service)

    async for _event in runner.run_async(
        user_id="citizen",
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=context)]),
    ):
        pass

    session = await session_service.get_session(
        app_name="fairfine", user_id="citizen", session_id=session_id
    )
    state = dict(session.state) if session else {}
    return _as_dict(state.get(agent.output_key))


# --------------------------------------------------------------------------- #
# CitizenAgent
# --------------------------------------------------------------------------- #
async def explain(challan_id: str, language: str = "en") -> CitizenView | None:
    record = await asyncio.to_thread(db.get_challan, challan_id)
    if not record:
        return None

    result = record["result"]
    verdict = _as_dict(result.get("verdict"))
    signal = _as_dict(result.get("signal"))
    attribution = _as_dict(result.get("attribution"))
    rule = _as_dict(result.get("rule"))
    account = result.get("account", {}) or {}
    amount_held = float(result.get("amount_held", 0) or 0)
    verdict_type = verdict.get("verdict", "ESCALATE")

    disputes = await asyncio.to_thread(db.get_disputes, challan_id)
    dispute_status = None
    if disputes:
        latest = disputes[0]
        dispute_status = (
            f"Reviewed — verdict changed from {latest['original']} to {latest['outcome']}"
            if latest["changed"]
            else f"Reviewed — original {latest['original']} verdict upheld"
        )

    packet = {
        "verdict": verdict_type,
        "trust_score": verdict.get("trust_score", 0.0),
        "fraud_label": fraud_rules.label_for(signal.get("fraud_type", "none")),
        "account_ref": attribution.get("account_ref", ""),
        "merchant": record["merchant"],
        "ts": record["event_ts"],
        "amount_held": amount_held,
        "reasoning": verdict.get("reasoning", ""),
        "checks": verdict.get("checks", {}),
        "ledger_hash": record["ledger_hash"],
    }

    written: dict | None = None
    if settings.live_llm:
        try:
            written = await _run_single_agent(
                build_citizen_agent(),
                prompts.build_citizen_context(packet, language, rule or None),
                f"cit_{challan_id}_{language}",
            )
        except Exception:
            written = None

    if not written:
        written = simulator.citizen_view(
            verdict=verdict_type,
            language=language,
            amount_held=amount_held,
            account_ref=attribution.get("account_ref", ""),
            reasoning_en=verdict.get("reasoning", ""),
        )

    return CitizenView(
        challan_id=challan_id,
        language=language,  # type: ignore[arg-type]
        headline=written.get("headline", ""),
        explanation=written.get("explanation", ""),
        what_this_means=written.get("what_this_means", ""),
        your_options=written.get("your_options", []),
        fraud_label=packet["fraud_label"],
        trust_score=float(packet["trust_score"]),
        verdict=verdict_type,  # type: ignore[arg-type]
        account_ref=packet["account_ref"],
        customer_masked=account.get("customer_masked", "—"),
        merchant=packet["merchant"],
        ts=packet["ts"],
        rule_citation=rule.get("section", "") if rule else "",
        rule_text=rule.get("text", "") if rule else "",
        auditor_reasoning=verdict.get("reasoning", ""),
        checks=verdict.get("checks", {}),  # type: ignore[arg-type]
        events=result.get("events", []),
        ledger_hash=record["ledger_hash"],
        amount_held=amount_held,
        disputable=verdict_type in {"ISSUE", "ESCALATE"},
        dispute_status=dispute_status,
    )


# --------------------------------------------------------------------------- #
# ReAuditAgent
# --------------------------------------------------------------------------- #
async def reaudit(challan_id: str, reason: str) -> DisputeOutcome | None:
    """Re-run the audit against the stored evidence, with the dispute in view."""
    record = await asyncio.to_thread(db.get_challan, challan_id)
    if not record:
        return None

    result = record["result"]
    signal = RiskSignal(**_as_dict(result.get("signal")))
    attribution = AttributionRead(**_as_dict(result.get("attribution")))
    duplicate = DuplicateCheck(**_as_dict(result.get("duplicate")))
    original = _as_dict(result.get("verdict"))
    original_verdict = original.get("verdict", "ESCALATE")
    rule = memory.rule_for_fraud_type(signal.fraud_type)
    scenario = result.get("scenario", "clean")

    # The customer's words go into a prompt — scrub before assembly, per the
    # PRD's non-negotiable. Redacting here also protects the disputant if they
    # paste a card number or Aadhaar into the free-text box.
    guarded = enkrypt.redact_pii(reason)
    safe_reason = guarded.text

    new_verdict: Verdict | None = None
    if settings.live_llm:
        try:
            from google.adk.agents import LlmAgent

            context = prompts.build_auditor_context(
                signal=signal.model_dump(),
                attribution=attribution.model_dump(),
                duplicate=duplicate.model_dump(),
                rule=rule.model_dump() if rule else None,
                events=result.get("events", []),
                account=result.get("account") or None,
                merchant=result.get("merchant_profile") or None,
                dispute_reason=safe_reason,
            )
            agent = LlmAgent(
                name="ReAuditAgent",
                model=settings.auditor_model,
                description="Re-decides a contested fraud decision.",
                instruction=f"{prompts.REAUDIT_PROMPT}\n\n{context}",
                output_schema=Verdict,
                output_key="verdict",
                before_model_callback=pii_scrub_callback,
                disallow_transfer_to_parent=True,
                disallow_transfer_to_peers=True,
            )
            raw = await _run_single_agent(agent, context, f"re_{challan_id}")
            if raw:
                new_verdict = Verdict(**raw)
        except Exception:
            new_verdict = None

    if new_verdict is None:
        new_verdict = simulator.audit(
            scenario,
            signal,
            attribution,
            duplicate,
            rule.section if rule else None,
            dispute_reason=safe_reason,
        )

    changed = new_verdict.verdict != original_verdict

    # Append the re-audit to the chain. The original record is never mutated —
    # both decisions stand side by side in the ledger.
    ledger_id, ledger_hash = await asyncio.to_thread(
        db.append_ledger,
        {
            "challan_id": challan_id,
            "event": "REAUDIT",
            "original_verdict": original_verdict,
            "verdict": new_verdict.verdict,
            "changed": changed,
            "trust_score": new_verdict.trust_score,
            "checks": new_verdict.checks.model_dump(),
            "dispute_reason_redacted": safe_reason[:500],
            "reasoning": new_verdict.reasoning,
            "mode": settings.mode,
        },
    )

    updated = dict(result)
    updated["verdict"] = new_verdict.model_dump()
    updated["reaudit"] = {
        "original_verdict": original_verdict,
        "changed": changed,
        "ledger_hash": ledger_hash,
        "reason_redacted": safe_reason[:500],
    }
    if new_verdict.verdict != "ISSUE":
        updated["amount_held"] = 0.0
    await asyncio.to_thread(
        db.update_challan_verdict,
        challan_id,
        new_verdict.verdict,
        new_verdict.trust_score,
        updated,
    )

    if new_verdict.verdict == "ESCALATE":
        await asyncio.to_thread(
            db.enqueue_review,
            challan_id,
            f"Customer dispute: {safe_reason[:300]}\n\n{new_verdict.reasoning}",
            new_verdict.trust_score,
        )

    await asyncio.to_thread(
        db.record_dispute,
        challan_id,
        safe_reason,
        original_verdict,
        new_verdict.verdict,
        changed,
        new_verdict.reasoning,
    )

    return DisputeOutcome(
        challan_id=challan_id,
        original_verdict=original_verdict,  # type: ignore[arg-type]
        new_verdict=new_verdict.verdict,
        changed=changed,
        trust_score=new_verdict.trust_score,
        reasoning=new_verdict.reasoning,
        checks=new_verdict.checks,
        ledger_hash=ledger_hash,
        ledger_id=ledger_id,
        reviewed_at=db.utc_now(),
    )
