"""IngestAgent — case-file parsing + account context.

Exposed to ADK as a FunctionTool. Reads an uploaded fraud alert (a JSON case
file exported from the bank's monitoring system) and normalises it into the
flagged transaction plus the account's surrounding activity, which is the
evidence every downstream agent reasons over.

The surrounding activity is not decoration. Almost every false positive in
fraud detection is a transaction that looks alarming alone and entirely
ordinary next to the customer's own history, so the auditor is never shown the
flagged transaction on its own.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from ..schemas import TxnEvent
from ..tools.accounts import mask_account

_JSON_SUFFIXES = {".json", ".txt"}

_CHANNELS = {"card_present", "ecom", "atm", "transfer", "wallet", "recurring"}
_STATUSES = {"approved", "declined", "pending", "reversed"}


def _parse_ts(value: str | None, fallback: datetime) -> str:
    """ISO-8601, tolerating the several shapes a monitoring export may use."""
    if value:
        text = str(value).strip().replace("Z", "+00:00")
        for parser in (
            lambda t: datetime.fromisoformat(t),
            lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S"),
            lambda t: datetime.strptime(t, "%d/%m/%Y %H:%M"),
        ):
            try:
                parsed = parser(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.isoformat(timespec="milliseconds")
            except (ValueError, TypeError):
                continue
    return fallback.isoformat(timespec="milliseconds")


def _coerce_event(raw: dict, index: int, fallback_ts: datetime, flagged: bool) -> TxnEvent:
    """One transaction row, with every field defaulted rather than trusted.

    A monitoring export is a foreign document — missing keys, string amounts and
    unexpected channel names are all normal, and none of them should be able to
    fail an audit.
    """
    try:
        amount = round(float(raw.get("amount", 0) or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0

    channel = str(raw.get("channel", "") or "").strip().lower().replace("-", "_")
    if channel not in _CHANNELS:
        channel = "ecom" if raw.get("merchant") else "transfer"

    status = str(raw.get("status", "") or "").strip().lower()
    if status not in _STATUSES:
        status = "approved"

    return TxnEvent(
        event_id=str(raw.get("id") or raw.get("event_id") or f"txn_{index + 1:03d}"),
        ts=_parse_ts(raw.get("ts") or raw.get("timestamp"), fallback_ts),
        amount=amount,
        currency=str(raw.get("currency", "INR") or "INR").upper()[:3],
        merchant=str(raw.get("merchant", "") or "Unknown merchant")[:120],
        category=str(raw.get("category", "") or "uncategorised").strip().lower(),
        channel=channel,
        device_id=str(raw.get("device_id", "") or "")[:64],
        city=str(raw.get("city", "") or "")[:80],
        country=str(raw.get("country", "IN") or "IN").upper()[:2],
        status=status,
        is_flagged=flagged,
    )


def ingest_case(
    source_path: str,
    events_per_case: int | None = None,
    account_ref: str | None = None,
) -> dict:
    """Parse an uploaded fraud alert into a flagged transaction plus history.

    Args:
        source_path: Path to an uploaded JSON case file.
        events_per_case: Cap on surrounding history events. Defaults to config.
        account_ref: Override the account reference found in the file.

    Returns:
        `{"events": [...], "case_ref": str, "account_ref": str, "source": str,
          "flagged_index": int}`.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if source.suffix.lower() not in _JSON_SUFFIXES:
        raise ValueError(
            f"{source.name} is not a case file. Upload the JSON alert exported "
            "from the monitoring system (.json)."
        )

    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{source.name} is not valid JSON: {exc}") from exc

    # Accept three shapes: the full case envelope, a bare list of transactions
    # (the first flagged one wins), or a single transaction object.
    if isinstance(payload, list):
        payload = {"recent_activity": payload}
    elif not isinstance(payload, dict):
        raise ValueError("Case file must be a JSON object or a list of transactions.")

    flagged_raw = (
        payload.get("flagged_transaction")
        or payload.get("transaction")
        or payload.get("alert")
    )
    history_raw = (
        payload.get("recent_activity")
        or payload.get("history")
        or payload.get("transactions")
        or []
    )
    if not isinstance(history_raw, list):
        history_raw = []

    if flagged_raw is None:
        flagged_candidates = [
            row for row in history_raw if isinstance(row, dict) and row.get("flagged")
        ]
        flagged_raw = flagged_candidates[0] if flagged_candidates else None
        if flagged_raw is None and history_raw:
            flagged_raw = history_raw[-1]
        history_raw = [row for row in history_raw if row is not flagged_raw]

    if not isinstance(flagged_raw, dict):
        raise ValueError(
            "No flagged transaction found. The case file needs a "
            "`flagged_transaction` object, or a `recent_activity` list with one "
            "entry marked `\"flagged\": true`."
        )

    now = datetime.now(timezone.utc)
    cap = events_per_case or settings.events_per_case

    flagged = _coerce_event(flagged_raw, 0, now, flagged=True)
    history = [
        _coerce_event(row, index, now, flagged=False)
        for index, row in enumerate(history_raw)
        if isinstance(row, dict)
    ]
    # Most recent history first, capped — the auditor gets the customer's
    # current behaviour, not their entire life.
    history.sort(key=lambda event: event.ts, reverse=True)
    history = history[: max(cap - 1, 0)]

    # Chronological, with the flagged transaction in its true position.
    events = sorted([flagged, *history], key=lambda event: event.ts)
    flagged_index = next(
        (i for i, event in enumerate(events) if event.is_flagged), 0
    )

    resolved_account = (
        account_ref
        or payload.get("account_ref")
        or payload.get("card")
        or payload.get("account")
        or flagged_raw.get("account_ref")
        or ""
    )
    resolved_account = mask_account(str(resolved_account)) if resolved_account else "UNRESOLVED"

    case_ref = str(
        payload.get("case_ref") or payload.get("alert_id") or f"alert_{uuid.uuid4().hex[:10]}"
    )

    return {
        "events": [event.model_dump() for event in events],
        "case_ref": case_ref,
        "account_ref": resolved_account,
        "source": source.name,
        "flagged_index": flagged_index,
        "history_count": len(history),
        "alert_rule": str(payload.get("alert_rule") or payload.get("rule") or ""),
    }


