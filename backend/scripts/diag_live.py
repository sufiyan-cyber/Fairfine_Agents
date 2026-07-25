"""Isolate why a live audit fails, layer by layer.

Runs three probes and prints the FULL error for each (ExceptionGroups unwrapped),
so we can tell whether the failure is auth/quota, a bad model id, structured
output, vision input, or the ADK wiring on top.

    python scripts/diag_live.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def show_exc(exc: BaseException, indent: str = "  ") -> None:
    """Print an exception, unwrapping ExceptionGroups (TaskGroup failures)."""
    if isinstance(exc, BaseExceptionGroup):
        print(f"{indent}ExceptionGroup: {exc.message} ({len(exc.exceptions)} sub)")
        for i, sub in enumerate(exc.exceptions):
            print(f"{indent}  [{i}] {type(sub).__name__}: {str(sub)[:500]}")
            show_exc(sub, indent + "      ")
    else:
        print(f"{indent}{type(exc).__name__}: {str(exc)[:600]}")


def a_test_image() -> tuple[bytes, str]:
    import cv2
    import numpy as np

    frame = np.full((480, 854, 3), 60, dtype=np.uint8)
    cv2.rectangle(frame, (0, 300), (854, 480), (70, 70, 74), -1)
    cv2.putText(frame, "DIAGNOSTIC", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (200, 200, 200), 2)
    ok, buf = cv2.imencode(".jpg", frame)
    return buf.tobytes(), "image/jpeg"


def probe_1_raw_text() -> None:
    """Cheapest possible call: text only, no schema. Tests auth + model id."""
    print("\n[1] Raw text call (auth + model id)")
    from google import genai

    from app.config import settings

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = client.models.generate_content(
            model=settings.detector_model, contents="Reply with the single word OK."
        )
        print(f"  OK — model replied: {resp.text!r}")
    except Exception as exc:  # noqa: BLE001
        show_exc(exc)


def probe_2_vision_schema() -> None:
    """Vision + structured output — exactly what DetectorAgent does."""
    print("\n[2] Vision + response_schema (what DetectorAgent needs)")
    from google import genai
    from google.genai import types

    from app.config import settings
    from app.schemas import Detection

    data, mime = a_test_image()
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = client.models.generate_content(
            model=settings.detector_model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                types.Part(text="Classify any traffic violation. Return JSON."),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Detection,
            ),
        )
        print(f"  OK — structured reply: {resp.text[:200]!r}")
    except Exception as exc:  # noqa: BLE001
        show_exc(exc)


async def probe_3_adk_detector() -> None:
    """The real DetectorAgent through an ADK Runner."""
    print("\n[3] DetectorAgent via ADK Runner (the real path)")
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from app.agents.adk_agents import build_detector_agent

    data, mime = a_test_image()
    svc = InMemorySessionService()
    await svc.create_session(app_name="diag", user_id="u", session_id="s", state={})
    runner = Runner(app_name="diag", agent=build_detector_agent(), session_service=svc)

    try:
        async for event in runner.run_async(
            user_id="u",
            session_id="s",
            new_message=types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=data, mime_type=mime),
                    types.Part(text="Classify the violation."),
                ],
            ),
        ):
            if event.error_message:
                print(f"  event error: {event.error_code} {event.error_message}")
        session = await svc.get_session(app_name="diag", user_id="u", session_id="s")
        print(f"  final state.detection: {str(session.state.get('detection'))[:200]}")
    except Exception as exc:  # noqa: BLE001
        show_exc(exc)


def main() -> int:
    from app.config import settings

    print("=== FairFine live diagnostic ===")
    print(f"  gemini key : {'set' if settings.gemini_api_key else 'MISSING'}")
    print(f"  detector   : {settings.detector_model}")
    print(f"  auditor    : {settings.auditor_model}")

    if not settings.gemini_api_key:
        print("\n  No GEMINI_API_KEY — nothing to diagnose. This runs in simulation.")
        return 1

    probe_1_raw_text()
    probe_2_vision_schema()
    asyncio.run(probe_3_adk_detector())
    print("\nDone. The first probe that fails is the root cause.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
