"""Generate the demo clips from PRD §9.

Every frame is drawn from scratch with OpenCV — there is no real footage and no
real registration plate anywhere in the output. That satisfies the guardrail
"blur/synthesize all plates, never use real vehicles' real plates" absolutely
rather than by best effort.

    python scripts/make_demo_clips.py

Writes four clips to `backend/data/demo_clips/`. Filenames carry the camera,
junction and timestamp that IngestAgent parses back out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "demo_clips"

W, H = 1280, 720
FPS = 12
DURATION = 4  # seconds

ASPHALT = (58, 58, 62)
LANE = (232, 232, 236)
SKY = (120, 96, 74)
KERB = (86, 88, 92)


def _base_scene(oblique: bool = False) -> np.ndarray:
    """Road, kerbs, lane markings and a stop line.

    `oblique` shifts the stop line into a steep perspective — this is what
    creates the genuine parallax ambiguity in clip 3.
    """
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:, :] = SKY

    road = np.array([[0, H], [W, H], [int(W * 0.78), int(H * 0.32)], [int(W * 0.22), int(H * 0.32)]])
    cv2.fillPoly(frame, [road], ASPHALT)

    cv2.line(frame, (0, H), (int(W * 0.22), int(H * 0.32)), KERB, 6)
    cv2.line(frame, (W, H), (int(W * 0.78), int(H * 0.32)), KERB, 6)

    # Lane divider, dashed, receding.
    for i in range(9):
        t0, t1 = i / 9, i / 9 + 0.055
        y0, y1 = int(H - t0 * H * 0.68), int(H - t1 * H * 0.68)
        x0, x1 = int(W * 0.5), int(W * 0.5)
        cv2.line(frame, (x0, y0), (x1, y1), LANE, max(6 - i // 2, 2))

    # Stop line.
    if oblique:
        cv2.line(frame, (int(W * 0.14), int(H * 0.70)), (int(W * 0.92), int(H * 0.54)), LANE, 9)
    else:
        cv2.line(frame, (int(W * 0.16), int(H * 0.66)), (int(W * 0.86), int(H * 0.66)), LANE, 9)

    return frame


def _signal(frame: np.ndarray, state: str) -> None:
    x, y = int(W * 0.86), int(H * 0.16)
    cv2.rectangle(frame, (x - 26, y - 30), (x + 26, y + 108), (34, 34, 38), -1)
    colors = {
        "red": [(40, 40, 220), (40, 55, 70), (45, 70, 45)],
        "green": [(40, 40, 70), (40, 55, 70), (60, 200, 60)],
    }[state]
    for i, color in enumerate(colors):
        cv2.circle(frame, (x, y + i * 44), 16, color, -1)


def _plate(frame: np.ndarray, cx: int, cy: int, text: str, width: int, occlude: bool) -> None:
    """Synthetic plate. `text` is invented — it matches no real registration."""
    h = max(int(width * 0.30), 12)
    cv2.rectangle(frame, (cx - width // 2, cy - h // 2), (cx + width // 2, cy + h // 2), (245, 245, 240), -1)
    cv2.rectangle(frame, (cx - width // 2, cy - h // 2), (cx + width // 2, cy + h // 2), (20, 20, 20), 2)
    scale = width / 190.0
    cv2.putText(
        frame, text, (cx - width // 2 + int(8 * scale), cy + int(7 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.62 * scale, (18, 18, 18), max(int(2 * scale), 1), cv2.LINE_AA,
    )
    if occlude:
        # A van in the adjacent lane clipping the last characters.
        cv2.rectangle(
            frame,
            (cx + width // 6, cy - h),
            (cx + width // 2 + 40, cy + h),
            (52, 74, 108),
            -1,
        )


def _two_wheeler(frame: np.ndarray, cx: int, cy: int, scale: float, helmet: bool, riders: int, plate_text: str, occlude: bool) -> None:
    s = scale
    wheel_r = int(26 * s)
    cv2.circle(frame, (cx - int(48 * s), cy), wheel_r, (24, 24, 26), -1)
    cv2.circle(frame, (cx + int(48 * s), cy), wheel_r, (24, 24, 26), -1)
    cv2.rectangle(
        frame,
        (cx - int(44 * s), cy - int(34 * s)),
        (cx + int(44 * s), cy - int(6 * s)),
        (168, 52, 44),
        -1,
    )
    for i in range(riders):
        rx = cx + int((10 - i * 34) * s)
        body_top = cy - int(96 * s)
        cv2.rectangle(frame, (rx - int(15 * s), body_top), (rx + int(15 * s), cy - int(28 * s)), (66, 92, 148), -1)
        head_c = (rx, body_top - int(19 * s))
        head_r = int(17 * s)
        if helmet and i == 0:
            cv2.circle(frame, head_c, head_r + int(3 * s), (28, 28, 34), -1)
            cv2.circle(frame, head_c, head_r, (44, 44, 52), -1)
        else:
            cv2.circle(frame, head_c, head_r, (128, 152, 176), -1)  # bare head
    _plate(frame, cx + int(58 * s), cy + int(6 * s), plate_text, int(120 * s), occlude)


def _car(frame: np.ndarray, cx: int, cy: int, scale: float, plate_text: str, color=(150, 148, 142)) -> None:
    s = scale
    cv2.rectangle(frame, (cx - int(92 * s), cy - int(44 * s)), (cx + int(92 * s), cy + int(20 * s)), color, -1)
    cv2.rectangle(frame, (cx - int(58 * s), cy - int(76 * s)), (cx + int(52 * s), cy - int(42 * s)), (96, 108, 120), -1)
    cv2.circle(frame, (cx - int(58 * s), cy + int(20 * s)), int(20 * s), (24, 24, 26), -1)
    cv2.circle(frame, (cx + int(58 * s), cy + int(20 * s)), int(20 * s), (24, 24, 26), -1)
    _plate(frame, cx, cy + int(4 * s), plate_text, int(132 * s), False)


def _overlay(frame: np.ndarray, camera: str, junction: str, t: float) -> None:
    cv2.rectangle(frame, (0, 0), (W, 46), (0, 0, 0), -1)
    cv2.putText(frame, f"{camera}  |  {junction}", (18, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (225, 225, 230), 2, cv2.LINE_AA)
    cv2.putText(frame, f"T+{t:04.1f}s", (W - 150, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (225, 225, 230), 2, cv2.LINE_AA)
    cv2.putText(frame, "SYNTHETIC DEMO FOOTAGE - NOT REAL", (18, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (90, 170, 245), 2, cv2.LINE_AA)


def _write(name: str, builder) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    total = FPS * DURATION
    for i in range(total):
        writer.write(builder(i / total, i / FPS))
    writer.release()
    return path


# --------------------------------------------------------------------------- #
# The four clips
# --------------------------------------------------------------------------- #
def clip_clean(progress: float, t: float) -> np.ndarray:
    frame = _base_scene()
    _signal(frame, "green")
    cx = int(W * 0.20 + progress * W * 0.46)
    _two_wheeler(frame, cx, int(H * 0.74), 1.25, helmet=False, riders=1, plate_text="KA05 MJ 2138", occlude=False)
    _overlay(frame, "CAM-KA05-014", "HSR Layout 27th Main", t)
    return frame


def clip_occluded(progress: float, t: float) -> np.ndarray:
    frame = _base_scene()
    _signal(frame, "green")
    cx = int(W * 0.22 + progress * W * 0.42)
    _two_wheeler(frame, cx, int(H * 0.74), 1.25, helmet=False, riders=1, plate_text="KA51 HB 4471", occlude=True)
    _overlay(frame, "CAM-KA51-008", "Silk Board Junction", t)
    return frame


def clip_parallax(progress: float, t: float) -> np.ndarray:
    """The money frame: the oblique camera makes a stopped car look over the line."""
    frame = _base_scene(oblique=True)
    _signal(frame, "red")
    # Car decelerates and halts *behind* the true stop line; the shallow camera
    # angle projects it past the painted line.
    travel = 1 - (1 - min(progress * 1.5, 1.0)) ** 2
    cx = int(W * 0.30 + travel * W * 0.16)
    _car(frame, cx, int(H * 0.63), 1.05, "KA03 NF 8802", color=(178, 172, 160))
    cv2.putText(frame, "camera axis 38deg off perpendicular", (18, H - 52), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (120, 190, 250), 1, cv2.LINE_AA)
    _overlay(frame, "CAM-KA03-021", "Indiranagar 100ft Road", t)
    return frame


def clip_triple(progress: float, t: float) -> np.ndarray:
    frame = _base_scene()
    _signal(frame, "green")
    cx = int(W * 0.20 + progress * W * 0.48)
    _two_wheeler(frame, cx, int(H * 0.75), 1.3, helmet=True, riders=3, plate_text="TN09 BX 5514", occlude=False)
    _overlay(frame, "CAM-TN09-003", "T Nagar Junction", t)
    return frame


CLIPS = [
    ("clean_helmet_CAM-KA05-014_hsr_2026-07-24T14-32-11.mp4", clip_clean, "ISSUE"),
    ("occluded_plate_CAM-KA51-008_silk_2026-07-24T15-02-44.mp4", clip_occluded, "ESCALATE"),
    ("parallax_redlight_CAM-KA03-021_indiranagar_2026-07-24T16-11-05.mp4", clip_parallax, "REJECT"),
    ("triple_riding_CAM-TN09-003_tnagar_2026-07-24T17-45-30.mp4", clip_triple, "ISSUE"),
]


def main() -> int:
    print(f"Writing synthetic demo clips to {OUT_DIR}\n")
    for name, builder, expected in CLIPS:
        path = _write(name, builder)
        size_kb = path.stat().st_size / 1024
        print(f"  {expected:<9} {name}  ({size_kb:,.0f} KB)")
    print(
        "\nAll plates and vehicles are drawn from scratch. No real footage, no real plates."
        "\nFeed the clean clip twice within 60s to demonstrate duplicate rejection."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
