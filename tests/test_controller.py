"""Integration tests for AppController pipeline wiring."""
# pyright: reportPrivateUsage=false, reportOptionalMemberAccess=false
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# win32 mocks are installed in tests/conftest.py before any imports
from voice_type.config import AppConfig
from voice_type.controller import AppController, State
from voice_type.cypher import CypherCommand


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=Path("/fake/creds.json"),
        gcp_project_id="test-project",
        stt_region="us-central1",
        stt_provider="cloud",
        whisper_model="large-v3-turbo",
        cypher_planner="gemini",
        cypher_planner_model="gemini-2.5-flash",
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
         patch("voice_type.controller.WhisperSTTClient"), \
         patch("voice_type.controller.GeminiCypherPlanner"), \
         patch("voice_type.controller.CypherExecutor"):
        ctrl = AppController(config, loop, tray=mock_tray)
    ctrl._cypher_planner = None
    return ctrl


@pytest.mark.asyncio
async def test_full_pipeline_happy_path(controller: AppController, mock_tray: MagicMock) -> None:
    """hotkey -> RECORDING -> hotkey -> STT -> LLM -> paste -> IDLE."""
    # Setup mocks
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="РїСЂРёРІРµС‚ РјРёСЂ РЅСѓ РІРѕС‚")
    controller._llm.clean = MagicMock(return_value="РџСЂРёРІРµС‚, РјРёСЂ.")
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
    controller._llm.clean.assert_called_once_with("РїСЂРёРІРµС‚ РјРёСЂ РЅСѓ РІРѕС‚")
    controller._paste.paste.assert_called_once_with("РџСЂРёРІРµС‚, РјРёСЂ.", 12345)


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
    controller._stt.recognize = AsyncMock(return_value="РїСЂРёРІРµС‚ РјРёСЂ")
    controller._llm.clean = MagicMock()
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="РџСЂРёРІРµС‚, РјРёСЂ."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_not_called()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with("РџСЂРёРІРµС‚, РјРёСЂ.", 1)


@pytest.mark.asyncio
async def test_auto_mode_uses_full_cleanup_for_medium_utterance(controller: AppController) -> None:
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 6, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="РїСЂРёРІРµС‚ РјРёСЂ Р±РµР· РїСѓРЅРєС‚СѓР°С†РёРё")
    controller._llm.clean = MagicMock(return_value="РџСЂРёРІРµС‚, РјРёСЂ Р±РµР· РїСѓРЅРєС‚СѓР°С†РёРё.")
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=5), \
         patch("voice_type.controller.fast_clean", return_value="РџСЂРёРІРµС‚, РјРёСЂ Р±РµР· РїСѓРЅРєС‚СѓР°С†РёРё."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_called_once()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with("РџСЂРёРІРµС‚, РјРёСЂ Р±РµР· РїСѓРЅРєС‚СѓР°С†РёРё.", 5)


@pytest.mark.asyncio
async def test_auto_mode_keeps_fast_cleanup_for_medium_punctuated_utterance(controller: AppController) -> None:
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 6, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Hello world, this is already clean.")
    controller._llm.clean = MagicMock()
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=7), \
         patch("voice_type.controller.fast_clean", return_value="Hello world, this is already clean."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_not_called()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with("Hello world, this is already clean.", 7)


@pytest.mark.asyncio
async def test_stt_provider_local_races_cloud_for_short_audio(controller: AppController) -> None:
    """Short local dictation starts BOTH cloud and whisper in parallel and
    prefers cloud's result when it succeeds (chirp handles ru/en code-
    switching more reliably than whisper-cpp).
    """
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="hello local")
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="hello cloud")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Hello cloud."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    # Both providers are queried in parallel; cloud's result wins because
    # it returned non-empty text.
    controller._stt.recognize.assert_called_once()
    controller._stt_whisper.recognize.assert_called_once()
    controller._paste.paste.assert_called_once_with("Hello cloud.", 1)


@pytest.mark.asyncio
async def test_stt_provider_cloud(controller: AppController) -> None:
    """When stt_provider='cloud', STTClient.recognize is used, not WhisperSTTClient."""
    controller.stt_provider = "cloud"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    assert controller._stt is not None
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
    assert controller._stt is not None
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

    # Second recording: switch to local. With the parallel race in place,
    # both providers are queried; cloud's result wins.
    controller.stt_provider = "local"
    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Cloud result."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt.recognize.assert_called_once()
    controller._stt_whisper.recognize.assert_called_once()


