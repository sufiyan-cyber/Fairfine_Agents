"""Enkrypt AI guardrails: PII redaction + bias screening.

Wired into the pipeline as an ADK `before_model_callback`, so owner data is
scrubbed during prompt assembly — before any text reaches an LLM — and the
auditor's reasoning is screened for prejudicial language on the way out.

When `ENKRYPT_API_KEY` is unset the local redactor runs instead. The local path
is a real regex/deny-list redactor, not a stub: the non-negotiable that no raw
PII reaches a prompt holds in both modes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from ..config import settings

# Indian PII patterns most likely to appear in registry data.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("DL_NUMBER", re.compile(r"\b[A-Z]{2}\d{2}\s?\d{11}\b")),
    ("ADDRESS_PIN", re.compile(r"\b[1-9]\d{5}\b")),
    ("ACCOUNT", re.compile(r"\b\d{11,18}\b")),
]

# Attributes an audit decision must never turn on.
_BIAS_TERMS = [
    "caste", "religion", "muslim", "hindu", "christian", "sikh", "dalit",
    "slum", "poor", "rich", "migrant", "north indian", "south indian",
    "looks like", "appears to be from", "typical of", "these people",
    "that kind of", "low income", "wealthy",
]


@dataclass
class GuardrailResult:
    text: str
    redactions: list[str] = field(default_factory=list)
    bias_flags: list[str] = field(default_factory=list)
    provider: str = "local"

    @property
    def clean(self) -> bool:
        return not self.bias_flags


def _local_redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    redacted = text
    for label, pattern in _PATTERNS:
        def _sub(match: re.Match[str]) -> str:
            found.append(label)
            return f"[REDACTED_{label}]"

        redacted = pattern.sub(_sub, redacted)
    return redacted, sorted(set(found))


def _local_bias_scan(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in _BIAS_TERMS if term in lowered]


def _enkrypt_call(endpoint: str, payload: dict) -> dict | None:
    """Best-effort call to Enkrypt. Never let a guardrail outage take down the
    pipeline — on failure we fall back to local enforcement rather than
    forwarding unscrubbed text."""
    try:
        response = httpx.post(
            f"{settings.enkrypt_base_url.rstrip('/')}{endpoint}",
            headers={
                "apikey": settings.enkrypt_api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=8.0,
        )
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception:
        return None


def redact_pii(text: str) -> GuardrailResult:
    """Scrub PII before prompt assembly. Local redaction always runs; Enkrypt
    is applied on top when configured."""
    local_text, local_found = _local_redact(text)

    if settings.live_enkrypt:
        data = _enkrypt_call(
            "/guardrails/detect",
            {"text": local_text, "detectors": {"pii": {"enabled": True}}},
        )
        if data:
            detected = data.get("details", {}).get("pii", {})
            anonymized = data.get("anonymized_text") or data.get("text") or local_text
            labels = sorted({str(k).upper() for k in detected.keys()}) if isinstance(detected, dict) else []
            return GuardrailResult(
                text=anonymized,
                redactions=sorted(set(local_found + labels)),
                provider="enkrypt",
            )

    return GuardrailResult(text=local_text, redactions=local_found, provider="local")


def check_bias(text: str) -> GuardrailResult:
    """Screen auditor reasoning for prejudicial justification."""
    flags = _local_bias_scan(text)

    if settings.live_enkrypt:
        data = _enkrypt_call(
            "/guardrails/detect",
            {"text": text, "detectors": {"bias": {"enabled": True}}},
        )
        if data:
            bias = data.get("details", {}).get("bias", {})
            if isinstance(bias, dict) and bias.get("detected"):
                flags = sorted(set(flags + [str(bias.get("category", "bias"))]))
            return GuardrailResult(text=text, bias_flags=flags, provider="enkrypt")

    return GuardrailResult(text=text, bias_flags=flags, provider="local")


def scrub_owner_record(record: dict) -> dict:
    """Strip an account record down to what an audit decision legitimately
    needs. Customer identity is never a valid input to whether a transaction
    was unauthorised, so it is dropped before the prompt is built — not merely
    masked.

    Note what survives: tenure, prior confirmed fraud, prior *wrongful* blocks
    and a travel notice are all legitimate evidence about the account. The
    person's name is not.
    """
    safe = {
        k: v
        for k, v in record.items()
        if k
        in {
            "found",
            "account_ref",
            "segment",
            "segment_label",
            "tenure_years",
            "prior_confirmed_fraud",
            "prior_disputes_12mo",
            "prior_false_positive_blocks_12mo",
            "travel_notice_on_file",
            "issuing_branch",
            "source",
        }
    }
    safe["customer"] = "[WITHHELD_FROM_MODEL]"
    return safe


def guard_prompt(text: str) -> tuple[str, dict]:
    """Entry point for the ADK `before_model_callback`."""
    result = redact_pii(text)
    return result.text, {
        "provider": result.provider,
        "redactions": result.redactions,
        "redaction_count": len(result.redactions),
    }
