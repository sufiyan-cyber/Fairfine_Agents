"""Motor Vehicles Act, 1988 (as amended 2019) — retrieval corpus.

Section text is paraphrased into plain language for the demo RAG index; it is
not a legal reproduction and must not be relied on as legal advice. Penalty
figures follow the 2019 amendment's central schedule — states notify their own
compounding amounts, which is exactly why the citizen portal cites the section
and lets a human contest the amount.
"""

from __future__ import annotations

MV_ACT_SECTIONS: list[dict] = [
    {
        "section": "MV Act §129",
        "title": "Wearing of protective headgear",
        "text": (
            "Every person driving or riding a motorcycle of any class must wear protective "
            "headgear conforming to Bureau of Indian Standards specifications. The requirement "
            "extends to pillion riders. Persons of the Sikh faith wearing a turban are exempt."
        ),
        "penalty": "₹1,000 and disqualification of licence for three months (via §194D)",
        "violations": ["no_helmet"],
        "keywords": ["helmet", "headgear", "motorcycle", "pillion", "two-wheeler", "bis"],
    },
    {
        "section": "MV Act §194D",
        "title": "Penalty for not wearing protective headgear",
        "text": (
            "Whoever drives or rides a motorcycle without protective headgear in contravention "
            "of section 129 or any rule made thereunder shall be punishable with a fine of one "
            "thousand rupees and shall be disqualified from holding a licence for three months."
        ),
        "penalty": "₹1,000 + 3-month licence disqualification",
        "violations": ["no_helmet"],
        "keywords": ["helmet", "penalty", "fine", "disqualification", "rider"],
    },
    {
        "section": "MV Act §184",
        "title": "Driving dangerously",
        "text": (
            "Whoever drives a motor vehicle at a speed or in a manner dangerous to the public, "
            "having regard to all the circumstances of the case including the nature, condition "
            "and use of the place and the amount of traffic actually present, shall be "
            "punishable. The section expressly covers jumping a red light, violating a stop "
            "sign, and using a handheld communication device while driving."
        ),
        "penalty": "₹1,000–₹5,000 and/or imprisonment up to 1 year (first offence)",
        "violations": ["red_light_jump", "phone_use", "wrong_side"],
        "keywords": [
            "dangerous",
            "red light",
            "signal",
            "stop line",
            "jumping",
            "handheld",
            "mobile phone",
            "reckless",
        ],
    },
    {
        "section": "MV Act §184(c)",
        "title": "Jumping a red light",
        "text": (
            "Driving a motor vehicle past a traffic signal displaying red, such that the vehicle "
            "crosses the marked stop line while the signal is against it, constitutes dangerous "
            "driving. The offence requires that the signal was actually red at the moment the "
            "vehicle crossed the stop line — not merely that the vehicle was within the junction."
        ),
        "penalty": "₹1,000–₹5,000",
        "violations": ["red_light_jump"],
        "keywords": ["red light", "stop line", "signal", "junction", "crossed", "amber"],
    },
    {
        "section": "MV Act §184(e)",
        "title": "Using a handheld communication device while driving",
        "text": (
            "Using a handheld communication device while driving a motor vehicle is dangerous "
            "driving. Hands-free operation is not an offence under this clause. The device must "
            "be visibly held in the hand and in use for the offence to be made out."
        ),
        "penalty": "₹1,000–₹5,000",
        "violations": ["phone_use"],
        "keywords": ["phone", "mobile", "handheld", "device", "calling", "texting"],
    },
    {
        "section": "MV Act §194B",
        "title": "Use of safety belts",
        "text": (
            "Whoever drives a motor vehicle without wearing a safety belt, or carries passengers "
            "not wearing seat belts, shall be punishable. The requirement applies to front and "
            "rear occupants of vehicles fitted with seat belts."
        ),
        "penalty": "₹1,000",
        "violations": ["no_seatbelt"],
        "keywords": ["seatbelt", "seat belt", "safety belt", "occupant", "restraint"],
    },
    {
        "section": "MV Act §194C",
        "title": "Overloading of two-wheelers",
        "text": (
            "Whoever drives a two-wheeled motorcycle carrying more persons than permitted — that "
            "is, more than the driver and one pillion rider — shall be punishable and shall be "
            "disqualified from holding a licence for three months."
        ),
        "penalty": "₹2,000 + 3-month licence disqualification",
        "violations": ["triple_riding"],
        "keywords": ["triple", "three", "pillion", "overload", "two-wheeler", "riders"],
    },
    {
        "section": "MV Act §177",
        "title": "General provision for punishment of offences",
        "text": (
            "Whoever contravenes any provision of this Act or of any rule, regulation or "
            "notification made thereunder shall, if no penalty is provided for the offence, be "
            "punishable for the first offence with a fine of five hundred rupees, and for any "
            "subsequent offence with a fine of one thousand five hundred rupees."
        ),
        "penalty": "₹500 first offence, ₹1,500 subsequent",
        "violations": ["wrong_side", "none"],
        "keywords": ["general", "residual", "contravention", "default", "rule"],
    },
    {
        "section": "MV Act §119",
        "title": "Duty to obey traffic signs",
        "text": (
            "Every driver of a motor vehicle shall drive the vehicle in conformity with any "
            "indication given by a mandatory traffic sign, and shall comply with all directions "
            "given by any police officer for the time being engaged in the regulation of traffic."
        ),
        "penalty": "Compounded under §177",
        "violations": ["wrong_side", "red_light_jump"],
        "keywords": ["traffic sign", "one way", "mandatory", "signage", "obey", "direction"],
    },
    {
        "section": "MV Act §112",
        "title": "Limits of speed",
        "text": (
            "No person shall drive a motor vehicle in any public place at a speed exceeding the "
            "maximum speed fixed for the vehicle under this Act or by the State Government for "
            "that class of vehicle on that stretch of road."
        ),
        "penalty": "₹1,000–₹2,000 depending on vehicle class (via §183)",
        "violations": [],
        "keywords": ["speed", "limit", "overspeeding", "maximum"],
    },
    {
        "section": "MV Act §183",
        "title": "Driving at excessive speed",
        "text": (
            "Whoever drives a motor vehicle in contravention of the speed limits under section "
            "112 shall be punishable with a fine of one thousand rupees for light motor vehicles "
            "and two thousand rupees for medium or heavy passenger or goods vehicles."
        ),
        "penalty": "₹1,000 (LMV) / ₹2,000 (MGV, HGV)",
        "violations": [],
        "keywords": ["speed", "excessive", "overspeed", "lmv", "heavy"],
    },
    {
        "section": "MV Act §132",
        "title": "Duty of driver to stop in certain cases",
        "text": (
            "The driver of a motor vehicle shall cause the vehicle to stop and remain stationary "
            "when required to do so by a police officer in uniform, or on the occurrence of an "
            "accident involving the vehicle."
        ),
        "penalty": "₹500–₹1,000",
        "violations": [],
        "keywords": ["stop", "police", "checkpoint", "accident", "stationary"],
    },
    {
        "section": "MV Act §185",
        "title": "Driving by a drunken person",
        "text": (
            "Whoever, while driving, has in his blood alcohol exceeding 30 mg per 100 ml "
            "detected in a test by a breath analyser, or is under the influence of a drug to "
            "such an extent as to be incapable of exercising proper control, shall be punishable."
        ),
        "penalty": "₹10,000 and/or 6 months imprisonment (first offence)",
        "violations": [],
        "keywords": ["drunk", "alcohol", "breath analyser", "intoxicated", "drug"],
    },
    {
        "section": "MV Act §146",
        "title": "Necessity for insurance against third-party risk",
        "text": (
            "No person shall use, or cause or allow any other person to use, a motor vehicle in "
            "a public place unless there is in force a policy of insurance complying with the "
            "requirements of this Chapter."
        ),
        "penalty": "₹2,000 and/or 3 months imprisonment (via §196)",
        "violations": [],
        "keywords": ["insurance", "third party", "policy", "uninsured"],
    },
    {
        "section": "MV Act §192",
        "title": "Using vehicle without registration",
        "text": (
            "Whoever drives a motor vehicle or causes a motor vehicle to be driven without it "
            "being registered, or in contravention of the conditions of registration, shall be "
            "punishable."
        ),
        "penalty": "₹2,000–₹5,000",
        "violations": [],
        "keywords": ["registration", "unregistered", "rc", "number plate"],
    },
    {
        "section": "MV Act §50",
        "title": "Transfer of ownership",
        "text": (
            "Where the ownership of a motor vehicle is transferred, the transferor and transferee "
            "shall jointly report the transfer to the registering authority within fourteen days. "
            "Until the transfer is recorded, the registered owner on record remains the person to "
            "whom notices are issued."
        ),
        "penalty": "₹500 per month of delay",
        "violations": [],
        "keywords": ["ownership", "transfer", "sold", "registered owner", "vahan"],
    },
    {
        "section": "MV Act §130",
        "title": "Duty to produce licence and certificate of registration",
        "text": (
            "The driver of a motor vehicle shall, on demand by any police officer in uniform, "
            "produce the licence for examination. Production may be made in physical or in "
            "electronic form through a government-recognised digital platform."
        ),
        "penalty": "Compounded under §177",
        "violations": [],
        "keywords": ["licence", "license", "produce", "digilocker", "documents"],
    },
    {
        "section": "MV Act §190",
        "title": "Using a vehicle in unsafe condition",
        "text": (
            "Any person who drives, or causes or allows to be driven, a motor vehicle which has "
            "any defect likely to cause danger to any person, or which violates standards "
            "prescribed for road safety, noise and air pollution control, shall be punishable."
        ),
        "penalty": "₹1,500–₹10,000 depending on the defect",
        "violations": [],
        "keywords": ["unsafe", "defect", "pollution", "puc", "emission", "roadworthy"],
    },
    {
        "section": "MV Act §194E",
        "title": "Failure to allow free passage to emergency vehicles",
        "text": (
            "Whoever, while driving, fails to draw to the side of the road on the approach of a "
            "fire service vehicle, ambulance or other emergency vehicle so as to allow it free "
            "passage, shall be punishable."
        ),
        "penalty": "₹10,000 and/or 6 months imprisonment",
        "violations": [],
        "keywords": ["ambulance", "emergency", "fire", "free passage", "siren"],
    },
    {
        "section": "MV Act §199A",
        "title": "Offences by juveniles",
        "text": (
            "Where an offence under this Act is committed by a juvenile, the guardian of the "
            "juvenile or the owner of the motor vehicle shall be deemed guilty, unless they prove "
            "the offence was committed without their knowledge or that they exercised due "
            "diligence to prevent it."
        ),
        "penalty": "₹25,000, 3 years imprisonment; registration cancelled for 12 months",
        "violations": [],
        "keywords": ["juvenile", "minor", "guardian", "underage", "owner liability"],
    },
    {
        "section": "MV Act §206",
        "title": "Power to detain vehicles and impound documents",
        "text": (
            "Any police officer authorised in this behalf may seize and detain a driving licence "
            "where an offence under sections 183, 184, 185, 189, 190, 194C, 194D or 194E is "
            "alleged, and forward it to the licensing authority."
        ),
        "penalty": "Not a fine — enforcement power",
        "violations": [],
        "keywords": ["detain", "impound", "seize", "licence", "enforcement"],
    },
    {
        "section": "MV Act §136A",
        "title": "Electronic monitoring and enforcement of road safety",
        "text": (
            "The State Government shall ensure electronic monitoring and enforcement of road "
            "safety on national highways, state highways and urban roads using speed cameras, "
            "closed-circuit television cameras, speed guns, body-wearable cameras and such other "
            "technology, in the manner prescribed by the Central Government. Rules made under "
            "this section govern how automatically captured evidence may be used."
        ),
        "penalty": "Not a fine — enabling provision for camera enforcement",
        "violations": [
            "red_light_jump",
            "no_helmet",
            "wrong_side",
            "triple_riding",
            "no_seatbelt",
            "phone_use",
        ],
        "keywords": [
            "electronic",
            "cctv",
            "camera",
            "automatic",
            "enforcement",
            "evidence",
            "anpr",
            "challan",
        ],
    },
]

