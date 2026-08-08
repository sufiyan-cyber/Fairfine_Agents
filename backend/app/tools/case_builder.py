"""Synthetic fraud-alert case files.

Every case is generated deterministically from a seed so a demo replays
identically, and every one is *plausible* rather than cartoonish — the whole
point of the auditor is that real false positives look alarming until you read
the surrounding history, so the surrounding history has to be real enough to
carry the argument.

No real cardholder data. No real merchant identifiers. Nothing here touches a
payment network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CITY = {
    "hsr": ("Bengaluru", "IN"),
    "koramangala": ("Bengaluru", "IN"),
    "indiranagar": ("Bengaluru", "IN"),
    "tnagar": ("Chennai", "IN"),
    "mgroad": ("Bengaluru", "IN"),
    "whitefield": ("Bengaluru", "IN"),
    "silk": ("Bengaluru", "IN"),
    "anna": ("Chennai", "IN"),
}

_GROCERY = ["FreshMart Daily", "More Supermarket", "Nilgiris 1905"]
_FUEL = ["HP Petro Stop", "Indian Oil Outlet"]
_FOOD = ["Empire Restaurant", "CTR Malleshwaram", "Anand Sweets"]
_UTIL = ["BESCOM Bill Pay", "ACT Fibernet", "Airtel Postpaid"]


_ALERT_SCORE = {
    "card_testing": 0.96,
    "takeover": 0.94,
    "traveller": 0.91,
    "firsttime": 0.88,
    "salary": 0.87,
    "thin": 0.83,
    "clean": 0.72,
}


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _txn(
    ts: datetime,
    amount: float,
    merchant: str,
    category: str,
    channel: str = "ecom",
    device: str = "dev_home_01",
    city: str = "Bengaluru",
    country: str = "IN",
    status: str = "approved",
    flagged: bool = False,
) -> dict:
    return {
        "ts": ts.isoformat(timespec="milliseconds"),
        "amount": round(amount, 2),
        "currency": "INR",
        "merchant": merchant,
        "category": category,
        "channel": channel,
        "device_id": device,
        "city": city,
        "country": country,
        "status": status,
        "flagged": flagged,
    }


def _baseline(base: datetime, city: str, seed: int, days: int = 9) -> list[dict]:
    """The customer's ordinary life: groceries, fuel, bills, the odd meal.

    This is the evidence that makes a false positive visible. Without it every
    transaction looks anomalous, which is precisely how threshold engines end
    up blocking people for buying something new.
    """
    rows: list[dict] = []
    for day in range(days, 0, -1):
        stamp = base - timedelta(days=day)
        if day % 3 == 0:
            rows.append(
                _txn(
                    stamp.replace(hour=19, minute=10 + (seed >> day) % 40),
                    380 + (seed >> (day + 2)) % 900,
                    _GROCERY[(seed >> day) % len(_GROCERY)],
                    "grocery",
                    channel="card_present",
                    city=city,
                )
            )
        if day % 4 == 1:
            rows.append(
                _txn(
                    stamp.replace(hour=8, minute=30 + (seed >> day) % 25),
                    1200 + (seed >> day) % 700,
                    _FUEL[(seed >> day) % len(_FUEL)],
                    "fuel",
                    channel="card_present",
                    city=city,
                )
            )
        if day % 5 == 2:
            rows.append(
                _txn(
                    stamp.replace(hour=13, minute=5 + (seed >> day) % 45),
                    240 + (seed >> day) % 460,
                    _FOOD[(seed >> day) % len(_FOOD)],
                    "restaurant",
                    channel="card_present",
                    city=city,
                )
            )
        if day == 6:
            rows.append(
                _txn(
                    stamp.replace(hour=11, minute=2),
                    1899.0,
                    _UTIL[seed % len(_UTIL)],
                    "utility",
                    channel="recurring",
                )
            )
    return rows


def build_case(scenario: str, junction: str, account_no: str, ts: str) -> dict:
    """One alert case file, matching a simulator scenario."""
    city, country = _CITY.get(junction, ("Bengaluru", "IN"))
    base = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    seed = _seed(f"{scenario}:{junction}:{account_no}")
    history = _baseline(base, city, seed)
    flagged: dict
    alert_rule = ""
    # The upstream model's own score — the number that fired this alert. Note
    # how high it is on the false positives: that is the entire problem. The
    # bank's model is not unsure and wrong, it is confident and wrong.
    alert_score = _ALERT_SCORE.get(scenario, 0.88)

    if scenario == "card_testing":
        alert_rule = "VELOCITY_CNP_BURST"
        for offset in (150, 110, 70):
            history.append(
                _txn(
                    base - timedelta(seconds=offset),
                    39.0 + offset % 7,
                    "GiftCardHub Online",
                    "gift_card",
                    channel="ecom",
                    device="dev_unknown_9f2",
                    city="Unknown",
                    status="declined",
                )
            )
        flagged = _txn(
            base, 42.0, "GiftCardHub Online", "gift_card",
            channel="ecom", device="dev_unknown_9f2", city="Unknown", flagged=True,
        )

    elif scenario == "takeover":
        alert_rule = "DEVICE_CHANGE_THEN_TRANSFER"
        history.append(
            _txn(
                base - timedelta(minutes=40), 0.0, "Device registration change",
                "transfer", channel="transfer", device="dev_new_4b8", city="Unknown",
                status="approved",
            )
        )
        flagged = _txn(
            base, 84_500.0, "Transfer to new beneficiary", "transfer",
            channel="transfer", device="dev_new_4b8", city="Unknown", flagged=True,
        )

    elif scenario == "traveller":
        alert_rule = "GEO_VELOCITY_IMPOSSIBLE"
        # The trap: this earlier purchase is real and card-present, but the
        # merchant settles in nightly batch, so its recorded time is hours
        # after the customer actually stood there.
        history.append(
            _txn(
                base - timedelta(hours=2), 2_450.0, "Seaside Cafe (batch settled)",
                "restaurant", channel="card_present", city="Goa",
            )
        )
        flagged = _txn(
            base, 3_100.0, "Duty Free Bengaluru", "travel",
            channel="card_present", city=city, flagged=True,
        )

    elif scenario == "firsttime":
        alert_rule = "MCC_OUT_OF_PROFILE"
        flagged = _txn(
            base, 64_990.0, "Croma Electronics", "electronics",
            channel="card_present", city=city, flagged=True,
        )

    elif scenario == "thin":
        alert_rule = "AMOUNT_OUT_OF_PROFILE"
        history = history[-2:]
        flagged = _txn(
            base, 12_400.0, "Reliance Digital", "electronics",
            channel="ecom", city=city, flagged=True,
        )

    elif scenario == "salary":
        alert_rule = "STRUCTURING_BELOW_THRESHOLD"
        for day, amount in ((3, 48_000.0), (2, 47_500.0), (1, 46_800.0)):
            history.append(
                _txn(
                    base - timedelta(days=day), amount, "Rent — landlord UPI",
                    "transfer", channel="transfer",
                )
            )
        flagged = _txn(
            base, 49_000.0, "Chit fund contribution", "transfer",
            channel="transfer", city=city, flagged=True,
        )

    else:  # clean
        alert_rule = "MODEL_SCORE_ELEVATED"
        flagged = _txn(
            base, 640.0, _GROCERY[seed % len(_GROCERY)], "grocery",
            channel="card_present", city=city, flagged=True,
        )

    return {
        "case_ref": f"ALERT-{_seed(account_no + ts) % 1_000_000:06d}",
        "account_ref": account_no,
        "alert_rule": alert_rule,
        "alert_score": alert_score,
        "flagged_transaction": flagged,
        "recent_activity": history,
        "disclaimer": "Synthetic case file. No real cardholder or merchant data.",
    }


def write_case(path: Path, scenario: str, junction: str, account_no: str, ts: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_case(scenario, junction, account_no, ts), indent=2),
        encoding="utf-8",
    )
    return path
