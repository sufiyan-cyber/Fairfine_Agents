"""Pipeline orchestration + the live agent trace.

Drives the audit stage by stage and yields trace events as it goes, which is
what the officer console renders over SSE. Two execution paths share one
contract:

  * live       — the ADK agent tree against Gemini.
  * simulation — the deterministic rule engine in `agents.simulator`.

Both paths write the same schemas, hit the same ledger, and produce the same
trace shape, so nothing downstream needs to know which one ran.
"""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from . import db
from .agents import ingest, prompts, simulator
from .agents.adk_agents import _as_dict
from .config import UPLOAD_DIR, settings
from .guardrails import enkrypt
from .retry import is_retryable, with_retry
from .schemas import (
    AttributionRead,
    AuditResult,
    AuditTrace,
    DuplicateCheck,
    EvidencePacket,
    NaiveComparison,
    RiskSignal,
    RuleCitation,
    TxnEvent,
    Verdict,
)
from .tools import fraud_rules
from .tools.accounts import account_lookup, infer_segment, merchant_profile
from .tools.memory import memory

STAGES: list[tuple[str, str]] = [
    ("IngestAgent", "Parsing alert + account history"),
    ("SignalAgent", "Classifying fraud pattern"),
    ("AttributionAgent", "Scoring attribution confidence"),
    ("MemoryAgent", "Duplicate sweep + rulebook retrieval"),
    ("AuditorAgent", "Adversarial review"),
    ("VerdictRouter", "Routing on verdict"),
    ("LedgerAgent", "Appending to hash chain"),
]

