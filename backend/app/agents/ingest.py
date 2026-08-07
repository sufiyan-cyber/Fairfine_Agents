"""IngestAgent — frame sampling + event metadata.

Exposed to ADK as a FunctionTool. Samples frames across the event window with
ffmpeg (falling back to OpenCV), and derives camera/location/timestamp from the
filename or file mtime. Real deployments would read this from the camera's
metadata sidecar; the parsing contract is the same.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..config import FRAME_DIR, settings
from ..schemas import Frame

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Junctions used when a clip carries no location metadata. Real deployments
# resolve camera_id -> location from the camera registry.
_KNOWN_JUNCTIONS = [
    ("hsr", "HSR Layout 27th Main Junction, Bengaluru"),
    ("silk", "Silk Board Junction, Bengaluru"),
    ("indiranagar", "Indiranagar 100ft Road, Bengaluru"),
    ("koramangala", "Koramangala 80ft Road, Bengaluru"),
    ("mgroad", "MG Road Signal, Bengaluru"),
    ("whitefield", "Whitefield Main Road, Bengaluru"),
    ("anna", "Anna Salai Signal, Chennai"),
    ("tnagar", "T Nagar Junction, Chennai"),
]

_DEFAULT_LOCATION = "HSR Layout 27th Main Junction, Bengaluru"


def _parse_camera_id(stem: str) -> str:
    """Camera ids are internally hyphenated (CAM-KA05-014) while filename
    fields are underscore-separated, so the id runs to the next underscore."""
    match = re.search(
        r"(?:cam|camera)[-_]?([a-z0-9]+(?:-[a-z0-9]+)*)", stem, re.IGNORECASE
    )
    if match:
        return f"CAM-{match.group(1).upper()}"
    return "CAM-KA05-014"


def _parse_location(stem: str) -> str:
    lowered = re.sub(r"[^a-z]", "", stem.lower())
    for key, name in _KNOWN_JUNCTIONS:
        if key in lowered:
            return name
    return _DEFAULT_LOCATION


def _parse_timestamp(stem: str, source: Path) -> str:
    """ISO-8601 from the filename when present, else the file's mtime."""
    patterns = [
        r"(\d{4}-\d{2}-\d{2})[T_](\d{2})[-:](\d{2})[-:](\d{2})",
        r"(\d{4}\d{2}\d{2})[T_](\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, stem)
        if match:
            date_part, hh, mm, ss = match.groups()
            date_part = date_part.replace("-", "")
            try:
                parsed = datetime(
                    int(date_part[0:4]), int(date_part[4:6]), int(date_part[6:8]),
                    int(hh), int(mm), int(ss), tzinfo=timezone.utc,
                )
                return parsed.isoformat(timespec="milliseconds")
            except ValueError:
                continue
    try:
        return datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
    except OSError:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _probe_duration(source: Path) -> float:
    """Clip length in seconds via ffprobe; 0.0 when it cannot be determined."""
    if shutil.which("ffprobe") is None:
        return 0.0
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    try:
        probe = subprocess.run(cmd, check=True, capture_output=True, timeout=20)
        return float(probe.stdout.decode().strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
        return 0.0


def _sample_by_seek(source: Path, out_dir: Path, count: int, duration: float) -> list[Path]:
    """Sample `count` frames spread across a clip longer than the event window.

    One decode per frame, seeking to each timestamp. Input seeking (`-ss` before
    `-i`) jumps to the nearest keyframe rather than decoding everything it
    passes over, so sampling a five-minute clip costs about what a five-second
    one does. Timestamps are centred in their slice — sampling at t=0 tends to
    land on a black or half-rendered opening frame.
    """
    written: list[Path] = []
    for i in range(count):
        ts = duration * (i + 0.5) / count
        path = out_dir / f"frame_{i + 1:03d}.jpg"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{ts:.3f}", "-i", str(source),
            "-vf", "scale='min(1280,iw)':-2",
            "-frames:v", "1",
            "-q:v", "3",
            str(path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
        if path.exists():
            written.append(path)
    return written


def _sample_with_ffmpeg(source: Path, out_dir: Path, count: int, window: int) -> list[Path]:
    """Sample `count` frames covering the event.

    A clip longer than the event window is sampled across its whole duration.
    Deriving fps from `window` alone — as this did — pins every frame inside the
    opening few seconds, so on a 30-second upload the models never see the other
    27 and the verdict is drawn from footage that may not contain the event at
    all. Short clips keep the single-pass `fps` filter, which is cheaper than a
    seek per frame and covers them completely either way.
    """
    duration = _probe_duration(source)
    if duration > window:
        frames = _sample_by_seek(source, out_dir, count, duration)
        if frames:
            return frames

    fps = max(count / max(window, 1), 1)
    pattern = out_dir / "frame_%03d.jpg"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vf", f"fps={fps:.3f},scale='min(1280,iw)':-2",
        "-frames:v", str(count),
        "-q:v", "3",
        str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []
    return sorted(out_dir.glob("frame_*.jpg"))


def _sample_with_opencv(source: Path, out_dir: Path, count: int) -> list[Path]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return []
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    written: list[Path] = []
    try:
        if total <= 0:
            index = 0
            while index < count:
                ok, image = capture.read()
                if not ok:
                    break
                path = out_dir / f"frame_{index + 1:03d}.jpg"
                cv2.imwrite(str(path), _downscale(image))
                written.append(path)
                index += 1
            return written

        step = max(total // count, 1)
        for i in range(count):
            capture.set(cv2.CAP_PROP_POS_FRAMES, min(i * step, max(total - 1, 0)))
            ok, image = capture.read()
            if not ok:
                break
            path = out_dir / f"frame_{i + 1:03d}.jpg"
            cv2.imwrite(str(path), _downscale(image))
            written.append(path)
    finally:
        capture.release()
    return written


def _downscale(image, max_width: int = 1280):
    height, width = image.shape[:2]
    if width <= max_width:
        return image
    scale = max_width / width
    return cv2.resize(image, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)


def ingest_event(
    source_path: str,
    event_window_seconds: int | None = None,
    location: str | None = None,
    camera_id: str | None = None,
) -> dict:
    """Sample frames from a clip or image and attach event metadata.

    Args:
        source_path: Path to an uploaded video or still image.
        event_window_seconds: Seconds around the event to sample. Defaults to 3.
        location: Override the junction name inferred from the filename.
        camera_id: Override the camera id inferred from the filename.

    Returns:
        `{"frames": [...], "event_id": str, "source": str, "sampler": str}`.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    window = event_window_seconds or settings.event_window_seconds
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    out_dir = FRAME_DIR / event_id
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = source.stem
    resolved_camera = camera_id or _parse_camera_id(stem)
    resolved_location = location or _parse_location(stem)
    ts = _parse_timestamp(stem, source)

    sampler = "single-image"
    if source.suffix.lower() in _IMAGE_SUFFIXES:
        target = out_dir / f"frame_001{source.suffix.lower()}"
        shutil.copyfile(source, target)
        paths = [target]
    else:
        paths = []
        if _ffmpeg_available():
            paths = _sample_with_ffmpeg(source, out_dir, settings.frames_per_event, window)
            sampler = "ffmpeg"
        if not paths:
            paths = _sample_with_opencv(source, out_dir, settings.frames_per_event)
            sampler = "opencv"
        if not paths:
            raise ValueError(
                f"Could not decode any frames from {source.name}. "
                "Supported: mp4/mov/avi/mkv video or jpg/png stills."
            )

    frames = [
        Frame(
            path=str(path),
            ts=ts,
            camera_id=resolved_camera,
            location=resolved_location,
        ).model_dump()
        for path in paths
    ]

    return {
        "frames": frames,
        "event_id": event_id,
        "source": source.name,
        "sampler": sampler,
        "window_seconds": window,
    }


def frame_to_part(path: str) -> tuple[bytes, str]:
    """Read a frame as (bytes, mime) for a Gemini vision content part."""
    file_path = Path(path)
    mime = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    return file_path.read_bytes(), mime


def frame_to_data_uri(path: str, max_width: int = 900) -> str:
    """Downscaled data URI so evidence renders in the browser without a CDN."""
    try:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("unreadable")
        image = _downscale(image, max_width)
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise ValueError("encode failed")
        return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode()
    except Exception:
        return ""
