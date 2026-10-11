"""Integration tests for AppController pipeline wiring."""
# pyright: reportPrivateUsage=false, reportOptionalMemberAccess=false
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# win32 mocks are installed in tests/conftest.py before any imports
from voice_type.config import AppConfig
from voice_type.controller import MAX_RECORDING_DURATION_S, AppController, State
from voice_type.cypher import CypherCommand


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


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
async def test_local_stt_warms_up_when_recording_starts(controller: AppController) -> None:
    controller._config = replace(controller._config, stt_provider="local")
    controller.stt_provider = "local"
    controller._recorder = MagicMock()

    with patch.object(controller._stt_whisper, "warmup") as mock_warmup:
        await controller._start_recording()

    mock_warmup.assert_called_once_with()


@pytest.mark.asyncio
async def test_recording_timeout_enqueues_stop(controller: AppController) -> None:
    controller._state = State.RECORDING

    controller._on_recording_timeout()

    assert await controller._queue.get() == "hotkey"
    assert MAX_RECORDING_DURATION_S == 15 * 60


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
async def test_auto_mode_uses_gemini_cleanup_for_medium_utterance(controller: AppController) -> None:
    """Long/unpunctuated dictation routes to Gemini (full) for real paragraph
    structure — not the instant fast path."""
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 6, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="РїСЂРёРІРµС‚ РјРёСЂ Р±РµР· РїСѓРЅРєС‚СѓР°С†РёРё")
    expected = "РџСЂРёРІРµС‚, РјРёСЂ.\n\nР‘РµР· РїСѓРЅРєС‚СѓР°С†РёРё."
    controller._llm.clean = MagicMock(return_value=expected)
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=5):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_called_once()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with(expected, 5)


@pytest.mark.asyncio
async def test_auto_mode_uses_gemini_cleanup_for_punctuated_utterance(controller: AppController) -> None:
    """Trailing punctuation no longer forces the fast path — a long but
    finished sentence still goes to Gemini for paragraph structure."""
    controller.mode = "auto"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 6, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="Hello world, this is already clean.")
    expected = "Hello world.\n\nThis is already clean."
    controller._llm.clean = MagicMock(return_value=expected)
    controller._llm_local = MagicMock()
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=7):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._llm.clean.assert_called_once()
    controller._llm_local.clean.assert_not_called()
    controller._paste.paste.assert_called_once_with(expected, 7)


