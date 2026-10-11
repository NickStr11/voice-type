"""App configuration — loaded once at startup from .env file.

Fails fast with clear error messages if required settings are missing.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Whisper vocabulary-bias prompt — whisper conditions decoding on this text, so
# listed terms survive ru<->en code-switching and get spelled consistently.
# Neutral by default (public repo); override per-user via VOICETYPE_WHISPER_PROMPT
# with your own jargon (product names, acronyms). Keep it under ~350 chars.
_DEFAULT_WHISPER_PROMPT = (
    "VoiceType, Cypher, Whisper, Telegram, GitHub, Python, "
    "CUDA, ROCm, Vulkan, GGUF, API, SDK, LLM"
)


@dataclass(frozen=True)
class AppConfig:
    """Immutable configuration for VoiceType.

    Attributes:
        hotkey: Key combination string for VoiceType's RegisterHotKey parser.
                Example: "<ctrl>+<alt>+r"
        gcp_credentials_path: Absolute path to GCP service account JSON file.
                              None when stt_provider is "local".
        gcp_project_id: GCP project ID for Speech-to-Text V2 API.
                        Empty string when stt_provider is "local".
        stt_region: Regional endpoint prefix for STT. Default: us.
                    Full endpoint will be "{stt_region}-speech.googleapis.com".
    stt_provider: STT backend to use. "cloud" (Google Chirp 3) or "local" (Whisper).
                      Default: "local" so audio stays on-device unless opted in.
        whisper_model: Faster-whisper model name. Only used when stt_provider="local".
                       Default: "large-v3-turbo" (fast, ~1.6GB).
    """
    hotkey: str
    gcp_credentials_path: Path | None
    gcp_project_id: str
    stt_region: str = "us"
    stt_provider: str = "local"
    whisper_model: str = "large-v3-turbo"
    whisper_prompt: str = _DEFAULT_WHISPER_PROMPT
    cypher_planner: str = "off"
    cypher_planner_model: str = "gemini-2.5-flash"
    cloud_fallback: bool = False
    log_transcripts: bool = False
    log_level: str = "INFO"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    """Load and validate AppConfig from environment / .env file.

    Reads .env from the current working directory (or project root if run via
    `uv run`). Fails fast with sys.exit(1) if required config is missing or
    invalid — this is intentional: a misconfigured app should not start silently.

    When stt_provider is "local", GCP credentials are optional (not required).
    When stt_provider is "cloud", or cloud fallback is enabled without an
    OPENROUTER_API_KEY, GCP credentials are required.

    Returns:
        Validated AppConfig instance.

    Raises:
        SystemExit(1): If stt_provider is "cloud" and GOOGLE_APPLICATION_CREDENTIALS
                       is missing or file does not exist, or if GCP_PROJECT_ID is missing.
    """
    # Look for .env relative to this file's parent (project root when installed)
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    errors: list[str] = []

    # --- STT_PROVIDER (optional, has default) ---
    stt_provider = os.environ.get("VOICETYPE_STT_PROVIDER", "local").strip().lower()

    # --- WHISPER_MODEL (optional, has default) ---
    whisper_model = os.environ.get("VOICETYPE_WHISPER_MODEL", "large-v3-turbo").strip()

    # --- WHISPER_PROMPT / vocabulary bias (optional, has default) ---
    whisper_prompt = os.environ.get("VOICETYPE_WHISPER_PROMPT", "").strip() or _DEFAULT_WHISPER_PROMPT

    # --- CYPHER PLANNER (optional, has default) ---
    cypher_planner = os.environ.get("VOICETYPE_CYPHER_PLANNER", "off").strip().lower()
    if cypher_planner not in {"gemini", "off"}:
        errors.append(
            "VOICETYPE_CYPHER_PLANNER must be 'gemini' or 'off'.\n"
            f"  Got: {cypher_planner!r}"
        )

    cypher_planner_model = os.environ.get("VOICETYPE_CYPHER_PLANNER_MODEL", "gemini-2.5-flash").strip()

    # --- Privacy / logging ---
    cloud_fallback = _env_bool("VOICETYPE_CLOUD_FALLBACK")
    log_transcripts = _env_bool("VOICETYPE_LOG_TRANSCRIPTS")
    log_level = os.environ.get("VOICETYPE_LOG_LEVEL", "INFO").strip().upper() or "INFO"

    # --- GCP credentials — only required for cloud provider ---
    creds_path: Path | None = None
    raw_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if raw_creds:
        resolved = Path(raw_creds).expanduser().resolve()
        if resolved.exists():
            creds_path = resolved
    gcp_project_id = os.environ.get("GCP_PROJECT_ID", "").strip()

    # Cloud fallback runs through OpenRouter when a key is set; Chirp otherwise.
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    requires_gcp = (
        stt_provider != "local"
        or (cloud_fallback and not has_openrouter)
        or cypher_planner == "gemini"
    )

    if requires_gcp:
        if not raw_creds:
            errors.append(
                "GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
                "  Set it to the path of your GCP service account JSON file.\n"
                "  Example: GOOGLE_APPLICATION_CREDENTIALS=/home/user/.config/gcp/key.json"
            )
        elif creds_path is None:
            resolved = Path(raw_creds).expanduser().resolve()
            errors.append(
                f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {resolved}\n"
                "  Create a service account key in the GCP Console and download the JSON."
            )

        if not gcp_project_id:
            errors.append(
                "GCP_PROJECT_ID is not set.\n"
                "  Set it to your GCP project ID (e.g. my-project-123456)."
            )

    if errors:
        print("VoiceType: configuration error — cannot start\n", file=sys.stderr)
        for i, err in enumerate(errors, 1):
            print(f"  [{i}] {err}\n", file=sys.stderr)
        print("Copy .env.example to .env and fill in the values.", file=sys.stderr)
        sys.exit(1)

    # --- HOTKEY (optional, has default) ---
    hotkey = os.environ.get("VOICETYPE_HOTKEY", "<ctrl>+<alt>+r").strip()

    # --- STT_REGION (optional, has default) ---
    stt_region = os.environ.get("VOICETYPE_STT_REGION", "us").strip()

    return AppConfig(
        hotkey=hotkey,
        gcp_credentials_path=creds_path,
        gcp_project_id=gcp_project_id,
        stt_region=stt_region,
        stt_provider=stt_provider,
        whisper_model=whisper_model,
        whisper_prompt=whisper_prompt,
        cypher_planner=cypher_planner,
        cypher_planner_model=cypher_planner_model,
        cloud_fallback=cloud_fallback,
        log_transcripts=log_transcripts,
        log_level=log_level,
    )


if __name__ == "__main__":
    # Quick smoke-test: `uv run python -m voice_type.config`
    cfg = load_config()
    print(f"hotkey:               {cfg.hotkey}")
    print(f"gcp_credentials_path: {cfg.gcp_credentials_path}")
    print(f"gcp_project_id:       {cfg.gcp_project_id}")
    print(f"stt_region:           {cfg.stt_region}")
    print(f"stt_provider:         {cfg.stt_provider}")
    print(f"whisper_model:        {cfg.whisper_model}")
    print(f"cloud_fallback:       {cfg.cloud_fallback}")
    print(f"log_transcripts:      {cfg.log_transcripts}")
    print(f"log_level:            {cfg.log_level}")
    print(f"cypher_planner:       {cfg.cypher_planner}")
    print(f"cypher_planner_model: {cfg.cypher_planner_model}")
    print("Config loaded successfully.")
