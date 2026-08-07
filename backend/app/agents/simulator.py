"""Deterministic pipeline used when no `GEMINI_API_KEY` is configured.

This is a *simulator, not a mock*: the auditor here is a real rule engine that
implements the PRD's verdict logic — the same trust thresholds, the same plate
floor, the same duplicate rule — over synthesised perception output. Given the
same input it always produces the same verdict, which is what makes it useful
for a live pitch and for regression-testing the auditor's decision boundaries.

The UI labels this mode `simulation` everywhere it appears. Nothing here claims
to be a model call.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from ..config import settings
from ..schemas import Detection, DuplicateCheck, PlateRead, Verdict, VerdictChecks

# --------------------------------------------------------------------------- #
# Scenario inference
# --------------------------------------------------------------------------- #
SCENARIOS = {
    "clean": {
        "label": "Clean violation, sharp plate",
        "violation": "no_helmet",
        "detector_conf": 0.94,
        "plate_floor": 0.93,
        "occluded": False,
        "visual_doubt": None,
        "environment": 0.92,
    },
    "occluded": {
        "label": "Violation clear, plate partially blocked",
        "violation": "no_helmet",
        "detector_conf": 0.91,
        "plate_floor": 0.58,
        "occluded": True,
        "visual_doubt": None,
        "environment": 0.74,
    },
    "parallax": {
        "label": "Camera-angle false positive at the stop line",
        "violation": "red_light_jump",
        "detector_conf": 0.88,
        "plate_floor": 0.91,
        "occluded": False,
        "visual_doubt": "parallax",
        "environment": 0.70,
    },
    "night": {
        "label": "Low light, heavy glare",
        "violation": "no_seatbelt",
        "detector_conf": 0.66,
        "plate_floor": 0.71,
        "occluded": False,
        "visual_doubt": "lighting",
        "environment": 0.44,
    },
    "triple": {
        "label": "Three riders, clear daylight",
        "violation": "triple_riding",
        "detector_conf": 0.96,
        "plate_floor": 0.91,
        "occluded": False,
        "visual_doubt": None,
        "environment": 0.90,
    },
    "phone": {
        "label": "Handheld phone use, moderate blur",
        "violation": "phone_use",
        "detector_conf": 0.79,
        "plate_floor": 0.88,
        "occluded": False,
        "visual_doubt": "blur",
        "environment": 0.66,
    },
    "empty": {
        "label": "No violation present",
        "violation": "none",
        "detector_conf": 0.21,
        "plate_floor": 0.90,
        "occluded": False,
        "visual_doubt": "absent",
        "environment": 0.88,
    },
}

_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("parallax", "falsepos", "false_positive", "angle", "stopline"), "parallax"),
    (("occlud", "blocked", "partial", "blur_plate", "obscur"), "occluded"),
    (("night", "glare", "lowlight", "dark", "rain"), "night"),
    (("triple", "three", "overload"), "triple"),
    (("phone", "mobile", "handheld"), "phone"),
    (("empty", "clear", "novio", "no_violation", "negative"), "empty"),
    (("clean", "helmet", "issue", "sharp", "valid"), "clean"),
]


def infer_scenario(filename: str, override: str | None = None) -> str:
    if override and override in SCENARIOS:
        return override
    stem = re.sub(r"[^a-z0-9]", "", Path(filename).stem.lower())
    for needles, scenario in _HINTS:
        if any(re.sub(r"[^a-z0-9]", "", n) in stem for n in needles):
            return scenario
    # No hint — spread deterministically across scenarios so repeated demo
    # uploads do not all land on the same verdict.
    seed = int(hashlib.sha256(filename.encode()).hexdigest()[:8], 16)
    weighted = ["clean", "clean", "occluded", "parallax", "triple", "phone", "night"]
    return weighted[seed % len(weighted)]


# --------------------------------------------------------------------------- #
# Perception
# --------------------------------------------------------------------------- #
_STATE_CODES = ["KA", "TN", "MH", "DL", "HR", "KL", "AP", "TS"]
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def synth_plate(seed_source: str) -> str:
    seed = int(hashlib.sha256(seed_source.encode()).hexdigest()[:16], 16)
    state = _STATE_CODES[seed % len(_STATE_CODES)]
    rto = f"{(seed >> 4) % 60:02d}"
    letters = _LETTERS[(seed >> 12) % 24] + _LETTERS[(seed >> 18) % 24]
    digits = f"{(seed >> 24) % 10000:04d}"
    return f"{state}{rto}{letters}{digits}"


_REGION_TEXT = {
    "clean": (
        "Rider on the two-wheeler in the centre-left of frame, travelling towards "
        "the junction. Head is bare — no helmet worn, none carried on the vehicle "
        "or on the arm. Subject is sharp across all sampled frames."
    ),
    "occluded": (
        "Rider on the two-wheeler at centre frame, head bare, no helmet visible. "
        "The violation itself is clear, but a vehicle in the adjacent lane crosses "
        "in front of the rear plate for most of the event window."
    ),
    "parallax": (
        "Car in the second lane from the left appears forward of the painted stop "
        "line while the signal shows red. The camera views the stop line at a "
        "shallow oblique angle, so the vehicle's apparent position ahead of the "
        "line is not reliable from this viewpoint."
    ),
    "night": (
        "Occupant of the light-coloured car, driver's side. Seat belt strap is not "
        "visible across the chest, but oncoming headlight glare washes out the "
        "windscreen for much of the window and the cabin is largely in shadow."
    ),
    "triple": (
        "Two-wheeler in the centre of frame carrying three occupants — rider plus "
        "two pillion. All three visible and separable in every sampled frame; "
        "daylight, no obstruction."
    ),
    "phone": (
        "Driver of the dark hatchback, right of frame, holding a phone to the right "
        "ear with the right hand. Moderate motion blur across the sequence; the "
        "hand position is consistent in three of five frames."
    ),
    "empty": (
        "Traffic proceeding normally through the junction on a green signal. No "
        "violation identified in any sampled frame."
    ),
}


def synth_detection(scenario: str, frames: list[dict]) -> Detection:
    spec = SCENARIOS[scenario]
    return Detection(
        violation_type=spec["violation"],
        region_description=_REGION_TEXT[scenario],
        raw_confidence=spec["detector_conf"],
        frame_ref=(
            f"frames 1-{len(frames)}" if len(frames) > 1 else "frame 1"
        ),
    )


def synth_plate_read(scenario: str, frames: list[dict], seed_source: str) -> PlateRead:
    spec = SCENARIOS[scenario]
    plate = synth_plate(seed_source)
    floor = spec["plate_floor"]
    occluded = spec["occluded"]

    seed = int(hashlib.sha256(f"{seed_source}:chars".encode()).hexdigest()[:16], 16)
    confidences: list[float] = []
    # Place the weakest character deterministically, and give the rest a tight
    # spread above the floor so `min_confidence` is a meaningful signal.
    weak_index = seed % len(plate)
    for idx in range(len(plate)):
        if idx == weak_index:
            confidences.append(round(floor, 2))
        else:
            jitter = ((seed >> (idx * 3 + 3)) % 9) / 100.0
            base = 0.96 if not occluded else 0.90
            confidences.append(round(min(base - jitter + 0.02, 0.99), 2))

    if occluded:
        # An occlusion rarely affects exactly one character.
        neighbour = (weak_index + 1) % len(plate)
        confidences[neighbour] = round(min(confidences[neighbour], floor + 0.08), 2)

    return PlateRead(
        plate=plate,
        per_char_confidence=confidences,
        min_confidence=round(min(confidences), 2),
        occluded=occluded,
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
    detection: Detection,
    plate: PlateRead,
    duplicate: DuplicateCheck,
    rule_section: str | None,
    dispute_reason: str | None = None,
) -> Verdict:
    """Implements the PRD's verdict rules over the synthesised evidence."""
    spec = SCENARIOS[scenario]
    doubt = spec["visual_doubt"]
    environment_quality = spec["environment"]

    # --- checks ---------------------------------------------------------- #
    violation_present = detection.violation_type != "none"
    visually_confirmed = violation_present and doubt not in {"parallax", "absent"}
    plate_reliable = plate.min_confidence >= settings.plate_confidence_floor
    environment_ok = environment_quality >= 0.60 and doubt != "lighting"
    rule_applies = bool(rule_section) and violation_present
    is_duplicate = duplicate.is_duplicate

    # --- calibrated trust score ------------------------------------------ #
    # Log-odds combination weighted towards the two independent evidence
    # sources, then hard-capped by any failed check so one failure dominates
    # rather than being averaged away.
    evidence = (
        0.55 * _logit(detection.raw_confidence)
        + 0.32 * _logit(plate.min_confidence)
        + 0.13 * _logit(environment_quality)
    )
    trust = _sigmoid(evidence)

    caps: list[float] = []
    if not visually_confirmed:
        caps.append(0.30)
    if not plate_reliable:
        caps.append(0.55)
    if not environment_ok:
        caps.append(0.58)
    if not rule_applies:
        caps.append(0.25)
    if is_duplicate:
        caps.append(0.10)
    if dispute_reason:
        # A contested case cannot retain full confidence — the citizen has
        # asserted facts the frames cannot settle.
        caps.append(0.72)
    if caps:
        trust = min(trust, min(caps))

    trust = round(min(max(trust, 0.0), 1.0), 3)

    # --- verdict ---------------------------------------------------------- #
    if is_duplicate:
        verdict = "REJECT"
    elif not violation_present or not visually_confirmed or not rule_applies:
        verdict = "REJECT"
    elif not plate_reliable:
        verdict = "ESCALATE"
    elif trust >= settings.issue_trust_threshold and environment_ok:
        verdict = "ISSUE"
    else:
        # A real, visually-confirmed violation with any remaining doubt — low
        # trust, poor lighting, etc. — is ESCALATED to a human, never REJECTed.
        # REJECT is reserved for duplicates and violations that aren't real
        # (handled above). Dismissing a genuine violation would let a real
        # offender off; a human should resolve the doubt instead.
        verdict = "ESCALATE"

    checks = VerdictChecks(
        visually_confirmed=visually_confirmed,
        plate_reliable=plate_reliable,
        duplicate=is_duplicate,
        rule_applies=rule_applies,
        environment_ok=environment_ok,
    )

    return Verdict(
        verdict=verdict,
        trust_score=trust,
        reasoning=_reasoning(
            verdict, scenario, detection, plate, duplicate, doubt, trust, dispute_reason
        ),
        checks=checks,
    )


