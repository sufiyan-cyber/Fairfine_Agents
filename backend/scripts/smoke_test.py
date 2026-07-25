"""End-to-end smoke test across the whole API surface.

    python scripts/smoke_test.py

Exercises every endpoint in PRD §6, all four citizen languages, the dispute
re-audit, and — importantly — proves the ledger actually detects tampering
rather than just reporting `valid: true` unconditionally.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Indic script in the citizen views would crash a cp1252 console on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

PASS, FAIL = "  PASS", "  FAIL"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL}  {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    client = TestClient(app)
    print("\n=== FairFine smoke test ===\n")

    # Start from zero. Duplicate detection keys on the event timestamp parsed
    # from the filename, so re-running against a populated database would
    # (correctly) reject every fixture as a duplicate.
    client.post("/api/demo/reset")

    # Seed decision history so the ledger and dashboard have volume to check.
    import asyncio
    import contextlib
    import io

    import seed_demo

    with contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(seed_demo.main())

    # -- meta ------------------------------------------------------------- #
    print("Meta")
    health = client.get("/api/health").json()
    check("health", health["status"] == "ok", f"mode={health['mode']}")
    arch = client.get("/api/architecture").json()
    check("architecture", arch["root"] == "FairFineOrchestrator", f"adk={arch['adk_version']}")
    check("thresholds exposed", arch["thresholds"]["issue_trust_threshold"] == 0.90)

    # -- audit ------------------------------------------------------------ #
    print("\nAudit pipeline")
    clips = sorted((ROOT / "data" / "demo_clips").glob("*.mp4"))
    if not clips:
        print("  ! No demo clips. Run scripts/make_demo_clips.py first.")
        return 1

    results: dict[str, dict] = {}
    for clip in clips:
        with clip.open("rb") as fh:
            response = client.post(
                "/api/audit?stream=false",
                files={"file": (clip.name, fh, "video/mp4")},
            )
        ok = response.status_code == 200
        data = response.json() if ok else {}
        verdict = data.get("verdict", {}).get("verdict", "?") if ok else "?"
        expected = (
            "ISSUE" if clip.name.startswith(("clean", "triple"))
            else "ESCALATE" if clip.name.startswith("occluded")
            else "REJECT"
        )
        check(f"{clip.name[:34]:<34} -> {verdict}", ok and verdict == expected,
              f"expected {expected}")
        if ok:
            results[verdict] = data

    # SSE streaming
    with clips[0].open("rb") as fh:
        with client.stream(
            "POST", "/api/audit?stream=true", files={"file": (clips[0].name, fh, "video/mp4")}
        ) as stream:
            events = [line for line in stream.iter_lines() if line.startswith("event:")]
    check("SSE stream emits trace events", len(events) >= 8, f"{len(events)} events")
    check("SSE emits result", any("result" in e for e in events))

    # -- challan views ----------------------------------------------------- #
    print("\nChallan + citizen portal")
    issued = results.get("ISSUE")
    if not issued:
        print("  ! No ISSUE verdict produced; cannot test citizen flow.")
        return 1
    challan_id = issued["challan_id"]

    officer = client.get(f"/api/challan/{challan_id}")
    check("officer evidence packet", officer.status_code == 200)
    check("evidence packet present", officer.json().get("evidence") is not None)

    for lang in ("en", "hi", "kn", "ta"):
        response = client.get(f"/api/challan/{challan_id}/citizen?lang={lang}")
        body = response.json() if response.status_code == 200 else {}
        has_text = bool(body.get("headline")) and bool(body.get("explanation"))
        non_ascii = lang == "en" or any(ord(c) > 127 for c in body.get("headline", ""))
        check(f"citizen view [{lang}]", response.status_code == 200 and has_text and non_ascii,
              body.get("headline", "")[:38])

    check("404 on unknown challan", client.get("/api/challan/CH-NOPE").status_code == 404)

    # -- dispute ----------------------------------------------------------- #
    print("\nDispute -> ReAudit")
    dispute = client.post(
        f"/api/challan/{challan_id}/dispute",
        json={"reason": "I was taking my father to hospital and the signal was not working. My phone is 9876543210."},
    )
    check("dispute accepted", dispute.status_code == 200)
    outcome = dispute.json() if dispute.status_code == 200 else {}
    check("re-audit produced a verdict", bool(outcome.get("new_verdict")),
          f"{outcome.get('original_verdict')} -> {outcome.get('new_verdict')}")
    check("re-audit appended to ledger", bool(outcome.get("ledger_hash")))

    record = client.get(f"/api/ledger/{outcome['ledger_id']}").json()
    payload_text = json.dumps(record["payload"])
    check("PII scrubbed from ledgered dispute", "9876543210" not in payload_text,
          "phone number redacted")

    # -- ledger ------------------------------------------------------------ #
    print("\nLedger")
    ledger = client.get("/api/ledger?limit=200").json()
    check("ledger lists records", ledger["total"] >= 10, f"{ledger['total']} records")
    verify = client.get("/api/ledger/verify").json()
    check("chain verifies", verify["valid"] is True, f"{verify['records_checked']} checked")

    # Tamper detection — mutate a payload directly in SQLite and re-verify.
    conn = db.get_conn()
    victim = conn.execute("SELECT id, payload FROM ledger ORDER BY seq ASC LIMIT 1 OFFSET 2").fetchone()
    original_payload = victim["payload"]
    tampered = json.loads(original_payload)
    tampered["verdict"] = "ISSUE"
    tampered["trust_score"] = 0.99
    conn.execute("UPDATE ledger SET payload = ? WHERE id = ?",
                 (json.dumps(tampered, sort_keys=True, separators=(",", ":")), victim["id"]))
    conn.commit()

    broken = client.get("/api/ledger/verify").json()
    check("tampering detected", broken["valid"] is False, broken.get("reason", "")[:46])
    check("tamper located", broken.get("broken_at") == victim["id"], str(broken.get("broken_at")))

    conn.execute("UPDATE ledger SET payload = ? WHERE id = ?", (original_payload, victim["id"]))
    conn.commit()
    restored = client.get("/api/ledger/verify").json()
    check("chain valid after restore", restored["valid"] is True)

    # -- dashboard + rules -------------------------------------------------- #
    print("\nDashboard + rules")
    dash = client.get("/api/dashboard/bias").json()
    check("dashboard aggregates", dash["total_events"] >= 10, f"{dash['total_events']} events")
    check("by_area populated", len(dash["by_area"]) >= 2, f"{len(dash['by_area'])} areas")
    check("by_vehicle_type populated", len(dash["by_vehicle_type"]) >= 1)
    check("over_time series", len(dash["over_time"]) >= 10)
    check("prevention rate computed", 0.0 <= dash["prevention_rate"] <= 1.0,
          f"{dash['prevention_rate']:.0%}")

    rules = client.get("/api/rules?q=helmet not worn on two wheeler").json()
    top = rules["results"][0]["section"] if rules["results"] else ""
    check("RAG retrieves helmet section", "129" in top or "194D" in top, top)

    queue = client.get("/api/review-queue").json()
    check("review queue populated", queue["count"] >= 1, f"{queue['count']} pending")

    scenarios = client.get("/api/demo/scenarios").json()
    check("demo scenarios listed", len(scenarios["scenarios"]) == 7)

    # -- validation --------------------------------------------------------- #
    print("\nInput validation")
    bad = client.post("/api/audit?stream=false", files={"file": ("x.txt", b"nope", "text/plain")})
    check("rejects unsupported file type", bad.status_code == 415)
    empty = client.post("/api/audit?stream=false", files={"file": ("x.jpg", b"", "image/jpeg")})
    check("rejects empty upload", empty.status_code == 400)

    print(f"\n=== {'ALL PASSED' if not failures else f'{len(failures)} FAILED'} ===")
    for name in failures:
        print(f"  - {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
