"""Deterministic pipeline used when no live model backend is configured.

This is a *simulator, not a mock*: the auditor here is a real rule engine that
implements the same verdict logic as the live path — the same trust thresholds,
the same attribution floor, the same duplicate rule — over synthesised
perception output. Given the same input it always produces the same verdict,
which is what makes it useful for a live pitch and for regression-testing the
auditor's decision boundaries.

The UI labels this mode `simulation` everywhere it appears. Nothing here claims
to be a model call.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from ..config import settings
from ..schemas import AttributionRead, DuplicateCheck, RiskSignal, Verdict, VerdictChecks

# --------------------------------------------------------------------------- #
# Scenario inference
# --------------------------------------------------------------------------- #
SCENARIOS = {
    "card_testing": {
        "label": "Card testing burst, unknown device",
        "fraud_type": "card_testing",
        "signal_conf": 0.94,
        "attribution_floor": 0.93,
        "ambiguous": False,
        "known_behaviour": False,
        "doubt": None,
        "context": 0.92,
    },
    "takeover": {
        "label": "Device change then outbound transfer",
        "fraud_type": "account_takeover",
        "signal_conf": 0.92,
        "attribution_floor": 0.90,
        "ambiguous": False,
        "known_behaviour": False,
        "doubt": None,
        "context": 0.88,
    },
    "traveller": {
        "label": "Impossible travel from batch settlement",
        "fraud_type": "impossible_travel",
        "signal_conf": 0.88,
        "attribution_floor": 0.91,
        "ambiguous": False,
        "known_behaviour": True,
        "doubt": "batch",
        "context": 0.70,
    },
    "firsttime": {
        "label": "First purchase in a new category",
        "fraud_type": "merchant_anomaly",
        "signal_conf": 0.71,
        "attribution_floor": 0.58,
        "ambiguous": True,
        "known_behaviour": False,
        "doubt": None,
        "context": 0.74,
    },
    "thin": {
        "label": "Thin history, pattern unverifiable",
        "fraud_type": "merchant_anomaly",
        "signal_conf": 0.66,
        "attribution_floor": 0.71,
        "ambiguous": False,
        "known_behaviour": False,
        "doubt": "thin",
        "context": 0.44,
    },
    "salary": {
        "label": "Salary and rent cycle read as structuring",
        "fraud_type": "structuring",
        "signal_conf": 0.79,
        "attribution_floor": 0.88,
        "ambiguous": False,
        "known_behaviour": True,
        "doubt": "known",
        "context": 0.86,
    },
    "clean": {
        "label": "No fraud pattern present",
        "fraud_type": "none",
        "signal_conf": 0.21,
        "attribution_floor": 0.90,
        "ambiguous": False,
        "known_behaviour": True,
        "doubt": "absent",
        "context": 0.88,
    },
}

_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("traveller", "travel", "batch", "falsepos", "false_positive", "geo"), "traveller"),
    (("firsttime", "first", "newcategory", "merchant", "electronics"), "firsttime"),
    (("thin", "sparse", "newaccount", "short"), "thin"),
    (("salary", "rent", "structuring", "smurf", "chit"), "salary"),
    (("takeover", "ato", "device", "beneficiary", "transfer"), "takeover"),
    (("clean", "none", "legit", "normal", "negative"), "clean"),
    (("cardtesting", "testing", "enumeration", "velocity", "burst", "fraud"), "card_testing"),
]


def infer_scenario(filename: str, override: str | None = None) -> str:
    if override and override in SCENARIOS:
        return override
    stem = re.sub(r"[^a-z0-9]", "", Path(filename).stem.lower())
    for needles, scenario in _HINTS:
        if any(re.sub(r"[^a-z0-9]", "", n) in stem for n in needles):
            return scenario
    # No hint — spread deterministically so repeated demo uploads do not all
    # land on the same verdict.
    seed = int(hashlib.sha256(filename.encode()).hexdigest()[:8], 16)
    weighted = [
        "card_testing", "card_testing", "traveller", "firsttime",
        "takeover", "salary", "thin",
    ]
    return weighted[seed % len(weighted)]


# --------------------------------------------------------------------------- #
# Perception
# --------------------------------------------------------------------------- #
_EVIDENCE_TEXT = {
    "card_testing": (
        "Three declined authorisations at the same online merchant within 90 seconds, "
        "followed immediately by an approved low-value charge. Every attempt originates "
        "from a device identifier that appears nowhere else in this account's history, "
        "and the merchant sits in a category with an elevated base fraud rate."
    ),
    "takeover": (
        "The registered device changed 40 minutes before the flagged transaction, and the "
        "flagged item is an outbound transfer to a beneficiary added the same day. No prior "
        "transfer on this account goes to that beneficiary, and the amount is well outside "
        "the account's usual transfer distribution."
    ),
    "traveller": (
        "Two card-present transactions 1,900 km apart within two hours. However, the earlier "
        "merchant settles in nightly batch, so its recorded timestamp reflects settlement "
        "rather than the moment of purchase, and the account has a travel notice on file "
        "covering this period."
    ),
    "firsttime": (
        "A consumer-electronics purchase well above this account's usual amount, in a "
        "category the customer has not used before. The device and city both match the "
        "customer's established pattern, so the only genuinely anomalous element is the "
        "category itself."
    ),
    "thin": (
        "The flagged transaction is out of pattern relative to the surrounding activity, but "
        "the account's available history is only a handful of events. There is not enough of "
        "a pattern established for 'out of pattern' to carry weight."
    ),
    "salary": (
        "Five outbound transfers over three days, each just below the reporting threshold, "
        "aggregating well above it. The amounts, the recipients and the timing match a salary "
        "credit followed by rent and a recurring savings-group contribution, all of which "
        "appear in the same shape in previous months."
    ),
    "clean": (
        "The flagged transaction sits squarely inside the account's established pattern — "
        "same merchant category, same city, same device, an amount within its normal range. "
        "No fraud pattern is present in any of the surrounding activity."
    ),
}

_INDICATOR_SETS = {
    "card_testing": ["unrecognised device", "authorisation velocity", "high-risk merchant category"],
    "takeover": ["registered device changed", "new beneficiary", "amount outside distribution"],
    "traveller": ["geographic separation", "card-present at both ends"],
    "firsttime": ["new merchant category", "amount above distribution"],
    "thin": ["out of pattern", "insufficient history"],
    "salary": ["amounts below threshold", "aggregate above threshold"],
    "clean": ["no distinguishing indicator"],
}


def synth_account_ref(seed_source: str) -> str:
    seed = int(hashlib.sha256(seed_source.encode()).hexdigest()[:16], 16)
    return f"•••• {seed % 10000:04d}"


def synth_signal(scenario: str, events: list[dict]) -> RiskSignal:
    spec = SCENARIOS[scenario]
    return RiskSignal(
        fraud_type=spec["fraud_type"],
        evidence_summary=_EVIDENCE_TEXT[scenario],
        raw_confidence=spec["signal_conf"],
        event_ref=(f"events 1-{len(events)}" if len(events) > 1 else "event 1"),
    )


def synth_attribution(
    scenario: str, events: list[dict], seed_source: str, account_ref: str = ""
) -> AttributionRead:
    spec = SCENARIOS[scenario]
    indicators = list(_INDICATOR_SETS[scenario])
    floor = spec["attribution_floor"]
    ambiguous = spec["ambiguous"]

    seed = int(hashlib.sha256(f"{seed_source}:ind".encode()).hexdigest()[:16], 16)
    confidences: list[float] = []
    # Place the weakest indicator deterministically, and give the rest a tight
    # spread above the floor so `min_confidence` is a meaningful signal.
    weak_index = seed % len(indicators)
    for idx in range(len(indicators)):
        if idx == weak_index:
            confidences.append(round(floor, 2))
        else:
            jitter = ((seed >> (idx * 3 + 3)) % 9) / 100.0
            base = 0.96 if not ambiguous else 0.90
            confidences.append(round(min(base - jitter + 0.02, 0.99), 2))

    if spec["fraud_type"] == "none":
        confidences = [0.0]
        indicators = ["no distinguishing indicator"]

    return AttributionRead(
        account_ref=account_ref or synth_account_ref(seed_source),
        indicators=indicators,
        per_indicator_confidence=confidences,
        min_confidence=round(min(confidences), 2),
        matches_known_behaviour=bool(spec["known_behaviour"]),
        ambiguous=ambiguous,
    )


# --------------------------------------------------------------------------- #
# The auditor, as a rule engine
# --------------------------------------------------------------------------- #
def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def audit(
    scenario: str,
    signal: RiskSignal,
    attribution: AttributionRead,
    duplicate: DuplicateCheck,
    rule_section: str | None,
    dispute_reason: str | None = None,
) -> Verdict:
    """Implements the auditor's verdict rules over the synthesised evidence."""
    spec = SCENARIOS[scenario]
    doubt = spec["doubt"]
    context_quality = spec["context"]

    # --- checks ---------------------------------------------------------- #
    pattern_present = signal.fraud_type != "none"
    pattern_confirmed = pattern_present and doubt not in {"batch", "absent", "known"}
    attribution_reliable = (
        attribution.min_confidence >= settings.attribution_confidence_floor
        and not attribution.matches_known_behaviour
    )
    context_ok = context_quality >= 0.60 and doubt != "thin"
    rule_applies = bool(rule_section) and pattern_present
    is_duplicate = duplicate.is_duplicate

    # --- calibrated trust score ------------------------------------------ #
    # Log-odds combination weighted towards the two independent evidence
    # sources, then hard-capped by any failed check so one failure dominates
    # rather than being averaged away.
    evidence = (
        0.55 * _logit(signal.raw_confidence)
        + 0.32 * _logit(attribution.min_confidence)
        + 0.13 * _logit(context_quality)
    )
    trust = _sigmoid(evidence)

    caps: list[float] = []
    if not pattern_confirmed:
        caps.append(0.30)
    if not attribution_reliable:
        caps.append(0.55)
    if not context_ok:
        caps.append(0.58)
    if not rule_applies:
        caps.append(0.25)
    if is_duplicate:
        caps.append(0.10)
    if dispute_reason:
        # A contested case cannot retain full confidence — the customer has
        # asserted facts the ledger cannot settle.
        caps.append(0.72)
    if caps:
        trust = min(trust, min(caps))

    trust = round(min(max(trust, 0.0), 1.0), 3)

    # --- verdict ---------------------------------------------------------- #
    if is_duplicate:
        verdict = "REJECT"
    elif not pattern_present or not pattern_confirmed or not rule_applies:
        verdict = "REJECT"
    elif not attribution_reliable:
        verdict = "ESCALATE"
    elif trust >= settings.issue_trust_threshold and context_ok:
        verdict = "ISSUE"
    else:
        # A real, confirmed pattern with any remaining doubt — thin history,
        # weak context — is ESCALATED to a human, never REJECTed. REJECT is
        # reserved for duplicates and patterns that aren't real (handled
        # above). Dismissing a genuine compromise would let it keep running.
        verdict = "ESCALATE"

    checks = VerdictChecks(
        pattern_confirmed=pattern_confirmed,
        attribution_reliable=attribution_reliable,
        duplicate=is_duplicate,
        rule_applies=rule_applies,
        context_ok=context_ok,
    )

    return Verdict(
        verdict=verdict,
        trust_score=trust,
        reasoning=_reasoning(
            verdict, scenario, signal, attribution, duplicate, doubt, trust, dispute_reason
        ),
        checks=checks,
    )