_MODEL_STAGES = ("SignalAgent", "AttributionAgent", "MemoryAgent", "AuditorAgent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _flatten_exception(exc: BaseException, depth: int = 0) -> str:
    """Human-readable message from an exception, unwrapping ExceptionGroups.

    The parallel perception stage runs on an asyncio TaskGroup, so a Gemini
    failure arrives as `ExceptionGroup: unhandled errors in a TaskGroup (N
    sub-exceptions)` — which says nothing about what actually went wrong.
    Recurse into the group and report the real leaf errors instead.
    """
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions and depth < 4:
        seen: list[str] = []
        for sub in exc.exceptions:
            msg = _flatten_exception(sub, depth + 1)
            if msg not in seen:
                seen.append(msg)
        return " · ".join(seen)
    return f"{type(exc).__name__}: {str(exc)[:300]}"


class TraceRecorder:
    """Accumulates the per-agent trace shown in the console."""

    def __init__(self) -> None:
        self.steps: dict[str, AuditTrace] = {
            name: AuditTrace(agent=name, status="pending", label=label)
            for name, label in STAGES
        }
        self._started: dict[str, float] = {}

    def snapshot(self) -> list[AuditTrace]:
        return [self.steps[name] for name, _ in STAGES]

    def start(self, agent: str) -> AuditTrace:
        step = self.steps[agent]
        step.status = "running"
        step.started_at = _now()
        self._started[agent] = time.perf_counter()
        return step

    def finish(
        self,
        agent: str,
        output: dict | None = None,
        detail: str = "",
        status: str = "done",
    ) -> AuditTrace:
        step = self.steps[agent]
        step.status = status  # type: ignore[assignment]
        step.finished_at = _now()
        step.output = output
        step.detail = detail
        if agent in self._started:
            step.duration_ms = int((time.perf_counter() - self._started[agent]) * 1000)
        return step

    def skip(self, agent: str, detail: str) -> AuditTrace:
        step = self.steps[agent]
        step.status = "skipped"
        step.detail = detail
        return step


# --------------------------------------------------------------------------- #
# Live path — ADK
# --------------------------------------------------------------------------- #
async def _run_adk(
    events: list[dict],
    challan_id: str,
    operator_note: str,
    dispute_reason: str | None,
    ingested: dict | None = None,
    account: dict | None = None,
    merchant: dict | None = None,
) -> dict:
    """Execute the ADK tree and return the final session state.

    Retried on transient Gemini failures. Each attempt builds its own session,
    so a retry starts from the same clean initial state rather than inheriting
    the half-populated state of the attempt that failed.

    If the model stays exhausted after those retries, the audit is re-run down
    a fallback ladder rather than failed. A 429 says a capacity pool is busy,
    not that anything is wrong with the request, and the pools are separate
    along two axes: *regions* don't share capacity (measured 2026-08-07, the
    `global` endpoint refused every image-bearing request while asia-south1,
    us-central1 and europe-west4 all served the identical payload), and neither
    do *models*. So the ladder tries the same model in the fallback region
    before it downgrades the model at all: same verdict quality in a different
    queue beats a shallower verdict. The prompt, the five vetoes and the
    thresholds are identical on every rung.
    """
    primary_model = settings.auditor_model
    fallback_model = settings.auditor_fallback_model.strip()
    if fallback_model == primary_model:
        fallback_model = ""
    backup_region = ""
    if settings.live_vertex:
        backup_region = settings.vertex_fallback_location.strip()
        if backup_region == settings.google_cloud_location:
            backup_region = ""

    rungs: list[tuple[str, str | None]] = [(primary_model, None)]
    if backup_region:
        rungs.append((primary_model, backup_region))
    if fallback_model:
        rungs.append((fallback_model, None))
        if backup_region:
            rungs.append((fallback_model, backup_region))

    last_exc: Exception | None = None
    for index, (model, location) in enumerate(rungs):
        region = location or settings.google_cloud_location
        if index:
            print(
                f"[fallback] still exhausted after retries; "
                f"re-running the audit on {model} in {region}",
                flush=True,
            )
        try:
            return await with_retry(
                lambda model=model, location=location: _run_adk_once(
                    events,
                    challan_id,
                    operator_note,
                    dispute_reason,
                    auditor_model=model,
                    location=location,
                    ingested=ingested,
                    account=account,
                    merchant=merchant,
                ),
                label=f"adk-tree[{model}@{region}]",
            )
        except Exception as exc:  # noqa: BLE001 — re-raised unless retryable
            if not is_retryable(exc):
                raise
            last_exc = exc

    assert last_exc is not None  # rungs is never empty
    raise last_exc


async def _run_adk_once(
    events: list[dict],
    challan_id: str,
    operator_note: str,
    dispute_reason: str | None,
    auditor_model: str | None = None,
    location: str | None = None,
    ingested: dict | None = None,
    account: dict | None = None,
    merchant: dict | None = None,
) -> dict:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from .agents.adk_agents import get_root_agent

    session_service = InMemorySessionService()
    app_name = "fairfine"
    user_id = "analyst"
    session_id = challan_id

    ingested = ingested or {}
    flagged_index = ingested.get("flagged_index", 0)

    initial_state: dict[str, Any] = {
        "events": events,
        "challan_id": challan_id,
        "operator_note": operator_note,
        "account_ref": ingested.get("account_ref", "UNRESOLVED"),
        "account": account or {},
        "merchant": merchant or {},
        "alert_rule": ingested.get("alert_rule", ""),
    }
    if dispute_reason:
        initial_state["dispute_reason"] = dispute_reason

    await session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id, state=initial_state
    )

    parts = [
        types.Part(
            text=prompts.build_signal_context(
                events,
                flagged_index=flagged_index,
                alert_rule=ingested.get("alert_rule", ""),
                analyst_note=operator_note,
                account=account,
            )
        )
    ]

    # Reuse the one agent tree across audits. Building a fresh tree per audit
    # (as this did) makes ADK construct new internal Gemini clients each time,
    # which leak connection pools and drive the container out of memory. Session
    # state keeps concurrent audits isolated, so a shared tree is safe — it is
    # exactly how `adk web`/`adk api_server` run.
    runner = Runner(
        app_name=app_name,
        agent=get_root_agent(auditor_model, location),
        session_service=session_service,
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=parts),
    ):
        pass  # state is read once at the end; trace is emitted by the caller

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session_id
    )
    return dict(session.state) if session else {}


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #
# One audit at a time per process. A single live audit peaks around 175 MB, but
# several running concurrently — which is what happens when an impatient user
# retries during a slow cold-start — stack their peaks and push a 512 MB
# instance out of memory. Serialising caps the resident footprint at one audit's
# worth; a queued request simply waits its turn rather than piling on.
_audit_gate = asyncio.Semaphore(1)


