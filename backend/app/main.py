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

def _parse_cors_origins(raw: str) -> list[str]:
    """Parse CORS_ORIGINS into an allow-list.

    Trailing slashes are stripped, because a browser's `Origin` header is only
    ever scheme+host+port with no path or slash — so a configured
    `https://app.vercel.app/` would silently never match `https://app.vercel.app`
    and every request would look like the API is offline. Normalising here means
    the value works whether or not someone pastes the slash.
    """
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return origins or ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
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
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                out.write(chunk)
    finally:
        # Starlette spools the multipart body into its own temp file, which
        # lives until the request ends — and the request does not end until the
        # SSE audit finishes streaming, minutes later. Closing here drops that
        # second copy as soon as we have our own, halving the peak for a large
        # clip. That matters most where the filesystem is in memory (Cloud
        # Run's is), because there the spare copy is spare RAM.
        await file.close()

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


def _load_seed_module():
    """Import `scripts/seed_demo.py`, which ships inside the image."""
    import importlib
    import sys

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return importlib.import_module("seed_demo")


@app.post("/api/demo/seed")
async def demo_seed(force: bool = Query(False)) -> dict:
    """Populate the ledger and bias dashboard with a decision history.

    A container's filesystem does not survive a redeploy or an instance
    recycle, and there is no shell to run `scripts/seed_demo.py` in, so a
    freshly deployed backend otherwise serves an empty ledger and an empty
    dashboard — the two screens a pitch opens on. This runs the same seed
    events through the same pipeline, so the hash chain still verifies:
    nothing is inserted behind the pipeline's back.

    Seeding forces simulation regardless of configured mode. The seed frames
    are flat synthetic stills carrying their scenario in the filename; sending
    them through live vision would spend real quota to have a model correctly
    report "no violation visible" on a blank rectangle. An audit that arrives
    during the ~30s seed therefore also runs in simulation — acceptable for
    what is an operator action taken before a demo, not during one.
    """
    existing = await asyncio.to_thread(db.list_challans, 1, None)
    if existing and not force:
        raise HTTPException(
            status_code=409,
            detail="Ledger already has records. Pass ?force=true to reset and reseed.",
        )

    seed = _load_seed_module()
    await asyncio.to_thread(db.reset_database)
    seed.SEED_DIR.mkdir(parents=True, exist_ok=True)

    was_forced = settings.force_simulation
    settings.force_simulation = True
    counts = {"ISSUE": 0, "REJECT": 0, "ESCALATE": 0}
    try:
        for scenario, junction, camera, ts in seed.SEED_EVENTS:
            filename = f"{scenario}_{camera}_{junction}_{ts}.jpg"
            path = seed.SEED_DIR / filename
            await asyncio.to_thread(seed._still, path, f"{scenario} @ {junction} {ts}")
            result = await seed._run_one(path, filename)
            if result:
                counts[result["verdict"]["verdict"]] += 1
    finally:
        settings.force_simulation = was_forced

    return {
        "status": "seeded",
        "events": sum(counts.values()),
        "verdicts": counts,
        "ledger": await asyncio.to_thread(db.verify_chain),
        "mode": settings.mode,
    }


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