def _reasoning(
    verdict: str,
    scenario: str,
    signal: RiskSignal,
    attribution: AttributionRead,
    duplicate: DuplicateCheck,
    doubt: str | None,
    trust: float,
    dispute_reason: str | None,
) -> str:
    """Customer-facing plain English. Names the actual doubt, never hedges into
    generic language."""
    account = attribution.account_ref

    if duplicate.is_duplicate:
        return (
            f"This is the same alert we already handled {duplicate.seconds_apart:.0f} seconds "
            f"earlier on card {account}. You should not be blocked twice for one event, so no "
            "new action has been taken and this alert has been closed as a duplicate."
        )

    if doubt == "batch":
        return (
            "Our system flagged two payments as being too far apart in distance to have been "
            "made by the same person. On checking, the earlier shop submits its card payments "
            "in a nightly batch, so the time on the record is when it was processed, not when "
            "you were there. Once that is accounted for, the two payments are perfectly "
            "possible, so your card has not been blocked."
        )

    if signal.fraud_type == "none":
        return (
            "Our system flagged this payment for review, but on inspection it matches your "
            "usual pattern — the same kind of merchant, the same city and device, and an "
            "amount in your normal range. Nothing has been blocked."
        )

    if doubt == "known":
        return (
            "Our system flagged a series of transfers as unusual because each was just under a "
            "reporting threshold. Looking at your history, the same pattern of amounts and "
            "recipients appears in previous months and lines up with your salary date. That is "
            "ordinary household activity, not something we should act on, so nothing has been "
            "blocked."
        )

    if doubt == "thin":
        return (
            "Our system flagged this payment as being out of pattern for your account. However, "
            "there is only a small amount of recent activity on record, which is not enough for "
            "us to say what your pattern actually is. Rather than guess, a member of our team "
            "will look at this and nothing has been blocked automatically."
        )

    if not attribution_is_reliable(attribution):
        weakest = min(attribution.per_indicator_confidence or [0.0])
        return (
            f"The unusual activity itself is visible on your account. However, we could not "
            f"confidently establish that it was someone other than you — our weakest indicator "
            f"scored only {weakest:.0%} against the {settings.attribution_confidence_floor:.0%} "
            "we require before acting. Blocking on that basis could lock you out of your own "
            "money, so a member of our team will contact you to confirm before anything happens."
        )

    if verdict == "ISSUE":
        base = (
            f"The activity on card {account} matches a known fraud pattern across several "
            f"independent indicators, and the weakest of them still scored "
            f"{min(attribution.per_indicator_confidence or [0.0]):.0%}. None of it matches your "
            f"own history, and there is no recent duplicate alert on this account. On that basis "
            f"I am {trust:.0%} confident this was not you, so the transaction has been held."
        )
        if dispute_reason:
            base += (
                " You have contested this, and I have re-examined the original activity against "
                "your account. The evidence still supports the decision."
            )
        return base

    if dispute_reason:
        return (
            "You have contested this and raised a point I cannot settle from the transaction "
            "records alone. Because I cannot verify your account against the ledger, this has "
            "been passed to a member of our team rather than upheld automatically, and nothing "
            "further will happen until they have looked at it."
        )

    return (
        f"Our system flagged this activity and some of it is genuinely unusual, but my overall "
        f"confidence is {trust:.0%}, below the {settings.issue_trust_threshold:.0%} we require "
        "before holding anyone's money. This has been sent to a member of our team instead of "
        "being actioned automatically."
    )


