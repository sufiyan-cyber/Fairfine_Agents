"""Mock customer + merchant reference data.

Deliberately synthetic. There is no real core-banking integration and no real
customer PII anywhere in this system — records are generated deterministically
from the masked account reference so the demo is reproducible. Identity is
returned already masked at the source; the raw name never leaves this module.

The customer *segment* returned here is what the bias dashboard slices on. That
is the point: a fraud engine that blocks students and pensioners at three times
the rate it blocks salaried professionals is discriminating, and nobody notices
unless someone measures it.
"""

from __future__ import annotations

import hashlib

_FIRST_NAMES = [
    "Aarav", "Divya", "Rohan", "Meera", "Imran", "Kavya",
    "Sanjay", "Lakshmi", "Farhan", "Ananya", "Vikram", "Nisha",
]
_LAST_NAMES = [
    "Sharma", "Reddy", "Iyer", "Khan", "Patel", "Nair",
    "Gowda", "Das", "Menon", "Kulkarni", "Rao", "Bose",
]

# Customer segments, in the order the bias dashboard reports them. These are
# the populations most often harmed by a wrongful block: a student or a
# pensioner has no buffer when their card stops working.
SEGMENTS = ["salaried", "student", "self_employed", "pensioner", "gig_worker"]

_SEGMENT_LABEL = {
    "salaried": "Salaried professional",
    "student": "Student account",
    "self_employed": "Self-employed / small business",
    "pensioner": "Pensioner",
    "gig_worker": "Gig / daily-wage worker",
}

_ISSUING_BRANCH = {
    "KA01": "Bengaluru — Residency Road",
    "KA03": "Bengaluru — Indiranagar",
    "KA05": "Bengaluru — HSR Layout",
    "KA51": "Bengaluru — Yelahanka",
    "TN01": "Chennai — Anna Salai",
    "TN09": "Chennai — T Nagar",
    "MH12": "Pune — Shivajinagar",
    "DL08": "Delhi — Rohini",
    "HR26": "Gurugram — Sector 44",
}

# Merchant reputation. A merchant's own fraud history is independent evidence:
# a first-time merchant category at a merchant with a clean multi-year record
# is a very different proposition from the same category at a two-week-old one.
_MERCHANT_PROFILES = {
    "grocery": ("Established grocery chain", 0.02, 6),
    "fuel": ("Fuel retailer", 0.03, 9),
    "electronics": ("Consumer electronics", 0.11, 4),
    "gift_card": ("Gift card / stored value", 0.38, 1),
    "crypto": ("Crypto on-ramp", 0.41, 1),
    "travel": ("Travel booking", 0.09, 5),
    "pharmacy": ("Pharmacy", 0.02, 8),
    "utility": ("Utility / bill payment", 0.01, 10),
    "restaurant": ("Restaurant", 0.04, 5),
    "transfer": ("Peer-to-peer transfer", 0.16, 3),
}


def _seed(value: str) -> int:
    return int(hashlib.sha256((value or "").upper().encode()).hexdigest()[:12], 16)


def infer_segment(account_ref: str, fraud_type: str = "") -> str:
    """Customer segment for an account reference.

    Deterministic from the reference so the same card always belongs to the
    same customer across a demo run.
    """
    return SEGMENTS[_seed(account_ref) % len(SEGMENTS)]


def segment_label(segment: str) -> str:
    return _SEGMENT_LABEL.get(segment, segment.replace("_", " ").title())


def mask_name(name: str) -> str:
    """`Divya Reddy` -> `D**** R****`. Never emit the full name."""
    parts = [p for p in name.split() if p]
    return " ".join(f"{p[0]}{'*' * max(len(p) - 1, 1)}" for p in parts)


def mask_account(account_ref: str) -> str:
    """Normalise any account/card reference to its last four digits."""
    digits = "".join(ch for ch in (account_ref or "") if ch.isdigit())
    if len(digits) >= 4:
        return f"•••• {digits[-4:]}"
    return account_ref or "UNKNOWN"


def merchant_profile(category: str, merchant_name: str = "") -> dict:
    """Reputation record for a merchant category.

    `historical_fraud_rate` is the share of this category's transactions later
    confirmed fraudulent — the base rate the auditor needs in order to reason
    about how much a category anomaly is actually worth.
    """
    label, fraud_rate, years = _MERCHANT_PROFILES.get(
        category, ("Uncategorised merchant", 0.07, 2)
    )
    seed = _seed(merchant_name or category)
    return {
        "category": category,
        "category_label": label,
        "historical_fraud_rate": fraud_rate,
        "years_active": years,
        "chargeback_ratio": round(fraud_rate * 0.6, 3),
        "acquirer_risk_band": (
            "high" if fraud_rate > 0.25 else "elevated" if fraud_rate > 0.08 else "standard"
        ),
        "merchant_id": f"MID{seed % 1_000_000:06d}",
        "source": "MOCK_MERCHANT_REGISTRY",
    }


def account_lookup(account_ref: str, fraud_type: str = "") -> dict:
    """Mock customer reference lookup for a masked account reference.

    Returns customer details already masked. This is the function exposed to
    the CaseFileAgent as a tool.

    Args:
        account_ref: Masked card or account reference, e.g. "•••• 4821".
        fraud_type: Optional hint used to contextualise the record.

    Returns:
        A dict of account details with the customer name masked.
    """
    ref = (account_ref or "").strip()
    if not ref or ref.upper() in {"UNKNOWN", "UNRESOLVED"}:
        return {
            "found": False,
            "account_ref": ref,
            "note": "Account reference unresolved — no customer lookup performed.",
            "source": "MOCK_CORE_BANKING",
        }

    seed = _seed(ref)
    first = _FIRST_NAMES[seed % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(seed >> 8) % len(_LAST_NAMES)]
    segment = infer_segment(ref, fraud_type)
    branch_code = list(_ISSUING_BRANCH)[(seed >> 20) % len(_ISSUING_BRANCH)]

    # Tenure and history matter to the auditor: a fifteen-year customer with no
    # prior disputes is weak ground for an automated block.
    tenure_years = 1 + (seed % 18)

    return {
        "found": True,
        "account_ref": mask_account(ref) if any(c.isdigit() for c in ref) else ref,
        "customer_masked": mask_name(f"{first} {last}"),
        "customer_initials": f"{first[0]}.{last[0]}.",
        "segment": segment,
        "segment_label": segment_label(segment),
        "tenure_years": tenure_years,
        "issuing_branch": _ISSUING_BRANCH[branch_code],
        "branch_code": branch_code,
        "prior_confirmed_fraud": (seed >> 4) % 7 == 0,
        "prior_disputes_12mo": (seed >> 6) % 3,
        "prior_false_positive_blocks_12mo": (seed >> 9) % 3,
        "travel_notice_on_file": (seed >> 11) % 4 == 0,
        "source": "MOCK_CORE_BANKING",
        "disclaimer": "Synthetic record. No real core-banking integration.",
    }