def _under_upload_dir(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(UPLOAD_DIR.resolve())
    except (OSError, ValueError):
        return False


def _discard_workspace(source_path: str, _unused: Path | None = None) -> None:
    """Drop an audit's uploaded case file once its evidence is in the database.

    The stored result carries the parsed events and a dispute re-decides from
    that record, so the uploaded JSON is never read again after the audit
    finishes. Keeping it is a slow leak: on a host whose filesystem is in
    memory — Cloud Run's is — every retained upload is a permanent charge
    against the instance's memory limit.

    Only paths under `UPLOAD_DIR` are removed. An audit can also run against a
    repo fixture (`data/demo_cases/`), and deleting those would consume the
    demo the first time it ran.
    """
    source = Path(source_path)
    if _under_upload_dir(source):
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass


async def run_audit(
    source_path: str,
    filename: str,
    operator_note: str = "",
    scenario_override: str | None = None,
    account_override: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the audit, yielding `{"type": ..., "data": ...}` envelopes.

    Envelope types: `trace` (a step changed), `result` (final AuditResult),
    `error` (fatal). Only one audit runs at a time process-wide, and the
    audit's scratch files are discarded when it ends — including when it fails
    part way, which is exactly when the largest uploads tend to be abandoned.
    """
    async with _audit_gate:
        workspace: dict[str, Any] = {}
        try:
            async for envelope in _run_audit_inner(
                source_path,
                filename,
                operator_note,
                scenario_override,
                account_override,
                workspace,
            ):
                yield envelope
        finally:
            _discard_workspace(source_path)


async def _run_audit_inner(
    source_path: str,
    filename: str,
    operator_note: str = "",
    scenario_override: str | None = None,
    account_override: str | None = None,
    workspace: dict[str, Any] | None = None,
) -> AsyncGenerator[dict, None]:
    recorder = TraceRecorder()
    challan_id = f"CH-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    mode = settings.mode

    yield {"type": "meta", "data": {"challan_id": challan_id, "mode": mode}}
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # -- Stage 1: Ingest ---------------------------------------------------- #
    recorder.start("IngestAgent")
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
    try:
        ingested = await asyncio.to_thread(
            ingest.ingest_case, source_path, settings.events_per_case, account_override
        )
    except (FileNotFoundError, ValueError) as exc:
        recorder.finish("IngestAgent", detail=str(exc), status="error")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        yield {"type": "error", "data": {"message": str(exc)}}
        return

    events: list[dict] = ingested["events"]
    flagged = next((e for e in events if e.get("is_flagged")), events[0])
    account_ref = ingested["account_ref"]
    account = await asyncio.to_thread(account_lookup, account_ref)
    merchant = merchant_profile(flagged.get("category", ""), flagged.get("merchant", ""))

    recorder.finish(
        "IngestAgent",
        output={
            "events_parsed": len(events),
            "account_ref": account_ref,
            "merchant": flagged.get("merchant"),
            "amount": flagged.get("amount"),
            "event_ts": flagged.get("ts"),
            "history_count": ingested["history_count"],
        },
        detail=f"{len(events)} events · {account_ref}",
    )
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    scenario = simulator.infer_scenario(filename, scenario_override)
    state: dict[str, Any] = {}

    if mode == "live":
        # ADK runs the whole tree; mark the model stages running for the UI,
        # then fill in their real outputs once the tree completes.
        for agent in _MODEL_STAGES:
            recorder.start(agent)
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        try:
            state = await _run_adk(
                events, challan_id, operator_note, None, ingested, account, merchant
            )
        except Exception as exc:  # noqa: BLE001 — surface any ADK/Gemini failure
            detail = _flatten_exception(exc)
            for agent in _MODEL_STAGES:
                recorder.finish(agent, detail=detail, status="error")
            yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
            yield {
                "type": "error",
                "data": {"message": f"Live pipeline failed: {detail}"},
            }
            return

        signal = RiskSignal(**_as_dict(state.get("signal")))
        attribution = AttributionRead(**_as_dict(state.get("attribution")))
        duplicate = DuplicateCheck(**_as_dict(state.get("duplicate")))
        rule_dict = _as_dict(state.get("rule"))
        rule = RuleCitation(**rule_dict) if rule_dict else None
        verdict = Verdict(**_as_dict(state.get("verdict")))

        recorder.finish("SignalAgent", output=signal.model_dump(),
                        detail=f"{signal.fraud_type} @ {signal.raw_confidence:.0%}")
        recorder.finish("AttributionAgent", output=attribution.model_dump(),
                        detail=f"{attribution.account_ref} · min {attribution.min_confidence:.0%}")
        recorder.finish("MemoryAgent",
                        output={"duplicate": duplicate.model_dump(),
                                "rule": rule.model_dump() if rule else None,
                                "backend": state.get("memory_backend", "local")},
                        detail=f"duplicate={duplicate.is_duplicate} · {rule.section if rule else 'no rule'}")
        recorder.finish("AuditorAgent", output=verdict.model_dump(),
                        detail=f"{verdict.verdict} · trust {verdict.trust_score:.0%}")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    else:
        # -- Simulation: signal + attribution concurrently ------------------ #
        recorder.start("SignalAgent")
        recorder.start("AttributionAgent")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        await asyncio.sleep(0.45)

        signal = simulator.synth_signal(scenario, events)
        recorder.finish(
            "SignalAgent",
            output=signal.model_dump(),
            detail=f"{signal.fraud_type} @ {signal.raw_confidence:.0%}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

        await asyncio.sleep(0.35)
        attribution = simulator.synth_attribution(
            scenario, events, f"{filename}:{flagged['ts']}", account_ref
        )
        recorder.finish(
            "AttributionAgent",
            output=attribution.model_dump(),
            detail=f"{attribution.account_ref} · min {attribution.min_confidence:.0%}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

        # -- Memory --------------------------------------------------------- #
        recorder.start("MemoryAgent")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        await asyncio.sleep(0.3)

        candidates = await asyncio.to_thread(
            db.recent_events_for_dedup,
            account_ref,
            flagged.get("merchant", ""),
            settings.duplicate_window_seconds,
        )
        duplicate = await asyncio.to_thread(
            memory.check_duplicate,
            account_ref,
            flagged.get("merchant", ""),
            signal.fraud_type,
            flagged.get("ts", ""),
            signal.evidence_summary,
            candidates,
        )
        rule = memory.rule_for_fraud_type(signal.fraud_type)
        recorder.finish(
            "MemoryAgent",
            output={
                "duplicate": duplicate.model_dump(),
                "rule": rule.model_dump() if rule else None,
                "backend": memory.backend,
            },
            detail=f"duplicate={duplicate.is_duplicate} · {rule.section if rule else 'no rule'}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

        # -- Auditor -------------------------------------------------------- #
        recorder.start("AuditorAgent")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        await asyncio.sleep(0.7)

        verdict = simulator.audit(
            scenario, signal, attribution, duplicate, rule.section if rule else None
        )
        bias = enkrypt.check_bias(verdict.reasoning)
        recorder.finish(
            "AuditorAgent",
            output={**verdict.model_dump(), "bias_check": {"clean": bias.clean, "flags": bias.bias_flags}},
            detail=f"{verdict.verdict} · trust {verdict.trust_score:.0%}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # -- Stage: branch ------------------------------------------------------ #
    recorder.start("VerdictRouter")
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    segment = account.get("segment") or infer_segment(account_ref, signal.fraud_type)
    # The money actually taken out of the customer's reach. Unlike a fine, this
    # is not a tariff we look up — it is their own transaction, held.
    amount_held = float(flagged.get("amount", 0)) if verdict.verdict == "ISSUE" else 0.0

    evidence: EvidencePacket | None = None
    branch_detail = ""
    review_id = None
    review_uncertainty = ""

    if verdict.verdict == "ISSUE":
        branch_detail = "ISSUE → EvidenceAgent · case file drafted"
    elif verdict.verdict == "ESCALATE":
        checks = verdict.checks.model_dump()
        failed = [k for k, v in checks.items() if v is False and k != "duplicate"]
        review_uncertainty = verdict.reasoning + (
            f"\n\nUnresolved checks: {', '.join(failed)}." if failed else ""
        )
        # Reserve the id now so the trace can show it; the row is inserted
        # after the challan it references exists.
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        branch_detail = f"ESCALATE → HumanQueueAgent · {review_id}"
    else:
        branch_detail = "REJECT → alert dismissed, still ledgered"

    recorder.finish(
        "VerdictRouter",
        output={
            "branch": verdict.verdict,
            "review_id": review_id,
            "amount_held": amount_held,
            "segment": segment,
        },
        detail=branch_detail,
    )
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # -- Stage: ledger ------------------------------------------------------ #
    recorder.start("LedgerAgent")
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # The evidence rows are digested before the append, not after, because the
    # ledger commits to that digest. Hashing them afterwards would leave the
    # evidence outside the chain — which is the gap this closes.
    evidence_rows = [
        f"{e.get('ts')}|{e.get('amount')}|{e.get('merchant')}|{e.get('channel')}|{e.get('status')}"
        for e in events
    ]
    events_sha256 = db.evidence_digest(evidence_rows)

    ledger_payload = {
        "challan_id": challan_id,
        "event": "AUDIT",
        "verdict": verdict.verdict,
        "trust_score": verdict.trust_score,
        "checks": verdict.checks.model_dump(),
        "fraud_type": signal.fraud_type,
        "signal_confidence": signal.raw_confidence,
        "account_ref": attribution.account_ref,
        "attribution_min_confidence": attribution.min_confidence,
        "merchant": flagged.get("merchant", ""),
        "channel": flagged.get("channel", ""),
        "event_ts": flagged.get("ts", ""),
        "rule_citation": rule.section if rule else "",
        "amount_held": amount_held,
        "mode": mode,
        "reasoning": verdict.reasoning,
        "events_sha256": events_sha256,
        "event_count": len(events),
    }
    ledger_id, ledger_hash = await asyncio.to_thread(db.append_ledger, ledger_payload)
    recorder.finish(
        "LedgerAgent",
        output={"ledger_id": ledger_id, "hash": ledger_hash, "prev_linked": True},
        detail=f"{ledger_hash[:16]}…",
    )
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # -- Assemble evidence packet ------------------------------------------ #
    if verdict.verdict == "ISSUE":
        evidence = EvidencePacket(
            challan_id=challan_id,
            account_ref=attribution.account_ref,
            customer_masked=account.get("customer_masked", "—"),
            fraud_type=signal.fraud_type,
            merchant=flagged.get("merchant", ""),
            ts=flagged.get("ts", ""),
            trust_score=verdict.trust_score,
            reasoning=verdict.reasoning,
            rule_citation=rule.section if rule else "",
            events=evidence_rows,
            ledger_hash=ledger_hash,
        )

    naive = _naive_comparison(
        signal, attribution, duplicate, verdict, flagged, ingested.get("alert_score", 0.90)
    )

    result = AuditResult(
        challan_id=challan_id,
        mode=mode,
        verdict=verdict,
        signal=signal,
        attribution=attribution,
        events=[TxnEvent(**e) for e in events],
        duplicate=duplicate,
        rule=rule,
        evidence=evidence,
        ledger_id=ledger_id,
        ledger_hash=ledger_hash,
        events_sha256=events_sha256,
        trace=recorder.snapshot(),
        naive=naive,
        created_at=_now(),
    )

    stored = result.model_dump()
    stored["account"] = enkrypt.scrub_owner_record(account) | {
        "customer_masked": account.get("customer_masked", "—")
    }
    stored["merchant_profile"] = merchant
    stored["amount_held"] = amount_held
    stored["flagged_amount"] = float(flagged.get("amount", 0))
    stored["scenario"] = scenario
    stored["review_id"] = review_id

    await asyncio.to_thread(
        db.save_challan,
        {
            "challan_id": challan_id,
            "verdict": verdict.verdict,
            "trust_score": verdict.trust_score,
            "fraud_type": signal.fraud_type,
            "account_ref": attribution.account_ref,
            "merchant": flagged.get("merchant", ""),
            "region": _region_of(flagged),
            "segment": segment,
            "channel": flagged.get("channel", ""),
            "event_ts": flagged.get("ts", ""),
            "amount_held": amount_held,
            "ledger_id": ledger_id,
            "ledger_hash": ledger_hash,
            "result": stored,
            "created_at": _now(),
        },
    )

    if review_id:
        await asyncio.to_thread(
            db.enqueue_review, challan_id, review_uncertainty, verdict.trust_score, review_id
        )

    await asyncio.to_thread(
        memory.remember_event,
        challan_id,
        attribution.account_ref,
        flagged.get("merchant", ""),
        signal.fraud_type,
        flagged.get("ts", ""),
        signal.evidence_summary,
    )

    yield {"type": "result", "data": stored}


def _naive_comparison(
    signal: RiskSignal,
    attribution: AttributionRead,
    duplicate: DuplicateCheck,
    verdict: Verdict,
    flagged: dict,
    alert_score: float,
) -> NaiveComparison:
    """What a score-threshold-only engine does with the same input.

    The comparison the demo turns on. Note which number this reads: the
    *upstream* model's score, the one that fired the alert — not our own
    perception stage. Deriving the baseline from our SignalAgent would be
    circular and would flatter us, because by then the auditor's work is
    already done. The existing engine sees one number and acts on it. It never
    checks whether the activity is attributable to anyone but the customer,
    whether the timestamps are settlement artifacts, or whether it already
    acted on this alert.
    """
    would_issue = alert_score >= 0.85
    amount = float(flagged.get("amount", 0)) if would_issue else 0.0

    if would_issue and verdict.verdict != "ISSUE":
        if duplicate.is_duplicate:
            basis = (
                f"The bank's model scored this {alert_score:.0%}, clearing a naive 85% threshold, so the "
                "account is blocked a second time for an alert already actioned."
            )
        elif attribution.matches_known_behaviour:
            basis = (
                f"The bank's model scored this {alert_score:.0%}, clearing a naive 85% threshold. The "
                "activity matches this customer's own established pattern, but a "
                "threshold-only engine never checks that — it blocks on the score alone."
            )
        elif attribution.min_confidence < settings.attribution_confidence_floor:
            basis = (
                f"The bank's model scored this {alert_score:.0%}, clearing a naive 85% threshold. The "
                f"weakest attribution indicator scores only {attribution.min_confidence:.0%}, "
                "but a threshold-only engine never asks whether this was actually someone "
                "other than the customer — the hold lands regardless."
            )
        else:
            basis = (
                f"The bank's model scored this {alert_score:.0%}, clearing a naive 85% threshold, so the "
                "hold is placed automatically with no second look at the evidence."
            )
    elif would_issue:
        basis = (
            f"The bank's model scored this {alert_score:.0%}, clearing the threshold, and the "
            "audit independently confirms the hold is justified."
        )
    else:
        basis = (
            f"The bank's model scored this {alert_score:.0%}, below a naive 85% threshold, so "
            "no hold is placed either way."
        )

    return NaiveComparison(would_issue=would_issue, basis=basis, amount_held=amount)


def _region_of(flagged: dict) -> str:
    """Bias slices report by city; an unnamed city still needs a bucket."""
    city = (flagged.get("city") or "").strip()
    return city or "unknown"