def _reasoning(
    verdict: str,
    scenario: str,
    detection: Detection,
    plate: PlateRead,
    duplicate: DuplicateCheck,
    doubt: str | None,
    trust: float,
    dispute_reason: str | None,
) -> str:
    """Citizen-facing plain English. Names the actual doubt, never hedges into
    generic language."""
    plate_txt = plate.plate

    if duplicate.is_duplicate:
        return (
            f"This appears to be the same event we already recorded {duplicate.seconds_apart:.0f} "
            f"seconds earlier at the same location for {plate_txt}. You should not be charged "
            "twice for one incident, so no new fine has been issued and this record has been "
            "closed as a duplicate."
        )

    if doubt == "parallax":
        return (
            "The camera flagged this vehicle for crossing on red, but the camera views the stop "
            "line at a steep angle rather than straight on. From that viewpoint a vehicle stopped "
            "just behind the line can look like it has crossed it. Looking at the frames directly, "
            "I cannot confirm the vehicle was actually past the line while the signal was red, so "
            "no fine has been issued."
        )

    if detection.violation_type == "none":
        return (
            "The camera flagged this clip for review, but on inspection no traffic violation is "
            "visible in any of the frames. No fine has been issued."
        )

    if doubt == "lighting":
        return (
            "The camera flagged a possible seat-belt violation, but oncoming headlight glare "
            "washes out the windscreen for most of this clip and the cabin is in shadow. I cannot "
            "reliably tell whether a belt was worn. Rather than guess, this has been sent to a "
            "human reviewer and no fine has been charged automatically."
        )

    if not plate.min_confidence >= settings.plate_confidence_floor:
        weakest = min(plate.per_char_confidence) if plate.per_char_confidence else 0.0
        return (
            f"The violation itself is clearly visible in the footage. However, part of the number "
            f"plate is blocked in these frames — the least readable character scored only "
            f"{weakest:.0%} confidence, against the {settings.plate_confidence_floor:.0%} we "
            f"require. Reading it as {plate_txt} could attribute this to the wrong vehicle, so no "
            "fine has been issued and a human reviewer will confirm the plate first."
        )

    if verdict == "ISSUE":
        base = (
            f"The violation is clearly visible across the sampled frames and the number plate "
            f"{plate_txt} reads cleanly, with the least certain character still at "
            f"{min(plate.per_char_confidence):.0%} confidence. Lighting and image quality are good "
            f"and there is no matching recent record for this vehicle at this location. On that "
            f"basis I am {trust:.0%} confident this fine is correctly attributed."
        )
        if dispute_reason:
            base += (
                " You have contested this notice, and I have re-examined the original footage "
                "against your account. The evidence still supports the violation."
            )
        return base

    if dispute_reason:
        return (
            "You have contested this notice and raised a point I cannot settle from the footage "
            "alone. Because I cannot verify your account against the frames, this has been passed "
            "to a human reviewer rather than upheld automatically, and no further action will be "
            "taken until they have looked at it."
        )

    return (
        f"The camera flagged a possible violation and the image quality is only moderate. My "
        f"overall confidence is {trust:.0%}, which is below the {settings.issue_trust_threshold:.0%} "
        "we require before charging anyone. This has been sent to a human reviewer instead of "
        "being issued automatically."
    )


