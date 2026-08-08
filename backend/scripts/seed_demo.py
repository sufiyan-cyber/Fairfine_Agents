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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, pipeline  # noqa: E402
from app.config import DATA_DIR  # noqa: E402
from app.tools.case_builder import write_case  # noqa: E402

SEED_DIR = DATA_DIR / "seed_cases"

# (scenario hint, city slug, masked account, timestamp) — spread across
# regions, customer segments and hours so the dashboard has something to
# disaggregate. The account reference drives the segment, so repeating one
# keeps the same customer.
SEED_EVENTS = [
    ("card_testing", "hsr", "4532111122224821", "2026-07-21T08:15:02"),
    ("clean", "koramangala", "4532111122223190", "2026-07-21T09:41:18"),
    ("firsttime", "silk", "5241333344445508", "2026-07-21T09:58:44"),
    ("traveller", "indiranagar", "4532111122226021", "2026-07-21T11:05:12"),
    ("takeover", "tnagar", "6011555566667703", "2026-07-21T13:22:40"),
    ("salary", "mgroad", "4532111122227007", "2026-07-21T14:47:55"),
    ("thin", "whitefield", "5241333344449019", "2026-07-21T21:33:09"),
    ("card_testing", "hsr", "4532111122224821", "2026-07-22T08:02:31"),
    ("traveller", "silk", "4532111122221106", "2026-07-22T10:17:06"),
    ("firsttime", "koramangala", "5241333344443033", "2026-07-22T12:40:27"),
    ("clean", "mgroad", "4532111122227007", "2026-07-22T15:01:49"),
    ("takeover", "whitefield", "6011555566662214", "2026-07-22T17:28:14"),
    ("salary", "anna", "4532111122225005", "2026-07-22T18:52:03"),
    ("thin", "indiranagar", "5241333344442438", "2026-07-22T22:11:38"),
    ("card_testing", "tnagar", "6011555566666051", "2026-07-23T07:44:51"),
    ("firsttime", "hsr", "4532111122221622", "2026-07-23T11:09:22"),
]


def _case(path: Path, scenario: str, junction: str, account: str, ts: str) -> None:
    """Write the alert case file the pipeline will ingest."""
    write_case(path, scenario, junction, account, ts)


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
        # Force simulation on the shared settings singleton for this process
        # only. Every downstream check (`pipeline`, `memory.embed`) reads the
        # same object, so the whole run — including embeddings — stays local.
        # `force_simulation` rather than blanking the key: on the Vertex path
        # there is no key to blank, and clearing it left the seed running
        # sixteen live audits against real quota.
        settings.force_simulation = True
        print("Seeding in SIMULATION to preserve your Gemini quota.")
        print("Pass --live to seed with real inference instead.\n")

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    db.get_conn()

    print(f"Seeding FairFine with real pipeline runs (mode: {settings.mode})\n")
    counts = {"ISSUE": 0, "REJECT": 0, "ESCALATE": 0}

    for scenario, junction, account, ts in SEED_EVENTS:
        filename = f"{scenario}_{junction}_{ts.replace(':', '-')}.json"
        path = SEED_DIR / filename
        _case(path, scenario, junction, account, ts)
        result = await _run_one(path, filename)
        if not result:
            continue
        verdict = result["verdict"]["verdict"]
        counts[verdict] += 1
        trust = result["verdict"]["trust_score"]
        print(
            f"  {verdict:<9} trust {trust:>5.0%}  "
            f"{result['attribution']['account_ref']:<12} "
            f"{junction:<13} {result['challan_id']}"
        )

    # Duplicate demonstration — same alert, same window, fed twice.
    print("\nDuplicate check: re-submitting an identical alert…")
    dup_name = "card_testing_hsr_2026-07-23T19-30-00.json"
    dup_path = SEED_DIR / dup_name
    _case(dup_path, "card_testing", "hsr", "4532111122224821", "2026-07-23T19:30:00")
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
    print(f"  Blocks prevented:     {prevented} ({prevented / total:.0%})" if total else "")
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