def attribution_is_reliable(attribution: AttributionRead) -> bool:
    return (
        attribution.min_confidence >= settings.attribution_confidence_floor
        and not attribution.matches_known_behaviour
    )


# --------------------------------------------------------------------------- #
# Customer explanations
# --------------------------------------------------------------------------- #
_CITIZEN_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "issue_headline": "A transaction on your account has been held",
        "reject_headline": "No action taken — this alert was dismissed",
        "escalate_headline": "On hold — a person is checking this",
        "issue_means": "₹{amount} is being held. You can confirm it was you, or contest this below.",
        "reject_means": "Nothing has been held and your account is working normally.",
        "escalate_means": "Nothing has been held yet. A member of our team will decide.",
        "opt_confirm": "Confirm this was me and release ₹{amount}",
        "opt_dispute": "Contest this decision",
        "opt_evidence": "View the transactions we looked at",
        "opt_verify": "Verify this record in the audit ledger",
        "opt_nothing": "No action needed from you",
    },
    "hi": {
        "issue_headline": "आपके खाते का एक लेन-देन रोका गया है",
        "reject_headline": "कोई कार्रवाई नहीं — यह अलर्ट रद्द कर दिया गया",
        "escalate_headline": "रुका हुआ — एक अधिकारी इसकी जाँच कर रहे हैं",
        "issue_means": "₹{amount} रोके गए हैं। आप पुष्टि कर सकते हैं कि यह आप थे, या नीचे चुनौती दें।",
        "reject_means": "कुछ भी नहीं रोका गया है और आपका खाता सामान्य रूप से चल रहा है।",
        "escalate_means": "अभी कुछ नहीं रोका गया है। हमारी टीम का सदस्य निर्णय लेगा।",
        "opt_confirm": "पुष्टि करें कि यह मैं था और ₹{amount} जारी करें",
        "opt_dispute": "इस निर्णय को चुनौती दें",
        "opt_evidence": "हमने जो लेन-देन देखे वे देखें",
        "opt_verify": "ऑडिट लेजर में यह रिकॉर्ड जाँचें",
        "opt_nothing": "आपको कुछ नहीं करना है",
    },
    "kn": {
        "issue_headline": "ನಿಮ್ಮ ಖಾತೆಯ ಒಂದು ವಹಿವಾಟು ತಡೆಹಿಡಿಯಲಾಗಿದೆ",
        "reject_headline": "ಯಾವುದೇ ಕ್ರಮವಿಲ್ಲ — ಈ ಎಚ್ಚರಿಕೆ ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ",
        "escalate_headline": "ತಡೆಹಿಡಿಯಲಾಗಿದೆ — ಅಧಿಕಾರಿಯೊಬ್ಬರು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದಾರೆ",
        "issue_means": "₹{amount} ತಡೆಹಿಡಿಯಲಾಗಿದೆ. ಇದು ನೀವೇ ಎಂದು ದೃಢೀಕರಿಸಬಹುದು ಅಥವಾ ಕೆಳಗೆ ಆಕ್ಷೇಪಿಸಬಹುದು.",
        "reject_means": "ಏನನ್ನೂ ತಡೆಹಿಡಿಯಲಾಗಿಲ್ಲ ಮತ್ತು ನಿಮ್ಮ ಖಾತೆ ಸಾಮಾನ್ಯವಾಗಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ.",
        "escalate_means": "ಸದ್ಯಕ್ಕೆ ಏನನ್ನೂ ತಡೆಹಿಡಿಯಲಾಗಿಲ್ಲ. ನಮ್ಮ ತಂಡದ ಸದಸ್ಯರು ನಿರ್ಧರಿಸುತ್ತಾರೆ.",
        "opt_confirm": "ಇದು ನಾನೇ ಎಂದು ದೃಢೀಕರಿಸಿ ಮತ್ತು ₹{amount} ಬಿಡುಗಡೆ ಮಾಡಿ",
        "opt_dispute": "ಈ ನಿರ್ಧಾರಕ್ಕೆ ಆಕ್ಷೇಪಿಸಿ",
        "opt_evidence": "ನಾವು ನೋಡಿದ ವಹಿವಾಟುಗಳನ್ನು ವೀಕ್ಷಿಸಿ",
        "opt_verify": "ಆಡಿಟ್ ಲೆಡ್ಜರ್‌ನಲ್ಲಿ ಈ ದಾಖಲೆ ಪರಿಶೀಲಿಸಿ",
        "opt_nothing": "ನಿಮ್ಮಿಂದ ಯಾವುದೇ ಕ್ರಮ ಅಗತ್ಯವಿಲ್ಲ",
    },
    "ta": {
        "issue_headline": "உங்கள் கணக்கின் ஒரு பரிவர்த்தனை நிறுத்தி வைக்கப்பட்டுள்ளது",
        "reject_headline": "நடவடிக்கை இல்லை — இந்த எச்சரிக்கை நிராகரிக்கப்பட்டது",
        "escalate_headline": "நிறுத்தி வைக்கப்பட்டுள்ளது — ஒரு அதிகாரி பரிசீலிக்கிறார்",
        "issue_means": "₹{amount} நிறுத்தி வைக்கப்பட்டுள்ளது. இது நீங்கள்தான் என உறுதிப்படுத்தலாம் அல்லது கீழே மறுக்கலாம்.",
        "reject_means": "எதுவும் நிறுத்தப்படவில்லை, உங்கள் கணக்கு இயல்பாக இயங்குகிறது.",
        "escalate_means": "இப்போது எதுவும் நிறுத்தப்படவில்லை. எங்கள் குழு உறுப்பினர் முடிவு செய்வார்.",
        "opt_confirm": "இது நான்தான் என உறுதிப்படுத்தி ₹{amount} விடுவிக்கவும்",
        "opt_dispute": "இந்த முடிவை மறுக்கவும்",
        "opt_evidence": "நாங்கள் பார்த்த பரிவர்த்தனைகளைப் பாருங்கள்",
        "opt_verify": "தணிக்கை லெட்ஜரில் இந்தப் பதிவைச் சரிபார்க்கவும்",
        "opt_nothing": "உங்களிடமிருந்து எந்த நடவடிக்கையும் தேவையில்லை",
    },
}

