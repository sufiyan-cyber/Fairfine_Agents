"""Fraud-decisioning rulebook — retrieval corpus.

Paraphrased into plain language for the demo RAG index. These are the rules a
fraud-operations team actually decides against: RBI's customer-liability
circular, card-network chargeback grounds, and the internal action policy that
says which signals justify blocking a customer's money.

Not legal advice, and deliberately not a verbatim reproduction. The point of
citing a rule at all is that an automated block must be *justifiable* under a
named policy, and the customer must be able to see which one was applied.
"""

from __future__ import annotations

FRAUD_RULES: list[dict] = [
    {
        "section": "RBI DBR.No.Leg.BC.78/09.07.005/2017-18 ¶6",
        "title": "Zero liability of a customer for third-party breach",
        "text": (
            "Where an unauthorised electronic transaction occurs due to a third-party breach "
            "and the deficiency lies neither with the bank nor with the customer, the customer "
            "bears zero liability provided they notify the bank within three working days. "
            "The burden of proving customer liability rests with the bank, not the customer."
        ),
        "penalty": "Full reversal to the customer; the bank absorbs the loss",
        "fraud_types": ["stolen_card_use", "account_takeover", "card_testing"],
        "keywords": [
            "unauthorised", "third party", "zero liability", "reversal",
            "burden of proof", "notify",
        ],
    },
    {
        "section": "RBI DBR.No.Leg.BC.78 ¶9",
        "title": "Burden of proof and the cost of a wrongful hold",
        "text": (
            "A bank that blocks or reverses a transaction must be able to evidence the basis "
            "for that action. Where a hold is placed on a customer's funds and the transaction "
            "is subsequently found to be genuine, the bank must restore access without delay "
            "and may be liable for consequential loss. A block is an action against the "
            "customer and requires the same evidentiary standard as a debit."
        ),
        "penalty": "Restoration plus compensation for consequential loss",
        "fraud_types": ["merchant_anomaly", "impossible_travel", "none"],
        "keywords": [
            "wrongful", "hold", "block", "evidence", "restore", "consequential loss",
            "genuine transaction",
        ],
    },
    {
        "section": "Card Network Rules §11.3 — Fraud / Card-Absent",
        "title": "Card-absent fraud chargeback ground",
        "text": (
            "A transaction may be charged back as fraudulent where the cardholder states they "
            "neither authorised nor participated in it and the merchant cannot evidence "
            "cardholder authentication. Repeated low-value authorisations against sequential "
            "card numbers are treated as enumeration and are chargeable to the acquirer."
        ),
        "penalty": "Chargeback to acquirer; issuer recovers the disputed amount",
        "fraud_types": ["card_testing", "stolen_card_use"],
        "keywords": [
            "card absent", "chargeback", "enumeration", "authentication", "cnp",
            "sequential", "low value",
        ],
    },
    {
        "section": "Card Network Rules §11.7 — Velocity and enumeration",
        "title": "Authorisation velocity thresholds",
        "text": (
            "A sustained burst of authorisation attempts on one card within a short window, "
            "particularly declining attempts followed by a successful low-value approval, is "
            "the signature of automated card testing. Velocity alone is not proof of fraud: a "
            "genuine cardholder retrying a failing payment produces a similar burst, "
            "distinguishable by whether the attempts share a merchant and device."
        ),
        "penalty": "Card block pending cardholder contact",
        "fraud_types": ["card_testing"],
        "keywords": [
            "velocity", "burst", "retry", "declines", "automated", "testing", "same merchant",
        ],
    },
    {
        "section": "Internal Action Policy §4.1 — Impossible travel",
        "title": "Geographic velocity as a signal, not a verdict",
        "text": (
            "Two card-present transactions whose separation in distance cannot be covered in "
            "the elapsed time indicate that one was not performed by the cardholder. This "
            "signal is void where either transaction is card-not-present, where the merchant "
            "settles in batch and the timestamp reflects settlement rather than authorisation, "
            "or where the cardholder is a known traveller. Batch settlement is the single most "
            "common cause of false impossible-travel alerts."
        ),
        "penalty": "Step-up authentication; block only on corroboration",
        "fraud_types": ["impossible_travel"],
        "keywords": [
            "impossible travel", "geo velocity", "distance", "batch", "settlement",
            "card present", "traveller",
        ],
    },
    {
        "section": "Internal Action Policy §4.4 — Account takeover indicators",
        "title": "Credential change preceding a debit",
        "text": (
            "A change to a registered device, phone number, or e-mail followed within a short "
            "window by an outbound transfer to a newly added beneficiary is the canonical "
            "account-takeover sequence. Where the credential change was itself authenticated "
            "from the customer's long-standing device, the sequence is far more likely to be "
            "the genuine customer replacing a handset."
        ),
        "penalty": "Freeze outbound transfers pending out-of-band verification",
        "fraud_types": ["account_takeover"],
        "keywords": [
            "takeover", "device change", "beneficiary", "credential", "transfer",
            "out of band", "handset",
        ],
    },
    {
        "section": "Internal Action Policy §4.6 — Merchant-profile anomaly",
        "title": "Out-of-pattern merchant category",
        "text": (
            "A transaction at a merchant category the customer has never used, at an amount "
            "well outside their distribution, raises risk but does not establish fraud. "
            "Customers legitimately make first-time purchases. This signal must be "
            "corroborated by an independent indicator — device, geography, or velocity — "
            "before any action is taken against the account."
        ),
        "penalty": "Monitor; corroboration required before action",
        "fraud_types": ["merchant_anomaly"],
        "keywords": [
            "merchant category", "mcc", "first time", "out of pattern", "amount",
            "corroboration", "distribution",
        ],
    },
    {
        "section": "Internal Action Policy §7.2 — Duplicate alert suppression",
        "title": "One event, one action",
        "text": (
            "Where the same underlying transaction is flagged more than once — by a retry, a "
            "reversal-and-represent, or two rules firing on one authorisation — only one "
            "action may be taken. Blocking a customer twice for a single event, or counting "
            "it twice in loss figures, is a reporting and customer-harm defect."
        ),
        "penalty": "Suppress the duplicate; no second action",
        "fraud_types": ["card_testing", "stolen_card_use", "account_takeover", "none"],
        "keywords": ["duplicate", "represent", "retry", "suppression", "double", "one event"],
    },
    {
        "section": "Internal Action Policy §9.1 — Structuring / smurfing",
        "title": "Amounts placed just under a reporting threshold",
        "text": (
            "A sequence of transfers individually below a regulatory reporting threshold but "
            "aggregating well above it may indicate deliberate structuring. Salary cycles, "
            "rent splitting, and informal savings groups produce statistically similar "
            "patterns and are not offences; intent cannot be inferred from amounts alone."
        ),
        "penalty": "File an internal report; do not block on this signal alone",
        "fraud_types": ["structuring"],
        "keywords": [
            "structuring", "smurfing", "threshold", "aggregate", "reporting", "salary",
            "rent", "chit",
        ],
    },
]

