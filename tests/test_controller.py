"""Integration tests for AppController pipeline wiring."""
# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# win32 mocks are installed in tests/conftest.py before any imports
from voice_type.config import AppConfig
from voice_type.controller import AppController, State


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=Path("/fake/creds.json"),
        gcp_project_id="test-project",
        stt_region="us-central1",
        stt_provider="cloud",
        whisper_model="large-v3-turbo",
    )


@pytest.fixture()
def loop() -> asyncio.AbstractEventLoop:
    return asyncio.new_event_loop()


@pytest.fixture()
def mock_tray() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def controller(config: AppConfig, loop: asyncio.AbstractEventLoop, mock_tray: MagicMock) -> AppController:
    with patch("voice_type.controller.STTClient"), \
         patch("voice_type.controller.LLMClient"), \
         patch("voice_type.controller.PasteService"), \
         patch("voice_type.controller.HotkeyListener"), \
         patch("voice_type.controller.WhisperSTTClient"):
        ctrl = AppController(config, loop, tray=mock_tray)
    return ctrl


@pytest.mark.asyncio
async def test_full_pipeline_happy_path(controller: AppController, mock_tray: MagicMock) -> None:
    """hotkey -> RECORDING -> hotkey -> STT -> LLM -> paste -> IDLE."""
    # Setup mocks
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="привет мир ну вот")
    controller._llm.clean = MagicMock(return_value="Привет, мир.")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=12345):
        # First hotkey: IDLE -> RECORDING
        await controller._handle_hotkey()
        assert controller._state == State.RECORDING

        # Second hotkey: RECORDING -> PROCESSING -> IDLE
        await controller._handle_hotkey()
        assert controller._state == State.IDLE

    # Verify pipeline was called
    controller._stt.recognize.assert_called_once()
    controller._llm.clean.assert_called_once_with("привет мир ну вот")
    controller._paste.paste.assert_called_once_with("Привет, мир.", 12345)


@pytest.mark.asyncio
async def test_tray_state_sequence(controller: AppController, mock_tray: MagicMock) -> None:
    """Tray must transition: RECORDING -> PROCESSING -> IDLE."""
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="test")
    controller._llm.clean = MagicMock(return_value="Test.")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> PROCESSING -> IDLE

    state_calls = [c.args[0] for c in mock_tray.set_state.call_args_list]
    assert State.RECORDING in state_calls
    assert State.PROCESSING in state_calls
    assert state_calls[-1] == State.IDLE


@pytest.mark.asyncio
async def test_hotkey_ignored_during_processing(controller: AppController) -> None:
    """PROCESSING state must not respond to hotkey -- prevents double-recording."""
    controller._state = State.PROCESSING
    recorder_mock = MagicMock()
    controller._recorder = recorder_mock

    await controller._handle_hotkey()

    recorder_mock.start.assert_not_called()


@pytest.mark.asyncio
async def test_empty_stt_skips_paste(controller: AppController) -> None:
    """Empty STT result must not trigger LLM or paste calls."""
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="")
    controller._llm.clean = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._llm.clean.assert_not_called()
    controller._paste.paste.assert_not_called()


@pytest.mark.asyncio
async def test_state_resets_to_idle_on_pipeline_error(controller: AppController, mock_tray: MagicMock) -> None:
    """Pipeline error must not leave controller stuck in PROCESSING."""
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(side_effect=RuntimeError("GCP error"))

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process (will error)

    assert controller._state == State.IDLE
    assert mock_tray.set_state.call_args_list[-1].args[0] == State.IDLE


@pytest.mark.asyncio
async def test_auto_mode_uses_fast_cleanup_for_short_utterance(controller: AppController) -> None:
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="привет мир")
    controller._llm.clean = MagicMock()
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Привет, мир."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_not_called()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with("Привет, мир.", 1)


@pytest.mark.asyncio
async def test_auto_mode_uses_fast_cleanup_for_medium_utterance(controller: AppController) -> None:
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 6, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="привет мир без пунктуации")
    controller._llm.clean = MagicMock(return_value="Привет, мир без пунктуации.")
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=5), \
         patch("voice_type.controller.fast_clean", return_value="Привет, мир без пунктуации."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_not_called()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with("Привет, мир без пунктуации.", 5)


@pytest.mark.asyncio
async def test_stt_provider_local(controller: AppController) -> None:
    """When stt_provider='local', WhisperSTTClient.recognize is used, not STTClient."""
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="hello local")
    controller._stt.recognize = AsyncMock(return_value="hello cloud")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Hello local."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()


@pytest.mark.asyncio
async def test_stt_provider_cloud(controller: AppController) -> None:
    """When stt_provider='cloud', STTClient.recognize is used, not WhisperSTTClient."""
    controller.stt_provider = "cloud"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="hello cloud")
    controller._stt_whisper.recognize = AsyncMock(return_value="hello local")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Hello cloud."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt.recognize.assert_called_once()
    controller._stt_whisper.recognize.assert_not_called()


@pytest.mark.asyncio
async def test_stt_provider_switch_at_runtime(controller: AppController) -> None:
    """Switching stt_provider at runtime changes which client is used on next recording."""
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="cloud result")
    controller._stt_whisper.recognize = AsyncMock(return_value="local result")
    controller._paste.paste = MagicMock()

    # First recording: cloud
    controller.stt_provider = "cloud"
    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Cloud result."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt.recognize.assert_called_once()
    controller._stt_whisper.recognize.assert_not_called()

    # Reset call counts
    controller._stt.recognize.reset_mock()
    controller._stt_whisper.recognize.reset_mock()

    # Second recording: switch to local
    controller.stt_provider = "local"
    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Local result."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()


def test_controller_initializes_both_stt_clients(
    config: AppConfig, loop: asyncio.AbstractEventLoop, mock_tray: MagicMock
) -> None:
    """Controller must initialize both STTClient and WhisperSTTClient at startup."""
    with patch("voice_type.controller.STTClient") as mock_stt_cls, \
         patch("voice_type.controller.WhisperSTTClient") as mock_whisper_cls, \
         patch("voice_type.controller.LLMClient"), \
         patch("voice_type.controller.PasteService"), \
         patch("voice_type.controller.HotkeyListener"):
        AppController(config, loop, tray=mock_tray)

    mock_whisper_cls.assert_called_once_with(config)
    mock_stt_cls.assert_called_once_with(config)