@pytest.mark.asyncio
async def test_local_stt_uses_whisper_only_for_very_long_audio(controller: AppController) -> None:
    """Audio longer than the cloud sync-API window (~50s) skips cloud
    entirely and uses whisper only. Cloud is reserved as fallback for an
    empty whisper result.
    """
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    # 55 seconds — past the 50s cloud-race threshold.
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 55, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="hello local long form")
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="hello cloud")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=9), \
         patch("voice_type.controller.fast_clean", return_value="Hello local long form"):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()
    controller._paste.paste.assert_called_once_with("Hello local long form", 9)


@pytest.mark.asyncio
async def test_local_stt_falls_back_to_whisper_when_cloud_short_audio_is_empty(controller: AppController) -> None:
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 5, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="Could we discuss this now?")
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=10), \
         patch("voice_type.controller.fast_clean", return_value="Could we discuss this now?"):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_called_once()
    controller._paste.paste.assert_called_once_with("Could we discuss this now?", 10)


@pytest.mark.asyncio
async def test_prefixed_cypher_command_executes_and_skips_paste(controller: AppController) -> None:
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Cypher, open telegram")
    controller._llm.clean = MagicMock()
    controller._paste.paste = MagicMock()
    controller._cypher.execute = MagicMock(return_value=None)

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._cypher.execute.assert_called_once_with(
        CypherCommand(
            kind="open_app",
            value="telegram",
            spoken_target="telegram",
        )
    )
    controller._llm.clean.assert_not_called()
    controller._paste.paste.assert_not_called()


@pytest.mark.asyncio
async def test_unrecognized_prefixed_cypher_command_skips_paste(controller: AppController) -> None:
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Cypher, СѓРґР°Р»Рё РІСЃРµ С„Р°Р№Р»С‹")
    controller._llm.clean = MagicMock()
    controller._paste.paste = MagicMock()
    controller._cypher.execute = MagicMock(return_value=None)

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._cypher.execute.assert_not_called()
    controller._llm.clean.assert_not_called()
    controller._paste.paste.assert_not_called()


@pytest.mark.asyncio
async def test_planner_executes_unrecognized_prefixed_cypher_command(controller: AppController) -> None:
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Cypher, throw a screenshot into Telegram for me")
    controller._llm.clean = MagicMock()
    controller._paste.paste = MagicMock()
    controller._cypher.execute = MagicMock(return_value=None)
    controller._cypher_planner = MagicMock()
    controller._cypher_planner.plan = MagicMock(
        return_value=CypherCommand(
            kind="telegram_send_screenshot",
            value="Saved Messages",
            spoken_target="Saved Messages",
        )
    )

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._cypher_planner.plan.assert_called_once_with("throw a screenshot into Telegram for me")
    controller._cypher.execute.assert_called_once_with(
        CypherCommand(
            kind="telegram_send_screenshot",
            value="Saved Messages",
            spoken_target="Saved Messages",
        )
    )
    controller._llm.clean.assert_not_called()
    controller._paste.paste.assert_not_called()


def test_controller_initializes_both_stt_clients(
    config: AppConfig, loop: asyncio.AbstractEventLoop, mock_tray: MagicMock
) -> None:
    """Controller must initialize both STTClient and WhisperSTTClient at startup."""
    with patch("voice_type.controller.STTClient") as mock_stt_cls, \
         patch("voice_type.controller.WhisperSTTClient") as mock_whisper_cls, \
         patch("voice_type.controller.LLMClient"), \
         patch("voice_type.controller.PasteService"), \
         patch("voice_type.controller.HotkeyListener"), \
         patch("voice_type.controller.GeminiCypherPlanner"):
        AppController(config, loop, tray=mock_tray)

    mock_whisper_cls.assert_called_once_with(config)
    mock_stt_cls.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_prefixed_cypher_command_can_paste_text_result(controller: AppController) -> None:
    controller.mode = "full"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Cypher, read last 2 messages in telegram Saved Messages")
    controller._llm.clean = MagicMock()
    controller._paste.paste = MagicMock()
    controller._cypher.execute = MagicMock(return_value="РїРµСЂРІРѕРµ\n\nРІС‚РѕСЂРѕРµ")

    with patch("voice_type.controller.capture_active_window", return_value=1):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._cypher.execute.assert_called_once()
    controller._paste.paste.assert_called_once_with("РїРµСЂРІРѕРµ\n\nРІС‚РѕСЂРѕРµ", 1)

