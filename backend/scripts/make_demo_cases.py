"""Generate the demo case files an analyst uploads during the pitch.

Five alerts spanning the decision boundary: two the auditor must refuse, two it
must act on, and one genuinely ambiguous case it must escalate rather than
guess at. The filenames say which is which so a demo can be driven without
notes; the pipeline itself only ever sees the transactions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR  # noqa: E402
from app.tools.case_builder import write_case  # noqa: E402

OUT_DIR = DATA_DIR / "demo_cases"

CASES = [
    ("traveller", "indiranagar", "4532111122226021", "2026-08-08T14:20:00",
     "01_impossible_travel_FALSE_POSITIVE"),
    ("card_testing", "hsr", "4532111122224821", "2026-08-08T02:14:00",
     "02_card_testing_REAL_FRAUD"),
    ("firsttime", "koramangala", "5241333344443033", "2026-08-08T18:05:00",
     "03_first_purchase_AMBIGUOUS"),
    ("salary", "mgroad", "4532111122227007", "2026-08-08T11:00:00",
     "04_salary_cycle_FALSE_POSITIVE"),
    ("takeover", "tnagar", "6011555566667703", "2026-08-08T03:47:00",
     "05_account_takeover_REAL_FRAUD"),
]


def main() -> int:
    for scenario, junction, account, ts, name in CASES:
        path = write_case(OUT_DIR / f"{name}.json", scenario, junction, account, ts)
        print(f"  {path.name:<44} {path.stat().st_size:>6} bytes")
    print(f"\nWrote {len(CASES)} case files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
