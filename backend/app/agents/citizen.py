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
from ..schemas import (
    CitizenView,
    Detection,
    DisputeOutcome,
    DuplicateCheck,
    PlateRead,
    Verdict,
)
from ..tools import mv_act
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
    """Run one LlmAgent to completion and return its structured output."""
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
    detection = _as_dict(result.get("detection"))
    plate = _as_dict(result.get("plate"))
    rule = _as_dict(result.get("rule"))
    registry = result.get("registry", {}) or {}
    fine_amount = int(result.get("fine_amount", 0) or 0)
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
        "violation_label": mv_act.label_for(detection.get("violation_type", "none")),
        "plate": plate.get("plate", ""),
        "location": record["location"],
        "ts": record["event_ts"],
        "fine_amount": fine_amount,
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
            fine_amount=fine_amount,
            plate=plate.get("plate", ""),
            reasoning_en=verdict.get("reasoning", ""),
        )

    return CitizenView(
        challan_id=challan_id,
        language=language,  # type: ignore[arg-type]
        headline=written.get("headline", ""),
        explanation=written.get("explanation", ""),
        what_this_means=written.get("what_this_means", ""),
        your_options=written.get("your_options", []),
        violation_label=packet["violation_label"],
        trust_score=float(packet["trust_score"]),
        verdict=verdict_type,  # type: ignore[arg-type]
        plate=packet["plate"],
        owner_masked=registry.get("owner_masked", "—"),
        location=packet["location"],
        ts=packet["ts"],
        rule_citation=rule.get("section", "") if rule else "",
        rule_text=rule.get("text", "") if rule else "",
        auditor_reasoning=verdict.get("reasoning", ""),
        checks=verdict.get("checks", {}),  # type: ignore[arg-type]
        frames=result.get("frame_uris", [])[:3],
        ledger_hash=record["ledger_hash"],
        fine_amount=fine_amount,
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
    detection = Detection(**_as_dict(result.get("detection")))
    plate = PlateRead(**_as_dict(result.get("plate")))
    duplicate = DuplicateCheck(**_as_dict(result.get("duplicate")))
    original = _as_dict(result.get("verdict"))
    original_verdict = original.get("verdict", "ESCALATE")
    rule = memory.rule_for_violation(detection.violation_type)
    scenario = result.get("scenario", "clean")

    # The citizen's words go into a prompt — scrub before assembly, per the
    # PRD's non-negotiable. Redacting here also protects the disputant if they
    # paste a phone number or Aadhaar into the free-text box.
    guarded = enkrypt.redact_pii(reason)
    safe_reason = guarded.text

    new_verdict: Verdict | None = None
    if settings.live_llm:
        try:
            from google.adk.agents import LlmAgent

            frames = result.get("frames", [])
            context = prompts.build_auditor_context(
                detection=detection.model_dump(),
                plate=plate.model_dump(),
                duplicate=duplicate.model_dump(),
                rule=rule.model_dump() if rule else None,
                frames=frames,
                dispute_reason=safe_reason,
            )
            agent = LlmAgent(
                name="ReAuditAgent",
                model=settings.auditor_model,
                description="Re-decides a contested enforcement decision.",
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
            detection,
            plate,
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
        updated["fine_amount"] = 0
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
            f"Citizen dispute: {safe_reason[:300]}\n\n{new_verdict.reasoning}",
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