# --------------------------------------------------------------------------- #
# Citizen explanations
# --------------------------------------------------------------------------- #
_CITIZEN_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "issue_headline": "A fine has been issued for your vehicle",
        "reject_headline": "No fine — this flag was dismissed",
        "escalate_headline": "On hold — a person is reviewing this",
        "issue_means": "You owe ₹{amount}. You can pay it or contest it below.",
        "reject_means": "Nothing is owed and no record is held against you.",
        "escalate_means": "Nothing is owed right now. A human reviewer will decide.",
        "opt_pay": "Pay ₹{amount} online",
        "opt_dispute": "Contest this notice",
        "opt_evidence": "View the camera evidence",
        "opt_verify": "Verify this record in the public ledger",
        "opt_nothing": "No action needed from you",
    },
    "hi": {
        "issue_headline": "आपके वाहन पर जुर्माना लगाया गया है",
        "reject_headline": "कोई जुर्माना नहीं — यह मामला रद्द कर दिया गया",
        "escalate_headline": "रुका हुआ — एक अधिकारी इसकी जाँच कर रहे हैं",
        "issue_means": "आपको ₹{amount} देना है। आप इसे भर सकते हैं या नीचे चुनौती दे सकते हैं।",
        "reject_means": "आपको कुछ नहीं देना है और आपके नाम कोई रिकॉर्ड दर्ज नहीं है।",
        "escalate_means": "अभी आपको कुछ नहीं देना है। एक अधिकारी निर्णय लेंगे।",
        "opt_pay": "₹{amount} ऑनलाइन भरें",
        "opt_dispute": "इस नोटिस को चुनौती दें",
        "opt_evidence": "कैमरे का सबूत देखें",
        "opt_verify": "सार्वजनिक लेजर में यह रिकॉर्ड जाँचें",
        "opt_nothing": "आपको कुछ नहीं करना है",
    },
    "kn": {
        "issue_headline": "ನಿಮ್ಮ ವಾಹನಕ್ಕೆ ದಂಡ ವಿಧಿಸಲಾಗಿದೆ",
        "reject_headline": "ದಂಡವಿಲ್ಲ — ಈ ಪ್ರಕರಣ ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ",
        "escalate_headline": "ತಡೆಹಿಡಿಯಲಾಗಿದೆ — ಅಧಿಕಾರಿಯೊಬ್ಬರು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದಾರೆ",
        "issue_means": "ನೀವು ₹{amount} ಪಾವತಿಸಬೇಕು. ಪಾವತಿಸಬಹುದು ಅಥವಾ ಕೆಳಗೆ ಆಕ್ಷೇಪಿಸಬಹುದು.",
        "reject_means": "ನೀವು ಏನನ್ನೂ ಪಾವತಿಸಬೇಕಿಲ್ಲ ಮತ್ತು ನಿಮ್ಮ ಹೆಸರಿನಲ್ಲಿ ಯಾವುದೇ ದಾಖಲೆ ಇಲ್ಲ.",
        "escalate_means": "ಸದ್ಯಕ್ಕೆ ಏನನ್ನೂ ಪಾವತಿಸಬೇಕಿಲ್ಲ. ಅಧಿಕಾರಿ ನಿರ್ಧರಿಸುತ್ತಾರೆ.",
        "opt_pay": "₹{amount} ಆನ್‌ಲೈನ್‌ನಲ್ಲಿ ಪಾವತಿಸಿ",
        "opt_dispute": "ಈ ನೋಟಿಸ್‌ಗೆ ಆಕ್ಷೇಪಿಸಿ",
        "opt_evidence": "ಕ್ಯಾಮೆರಾ ಸಾಕ್ಷ್ಯ ನೋಡಿ",
        "opt_verify": "ಸಾರ್ವಜನಿಕ ಲೆಡ್ಜರ್‌ನಲ್ಲಿ ಈ ದಾಖಲೆ ಪರಿಶೀಲಿಸಿ",
        "opt_nothing": "ನಿಮ್ಮಿಂದ ಯಾವುದೇ ಕ್ರಮ ಅಗತ್ಯವಿಲ್ಲ",
    },
    "ta": {
        "issue_headline": "உங்கள் வாகனத்திற்கு அபராதம் விதிக்கப்பட்டுள்ளது",
        "reject_headline": "அபராதம் இல்லை — இந்த வழக்கு நிராகரிக்கப்பட்டது",
        "escalate_headline": "நிறுத்தி வைக்கப்பட்டுள்ளது — ஒரு அதிகாரி பரிசீலிக்கிறார்",
        "issue_means": "நீங்கள் ₹{amount} செலுத்த வேண்டும். செலுத்தலாம் அல்லது கீழே மறுக்கலாம்.",
        "reject_means": "நீங்கள் எதுவும் செலுத்த வேண்டியதில்லை, உங்கள் பெயரில் பதிவு எதுவும் இல்லை.",
        "escalate_means": "இப்போது எதுவும் செலுத்த வேண்டாம். ஒரு அதிகாரி முடிவு செய்வார்.",
        "opt_pay": "₹{amount} ஆன்லைனில் செலுத்துங்கள்",
        "opt_dispute": "இந்த அறிவிப்பை மறுக்கவும்",
        "opt_evidence": "கேமரா ஆதாரத்தைப் பாருங்கள்",
        "opt_verify": "பொது லெட்ஜரில் இந்தப் பதிவைச் சரிபார்க்கவும்",
        "opt_nothing": "உங்களிடமிருந்து எந்த நடவடிக்கையும் தேவையில்லை",
    },
}

