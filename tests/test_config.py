"""Tests for AppConfig — stt_provider + whisper_model fields, optional GCP credentials."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from voice_type.config import AppConfig, load_config


def _no_dotenv(*args: object, **kwargs: object) -> bool:
    """Stub for load_dotenv — prevents reading the real .env from disk."""
    return False


@pytest.fixture()
def minimal_gcp_env(tmp_path: Path) -> dict[str, str]:
    """Minimal env vars for a valid GCP (cloud) config."""
    creds = tmp_path / "key.json"
    creds.write_text("{}")
    return {
        "GOOGLE_APPLICATION_CREDENTIALS": str(creds),
        "GCP_PROJECT_ID": "test-project",
    }


def test_default_stt_provider_is_cloud(minimal_gcp_env: dict[str, str]) -> None:
    """Default stt_provider should be 'cloud' for backward compatibility."""
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, minimal_gcp_env, clear=True):
        config = load_config()
    assert config.stt_provider == "cloud"


def test_stt_provider_local_from_env() -> None:
    """stt_provider reads from VOICETYPE_STT_PROVIDER env var."""
    env = {"VOICETYPE_STT_PROVIDER": "local"}
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, env, clear=True):
        config = load_config()
    assert config.stt_provider == "local"


def test_whisper_model_default(minimal_gcp_env: dict[str, str]) -> None:
    """Default whisper_model is 'large-v3-turbo'."""
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, minimal_gcp_env, clear=True):
        config = load_config()
    assert config.whisper_model == "large-v3-turbo"


def test_whisper_model_override(minimal_gcp_env: dict[str, str]) -> None:
    """VOICETYPE_WHISPER_MODEL env var overrides the default."""
    env = {**minimal_gcp_env, "VOICETYPE_WHISPER_MODEL": "large-v3"}
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, env, clear=True):
        config = load_config()
    assert config.whisper_model == "large-v3"


def test_local_provider_no_gcp_credentials_succeeds() -> None:
    """When stt_provider=local, GCP credentials are NOT required."""
    env = {"VOICETYPE_STT_PROVIDER": "local"}
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, env, clear=True):
        config = load_config()  # must not raise SystemExit
    assert config.stt_provider == "local"
    assert config.gcp_credentials_path is None
    assert config.gcp_project_id == ""


def test_cloud_provider_no_gcp_credentials_fails() -> None:
    """When stt_provider=cloud (default), missing GCP credentials → SystemExit."""
    env = {"VOICETYPE_STT_PROVIDER": "cloud"}
    with patch("voice_type.config.load_dotenv", _no_dotenv), \
         patch.dict(os.environ, env, clear=True):
        with pytest.raises(SystemExit):
            load_config()


def test_appconfig_has_stt_provider_field() -> None:
    """AppConfig dataclass has stt_provider field with correct default."""
    config = AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=None,
        gcp_project_id="",
        stt_provider="local",
        whisper_model="large-v3-turbo",
    )
    assert config.stt_provider == "local"


def test_appconfig_has_whisper_model_field() -> None:
    """AppConfig dataclass has whisper_model field with correct default."""
    config = AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=None,
        gcp_project_id="",
    )
    assert config.whisper_model == "large-v3-turbo"
