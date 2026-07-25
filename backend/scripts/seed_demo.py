"""Seed the ledger and dashboard with a realistic decision history.

Runs real audits through the real pipeline — nothing is inserted behind the
pipeline's back, so the resulting hash chain verifies and the bias dashboard
reflects genuine verdicts.

    python scripts/seed_demo.py            # simulation (default)
    python scripts/seed_demo.py --live     # force live Gemini inference

Seeding runs in SIMULATION even when a GEMINI_API_KEY is present, on purpose.
The seed fixtures are flat synthetic frames carrying their scenario in the
filename; sending 19 of them through live vision would spend real quota to have
a model correctly report "no violation visible" on a blank rectangle. The point
of this script is to populate the ledger and dashboard, and the simulator does
that deterministically for free. Audit real footage through /console to
exercise the live path.

Ends by feeding the clean clip a second time to demonstrate duplicate
rejection, then verifies the whole chain.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, pipeline  # noqa: E402
from app.config import DATA_DIR  # noqa: E402

SEED_DIR = DATA_DIR / "seed_frames"

# (scenario hint, junction slug, camera, timestamp) — spread across areas,
# vehicle classes and hours so the dashboard has something to disaggregate.
SEED_EVENTS = [
    ("clean_helmet", "hsr", "CAM-KA05-014", "2026-07-21T08-15-02"),
    ("clean_helmet", "koramangala", "CAM-KA05-031", "2026-07-21T09-41-18"),
    ("occluded_plate", "silk", "CAM-KA51-008", "2026-07-21T09-58-44"),
    ("parallax_redlight", "indiranagar", "CAM-KA03-021", "2026-07-21T11-05-12"),
    ("triple_riding", "tnagar", "CAM-TN09-003", "2026-07-21T13-22-40"),
    ("phone_use", "mgroad", "CAM-KA01-007", "2026-07-21T14-47-55"),
    ("night_glare", "whitefield", "CAM-KA53-019", "2026-07-21T21-33-09"),
    ("clean_helmet", "hsr", "CAM-KA05-014", "2026-07-22T08-02-31"),
    ("parallax_redlight", "silk", "CAM-KA51-011", "2026-07-22T10-17-06"),
    ("occluded_plate", "koramangala", "CAM-KA05-033", "2026-07-22T12-40-27"),
    ("empty_clear", "mgroad", "CAM-KA01-007", "2026-07-22T15-01-49"),
    ("triple_riding", "whitefield", "CAM-KA53-022", "2026-07-22T17-28-14"),
    ("phone_use", "anna", "CAM-TN01-005", "2026-07-22T18-52-03"),
    ("night_glare", "indiranagar", "CAM-KA03-024", "2026-07-22T22-11-38"),
    ("clean_helmet", "tnagar", "CAM-TN09-006", "2026-07-23T07-44-51"),
    ("occluded_plate", "hsr", "CAM-KA05-016", "2026-07-23T11-09-22"),
]


def _still(path: Path, label: str) -> None:
    """A placeholder still. The scenario is carried by the filename; in
    simulation mode perception is deterministic, so the pixels only need to be
    a decodable frame of the right shape."""
    frame = np.full((720, 1280, 3), 52, dtype=np.uint8)
    cv2.rectangle(frame, (0, 430), (1280, 720), (62, 62, 66), -1)
    cv2.line(frame, (0, 470), (1280, 470), (210, 210, 214), 4)
    cv2.putText(frame, "SYNTHETIC SEED FRAME", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (150, 190, 240), 2, cv2.LINE_AA)
    cv2.putText(frame, label, (40, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 205), 2, cv2.LINE_AA)
    cv2.imwrite(str(path), frame)


async def _run_one(path: Path, filename: str) -> dict | None:
    result = None
    async for envelope in pipeline.run_audit(str(path), filename):
        if envelope["type"] == "result":
            result = envelope["data"]
        elif envelope["type"] == "error":
            print(f"    ! {envelope['data']['message']}")
    return result


async def main(force_live: bool = False) -> int:
    from app.config import settings

    if not force_live and settings.live_llm:
        # Blank the key on the shared settings singleton for this process only.
        # Every downstream check (`pipeline`, `memory.embed`) reads the same
        # object, so the whole run — including embeddings — stays local.
        settings.gemini_api_key = ""
        print("Seeding in SIMULATION to preserve your Gemini quota.")
        print("Pass --live to seed with real inference instead.\n")

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    db.get_conn()

    print(f"Seeding FairFine with real pipeline runs (mode: {settings.mode})\n")
    counts = {"ISSUE": 0, "REJECT": 0, "ESCALATE": 0}

    for scenario, junction, camera, ts in SEED_EVENTS:
        filename = f"{scenario}_{camera}_{junction}_{ts}.jpg"
        path = SEED_DIR / filename
        _still(path, f"{scenario} @ {junction} {ts}")
        result = await _run_one(path, filename)
        if not result:
            continue
        verdict = result["verdict"]["verdict"]
        counts[verdict] += 1
        trust = result["verdict"]["trust_score"]
        print(
            f"  {verdict:<9} trust {trust:>5.0%}  {result['plate']['plate']:<12} "
            f"{junction:<13} {result['challan_id']}"
        )

    # Duplicate demonstration — same clip, same event window, fed twice.
    print("\nDuplicate check: re-submitting an identical event…")
    dup_name = "clean_helmet_CAM-KA05-014_hsr_2026-07-23T19-30-00.jpg"
    dup_path = SEED_DIR / dup_name
    _still(dup_path, "duplicate probe")
    first = await _run_one(dup_path, dup_name)
    second = await _run_one(dup_path, dup_name)
    for tag, res in (("first ", first), ("second", second)):
        if res:
            counts[res["verdict"]["verdict"]] = counts.get(res["verdict"]["verdict"], 0) + 1
            print(
                f"  {tag}: {res['verdict']['verdict']:<9} "
                f"duplicate={res['duplicate']['is_duplicate']}  {res['challan_id']}"
            )

    verification = db.verify_chain()
    print("\n--- Summary ---")
    total = sum(counts.values())
    print(f"  Decisions:            {total}")
    print(f"  ISSUE:                {counts['ISSUE']}")
    print(f"  ESCALATE:             {counts['ESCALATE']}")
    print(f"  REJECT:               {counts['REJECT']}")
    prevented = counts["ESCALATE"] + counts["REJECT"]
    print(f"  Fines prevented:      {prevented} ({prevented / total:.0%})" if total else "")
    print(f"\n  Ledger valid:         {verification['valid']}")
    print(f"  Records checked:      {verification['records_checked']}")
    print(f"  Head hash:            {str(verification['head_hash'])[:32]}…")

    return 0 if verification["valid"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Seed with real Gemini inference instead of the simulator (spends quota).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(force_live=args.live)))