@pytest.mark.asyncio
async def test_stt_provider_local_uses_whisper_only(controller: AppController) -> None:
    """Local mode is whisper-only now — Cloud Chirp is no longer raced on every
    utterance (it billed GCP and caused mid-word splits). Cloud is not touched
    when whisper returns text.
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
         patch("voice_type.controller.fast_clean", return_value="Hello local."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()
    controller._paste.paste.assert_called_once_with("Hello local.", 1)


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

    # Second recording: switch to local — whisper only, cloud not touched.
    controller.stt_provider = "local"
    with patch("voice_type.controller.capture_active_window", return_value=1), \
         patch("voice_type.controller.fast_clean", return_value="Local result."):
        await controller._handle_hotkey()  # IDLE -> RECORDING
        await controller._handle_hotkey()  # RECORDING -> process

    controller._stt_whisper.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()


@pytest.mark.asyncio
async def test_local_stt_long_audio_uses_whisper_only(controller: AppController) -> None:
    """Local mode uses whisper only regardless of audio length; cloud is never
    called when whisper returns text."""
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
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
async def test_local_stt_falls_back_to_cloud_when_whisper_empty(controller: AppController) -> None:
    """Local mode does not send audio to cloud when fallback is disabled."""
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 5, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="")  # whisper failed
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="Could we discuss this now?")
    controller._paste.paste = MagicMock()
    controller._cloud_fallback_enabled = False

    with patch("voice_type.controller.capture_active_window", return_value=10), \
         patch("voice_type.controller.fast_clean", return_value="Could we discuss this now?"):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._stt_whisper.recognize.assert_called_once()
    assert controller._stt_whisper.recognize.call_args.kwargs == {"fast_fail": False}
    controller._stt.recognize.assert_not_called()
    controller._paste.paste.assert_not_called()


@pytest.mark.asyncio
async def test_local_stt_cloud_fallback_requires_explicit_opt_in(controller: AppController) -> None:
    """If explicitly enabled, cloud STT is the one-shot fallback for empty Whisper output."""
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 5, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="")
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="Could we discuss this now?")
    controller._paste.paste = MagicMock()
    controller._cloud_fallback_enabled = True

    with patch("voice_type.controller.capture_active_window", return_value=10), \
         patch("voice_type.controller.fast_clean", return_value="Could we discuss this now?"):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._stt_whisper.recognize.assert_called_once()
    assert controller._stt_whisper.recognize.call_args.kwargs == {"fast_fail": True}
    controller._stt.recognize.assert_called_once()
    controller._paste.paste.assert_called_once_with("Could we discuss this now?", 10)


@pytest.mark.asyncio
async def test_cloud_fallback_prefers_openrouter_over_chirp(controller: AppController) -> None:
    controller.stt_provider = "local"
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 5, 500, dtype=np.int16))
    controller._stt_whisper.recognize = AsyncMock(return_value="")
    assert controller._stt is not None
    controller._stt.recognize = AsyncMock(return_value="chirp")
    controller._openrouter_stt = MagicMock()
    controller._openrouter_stt.recognize = AsyncMock(return_value="Через OpenRouter.")
    controller._paste.paste = MagicMock()
    controller._cloud_fallback_enabled = True

    with patch("voice_type.controller.capture_active_window", return_value=10), \
         patch("voice_type.controller.fast_clean", return_value="Через OpenRouter."):
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    controller._openrouter_stt.recognize.assert_called_once()
    controller._stt.recognize.assert_not_called()
    controller._paste.paste.assert_called_once_with("Через OpenRouter.", 10)


@pytest.mark.asyncio
async def test_cleaned_transcript_is_not_logged_by_default(controller: AppController) -> None:
    controller.mode = "fast"
    controller._recorder = MagicMock()
    controller._recorder.start = MagicMock()
    controller._recorder.stop = MagicMock(return_value=np.full(16000 * 5, 500, dtype=np.int16))
    controller._stt.recognize = AsyncMock(return_value="private dictation")
    controller._paste.paste = MagicMock()

    with patch("voice_type.controller.capture_active_window", return_value=10), \
         patch("voice_type.controller.fast_clean", return_value="Private dictation."), \
         patch("voice_type.controller.logger.debug") as mock_debug:
        await controller._handle_hotkey()
        await controller._handle_hotkey()

    assert not any("CLEANED text" in str(call.args[0]) for call in mock_debug.call_args_list)


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


@pytest.mark.asyncio
async def test_run_loop_drops_hotkey_received_during_processing(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller._loop = asyncio.get_running_loop()
    controller.mode = "fast"
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    entered, release = asyncio.Event(), asyncio.Event()

    async def transcribe(_: bytes) -> str:
        entered.set()
        await release.wait()
        return "Тест"

    controller._transcribe = AsyncMock(side_effect=transcribe)
    controller._paste.paste.return_value = True
    with patch("voice_type.controller.capture_active_window", return_value=42):
        runner = asyncio.create_task(controller.run())
        try:
            controller._on_hotkey_from_thread()
            await asyncio.wait_for(entered.wait(), 2)
            controller._on_hotkey_from_thread()
            await asyncio.sleep(0.01)
            release.set()
            await wait_until(lambda: controller._state == State.IDLE)
            await asyncio.sleep(0.01)
            controller._recorder.start.assert_not_called()
            controller._paste.paste.assert_called_once()
        finally:
            release.set()
            controller.shutdown()
            await asyncio.wait_for(runner, 2)


@pytest.mark.asyncio
async def test_cancel_during_stt_keeps_late_text_without_paste(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller._loop = asyncio.get_running_loop()
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    entered, release = asyncio.Event(), asyncio.Event()

    async def transcribe(_: bytes) -> str:
        entered.set()
        await release.wait()
        return "Сохранить мысль"

    controller._transcribe = AsyncMock(side_effect=transcribe)
    with patch("voice_type.controller.capture_active_window", return_value=42):
        task = asyncio.create_task(controller._stop_and_process())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            controller.cancel_processing()
            await asyncio.sleep(0)
            assert controller._state == State.PROCESSING
            assert controller._cancel_requested
            release.set()
            await asyncio.wait_for(task, 2)
        finally:
            release.set()
            await task
    assert controller.last_raw_text == "Сохранить мысль"
    assert controller.last_text == "Сохранить мысль"
    assert controller._state == State.IDLE
    controller._paste.paste.assert_not_called()
    controller._llm.clean.assert_not_called()
    assert "Отменено" in controller.status


@pytest.mark.asyncio
async def test_cancel_during_worker_cleanup_never_pastes_late_result(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller._loop = asyncio.get_running_loop()
    controller.mode = "full"
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    controller._transcribe = AsyncMock(return_value="черновик")
    entered, release = threading.Event(), threading.Event()

    def delayed_cleanup(_: str) -> str:
        entered.set()
        if not release.wait(3):
            raise TimeoutError("test release was not signaled")
        return "Черновик."

    controller._llm.clean.side_effect = delayed_cleanup
    with patch("voice_type.controller.capture_active_window", return_value=42):
        task = asyncio.create_task(controller._stop_and_process())
        try:
            await wait_until(entered.is_set)
            controller.cancel_processing()
            await asyncio.sleep(0)
            assert not task.done()  # The thread stays owned until it really finishes.
            assert controller.last_text == "черновик"
            release.set()
            await asyncio.wait_for(task, 2)
        finally:
            release.set()
            await task
    controller._paste.paste.assert_not_called()
    assert controller.last_text == "Черновик."
    assert controller._state == State.IDLE


@pytest.mark.asyncio
async def test_failed_paste_can_copy_and_retry_saved_target(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller.mode = "fast"
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    controller._transcribe = AsyncMock(return_value="Сохранённый текст")
    controller._paste.paste.return_value = False
    with patch("voice_type.controller.capture_active_window", return_value=42):
        await controller._stop_and_process()
    assert "не удалась" in controller.status
    saved = controller.last_text
    assert saved
    controller._paste.copy.return_value = True
    await controller._recover_last(copy_only=True)
    controller._paste.copy.assert_called_once_with(saved)
    assert controller.status == "Текст скопирован"
    controller._paste.paste.return_value = True
    with patch("voice_type.controller.capture_active_window", return_value=999):
        await controller._recover_last(copy_only=False)
    controller._paste.paste.assert_called_with(saved, 42)
    assert "отправлена" in controller.status


@pytest.mark.asyncio
async def test_cleanup_exception_keeps_raw_text_for_recovery(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller.mode = "full"
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    controller._transcribe = AsyncMock(return_value="Не потерять")
    controller._llm.clean.side_effect = RuntimeError("simulated cleanup failure")
    with patch("voice_type.controller.capture_active_window", return_value=42):
        await controller._stop_and_process()
    assert controller.last_text == "Не потерять"
    assert "Ошибка" in controller.status
    controller._paste.paste.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_cannot_race_an_active_pipeline(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller.last_text = "Предыдущая запись"
    controller._state = State.PROCESSING
    await controller._recover_last(copy_only=True)
    await controller._recover_last(copy_only=False)
    controller._paste.copy.assert_not_called()
    controller._paste.paste.assert_not_called()


def test_cancel_does_not_claim_to_undo_dispatched_action(controller: AppController) -> None:
    controller._paste = MagicMock()
    controller._llm = MagicMock()
    controller._state = State.PROCESSING
    controller._side_effect_started = True
    controller._cancel_processing()
    assert not controller._cancel_requested
    assert "уже началось" in controller.status

@pytest.mark.asyncio
async def test_shutdown_drains_inflight_recognition_without_late_paste(controller: AppController) -> None:
    controller._loop = asyncio.get_running_loop()
    controller._state = State.RECORDING
    controller._recorder = MagicMock()
    controller._recorder.stop.return_value = np.full(16000, 500, dtype=np.int16)
    controller._paste = MagicMock()
    entered, release = asyncio.Event(), asyncio.Event()

    async def transcribe(_: bytes) -> str:
        entered.set()
        await release.wait()
        return "Поздний результат"

    controller._transcribe = AsyncMock(side_effect=transcribe)
    with patch("voice_type.controller.capture_active_window", return_value=42):
        runner = asyncio.create_task(controller.run())
        try:
            controller._on_hotkey_from_thread()
            await asyncio.wait_for(entered.wait(), 2)
            controller.shutdown()
            await wait_until(lambda: controller._cancel_requested)
            assert not runner.done()
            release.set()
            await asyncio.wait_for(runner, 2)
        finally:
            release.set()
            if not runner.done():
                controller.shutdown()
                await asyncio.wait_for(runner, 2)
    controller._paste.paste.assert_not_called()
    assert controller.last_text == "Поздний результат"
    assert controller._state == State.IDLE