def events_to_text(events: list[dict], flagged_index: int = 0) -> str:
    """The transaction ledger as a fixed-width block for the model to read.

    Rendered as a table rather than raw JSON because the temporal and amount
    patterns — which are what actually distinguish fraud from an unusual day —
    are far easier to see in aligned columns.
    """
    if not events:
        return "No transaction events available."

    header = (
        f"{'':2} {'TIME (UTC)':<20} {'AMOUNT':>12}  {'CHANNEL':<14} "
        f"{'CATEGORY':<14} {'MERCHANT':<28} {'CITY':<16} {'STATUS':<9} DEVICE"
    )
    lines = [header, "-" * len(header)]

    for index, event in enumerate(events):
        marker = ">>" if index == flagged_index or event.get("is_flagged") else "  "
        amount = f"{event.get('currency', 'INR')} {float(event.get('amount', 0)):,.2f}"
        lines.append(
            f"{marker} {str(event.get('ts', ''))[:19]:<20} {amount:>12}  "
            f"{str(event.get('channel', '')):<14} {str(event.get('category', '')):<14} "
            f"{str(event.get('merchant', ''))[:27]:<28} "
            f"{(str(event.get('city', '')) + ', ' + str(event.get('country', ''))).strip(', ')[:15]:<16} "
            f"{str(event.get('status', '')):<9} {str(event.get('device_id', '')) or '—'}"
        )

    lines.append("")
    lines.append(">> marks the transaction the monitoring system flagged.")
    return "\n".join(lines)
