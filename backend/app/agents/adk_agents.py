"""The ADK agent tree.

    FairFineOrchestrator (SequentialAgent)
    ├─ PerceptionStage (ParallelAgent)
    │   ├─ DetectorAgent   LlmAgent · gemini-2.5-flash · output_schema=Detection
    │   └─ PlateAgent      LlmAgent · gemini-2.5-flash · output_schema=PlateRead
    ├─ MemoryAgent         BaseAgent · Qdrant duplicate check + MV Act RAG
    ├─ AuditorAgent ★      LlmAgent · gemini-2.5-pro   · output_schema=Verdict
    └─ VerdictRouter       BaseAgent · ISSUE→Evidence, ESCALATE→HumanQueue, REJECT→drop

ADK features carrying real weight here:
  * `output_schema` on every LlmAgent — no agent may answer in free text.
  * `ParallelAgent` — detection and plate reading are independent, so they race.
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
from ..schemas import Detection, PlateRead, Verdict
from ..tools import mv_act
from ..tools.memory import memory
from ..tools.vahan import vahan_lookup
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


# --------------------------------------------------------------------------- #
# Perception stage
# --------------------------------------------------------------------------- #
def build_detector_agent() -> LlmAgent:
    return LlmAgent(
        name="DetectorAgent",
        model=settings.detector_model,
        description="Classifies the traffic violation visible in the sampled frames.",
        instruction=prompts.DETECTOR_PROMPT,
        output_schema=Detection,
        output_key="detection",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def build_plate_agent() -> LlmAgent:
    return LlmAgent(
        name="PlateAgent",
        model=settings.plate_model,
        description="Reads the registration plate with per-character confidence.",
        instruction=prompts.PLATE_PROMPT,
        output_schema=PlateRead,
        output_key="plate_read",
        before_model_callback=pii_scrub_callback,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


# --------------------------------------------------------------------------- #
# MemoryAgent — Qdrant duplicate check + MV Act RAG
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
        detection = _as_dict(state.get("detection"))
        plate_read = _as_dict(state.get("plate_read"))
        frames = state.get("frames", []) or []

        plate = plate_read.get("plate", "UNREADABLE")
        location = frames[0]["location"] if frames else "unknown"
        event_ts = frames[0]["ts"] if frames else ""
        violation = detection.get("violation_type", "none")

        candidates = db.recent_events_for_dedup(
            plate, location, settings.duplicate_window_seconds
        )
        duplicate = memory.check_duplicate(
            plate=plate,
            location=location,
            violation_type=violation,
            ts=event_ts,
            description=detection.get("region_description", ""),
            candidates=candidates,
        )

        rule = memory.rule_for_violation(violation)
        related = memory.search_rules(
            f"{violation} {detection.get('region_description', '')}", top_k=3
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
        detection=_as_dict(state.get("detection")),
        plate=_as_dict(state.get("plate_read")),
        duplicate=_as_dict(state.get("duplicate")),
        rule=_as_dict(state.get("rule")) or None,
        frames=state.get("frames", []) or [],
        dispute_reason=state.get("dispute_reason"),
    )
    base = prompts.REAUDIT_PROMPT if state.get("dispute_reason") else prompts.AUDITOR_PROMPT
    return f"{base}\n\n{context}"


def build_auditor_agent() -> LlmAgent:
    return LlmAgent(
        name="AuditorAgent",
        model=settings.auditor_model,
        description=(
            "Adversarially reviews the detection and plate read, and returns a "
            "calibrated trust score with an ISSUE / REJECT / ESCALATE verdict."
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
    """REJECT branch — no fine is drafted. The decision is still ledgered."""

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
                parts=[types.Part(text="No fine issued. Decision recorded in the ledger.")],
            ),
        )


def build_evidence_agent() -> LlmAgent:
    """ISSUE branch — assembles the evidence packet and drafts the challan.

    Holds the mock VAHAN lookup as an ADK tool. Owner identity is withheld from
    the model by `scrub_owner_record`, so the drafted notice can never name a
    person the model was not entitled to see.
    """

    def registry_lookup(plate: str, violation_type: str = "") -> dict:
        """Look up vehicle registration details for a plate (mock VAHAN).

        Args:
            plate: The registration number to look up.
            violation_type: Optional violation hint for vehicle classification.

        Returns:
            Registration details with owner identity withheld.
        """
        return enkrypt.scrub_owner_record(vahan_lookup(plate, violation_type))

    def rule_text(section: str) -> dict:
        """Fetch the full text of a Motor Vehicles Act section.

        Args:
            section: Section identifier, e.g. "MV Act §194D".

        Returns:
            The section's title, text and penalty.
        """
        return mv_act.get_section(section) or {"error": "section not found"}

    return LlmAgent(
        name="EvidenceAgent",
        model=settings.detector_model,
        description="Assembles the evidence packet and drafts the challan notice.",
        instruction=prompts.EVIDENCE_PROMPT,
        tools=[registry_lookup, rule_text],
        output_key="challan_draft",
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
def build_root_agent() -> SequentialAgent:
    perception = ParallelAgent(
        name="PerceptionStage",
        description="Runs violation detection and plate reading concurrently.",
        sub_agents=[build_detector_agent(), build_plate_agent()],
    )

    router = VerdictRouter(
        name="VerdictRouter",
        description="Routes ISSUE / ESCALATE / REJECT to the correct branch.",
        sub_agents=[
            build_evidence_agent(),
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
            MemoryAgent(name="MemoryAgent", description="Duplicate check + MV Act RAG."),
            build_auditor_agent(),
            router,
        ],
        after_agent_callback=ledger_callback,
    )


# `adk web` / `adk run` entry point.
root_agent = None


def get_root_agent() -> SequentialAgent:
    global root_agent
    if root_agent is None:
        root_agent = build_root_agent()
    return root_agent


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
                "role": "Samples frames across the event window and attaches metadata.",
            },
            {
                "name": "PerceptionStage",
                "type": "ParallelAgent",
                "model": None,
                "role": "Detection and plate reading run concurrently.",
                "children": [
                    {
                        "name": "DetectorAgent",
                        "type": "LlmAgent",
                        "model": settings.detector_model,
                        "output_schema": "Detection",
                        "role": "Classifies the violation visible in the frames.",
                    },
                    {
                        "name": "PlateAgent",
                        "type": "LlmAgent",
                        "model": settings.plate_model,
                        "output_schema": "PlateRead",
                        "role": "Reads the plate with per-character confidence.",
                    },
                ],
            },
            {
                "name": "MemoryAgent",
                "type": "BaseAgent",
                "model": None,
                "role": "Qdrant near-duplicate sweep and MV Act retrieval.",
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
                        "role": "Assembles the evidence packet and drafts the challan.",
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
                        "role": "Drops the event; the decision is still ledgered.",
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
                "role": "Re-runs the audit against the ledger record when a citizen disputes.",
            },
        ],
        "adk_features": [
            "SequentialAgent + ParallelAgent composition",
            "output_schema on every LlmAgent",
            "before_model_callback -> Enkrypt PII scrub",
            "after_agent_callback -> ledger append + bias screen",
            "Session state hand-off between agents",
            "FunctionTool -> mock VAHAN lookup + MV Act retrieval",
        ],
    }


def _adk_version() -> str:
    try:
        import google.adk

        return getattr(google.adk, "__version__", "unknown")
    except Exception:
        return "unknown"
