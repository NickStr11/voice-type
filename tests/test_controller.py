"""Integration tests for AppController pipeline wiring."""
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
         patch("voice_type.controller.HotkeyListener"):
        ctrl = AppController(config, loop, tray=mock_tray)
    return ctrl


@pytest.mark.asyncio
async def test_full_pipeline_happy_path(controller: AppController, mock_tray: MagicMock) -> None:
    """hotkey -> RECORDING -> hotkey -> STT -> LLM -> paste -> IDLE."""
    # Setup mocks
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.zeros(16000, dtype=np.int16))
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
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.zeros(16000, dtype=np.int16))
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
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.zeros(16000, dtype=np.int16))
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
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.zeros(16000, dtype=np.int16))
    controller._stt.recognize = AsyncMock(side_effect=RuntimeError("GCP error"))

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process (will error)

    assert controller._state == State.IDLE
    assert mock_tray.set_state.call_args_list[-1].args[0] == State.IDLE
