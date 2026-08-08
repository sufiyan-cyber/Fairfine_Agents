"""Runtime configuration for FairFine.

Every external dependency (Gemini, Qdrant, Enkrypt) is optional. When a key is
absent the corresponding subsystem falls back to a deterministic local
implementation so the full pipeline still runs end-to-end. `Settings.mode`
reports which posture we are in so the UI can label it honestly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
UPLOAD_DIR = BACKEND_ROOT / "uploads"
FRAME_DIR = UPLOAD_DIR / "frames"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Models (detection stack is locked by the PRD) ---
    gemini_api_key: str = ""
    # Route Gemini through Vertex AI instead of the Developer API. Vertex bills
    # to the project's Cloud billing account — which Google Cloud trial credits
    # do cover, while Gemini API/AI Studio usage is explicitly excluded from
    # them — and authenticates with the runtime's service account, so a Cloud
    # Run deployment carries no API key at all. Leave false to keep using
    # GEMINI_API_KEY; nothing else in the pipeline changes either way.
    use_vertex: bool = False
    google_cloud_project: str = ""
    # A concrete region, not `global`. The global endpoint shed every
    # multimodal (frames-attached) request from this project with 429
    # "Resource exhausted" while serving text-only calls fine — measured
    # 2026-08-07: identical 3-frame requests got 429 on `global` and 200 on
    # asia-south1, us-central1 and europe-west4. Regional endpoints have their
    # own capacity pools; asia-south1 is where the Cloud Run service runs.
    google_cloud_location: str = "asia-south1"
    # Tried when the primary region is still refusing the audit after retries.
    # Regions have separate capacity pools, so a second region is a genuine
    # second chance rather than another spin of the same wheel. Vertex-only;
    # empty disables the hop.
    vertex_fallback_location: str = "us-central1"
    # Force the deterministic simulator even when a Gemini key is present. Set
    # FORCE_SIMULATION=1 for a reliable, quota-free, controllable demo — a real
    # value that PowerShell handles cleanly, unlike blanking GEMINI_API_KEY.
    force_simulation: bool = False
    detector_model: str = "gemini-2.5-flash"
    plate_model: str = "gemini-2.5-flash"
    # Flash rather than Pro for the audit, which the PRD's locked stack called
    # for. Pro is served from a busier shared pool: measured against these
    # clips it answered in 57-103s and returned 429s under ordinary rehearsal
    # load, while Flash answered in 41-57s and reached the same verdicts. The
    # prompt, the five vetoes and the thresholds are what decide a case, and
    # they are identical either way. Set AUDITOR_MODEL=gemini-2.5-pro to take
    # the deeper reasoning and accept the latency.
    auditor_model: str = "gemini-2.5-flash"
    citizen_model: str = "gemini-2.5-flash"
    # Used only when the auditor's model is still rate-limited after retries.
    # Vertex serves the larger models from a shared capacity pool, so a 429
    # there means the pool is busy, not that the request is wrong. Ignored when
    # it matches `auditor_model`; set empty to let the audit fail instead.
    auditor_fallback_model: str = "gemini-2.5-flash-lite"

    # --- Semantic memory ---
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "fairfine"

    # --- Guardrails ---
    enkrypt_api_key: str = ""
    enkrypt_base_url: str = "https://api.enkryptai.com"

    # --- Storage ---
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'fairfine.db').as_posix()}"

    # --- Pipeline tuning (mirrors the auditor's verdict rules) ---
    event_window_seconds: int = 3
    frames_per_event: int = 5
    plate_confidence_floor: float = 0.85
    issue_trust_threshold: float = 0.90
    escalate_trust_floor: float = 0.60
    duplicate_window_seconds: int = 60

    cors_origins: str = "*"

    @property
    def sqlite_path(self) -> Path:
        raw = self.database_url.replace("sqlite:///", "").replace("sqlite://", "")
        return Path(raw)

    @property
    def live_vertex(self) -> bool:
        """Vertex needs a project; the credentials come from the environment."""
        return self.use_vertex and bool(self.google_cloud_project.strip())

    @property
    def live_llm(self) -> bool:
        if self.force_simulation:
            return False
        return self.live_vertex or bool(self.gemini_api_key.strip())

    @property
    def live_qdrant(self) -> bool:
        return bool(self.qdrant_url.strip())

    @property
    def live_enkrypt(self) -> bool:
        return bool(self.enkrypt_api_key.strip())

    @property
    def mode(self) -> str:
        """`live` when Gemini is wired up, `simulation` otherwise."""
        return "live" if self.live_llm else "simulation"

    def capability_report(self) -> dict[str, str]:
        def label(is_live: bool, live_name: str, fallback_name: str) -> str:
            return live_name if is_live else fallback_name

        inference = "deterministic-simulator"
        if self.live_llm:
            inference = "gemini-via-vertex" if self.live_vertex else "gemini"

        return {
            "inference": inference,
            "memory": label(self.live_qdrant, "qdrant", "sqlite-vector-fallback"),
            "guardrails": label(self.live_enkrypt, "enkrypt-ai", "local-pii-redactor"),
            "ledger": "sqlite-hash-chain",
        }


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (DATA_DIR, UPLOAD_DIR, FRAME_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    # Bridge the Gemini key into the process environment.
    #
    # We read the key from .env via pydantic-settings and pass it explicitly to
    # our own `genai.Client(...)` calls. But an ADK `LlmAgent` builds its *own*
    # Gemini client internally, and that client reads the key from the
    # environment (GOOGLE_API_KEY / GEMINI_API_KEY) — which pydantic-settings
    # does NOT populate. Without this, every LlmAgent fails with "No API key was
    # provided" even though the key is configured. Export the resolved value so
    # the ADK path and our direct path use exactly the same key.
    if settings.live_vertex:
        # Vertex authenticates with Application Default Credentials — the
        # service account on Cloud Run, or `gcloud auth application-default
        # login` locally. There is no key to pass, so the API key vars are
        # cleared: leaving one set makes the SDK prefer the Developer API and
        # silently ignore every Vertex setting below it.
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
    elif settings.live_llm:
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        # Force the Gemini Developer API backend, not Vertex, so a stray
        # GOOGLE_GENAI_USE_VERTEXAI in the shell can't redirect ADK to an auth
        # path this key won't satisfy.
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"

    return settings


settings = get_settings()
