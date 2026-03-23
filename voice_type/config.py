"""App configuration — loaded once at startup from .env file.

Fails fast with clear error messages if required settings are missing.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class AppConfig:
    """Immutable configuration for VoiceType.

    Attributes:
        hotkey: Key combination string for pynput GlobalHotKeys format.
                Example: "<ctrl>+<alt>+r"
        gcp_credentials_path: Absolute path to GCP service account JSON file.
        gcp_project_id: GCP project ID for Speech-to-Text V2 API.
        stt_region: Regional endpoint prefix for Chirp 2. Default: us-central1.
                    Full endpoint will be "{stt_region}-speech.googleapis.com".
    """
    hotkey: str
    gcp_credentials_path: Path
    gcp_project_id: str
    stt_region: str = "us-central1"


def load_config() -> AppConfig:
    """Load and validate AppConfig from environment / .env file.

    Reads .env from the current working directory (or project root if run via
    `uv run`). Fails fast with sys.exit(1) if required config is missing or
    invalid — this is intentional: a misconfigured app should not start silently.

    Returns:
        Validated AppConfig instance.

    Raises:
        SystemExit(1): If GOOGLE_APPLICATION_CREDENTIALS is missing or the file
                       does not exist, or if GCP_PROJECT_ID is missing.
    """
    # Look for .env relative to this file's parent (project root when installed)
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    errors: list[str] = []

    # --- GOOGLE_APPLICATION_CREDENTIALS ---
    raw_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw_creds:
        errors.append(
            "GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
            "  Set it to the path of your GCP service account JSON file.\n"
            "  Example: GOOGLE_APPLICATION_CREDENTIALS=/home/user/.config/gcp/key.json"
        )
        creds_path = Path("/dev/null")  # placeholder, will not be used
    else:
        creds_path = Path(raw_creds).expanduser().resolve()
        if not creds_path.exists():
            errors.append(
                f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {creds_path}\n"
                "  Create a service account key in the GCP Console and download the JSON."
            )

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
    stt_region = os.environ.get("VOICETYPE_STT_REGION", "us-central1").strip()

    return AppConfig(
        hotkey=hotkey,
        gcp_credentials_path=creds_path,
        gcp_project_id=gcp_project_id,
        stt_region=stt_region,
    )


if __name__ == "__main__":
    # Quick smoke-test: `uv run python -m voice_type.config`
    cfg = load_config()
    print(f"hotkey:               {cfg.hotkey}")
    print(f"gcp_credentials_path: {cfg.gcp_credentials_path}")
    print(f"gcp_project_id:       {cfg.gcp_project_id}")
    print(f"stt_region:           {cfg.stt_region}")
    print("Config loaded successfully.")
