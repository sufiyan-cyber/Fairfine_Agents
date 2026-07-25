"""SQLite persistence + the append-only hash chain.

The chain is the product's spine: every verdict — ISSUE, REJECT *and* ESCALATE —
is committed here before it can be shown to anyone. A record's hash is
SHA-256 over `prev_hash + canonical_json(payload) + ts`, so rewriting any
historical payload invalidates every hash after it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import settings

GENESIS_HASH = "0" * 64

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_json(payload: Any) -> str:
    """Deterministic serialisation — key order and spacing must never drift,
    otherwise an identical payload would hash differently on replay."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, payload: Any, ts: str) -> str:
    material = f"{prev_hash}{canonical_json(payload)}{ts}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = settings.sqlite_path
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(path), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _init_schema(_conn)
        return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger (
            seq       INTEGER PRIMARY KEY AUTOINCREMENT,
            id        TEXT NOT NULL UNIQUE,
            prev_hash TEXT NOT NULL,
            payload   TEXT NOT NULL,
            hash      TEXT NOT NULL,
            ts        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS challans (
            challan_id     TEXT PRIMARY KEY,
            verdict        TEXT NOT NULL,
            trust_score    REAL NOT NULL,
            violation_type TEXT NOT NULL,
            plate          TEXT NOT NULL,
            location       TEXT NOT NULL,
            area           TEXT NOT NULL DEFAULT 'unknown',
            vehicle_type   TEXT NOT NULL DEFAULT 'unknown',
            camera_id      TEXT NOT NULL DEFAULT '',
            event_ts       TEXT NOT NULL,
            ledger_id      TEXT NOT NULL DEFAULT '',
            ledger_hash    TEXT NOT NULL DEFAULT '',
            result_json    TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_review (
            id            TEXT PRIMARY KEY,
            challan_id    TEXT NOT NULL,
            uncertainty   TEXT NOT NULL,
            trust_score   REAL NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open',
            created_at    TEXT NOT NULL,
            FOREIGN KEY (challan_id) REFERENCES challans(challan_id)
        );

        CREATE TABLE IF NOT EXISTS disputes (
            id             TEXT PRIMARY KEY,
            challan_id     TEXT NOT NULL,
            reason         TEXT NOT NULL,
            original       TEXT NOT NULL,
            outcome        TEXT NOT NULL,
            changed        INTEGER NOT NULL DEFAULT 0,
            reasoning      TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL,
            FOREIGN KEY (challan_id) REFERENCES challans(challan_id)
        );

        CREATE INDEX IF NOT EXISTS idx_challans_created ON challans(created_at);
        CREATE INDEX IF NOT EXISTS idx_challans_plate   ON challans(plate);
        CREATE INDEX IF NOT EXISTS idx_ledger_ts        ON ledger(ts);
        """
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def head() -> sqlite3.Row | None:
    conn = get_conn()
    with _lock:
        return conn.execute("SELECT * FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()


def append_ledger(payload: dict) -> tuple[str, str]:
    """Append one record. Returns `(ledger_id, hash)`.

    Holds the lock across read-head + insert so two concurrent verdicts can
    never chain off the same predecessor and fork the chain.
    """
    conn = get_conn()
    with _lock:
        tip = conn.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = tip["hash"] if tip else GENESIS_HASH
        record_id = f"lgr_{uuid.uuid4().hex[:16]}"
        ts = utc_now()
        digest = compute_hash(prev_hash, payload, ts)
        conn.execute(
            "INSERT INTO ledger (id, prev_hash, payload, hash, ts) VALUES (?, ?, ?, ?, ?)",
            (record_id, prev_hash, canonical_json(payload), digest, ts),
        )
        conn.commit()
    return record_id, digest


def list_ledger(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    conn = get_conn()
    with _lock:
        total = conn.execute("SELECT COUNT(*) AS c FROM ledger").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM ledger ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [_row_to_ledger(r) for r in rows], total


def get_ledger_record(record_id: str) -> dict | None:
    conn = get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (record_id,)).fetchone()
    return _row_to_ledger(row) if row else None


def _row_to_ledger(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "id": row["id"],
        "prev_hash": row["prev_hash"],
        "payload": json.loads(row["payload"]),
        "hash": row["hash"],
        "ts": row["ts"],
    }


def verify_chain() -> dict:
    """Recompute every link. Detects payload tampering *and* re-linking."""
    conn = get_conn()
    with _lock:
        rows = conn.execute("SELECT * FROM ledger ORDER BY seq ASC").fetchall()

    expected_prev = GENESIS_HASH
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return {
                "valid": False,
                "records_checked": len(rows),
                "broken_at": row["id"],
                "reason": (
                    f"Link mismatch: record claims prev_hash "
                    f"{row['prev_hash'][:12]}… but chain head was {expected_prev[:12]}…"
                ),
                "head_hash": rows[-1]["hash"] if rows else None,
            }
        recomputed = compute_hash(row["prev_hash"], json.loads(row["payload"]), row["ts"])
        if recomputed != row["hash"]:
            return {
                "valid": False,
                "records_checked": len(rows),
                "broken_at": row["id"],
                "reason": (
                    "Payload tampering: stored hash does not match SHA-256 of "
                    "(prev_hash + canonical_json(payload) + ts)"
                ),
                "head_hash": rows[-1]["hash"] if rows else None,
            }
        expected_prev = row["hash"]

    return {
        "valid": True,
        "records_checked": len(rows),
        "broken_at": None,
        "reason": None,
        "head_hash": rows[-1]["hash"] if rows else GENESIS_HASH,
    }


# --------------------------------------------------------------------------- #
# Challans
# --------------------------------------------------------------------------- #
def save_challan(record: dict) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT OR REPLACE INTO challans (
                challan_id, verdict, trust_score, violation_type, plate, location,
                area, vehicle_type, camera_id, event_ts, ledger_id, ledger_hash,
                result_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["challan_id"],
                record["verdict"],
                record["trust_score"],
                record["violation_type"],
                record["plate"],
                record["location"],
                record.get("area", "unknown"),
                record.get("vehicle_type", "unknown"),
                record.get("camera_id", ""),
                record["event_ts"],
                record.get("ledger_id", ""),
                record.get("ledger_hash", ""),
                canonical_json(record["result"]),
                record.get("created_at") or utc_now(),
            ),
        )
        conn.commit()


def get_challan(challan_id: str) -> dict | None:
    conn = get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM challans WHERE challan_id = ?", (challan_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["result"] = json.loads(data.pop("result_json"))
    return data


def list_challans(limit: int = 100, verdict: str | None = None) -> list[dict]:
    conn = get_conn()
    query = "SELECT * FROM challans"
    params: list[Any] = []
    if verdict:
        query += " WHERE verdict = ?"
        params.append(verdict)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json"))
        out.append(data)
    return out


def recent_events_for_dedup(plate: str, location: str, window_seconds: int) -> list[dict]:
    """Candidate near-duplicates: same plate, recent. Location match is scored
    by the caller rather than filtered here, since junction naming varies."""
    conn = get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM challans WHERE plate = ? ORDER BY created_at DESC LIMIT 25",
            (plate,),
        ).fetchall()

    matches = []
    for row in rows:
        data = dict(row)
        blob = data.pop("result_json", None)
        # Carry the detector's description forward so the semantic comparison
        # is made against like text on both sides.
        data["description"] = ""
        if blob:
            try:
                data["description"] = (
                    json.loads(blob).get("detection", {}).get("region_description", "")
                )
            except (json.JSONDecodeError, AttributeError):
                pass
        matches.append(data)
    return matches


def update_challan_verdict(
    challan_id: str, verdict: str, trust_score: float, result: dict
) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            "UPDATE challans SET verdict = ?, trust_score = ?, result_json = ? WHERE challan_id = ?",
            (verdict, trust_score, canonical_json(result), challan_id),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Human review queue + disputes
# --------------------------------------------------------------------------- #
def enqueue_review(
    challan_id: str, uncertainty: str, trust_score: float, review_id: str | None = None
) -> str:
    """Insert a human-review row. The caller may supply `review_id` so it can
    be surfaced in the agent trace before the challan row is committed."""
    conn = get_conn()
    review_id = review_id or f"rev_{uuid.uuid4().hex[:12]}"
    with _lock:
        conn.execute(
            "INSERT INTO pending_review (id, challan_id, uncertainty, trust_score, created_at)"
            " VALUES (?,?,?,?,?)",
            (review_id, challan_id, uncertainty, trust_score, utc_now()),
        )
        conn.commit()
    return review_id


def list_pending_reviews(limit: int = 50) -> list[dict]:
    conn = get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM pending_review WHERE status = 'open' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def record_dispute(
    challan_id: str, reason: str, original: str, outcome: str, changed: bool, reasoning: str
) -> str:
    conn = get_conn()
    dispute_id = f"dsp_{uuid.uuid4().hex[:12]}"
    with _lock:
        conn.execute(
            "INSERT INTO disputes (id, challan_id, reason, original, outcome, changed, reasoning, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (dispute_id, challan_id, reason, original, outcome, int(changed), reasoning, utc_now()),
        )
        conn.commit()
    return dispute_id


def get_disputes(challan_id: str) -> list[dict]:
    conn = get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM disputes WHERE challan_id = ? ORDER BY created_at DESC", (challan_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def reset_database() -> None:
    """Demo helper — wipes state so a pitch can be re-run from zero."""
    conn = get_conn()
    with _lock:
        for table in ("disputes", "pending_review", "challans", "ledger"):
            conn.execute(f"DELETE FROM {table}")
        # Restart the ledger sequence too, so a reset demo opens at record #1
        # rather than continuing from the previous run's numbering.
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ledger'")
        conn.commit()