_REASONING_TRANSLATED: dict[str, dict[str, str]] = {
    "hi": {
        "ISSUE": (
            "कार्ड {account} पर हुई गतिविधि कई स्वतंत्र संकेतों के आधार पर एक ज्ञात धोखाधड़ी "
            "पैटर्न से मेल खाती है, और इनमें से कोई भी आपके अपने पिछले लेन-देन से मेल नहीं खाता। "
            "इसी आधार पर यह लेन-देन रोका गया है।"
        ),
        "REJECT": (
            "जाँच के बाद पाया गया कि उपलब्ध रिकॉर्ड से इस गतिविधि को संदिग्ध नहीं माना जा सकता — "
            "यह आपके सामान्य पैटर्न से मेल खाती है। इसलिए कुछ भी नहीं रोका गया है और यह अलर्ट बंद कर दिया गया है।"
        ),
        "ESCALATE": (
            "गतिविधि असामान्य तो दिखती है, लेकिन सबूत पूरी तरह भरोसेमंद नहीं है — इसलिए स्वचालित रूप से "
            "कुछ नहीं रोका गया। हमारी टीम का सदस्य इसकी जाँच करेगा। तब तक आपका खाता सामान्य रूप से चलेगा।"
        ),
    },
    "kn": {
        "ISSUE": (
            "ಕಾರ್ಡ್ {account} ನಲ್ಲಿನ ಚಟುವಟಿಕೆ ಹಲವು ಸ್ವತಂತ್ರ ಸೂಚಕಗಳ ಆಧಾರದ ಮೇಲೆ ತಿಳಿದಿರುವ ವಂಚನೆ "
            "ಮಾದರಿಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತದೆ, ಮತ್ತು ಅವುಗಳಲ್ಲಿ ಯಾವುದೂ ನಿಮ್ಮ ಹಿಂದಿನ ವಹಿವಾಟಿಗೆ ಹೊಂದಿಕೆಯಾಗುವುದಿಲ್ಲ. "
            "ಈ ಆಧಾರದ ಮೇಲೆ ಈ ವಹಿವಾಟು ತಡೆಹಿಡಿಯಲಾಗಿದೆ."
        ),
        "REJECT": (
            "ಪರಿಶೀಲನೆಯ ನಂತರ, ಲಭ್ಯವಿರುವ ದಾಖಲೆಗಳಿಂದ ಈ ಚಟುವಟಿಕೆಯನ್ನು ಸಂಶಯಾಸ್ಪದವೆಂದು ಪರಿಗಣಿಸಲಾಗದು — "
            "ಇದು ನಿಮ್ಮ ಸಾಮಾನ್ಯ ಮಾದರಿಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತದೆ. ಆದ್ದರಿಂದ ಏನನ್ನೂ ತಡೆಹಿಡಿಯಲಾಗಿಲ್ಲ."
        ),
        "ESCALATE": (
            "ಚಟುವಟಿಕೆ ಅಸಾಮಾನ್ಯವಾಗಿ ಕಾಣಿಸುತ್ತದೆ, ಆದರೆ ಸಾಕ್ಷ್ಯ ಸಂಪೂರ್ಣ ವಿಶ್ವಾಸಾರ್ಹವಲ್ಲ — ಆದ್ದರಿಂದ "
            "ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಏನನ್ನೂ ತಡೆಹಿಡಿಯಲಾಗಿಲ್ಲ. ನಮ್ಮ ತಂಡದ ಸದಸ್ಯರು ಪರಿಶೀಲಿಸುತ್ತಾರೆ."
        ),
    },
    "ta": {
        "ISSUE": (
            "அட்டை {account} இல் நடந்த செயல்பாடு பல தனித்தனி குறியீடுகளின் அடிப்படையில் அறியப்பட்ட "
            "மோசடி முறையுடன் பொருந்துகிறது, அவற்றில் எதுவும் உங்கள் முந்தைய பரிவர்த்தனைகளுடன் "
            "பொருந்தவில்லை. இதன் அடிப்படையில் இந்தப் பரிவர்த்தனை நிறுத்தப்பட்டுள்ளது."
        ),
        "REJECT": (
            "பரிசீலனைக்குப் பிறகு, கிடைத்த பதிவுகளிலிருந்து இந்தச் செயல்பாட்டைச் சந்தேகத்திற்குரியதாகக் "
            "கருத முடியவில்லை — இது உங்கள் வழக்கமான முறையுடன் பொருந்துகிறது. எனவே எதுவும் நிறுத்தப்படவில்லை."
        ),
        "ESCALATE": (
            "செயல்பாடு அசாதாரணமாகத் தெரிகிறது, ஆனால் ஆதாரம் முழுமையாக நம்பகமானதாக இல்லை — எனவே "
            "தானாக எதுவும் நிறுத்தப்படவில்லை. எங்கள் குழு உறுப்பினர் பரிசீலிப்பார்."
        ),
    },
}


