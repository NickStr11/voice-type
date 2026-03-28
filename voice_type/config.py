"""App configuration — loaded once at startup from .env file.

Fails fast with clear error messages if required settings are missing.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


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
                      Default: "cloud" for backward compatibility.
        whisper_model: Faster-whisper model name. Only used when stt_provider="local".
                       Default: "large-v3-turbo" (fast, ~1.6GB).
    """
    hotkey: str
    gcp_credentials_path: Path | None
    gcp_project_id: str
    stt_region: str = "us"
    stt_provider: str = "cloud"
    whisper_model: str = "large-v3-turbo"


def load_config() -> AppConfig:
    """Load and validate AppConfig from environment / .env file.

    Reads .env from the current working directory (or project root if run via
    `uv run`). Fails fast with sys.exit(1) if required config is missing or
    invalid — this is intentional: a misconfigured app should not start silently.

    When stt_provider is "local", GCP credentials are optional (not required).
    When stt_provider is "cloud" (default), GCP credentials are required.

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
    stt_provider = os.environ.get("VOICETYPE_STT_PROVIDER", "cloud").strip().lower()

    # --- WHISPER_MODEL (optional, has default) ---
    whisper_model = os.environ.get("VOICETYPE_WHISPER_MODEL", "large-v3-turbo").strip()

    # --- GCP credentials — only required for cloud provider ---
    creds_path: Path | None = None
    gcp_project_id = ""

    if stt_provider != "local":
        # --- GOOGLE_APPLICATION_CREDENTIALS ---
        raw_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not raw_creds:
            errors.append(
                "GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
                "  Set it to the path of your GCP service account JSON file.\n"
                "  Example: GOOGLE_APPLICATION_CREDENTIALS=/home/user/.config/gcp/key.json"
            )
        else:
            resolved = Path(raw_creds).expanduser().resolve()
            if not resolved.exists():
                errors.append(
                    f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {resolved}\n"
                    "  Create a service account key in the GCP Console and download the JSON."
                )
            else:
                creds_path = resolved

        # --- GCP_PROJECT_ID ---
        gcp_project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
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
    print("Config loaded successfully.")
