"""Mock VAHAN / Parivahan registry.

Deliberately synthetic. Per the PRD's non-negotiables there is no real registry
integration and no real citizen PII anywhere in this system — records are
generated deterministically from the plate string so the demo is reproducible.
Registration data is returned already masked at the source; the raw owner name
never leaves this module.
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
_VEHICLE_MAKES = {
    "two_wheeler": ["Hero Splendor", "Honda Activa", "Bajaj Pulsar", "TVS Jupiter", "Royal Enfield Classic"],
    "car": ["Maruti Swift", "Hyundai i20", "Tata Nexon", "Honda City", "Mahindra XUV300"],
    "auto_rickshaw": ["Bajaj RE", "Piaggio Ape"],
    "truck": ["Tata 407", "Ashok Leyland Dost"],
}

_RTO_CITY = {
    "KA01": "Bengaluru Central",
    "KA03": "Bengaluru East",
    "KA05": "Bengaluru South",
    "KA51": "Bengaluru North",
    "TN01": "Chennai Central",
    "TN09": "Chennai South",
    "MH12": "Pune",
    "DL08": "Delhi North West",
    "HR26": "Gurugram",
}


def _seed(plate: str) -> int:
    return int(hashlib.sha256(plate.upper().encode()).hexdigest()[:12], 16)


def infer_vehicle_type(plate: str, violation_type: str = "") -> str:
    """Two-wheeler offences imply a two-wheeler; otherwise derive from the plate."""
    if violation_type in {"no_helmet", "triple_riding"}:
        return "two_wheeler"
    if violation_type in {"no_seatbelt"}:
        return "car"
    seed = _seed(plate)
    return ["two_wheeler", "car", "two_wheeler", "auto_rickshaw", "car", "truck"][seed % 6]


def mask_owner(name: str) -> str:
    """`Divya Reddy` -> `D**** R****`. Never emit the full name."""
    parts = [p for p in name.split() if p]
    return " ".join(f"{p[0]}{'*' * max(len(p) - 1, 1)}" for p in parts)


def vahan_lookup(plate: str, violation_type: str = "") -> dict:
    """Mock registry lookup for a plate.

    Returns owner details already masked. This is the function exposed to the
    EvidenceAgent as a tool.

    Args:
        plate: Registration number, e.g. "KA05MJ2138".
        violation_type: Optional hint used to infer the vehicle class.

    Returns:
        A dict of registration details with the owner name masked.
    """
    plate = (plate or "").upper().replace(" ", "").replace("-", "")
    if not plate or plate in {"UNKNOWN", "UNREADABLE"}:
        return {
            "found": False,
            "plate": plate,
            "note": "Plate not readable — no registry lookup performed.",
            "source": "MOCK_VAHAN",
        }

    seed = _seed(plate)
    first = _FIRST_NAMES[seed % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(seed >> 8) % len(_LAST_NAMES)]
    full_name = f"{first} {last}"
    vehicle_type = infer_vehicle_type(plate, violation_type)
    makes = _VEHICLE_MAKES.get(vehicle_type, _VEHICLE_MAKES["car"])
    rto_code = plate[:4]

    return {
        "found": True,
        "plate": plate,
        "owner_masked": mask_owner(full_name),
        "owner_initials": f"{first[0]}.{last[0]}.",
        "vehicle_type": vehicle_type,
        "vehicle_make": makes[(seed >> 16) % len(makes)],
        "registration_year": 2012 + (seed % 13),
        "rto": _RTO_CITY.get(rto_code, "Regional Transport Office"),
        "rto_code": rto_code,
        "insurance_valid": (seed % 10) != 3,
        "prior_challans_12mo": seed % 4,
        "source": "MOCK_VAHAN",
        "disclaimer": "Synthetic record. No real Parivahan/VAHAN integration.",
    }
