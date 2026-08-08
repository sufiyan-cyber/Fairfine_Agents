"""One live audit against a demo case — the pre-flight check before a pitch.

Run it fifteen minutes before presenting. It proves the model backend is
serving, warms the connection pools, and prints the verdict so a surprise is
found here rather than on stage.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import pipeline  # noqa: E402
from app.config import DATA_DIR, settings  # noqa: E402


async def main(case: str) -> int:
    path = DATA_DIR / "demo_cases" / case
    if not path.exists():
        print(f"No such case: {path}\nRun scripts/make_demo_cases.py first.")
        return 1

    print(f"mode={settings.mode}  region={settings.google_cloud_location}")
    print(f"case={path.name}\n")

    result = None
    async for envelope in pipeline.run_audit(str(path), path.name):
        kind = envelope["type"]
        if kind == "trace":
            for step in envelope["data"]:
                if step["status"] in {"done", "error"} and step.get("detail"):
                    print(f"  {step['agent']:<18} {step['status']:<7} {step['detail'][:88]}")
        elif kind == "result":
            result = envelope["data"]
        elif kind == "error":
            print(f"\nERROR: {envelope['data']['message']}")
            return 1

    if not result:
        print("\nNo result produced.")
        return 1

    verdict = result["verdict"]
    print(f"\n  VERDICT      {verdict['verdict']}")
    print(f"  TRUST        {verdict['trust_score']:.0%}")
    print(f"  PATTERN      {result['signal']['fraud_type']}")
    print(f"  ATTRIBUTION  {result['attribution']['account_ref']} "
          f"min={result['attribution']['min_confidence']:.0%} "
          f"known_behaviour={result['attribution']['matches_known_behaviour']}")
    print(f"  CHECKS       {verdict['checks']}")
    print(f"\n  REASONING\n  {verdict['reasoning']}")
    if result.get("naive"):
        print(f"\n  NAIVE ENGINE would_block={result['naive']['would_issue']} "
              f"amount={result['naive']['amount_held']}")
    return 0


if __name__ == "__main__":
    case = sys.argv[1] if len(sys.argv) > 1 else "01_impossible_travel_FALSE_POSITIVE.json"
    raise SystemExit(asyncio.run(main(case)))
