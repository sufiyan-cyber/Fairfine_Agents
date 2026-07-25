"""Bias dashboard aggregation.

The metric that matters is `false_positive_rate`: the share of AI-flagged
events that the auditor stopped before a citizen was charged. A high rate for
one area or vehicle class is not a compliment to the auditor — it is a signal
that the upstream detector performs worse there, which is exactly the kind of
disparity automated enforcement tends to hide.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from . import db
from .schemas import BiasDashboard, BiasSlice
from .tools import mv_act


def _slice(key: str, rows: list[dict]) -> BiasSlice:
    total = len(rows)
    issued = sum(1 for r in rows if r["verdict"] == "ISSUE")
    rejected = sum(1 for r in rows if r["verdict"] == "REJECT")
    escalated = sum(1 for r in rows if r["verdict"] == "ESCALATE")
    stopped = rejected + escalated
    avg_trust = sum(float(r["trust_score"]) for r in rows) / total if total else 0.0
    return BiasSlice(
        key=key,
        total=total,
        issued=issued,
        rejected=rejected,
        escalated=escalated,
        false_positive_rate=round(stopped / total, 4) if total else 0.0,
        avg_trust=round(avg_trust, 3),
    )


def _group(rows: list[dict], key_fn) -> list[BiasSlice]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[key_fn(row)].append(row)
    slices = [_slice(k, v) for k, v in buckets.items()]
    slices.sort(key=lambda s: s.total, reverse=True)
    return slices


def _hour_of(row: dict) -> str:
    try:
        parsed = datetime.fromisoformat(str(row["event_ts"]).replace("Z", "+00:00"))
        return f"{parsed.hour:02d}:00"
    except (ValueError, AttributeError, KeyError):
        return "unknown"


def build_dashboard(limit: int = 1000) -> BiasDashboard:
    rows = db.list_challans(limit=limit)
    total = len(rows)
    issued = sum(1 for r in rows if r["verdict"] == "ISSUE")
    rejected = sum(1 for r in rows if r["verdict"] == "REJECT")
    escalated = sum(1 for r in rows if r["verdict"] == "ESCALATE")
    prevented = rejected + escalated

    by_hour = _group(rows, _hour_of)
    by_hour.sort(key=lambda s: s.key)

    # Cumulative prevention rate over the decision sequence — the trend line.
    over_time: list[dict] = []
    ordered = sorted(rows, key=lambda r: r["created_at"])
    running_total = 0
    running_prevented = 0
    for row in ordered:
        running_total += 1
        if row["verdict"] in {"REJECT", "ESCALATE"}:
            running_prevented += 1
        over_time.append(
            {
                "index": running_total,
                "challan_id": row["challan_id"],
                "ts": row["created_at"],
                "verdict": row["verdict"],
                "trust_score": round(float(row["trust_score"]), 3),
                "prevention_rate": round(running_prevented / running_total, 4),
            }
        )

    return BiasDashboard(
        generated_at=db.utc_now(),
        total_events=total,
        issued=issued,
        rejected=rejected,
        escalated=escalated,
        wrongful_fines_prevented=prevented,
        prevention_rate=round(prevented / total, 4) if total else 0.0,
        by_area=_group(rows, lambda r: r.get("area") or "unknown"),
        by_vehicle_type=_group(rows, lambda r: r.get("vehicle_type") or "unknown"),
        by_violation_type=_group(
            rows, lambda r: mv_act.label_for(r.get("violation_type", "none"))
        ),
        by_hour=by_hour,
        over_time=over_time,
    )
