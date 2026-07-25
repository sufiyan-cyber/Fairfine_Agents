"""FastAPI application — the API surface from PRD §6."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import analytics, db, pipeline
from .agents import citizen as citizen_agent
from .agents.adk_agents import describe_architecture
from .config import UPLOAD_DIR, settings
from .schemas import (
    AuditResult,
    BiasDashboard,
    CitizenView,
    DisputeOutcome,
    DisputeRequest,
    LedgerVerification,
)
from .tools import mv_act
from .tools.memory import memory

app = FastAPI(
    title="FairFine",
    version="1.0.0",
    description=(
        "The accountability layer for automated traffic enforcement. An adversarial "
        "agent pipeline audits every AI-flagged violation before a rupee is charged."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"}


@app.on_event("startup")
async def _startup() -> None:
    db.get_conn()
    await asyncio.to_thread(memory.ensure_ready)


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
def _capabilities() -> dict[str, str]:
    """Configured capabilities, corrected by what actually connected.

    `capability_report()` only knows whether a URL was configured. If Qdrant
    was unreachable at startup the store has already fallen back to the local
    index, and reporting "qdrant" here would be a lie in the one place an
    operator looks to check.
    """
    report = settings.capability_report()
    if settings.live_qdrant:
        report["memory"] = (
            "qdrant" if memory.backend == "qdrant" else "sqlite-vector-fallback (qdrant unreachable)"
        )
    return report


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.mode,
        "capabilities": _capabilities(),
    }


@app.get("/api/architecture")
async def architecture() -> dict:
    return describe_architecture() | {
        "mode": settings.mode,
        "capabilities": _capabilities(),
        "thresholds": {
            "issue_trust_threshold": settings.issue_trust_threshold,
            "escalate_trust_floor": settings.escalate_trust_floor,
            "plate_confidence_floor": settings.plate_confidence_floor,
            "duplicate_window_seconds": settings.duplicate_window_seconds,
        },
    }


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
async def _persist_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "clip.mp4").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )

    target = UPLOAD_DIR / f"{uuid.uuid4().hex[:10]}_{Path(file.filename or 'clip').name}"
    size = 0
    with target.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File exceeds the 60 MB limit.")
            out.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return target


@app.post("/api/audit")
async def audit(
    file: UploadFile = File(...),
    operator_note: str = Form(""),
    scenario: str = Form(""),
    location: str = Form(""),
    stream: bool = Query(True, description="Stream the agent trace over SSE"),
):
    """Run the full pipeline on an uploaded clip or still.

    Streams the live agent trace as Server-Sent Events by default; pass
    `?stream=false` for a single JSON response.
    """
    saved = await _persist_upload(file)
    filename = file.filename or saved.name

    if not stream:
        final: dict | None = None
        error: dict | None = None
        async for envelope in pipeline.run_audit(
            str(saved), filename, operator_note, scenario or None, location or None
        ):
            if envelope["type"] == "result":
                final = envelope["data"]
            elif envelope["type"] == "error":
                error = envelope["data"]
        if error:
            raise HTTPException(status_code=422, detail=error["message"])
        if final is None:
            raise HTTPException(status_code=500, detail="Pipeline produced no result.")
        return final

    async def event_stream():
        try:
            async for envelope in pipeline.run_audit(
                str(saved), filename, operator_note, scenario or None, location or None
            ):
                yield f"event: {envelope['type']}\ndata: {json.dumps(envelope['data'], default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 — the client must learn the stream died
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': f'{type(exc).__name__}: {exc}'})}\n\n"
            )
        finally:
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Challans
# --------------------------------------------------------------------------- #
@app.get("/api/challans")
async def list_challans(limit: int = Query(50, ge=1, le=500), verdict: str | None = None) -> dict:
    rows = await asyncio.to_thread(db.list_challans, limit, verdict)
    return {
        "items": [
            {
                "challan_id": r["challan_id"],
                "verdict": r["verdict"],
                "trust_score": r["trust_score"],
                "violation_type": r["violation_type"],
                "violation_label": mv_act.label_for(r["violation_type"]),
                "plate": r["plate"],
                "location": r["location"],
                "area": r["area"],
                "vehicle_type": r["vehicle_type"],
                "event_ts": r["event_ts"],
                "ledger_hash": r["ledger_hash"],
                "created_at": r["created_at"],
                "fine_amount": r["result"].get("fine_amount", 0),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@app.get("/api/challan/{challan_id}")
async def get_challan(challan_id: str) -> dict:
    """Officer view — the full evidence packet."""
    record = await asyncio.to_thread(db.get_challan, challan_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No challan {challan_id}")
    disputes = await asyncio.to_thread(db.get_disputes, challan_id)
    return record["result"] | {
        "disputes": disputes,
        "ledger_id": record["ledger_id"],
        "ledger_hash": record["ledger_hash"],
    }


@app.get("/api/challan/{challan_id}/citizen", response_model=CitizenView)
async def citizen_view(
    challan_id: str,
    lang: str = Query("en", pattern="^(en|hi|kn|ta)$"),
) -> CitizenView:
    """Citizen view — plain language, in the requested language."""
    view = await citizen_agent.explain(challan_id, lang)
    if not view:
        raise HTTPException(status_code=404, detail=f"No challan {challan_id}")
    return view


@app.post("/api/challan/{challan_id}/dispute", response_model=DisputeOutcome)
async def dispute(challan_id: str, body: DisputeRequest) -> DisputeOutcome:
    """File a dispute — triggers ReAuditAgent against the stored evidence."""
    outcome = await citizen_agent.reaudit(challan_id, body.reason)
    if not outcome:
        raise HTTPException(status_code=404, detail=f"No challan {challan_id}")
    return outcome


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
@app.get("/api/ledger")
async def ledger(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> dict:
    records, total = await asyncio.to_thread(db.list_ledger, limit, offset)
    return {"items": records, "total": total, "limit": limit, "offset": offset}


@app.get("/api/ledger/verify", response_model=LedgerVerification)
async def verify_ledger() -> LedgerVerification:
    """Recompute the entire chain from genesis."""
    result = await asyncio.to_thread(db.verify_chain)
    return LedgerVerification(**result)


@app.get("/api/ledger/{record_id}")
async def ledger_record(record_id: str) -> dict:
    record = await asyncio.to_thread(db.get_ledger_record, record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No ledger record {record_id}")
    return record


# --------------------------------------------------------------------------- #
# Review queue + dashboard
# --------------------------------------------------------------------------- #
@app.get("/api/review-queue")
async def review_queue(limit: int = Query(50, ge=1, le=200)) -> dict:
    rows = await asyncio.to_thread(db.list_pending_reviews, limit)
    return {"items": rows, "count": len(rows)}


@app.get("/api/dashboard/bias", response_model=BiasDashboard)
async def bias_dashboard() -> BiasDashboard:
    return await asyncio.to_thread(analytics.build_dashboard)


@app.get("/api/rules")
async def rules(q: str = Query("", description="Semantic query over the MV Act corpus")) -> dict:
    if q:
        hits = await asyncio.to_thread(memory.search_rules, q, 5)
        return {"query": q, "results": [h.model_dump() for h in hits], "backend": memory.backend}
    return {"sections": mv_act.MV_ACT_SECTIONS, "count": len(mv_act.MV_ACT_SECTIONS)}


# --------------------------------------------------------------------------- #
# Demo controls
# --------------------------------------------------------------------------- #
@app.post("/api/demo/reset")
async def demo_reset() -> dict:
    """Wipe all state so a pitch can be run from zero."""
    await asyncio.to_thread(db.reset_database)
    return {"status": "reset", "ledger": await asyncio.to_thread(db.verify_chain)}


@app.get("/api/demo/scenarios")
async def demo_scenarios() -> dict:
    """The scenario set the simulator can reproduce, for the console's picker."""
    from .agents.simulator import SCENARIOS

    return {
        "scenarios": [
            {
                "id": key,
                "label": spec["label"],
                "violation": spec["violation"],
                "expected_verdict": _expected(key),
            }
            for key, spec in SCENARIOS.items()
        ],
        "mode": settings.mode,
    }


def _expected(scenario: str) -> str:
    return {
        "clean": "ISSUE",
        "triple": "ISSUE",
        "occluded": "ESCALATE",
        "phone": "ESCALATE",
        "night": "ESCALATE",
        "parallax": "REJECT",
        "empty": "REJECT",
    }.get(scenario, "ESCALATE")
