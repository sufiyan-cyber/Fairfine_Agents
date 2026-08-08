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
from .guardrails import enkrypt
from .schemas import (
    AuditResult,
    BiasDashboard,
    CitizenView,
    DisputeOutcome,
    DisputeRequest,
    LedgerVerification,
    ReviewDecision,
    ReviewOutcome,
)
from .tools import fraud_rules
from .tools.memory import memory

app = FastAPI(
    title="FairFine",
    version="1.0.0",
    description=(
        "The accountability layer for automated traffic enforcement. An adversarial "
        "agent pipeline audits every AI-flagged transaction before a rupee is held."
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
            "attribution_confidence_floor": settings.attribution_confidence_floor,
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
    account: str = Form(""),
    stream: bool = Query(True, description="Stream the agent trace over SSE"),
):
    """Run the full pipeline on an uploaded fraud alert.

    Streams the live agent trace as Server-Sent Events by default; pass
    `?stream=false` for a single JSON response.
    """
    saved = await _persist_upload(file)
    filename = file.filename or saved.name

    if not stream:
        final: dict | None = None
        error: dict | None = None
        async for envelope in pipeline.run_audit(
            str(saved), filename, operator_note, scenario or None, account or None
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
                "fraud_type": r["fraud_type"],
                "fraud_label": fraud_rules.label_for(r["fraud_type"]),
                "account_ref": r["account_ref"],
                "merchant": r["merchant"],
                "region": r["region"],
                "segment": r["segment"],
                "event_ts": r["event_ts"],
                "ledger_hash": r["ledger_hash"],
                "created_at": r["created_at"],
                "amount_held": r["result"].get("amount_held", 0),
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
@app.post("/api/review/{review_id}/decide", response_model=ReviewOutcome)
async def decide_review(review_id: str, body: ReviewDecision) -> ReviewOutcome:
    """Close an escalated case with an officer's decision.

    The decision is appended to the ledger rather than applied silently, and
    the audit's own verdict is left standing. A human overruling the machine is
    the single most consequential event in the system, so it is the one that
    most needs to be permanently visible next to what the machine said —
    exactly as a dispute appends its re-audit instead of overwriting.
    """
    review = await asyncio.to_thread(db.get_review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"No review {review_id}.")
    if review["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review {review_id} was already decided ({review['decision']}).",
        )

    # The officer's free text is ledgered and shown to the citizen, so it goes
    # through the same redaction as every other human-authored string.
    guarded = enkrypt.redact_pii(body.note)
    resolved = await asyncio.to_thread(
        db.resolve_review, review_id, body.decision, body.officer.strip(), guarded.text
    )
    if resolved is None:
        raise HTTPException(status_code=409, detail="Review was decided concurrently.")

    ledger_id, ledger_hash = await asyncio.to_thread(
        db.append_ledger,
        {
            "challan_id": review["challan_id"],
            "event": "HUMAN_REVIEW",
            "review_id": review_id,
            "decision": body.decision,
            "officer": body.officer.strip(),
            "note": guarded.text,
            "escalated_at_trust": review["trust_score"],
            "uncertainty": review["uncertainty"],
        },
    )

    return ReviewOutcome(
        review_id=review_id,
        challan_id=review["challan_id"],
        decision=body.decision,
        officer=body.officer.strip(),
        note=guarded.text,
        decided_at=resolved["decided_at"],
        ledger_id=ledger_id,
        ledger_hash=ledger_hash,
    )


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
    return {"sections": fraud_rules.FRAUD_RULES, "count": len(fraud_rules.FRAUD_RULES)}


# --------------------------------------------------------------------------- #
# Demo controls
# --------------------------------------------------------------------------- #
@app.post("/api/demo/reset")
async def demo_reset() -> dict:
    """Wipe all state so a pitch can be run from zero.

    Semantic memory is cleared alongside the tables. Leaving it behind meant a
    reset only *looked* clean: the duplicate sweep still remembered every clip
    audited during rehearsal, so the first upload after a reset came back
    REJECT as a duplicate of a run nobody could see any more.
    """
    await asyncio.to_thread(db.reset_database)
    await asyncio.to_thread(memory.reset_events)
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

    Seeding forces simulation regardless of configured mode. The seed cases
    carry their scenario in the filename and the simulator reproduces them
    deterministically; sending sixteen of them through live inference would
    spend real quota to reach verdicts we already know. An audit that arrives
    during the ~20s seed therefore also runs in simulation — acceptable for
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
    await asyncio.to_thread(memory.reset_events)
    seed.SEED_DIR.mkdir(parents=True, exist_ok=True)

    was_forced = settings.force_simulation
    settings.force_simulation = True
    counts = {"ISSUE": 0, "REJECT": 0, "ESCALATE": 0}
    try:
        for scenario, junction, account, ts in seed.SEED_EVENTS:
            filename = f"{scenario}_{junction}_{ts.replace(':', '-')}.json"
            path = seed.SEED_DIR / filename
            await asyncio.to_thread(seed._case, path, scenario, junction, account, ts)
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
                "fraud_type": spec["fraud_type"],
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