_REASONING_TRANSLATED: dict[str, dict[str, str]] = {
    "hi": {
        "ISSUE": (
            "कैमरे में उल्लंघन साफ़ दिखाई देता है और नंबर प्लेट {plate} स्पष्ट रूप से पढ़ी जा सकी। "
            "तस्वीर की गुणवत्ता अच्छी है और इसी वाहन का इसी जगह का कोई हालिया रिकॉर्ड नहीं मिला। "
            "इसी आधार पर यह जुर्माना जारी किया गया है।"
        ),
        "REJECT": (
            "जाँच के बाद यह पाया गया कि उपलब्ध फ़ुटेज से उल्लंघन की पुष्टि नहीं होती। "
            "इसलिए कोई जुर्माना जारी नहीं किया गया है और यह मामला बंद कर दिया गया है।"
        ),
        "ESCALATE": (
            "उल्लंघन तो दिखता है, लेकिन सबूत पूरी तरह भरोसेमंद नहीं है — इसलिए स्वचालित रूप से "
            "जुर्माना नहीं लगाया गया। एक मानव समीक्षक इसकी जाँच करेंगे। तब तक आपको कुछ नहीं देना है।"
        ),
    },
    "kn": {
        "ISSUE": (
            "ಕ್ಯಾಮೆರಾದಲ್ಲಿ ಉಲ್ಲಂಘನೆ ಸ್ಪಷ್ಟವಾಗಿ ಕಾಣಿಸುತ್ತದೆ ಮತ್ತು ನೋಂದಣಿ ಫಲಕ {plate} ಸ್ಪಷ್ಟವಾಗಿ ಓದಲಾಗಿದೆ. "
            "ಚಿತ್ರದ ಗುಣಮಟ್ಟ ಉತ್ತಮವಾಗಿದೆ ಮತ್ತು ಇದೇ ಸ್ಥಳದಲ್ಲಿ ಈ ವಾಹನದ ಇತ್ತೀಚಿನ ದಾಖಲೆ ಇಲ್ಲ. "
            "ಈ ಆಧಾರದ ಮೇಲೆ ದಂಡ ವಿಧಿಸಲಾಗಿದೆ."
        ),
        "REJECT": (
            "ಪರಿಶೀಲನೆಯ ನಂತರ, ಲಭ್ಯವಿರುವ ದೃಶ್ಯಾವಳಿಯಿಂದ ಉಲ್ಲಂಘನೆಯನ್ನು ಖಚಿತಪಡಿಸಲು ಸಾಧ್ಯವಾಗಿಲ್ಲ. "
            "ಆದ್ದರಿಂದ ಯಾವುದೇ ದಂಡ ವಿಧಿಸಿಲ್ಲ ಮತ್ತು ಈ ಪ್ರಕರಣವನ್ನು ಮುಚ್ಚಲಾಗಿದೆ."
        ),
        "ESCALATE": (
            "ಉಲ್ಲಂಘನೆ ಕಾಣಿಸುತ್ತದೆ, ಆದರೆ ಸಾಕ್ಷ್ಯ ಸಂಪೂರ್ಣ ವಿಶ್ವಾಸಾರ್ಹವಲ್ಲ — ಆದ್ದರಿಂದ ಸ್ವಯಂಚಾಲಿತವಾಗಿ "
            "ದಂಡ ವಿಧಿಸಿಲ್ಲ. ಅಧಿಕಾರಿಯೊಬ್ಬರು ಪರಿಶೀಲಿಸುತ್ತಾರೆ. ಅಲ್ಲಿಯವರೆಗೆ ನೀವು ಏನನ್ನೂ ಪಾವತಿಸಬೇಕಿಲ್ಲ."
        ),
    },
    "ta": {
        "ISSUE": (
            "கேமராவில் மீறல் தெளிவாகத் தெரிகிறது, பதிவு எண் {plate} தெளிவாகப் படிக்கப்பட்டது. "
            "படத்தின் தரம் நன்றாக உள்ளது, இதே இடத்தில் இந்த வாகனத்தின் சமீபத்திய பதிவு எதுவும் இல்லை. "
            "இதன் அடிப்படையில் அபராதம் விதிக்கப்பட்டுள்ளது."
        ),
        "REJECT": (
            "பரிசீலனைக்குப் பிறகு, கிடைத்த காணொளியிலிருந்து மீறலை உறுதிப்படுத்த முடியவில்லை. "
            "எனவே அபராதம் எதுவும் விதிக்கப்படவில்லை, இந்த வழக்கு மூடப்பட்டது."
        ),
        "ESCALATE": (
            "மீறல் தெரிகிறது, ஆனால் ஆதாரம் முழுமையாக நம்பகமானதாக இல்லை — எனவே தானாக அபராதம் "
            "விதிக்கப்படவில்லை. ஒரு அதிகாரி பரிசீலிப்பார். அதுவரை நீங்கள் எதுவும் செலுத்த வேண்டாம்."
        ),
    },
}


def citizen_view(
    verdict: str,
    language: str,
    fine_amount: int,
    plate: str,
    reasoning_en: str,
) -> dict:
    """Template-based citizen explanation for simulation mode."""
    strings = _CITIZEN_STRINGS.get(language, _CITIZEN_STRINGS["en"])
    key = {"ISSUE": "issue", "REJECT": "reject", "ESCALATE": "escalate"}[verdict]

    headline = strings[f"{key}_headline"]
    what_means = strings[f"{key}_means"].format(amount=f"{fine_amount:,}")

    if language == "en":
        explanation = reasoning_en
    else:
        explanation = _REASONING_TRANSLATED[language][verdict].format(plate=plate)

    if verdict == "ISSUE":
        options = [
            strings["opt_pay"].format(amount=f"{fine_amount:,}"),
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
