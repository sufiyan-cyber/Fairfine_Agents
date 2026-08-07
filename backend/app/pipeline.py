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
    AuditResult,
    AuditTrace,
    Detection,
    DuplicateCheck,
    EvidencePacket,
    Frame,
    NaiveComparison,
    PlateRead,
    RuleCitation,
    Verdict,
)
from .tools import mv_act
from .tools.memory import memory
from .tools.vahan import infer_vehicle_type, vahan_lookup

STAGES: list[tuple[str, str]] = [
    ("IngestAgent", "Sampling frames + metadata"),
    ("DetectorAgent", "Classifying violation"),
    ("PlateAgent", "Reading plate + per-char confidence"),
    ("MemoryAgent", "Duplicate sweep + MV Act retrieval"),
    ("AuditorAgent", "Adversarial review"),
    ("VerdictRouter", "Routing on verdict"),
    ("LedgerAgent", "Appending to hash chain"),
]


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
    frames: list[dict], challan_id: str, operator_note: str, dispute_reason: str | None
) -> dict:
    """Execute the ADK tree and return the final session state.

    Retried on transient Gemini failures. Each attempt builds its own session,
    so a retry starts from the same clean initial state rather than inheriting
    the half-populated state of the attempt that failed.

    If the auditor's model stays exhausted after those retries, the audit is
    re-run on the fallback model rather than failed. Vertex serves the larger
    models from a shared capacity pool, so a 429 there says the pool is busy,
    not that anything is wrong with the request — and the smaller model applies
    the same prompt, the same five vetoes and the same thresholds. A shallower
    verdict is worth more than an error, and `capability_report` reports which
    model actually answered.
    """
    try:
        return await with_retry(
            lambda: _run_adk_once(frames, challan_id, operator_note, dispute_reason),
            label=f"adk-tree[{settings.auditor_model}]",
        )
    except Exception as exc:  # noqa: BLE001 — re-raised below unless retryable
        fallback = settings.auditor_fallback_model.strip()
        if not fallback or fallback == settings.auditor_model or not is_retryable(exc):
            raise
        print(
            f"[fallback] {settings.auditor_model} still exhausted after retries; "
            f"re-running the audit on {fallback}",
            flush=True,
        )
        return await with_retry(
            lambda: _run_adk_once(
                frames, challan_id, operator_note, dispute_reason, auditor_model=fallback
            ),
            label=f"adk-tree[{fallback}]",
        )


async def _run_adk_once(
    frames: list[dict],
    challan_id: str,
    operator_note: str,
    dispute_reason: str | None,
    auditor_model: str | None = None,
) -> dict:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from .agents.adk_agents import get_root_agent

    session_service = InMemorySessionService()
    app_name = "fairfine"
    user_id = "officer"
    session_id = challan_id

    initial_state: dict[str, Any] = {
        "frames": frames,
        "challan_id": challan_id,
        "operator_note": operator_note,
    }
    if dispute_reason:
        initial_state["dispute_reason"] = dispute_reason

    await session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id, state=initial_state
    )

    parts = []
    for frame in frames:
        try:
            data, mime = ingest.frame_to_part(frame["path"])
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        except OSError:
            continue
    parts.append(
        types.Part(text=prompts.build_detector_context(frames, operator_note))
    )

    # Reuse the one agent tree across audits. Building a fresh tree per audit
    # (as this did) makes ADK construct new internal Gemini clients each time,
    # which leak connection pools and drive the container out of memory. Session
    # state keeps concurrent audits isolated, so a shared tree is safe — it is
    # exactly how `adk web`/`adk api_server` run.
    runner = Runner(
        app_name=app_name,
        agent=get_root_agent(auditor_model),
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


def _discard_workspace(source_path: str, frame_dir: Path | None) -> None:
    """Drop an audit's scratch files once its evidence is in the database.

    The evidence packet stores frames as base64 data URIs and a dispute
    re-decides from that stored record, so neither the uploaded clip nor the
    sampled JPEGs are ever read again after the audit finishes. Keeping them
    was a slow leak: on a host whose filesystem is in memory — Cloud Run's is —
    every retained upload is a permanent charge against the instance's memory
    limit, and a handful of large clips is the entire allowance.

    Only paths under `UPLOAD_DIR` are removed. An audit can also run against a
    repo fixture (`scripts/seed_demo.py` replays `data/seed_frames/`, the demo
    clips live in `data/demo_clips/`), and deleting those would consume the
    demo the first time it ran.
    """
    if frame_dir is not None and _under_upload_dir(frame_dir):
        shutil.rmtree(frame_dir, ignore_errors=True)

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
    location_override: str | None = None,
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
                location_override,
                workspace,
            ):
                yield envelope
        finally:
            _discard_workspace(source_path, workspace.get("frame_dir"))