# Which section is cited when a violation is confirmed.
PRIMARY_SECTION: dict[str, str] = {
    "no_helmet": "MV Act §194D",
    "red_light_jump": "MV Act §184(c)",
    "phone_use": "MV Act §184(e)",
    "no_seatbelt": "MV Act §194B",
    "triple_riding": "MV Act §194C",
    "wrong_side": "MV Act §184",
    "none": "MV Act §177",
}

FINE_AMOUNT: dict[str, int] = {
    "no_helmet": 1000,
    "red_light_jump": 1000,
    "phone_use": 1000,
    "no_seatbelt": 1000,
    "triple_riding": 2000,
    "wrong_side": 500,
    "none": 0,
}

VIOLATION_LABEL: dict[str, str] = {
    "no_helmet": "Riding without a helmet",
    "red_light_jump": "Crossing on a red signal",
    "wrong_side": "Driving against the flow of traffic",
    "triple_riding": "Three people on a two-wheeler",
    "no_seatbelt": "Driving without a seat belt",
    "phone_use": "Using a phone while driving",
    "none": "No violation detected",
}


def get_section(section_id: str) -> dict | None:
    for entry in MV_ACT_SECTIONS:
        if entry["section"] == section_id:
            return entry
    return None


def section_for_violation(violation_type: str) -> dict | None:
    return get_section(PRIMARY_SECTION.get(violation_type, "MV Act §177"))


def fine_for(violation_type: str) -> int:
    return FINE_AMOUNT.get(violation_type, 0)


def label_for(violation_type: str) -> str:
    return VIOLATION_LABEL.get(violation_type, violation_type.replace("_", " ").title())


def corpus_documents() -> list[dict]:
    """Flatten to indexable documents for the vector store."""
    docs = []
    for entry in MV_ACT_SECTIONS:
        docs.append(
            {
                "id": entry["section"],
                "text": f"{entry['section']} — {entry['title']}. {entry['text']} Penalty: {entry['penalty']}",
                "metadata": entry,
            }
        )
    return docs