_BY_SECTION = {rule["section"]: rule for rule in FRAUD_RULES}

# The rule a fraud-ops analyst would cite first for each pattern.
PRIMARY_SECTION = {
    "card_testing": "Card Network Rules §11.7 — Velocity and enumeration",
    "account_takeover": "Internal Action Policy §4.4 — Account takeover indicators",
    "stolen_card_use": "Card Network Rules §11.3 — Fraud / Card-Absent",
    "impossible_travel": "Internal Action Policy §4.1 — Impossible travel",
    "merchant_anomaly": "Internal Action Policy §4.6 — Merchant-profile anomaly",
    "structuring": "Internal Action Policy §9.1 — Structuring / smurfing",
    "none": "RBI DBR.No.Leg.BC.78 ¶9",
}

FRAUD_LABEL = {
    "card_testing": "Card testing",
    "account_takeover": "Account takeover",
    "stolen_card_use": "Stolen card use",
    "impossible_travel": "Impossible travel",
    "merchant_anomaly": "Merchant anomaly",
    "structuring": "Structuring",
    "none": "No fraud pattern",
}


def get_section(section: str) -> dict | None:
    """Exact-match lookup by section identifier."""
    return _BY_SECTION.get((section or "").strip())


def rule_for_fraud_type(fraud_type: str) -> dict | None:
    """The primary rule that governs action on a given fraud pattern.

    Ordering in `FRAUD_RULES` is significant: the first rule listing a fraud
    type is the one a fraud-ops analyst would cite for it.
    """
    for rule in FRAUD_RULES:
        if fraud_type in rule["fraud_types"]:
            return rule
    return None


def section_for_fraud_type(fraud_type: str) -> dict | None:
    return get_section(PRIMARY_SECTION.get(fraud_type, "RBI DBR.No.Leg.BC.78 ¶9"))


def label_for(fraud_type: str) -> str:
    return FRAUD_LABEL.get(fraud_type, (fraud_type or "").replace("_", " ").title())


def corpus_documents() -> list[dict]:
    """Flatten to indexable documents for the vector store."""
    return [
        {
            "id": entry["section"],
            "text": (
                f"{entry['section']} — {entry['title']}. {entry['text']} "
                f"Action: {entry['penalty']}"
            ),
            "metadata": entry,
        }
        for entry in FRAUD_RULES
    ]


def search(query: str, limit: int = 3) -> list[dict]:
    """Keyword-overlap retrieval over the rulebook.

    Deliberately simple and dependency-free. The semantic index in
    `tools.memory` handles the fuzzy case; this is the deterministic fallback
    so a rule citation never depends on a network call.
    """
    terms = {t for t in (query or "").lower().replace(",", " ").split() if len(t) > 2}
    if not terms:
        return []

    scored: list[tuple[float, dict]] = []
    for rule in FRAUD_RULES:
        haystack = " ".join(
            [rule["title"], rule["text"], " ".join(rule["keywords"])]
        ).lower()
        hits = sum(1 for term in terms if term in haystack)
        if hits:
            scored.append((hits / len(terms), rule))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {**rule, "relevance": round(score, 3)} for score, rule in scored[:limit]
    ]