async def _run_audit_inner(
    source_path: str,
    filename: str,
    operator_note: str = "",
    scenario_override: str | None = None,
    location_override: str | None = None,
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
            ingest.ingest_event, source_path, settings.event_window_seconds, location_override
        )
    except (FileNotFoundError, ValueError) as exc:
        recorder.finish("IngestAgent", detail=str(exc), status="error")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        yield {"type": "error", "data": {"message": str(exc)}}
        return

    frames: list[dict] = ingested["frames"]
    if workspace is not None and frames:
        workspace["frame_dir"] = Path(frames[0]["path"]).parent
    recorder.finish(
        "IngestAgent",
        output={
            "frames_sampled": len(frames),
            "sampler": ingested["sampler"],
            "camera_id": frames[0]["camera_id"],
            "location": frames[0]["location"],
            "event_ts": frames[0]["ts"],
        },
        detail=f"{len(frames)} frames via {ingested['sampler']}",
    )
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    scenario = simulator.infer_scenario(filename, scenario_override)
    state: dict[str, Any] = {}

    if mode == "live":
        # ADK runs the whole tree; mark the model stages running for the UI,
        # then fill in their real outputs once the tree completes.
        for agent in ("DetectorAgent", "PlateAgent", "MemoryAgent", "AuditorAgent"):
            recorder.start(agent)
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        try:
            state = await _run_adk(frames, challan_id, operator_note, None)
        except Exception as exc:  # noqa: BLE001 — surface any ADK/Gemini failure
            detail = _flatten_exception(exc)
            for agent in ("DetectorAgent", "PlateAgent", "MemoryAgent", "AuditorAgent"):
                recorder.finish(agent, detail=detail, status="error")
            yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
            yield {
                "type": "error",
                "data": {"message": f"Live pipeline failed: {detail}"},
            }
            return

        detection = Detection(**_as_dict(state.get("detection")))
        plate = PlateRead(**_as_dict(state.get("plate_read")))
        duplicate = DuplicateCheck(**_as_dict(state.get("duplicate")))
        rule_dict = _as_dict(state.get("rule"))
        rule = RuleCitation(**rule_dict) if rule_dict else None
        verdict = Verdict(**_as_dict(state.get("verdict")))

        recorder.finish("DetectorAgent", output=detection.model_dump(),
                        detail=f"{detection.violation_type} @ {detection.raw_confidence:.0%}")
        recorder.finish("PlateAgent", output=plate.model_dump(),
                        detail=f"{plate.plate} · min {plate.min_confidence:.0%}")
        recorder.finish("MemoryAgent",
                        output={"duplicate": duplicate.model_dump(),
                                "rule": rule.model_dump() if rule else None,
                                "backend": state.get("memory_backend", "local")},
                        detail=f"duplicate={duplicate.is_duplicate} · {rule.section if rule else 'no rule'}")
        recorder.finish("AuditorAgent", output=verdict.model_dump(),
                        detail=f"{verdict.verdict} · trust {verdict.trust_score:.0%}")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    else:
        # -- Simulation: detector + plate concurrently ---------------------- #
        recorder.start("DetectorAgent")
        recorder.start("PlateAgent")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        await asyncio.sleep(0.45)

        detection = simulator.synth_detection(scenario, frames)
        recorder.finish(
            "DetectorAgent",
            output=detection.model_dump(),
            detail=f"{detection.violation_type} @ {detection.raw_confidence:.0%}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

        await asyncio.sleep(0.35)
        plate = simulator.synth_plate_read(scenario, frames, f"{filename}:{frames[0]['ts']}")
        recorder.finish(
            "PlateAgent",
            output=plate.model_dump(),
            detail=f"{plate.plate} · min {plate.min_confidence:.0%}",
        )
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

        # -- Memory --------------------------------------------------------- #
        recorder.start("MemoryAgent")
        yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}
        await asyncio.sleep(0.3)

        candidates = await asyncio.to_thread(
            db.recent_events_for_dedup,
            plate.plate,
            frames[0]["location"],
            settings.duplicate_window_seconds,
        )
        duplicate = await asyncio.to_thread(
            memory.check_duplicate,
            plate.plate,
            frames[0]["location"],
            detection.violation_type,
            frames[0]["ts"],
            detection.region_description,
            candidates,
        )
        rule = memory.rule_for_violation(detection.violation_type)
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
            scenario, detection, plate, duplicate, rule.section if rule else None
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

    registry = await asyncio.to_thread(vahan_lookup, plate.plate, detection.violation_type)
    vehicle_type = registry.get("vehicle_type") or infer_vehicle_type(
        plate.plate, detection.violation_type
    )
    fine_amount = mv_act.fine_for(detection.violation_type) if verdict.verdict == "ISSUE" else 0

    evidence: EvidencePacket | None = None
    branch_detail = ""
    review_id = None
    review_uncertainty = ""

    if verdict.verdict == "ISSUE":
        branch_detail = "ISSUE → EvidenceAgent · challan drafted"
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
        branch_detail = "REJECT → dropped, still ledgered"

    recorder.finish(
        "VerdictRouter",
        output={
            "branch": verdict.verdict,
            "review_id": review_id,
            "fine_amount": fine_amount,
            "vehicle_type": vehicle_type,
        },
        detail=branch_detail,
    )
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # -- Stage: ledger ------------------------------------------------------ #
    recorder.start("LedgerAgent")
    yield {"type": "trace", "data": [s.model_dump() for s in recorder.snapshot()]}

    # The evidence frames are rendered before the append, not after, because
    # the ledger commits to their digest. Hashing them afterwards would leave
    # the evidence outside the chain — which is the gap this closes.
    frame_uris: list[str] = []
    for frame in frames[:4]:
        uri = await asyncio.to_thread(ingest.frame_to_data_uri, frame["path"])
        if uri:
            frame_uris.append(uri)
    frames_sha256 = db.evidence_digest(frame_uris)

    ledger_payload = {
        "challan_id": challan_id,
        "event": "AUDIT",
        "verdict": verdict.verdict,
        "trust_score": verdict.trust_score,
        "checks": verdict.checks.model_dump(),
        "violation_type": detection.violation_type,
        "detector_confidence": detection.raw_confidence,
        "plate": plate.plate,
        "plate_min_confidence": plate.min_confidence,
        "location": frames[0]["location"],
        "camera_id": frames[0]["camera_id"],
        "event_ts": frames[0]["ts"],
        "rule_citation": rule.section if rule else "",
        "fine_amount": fine_amount,
        "mode": mode,
        "reasoning": verdict.reasoning,
        "frames_sha256": frames_sha256,
        "frame_count": len(frame_uris),
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
            plate=plate.plate,
            owner_masked=registry.get("owner_masked", "—"),
            violation_type=detection.violation_type,
            location=frames[0]["location"],
            ts=frames[0]["ts"],
            trust_score=verdict.trust_score,
            reasoning=verdict.reasoning,
            rule_citation=rule.section if rule else "",
            frames=frame_uris,
            ledger_hash=ledger_hash,
        )

    naive = _naive_comparison(detection, plate, duplicate, verdict, fine_amount)

    result = AuditResult(
        challan_id=challan_id,
        mode=mode,
        verdict=verdict,
        detection=detection,
        plate=plate,
        frames=[Frame(**f) for f in frames],
        duplicate=duplicate,
        rule=rule,
        evidence=evidence,
        ledger_id=ledger_id,
        ledger_hash=ledger_hash,
        frames_sha256=frames_sha256,
        trace=recorder.snapshot(),
        naive=naive,
        created_at=_now(),
    )

    stored = result.model_dump()
    stored["frame_uris"] = frame_uris
    stored["registry"] = enkrypt.scrub_owner_record(registry) | {
        "owner_masked": registry.get("owner_masked", "—")
    }
    stored["fine_amount"] = fine_amount
    stored["scenario"] = scenario
    stored["review_id"] = review_id

    await asyncio.to_thread(
        db.save_challan,
        {
            "challan_id": challan_id,
            "verdict": verdict.verdict,
            "trust_score": verdict.trust_score,
            "violation_type": detection.violation_type,
            "plate": plate.plate,
            "location": frames[0]["location"],
            "area": _area_of(frames[0]["location"]),
            "vehicle_type": vehicle_type,
            "camera_id": frames[0]["camera_id"],
            "event_ts": frames[0]["ts"],
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
        plate.plate,
        frames[0]["location"],
        detection.violation_type,
        frames[0]["ts"],
        detection.region_description,
    )

    yield {"type": "result", "data": stored}


def _naive_comparison(
    detection: Detection,
    plate: PlateRead,
    duplicate: DuplicateCheck,
    verdict: Verdict,
    fine_amount: int,
) -> NaiveComparison:
    """What a confidence-threshold-only system does with the same input.

    The comparison the demo turns on: a naive system reads one number — the
    detector's confidence — and charges on it. It never sees the plate
    reliability, the camera geometry, or the duplicate.
    """
    would_issue = detection.raw_confidence >= 0.85 and detection.violation_type != "none"
    amount = mv_act.fine_for(detection.violation_type) if would_issue else 0

    if would_issue and verdict.verdict != "ISSUE":
        if duplicate.is_duplicate:
            basis = (
                f"Detector confidence {detection.raw_confidence:.0%} clears a naive 85% "
                "threshold, so a second fine is issued for an event already charged."
            )
        elif plate.min_confidence < settings.plate_confidence_floor:
            basis = (
                f"Detector confidence {detection.raw_confidence:.0%} clears a naive 85% "
                f"threshold. The plate's weakest character reads at {plate.min_confidence:.0%}, "
                "but a threshold-only system never checks that — the fine goes to whichever "
                "plate the OCR guessed."
            )
        else:
            basis = (
                f"Detector confidence {detection.raw_confidence:.0%} clears a naive 85% "
                "threshold, so the fine issues automatically with no second look at the "
                "camera geometry."
            )
    elif would_issue:
        basis = (
            f"Detector confidence {detection.raw_confidence:.0%} clears the threshold, and "
            "the audit independently confirms the fine is safe to issue."
        )
    else:
        basis = (
            f"Detector confidence {detection.raw_confidence:.0%} is below a naive 85% "
            "threshold, so no fine issues either way."
        )

    return NaiveComparison(would_issue=would_issue, basis=basis, fine_amount=amount)


def _area_of(location: str) -> str:
    return (location or "unknown").split(",")[0].strip() or "unknown"