def citizen_view(
    verdict: str,
    language: str,
    amount_held: float,
    account_ref: str,
    reasoning_en: str,
) -> dict:
    """Template-based customer explanation for simulation mode."""
    strings = _CITIZEN_STRINGS.get(language, _CITIZEN_STRINGS["en"])
    key = {"ISSUE": "issue", "REJECT": "reject", "ESCALATE": "escalate"}[verdict]

    amount_text = f"{amount_held:,.0f}"
    headline = strings[f"{key}_headline"]
    what_means = strings[f"{key}_means"].format(amount=amount_text)

    if language == "en":
        explanation = reasoning_en
    else:
        explanation = _REASONING_TRANSLATED[language][verdict].format(account=account_ref)

    if verdict == "ISSUE":
        options = [
            strings["opt_confirm"].format(amount=amount_text),
            strings["opt_dispute"],
            strings["opt_evidence"],
            strings["opt_verify"],
        ]
    elif verdict == "ESCALATE":
        options = [strings["opt_evidence"], strings["opt_dispute"], strings["opt_verify"]]
    else:
        options = [strings["opt_nothing"], strings["opt_evidence"], strings["opt_verify"]]

    return {
        "headline": headline,
        "explanation": explanation,
        "what_this_means": what_means,
        "your_options": options,
    }
