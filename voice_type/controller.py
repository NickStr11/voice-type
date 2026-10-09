"""AppController — state machine that orchestrates the full recording pipeline.

State machine:
    IDLE -> (hotkey) -> RECORDING -> (hotkey) -> PROCESSING -> IDLE
                                                  ^
                                (hotkey during PROCESSING is ignored)

Thread safety:
    on_hotkey() is called from the hotkey listener thread via
    loop.call_soon_threadsafe(). All state transitions happen inside
    the asyncio event loop -- no locks needed for state itself.

Pipeline (Phase 2):
    hotkey stop -> STTClient.recognize() -> LLMClient.clean() -> PasteService.paste()
    STT and Paste are I/O-bound blocking calls -- run via asyncio.to_thread().
    LLMClient.clean() is synchronous with its own wall-clock timeout -- also
    run via asyncio.to_thread() so it doesn't block the event loop.
"""
from __future__ import annotations

import asyncio
import time as _time

import numpy as np
import numpy.typing as npt
from loguru import logger

from voice_type.audio import AudioRecorder, MicrophoneError, trim_silence
from voice_type.cleanup import fast_clean
from voice_type.config import AppConfig
from voice_type.cypher import CypherExecutor, extract_cypher_body, parse_cypher_command
from voice_type.cypher_planner import GeminiCypherPlanner
from voice_type.hotkey import HotkeyListener
from voice_type.llm import LLMClient
from voice_type.llm_local import LocalLLMClient
from voice_type.paste import PasteService
from voice_type.states import State
from voice_type.stt import STTClient
from voice_type.stt_whisper import WhisperSTTClient
from voice_type.tray import TrayIcon
from voice_type.window import capture_active_window

# Short utterances skip the LLM and get instant regex cleanup — never worth a
# network round-trip for a couple of words.
FAST_CLEANUP_MAX_DURATION_S = 3.0
FAST_CLEANUP_MAX_CHARS = 120
MAX_RECORDING_DURATION_S = 15 * 60


class AppController:
    """Orchestrates the recording lifecycle and pipeline.

    Usage (from main.py):
        loop = asyncio.new_event_loop()
        tray = TrayIcon(on_quit=...)
        controller = AppController(config, loop, tray=tray)
        controller.start_hotkey_listener()
        tray.run_detached()
        loop.run_until_complete(controller.run())
    """

    def __init__(
        self,
        config: AppConfig,
        loop: asyncio.AbstractEventLoop,
        tray: TrayIcon | None = None,
    ) -> None:
        self._config = config
        self._loop = loop
        self._state = State.IDLE
        self._recorder = AudioRecorder()
        self._hotkey_listener = HotkeyListener(config, self._on_hotkey_from_thread)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._target_hwnd: int = 0
        self._tray = tray
        self._recording_timeout: asyncio.TimerHandle | None = None
        self._processing_task: asyncio.Task[None] | None = None
        self._cancel_requested = False
        self._side_effect_started = False
        self.last_text = ""
        self.last_raw_text = ""
        self._last_target_hwnd = 0
        self.status = "Готов к записи"

        # Pipeline components -- initialized once, reused per recording
        self._stt = STTClient(config) if config.gcp_credentials_path is not None else None
        self._stt_whisper = WhisperSTTClient(config)
        self._cloud_fallback_enabled = config.cloud_fallback
        self._log_transcripts = config.log_transcripts
        self._llm = LLMClient(project=config.gcp_project_id)
        self._paste = PasteService()
        self._llm_local = LocalLLMClient()
        self._cypher = CypherExecutor()
        self._cypher_planner = self._build_cypher_planner(config)
        self.mode: str = "auto"  # "auto" | "fast" | "local" | "full"
        self.stt_provider: str = config.stt_provider  # "cloud" | "local"

    def _build_cypher_planner(self, config: AppConfig) -> GeminiCypherPlanner | None:
        if config.cypher_planner != "gemini":
            logger.info("Cypher planner disabled")
            return None
        if not config.gcp_project_id:
            logger.warning("Cypher planner disabled — GCP_PROJECT_ID missing")
            return None
        return GeminiCypherPlanner(
            project=config.gcp_project_id,
            model=config.cypher_planner_model,
        )

    def _resolve_cleanup_mode(self, duration_s: float, raw_text: str) -> str:
        """Select cleanup mode for the current utterance.

        Short utterances → instant regex (fast_clean), never worth a network
        round-trip. Long dictation → Gemini ("full") when credentials are
        configured. fast_clean is the in-executor fallback if Gemini fails.
        """
        if self.mode != "auto":
            return self.mode
        if duration_s <= FAST_CLEANUP_MAX_DURATION_S and len(raw_text) <= FAST_CLEANUP_MAX_CHARS:
            return "fast"
        # Gemini only when credentials exist; otherwise stay fully offline on
        # regex fast_clean (public users without a GEMINI_API_KEY).
        return "full" if self._llm.available else "fast"

    def start_hotkey_listener(self) -> None:
        """Start the hotkey listener in a daemon thread."""
        self._hotkey_listener.start()
        logger.info(f"Hotkey listener started -- hotkey: {self._config.hotkey}")

    def stop_hotkey_listener(self) -> None:
        """Stop the hotkey listener. Safe to call multiple times."""
        self._hotkey_listener.stop()

    def _on_hotkey_from_thread(self) -> None:
        """Callback fired from the hotkey listener thread.

        Bridges the hotkey thread to the asyncio event loop via
        call_soon_threadsafe -- the only safe way to enqueue work
        from a non-asyncio thread into an asyncio loop.
        """
        self._loop.call_soon_threadsafe(self._enqueue_hotkey)

    def _enqueue_hotkey(self) -> None:
        # Drop the event when received, not after an in-flight pipeline finishes.
        if self._state != State.PROCESSING:
            self._queue.put_nowait("hotkey")

    def _set_status(self, message: str) -> None:
        self.status = message
        if self._tray is not None:
            self._tray.set_status(message)

    def cancel_processing(self) -> None:
        self._loop.call_soon_threadsafe(self._cancel_processing)

    def _cancel_processing(self) -> None:
        if self._state != State.PROCESSING:
            return
        if self._side_effect_started:
            self._set_status("Действие уже началось; отменить его нельзя")
            return
        self._cancel_requested = True
        self._set_status("Отменено. Жду завершения фонового запроса")

    def copy_last(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "copy_last")

    def repaste_last(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "repaste_last")

    async def _recover_last(self, copy_only: bool) -> None:
        if self._state != State.IDLE:
            self._set_status("Повторить можно после завершения записи или обработки")
            return
        if not self.last_text:
            self._set_status("Сохранённого текста пока нет")
            return
        try:
            if copy_only:
                success = await asyncio.to_thread(self._paste.copy, self.last_text)
                self._set_status("Текст скопирован" if success else "Не удалось скопировать; текст сохранён")
            else:
                await self._deliver_text(self.last_text, self._last_target_hwnd)
        except Exception as exc:
            logger.error(f"Recovery error: {type(exc).__name__}")
            self._set_status("Не удалось восстановить текст; попробуй ещё раз")

    async def _deliver_text(self, text: str, hwnd: int) -> None:
        success = await asyncio.to_thread(self._paste.paste, text, hwnd)
        self._set_status(
            "Вставка отправлена. Текст доступен для повтора"
            if success else "Вставка не удалась. Текст сохранён — скопируй или повтори"
        )

    async def run(self) -> None:
        """Main event loop -- process hotkey events until shutdown.

        Exits when a 'shutdown' event is enqueued (e.g. on Ctrl+C in main.py).
        """
        logger.info(f"Controller running -- state: {self._state.name}")
        try:
            while True:
                event = await self._queue.get()
                if event == "shutdown":
                    logger.info("Shutdown signal received")
                    await self.finish_pending()
                    break
                if event == "hotkey":
                    if self._state == State.RECORDING:
                        self._processing_task = asyncio.create_task(self._stop_and_process())
                        # Let the task enter PROCESSING before consuming another event.
                        await asyncio.sleep(0)
                    else:
                        await self._handle_hotkey()
                elif event in {"copy_last", "repaste_last"}:
                    await self._recover_last(copy_only=event == "copy_last")
        except asyncio.CancelledError:
            pass

    async def _handle_hotkey(self) -> None:
        """Process a hotkey event according to current state."""
        if self._state == State.IDLE:
            await self._start_recording()
        elif self._state == State.RECORDING:
            await self._stop_and_process()
        elif self._state == State.PROCESSING:
            logger.debug("Hotkey ignored -- currently processing")

    async def _start_recording(self) -> None:
        """IDLE -> RECORDING: open mic stream, update state and tray."""
        logger.info("Recording started")

        if self.stt_provider == "local":
            self._stt_whisper.warmup()

        try:
            await asyncio.to_thread(self._recorder.start)
        except MicrophoneError as exc:
            logger.error(f"Cannot start recording: {exc}")
            self._set_status("Микрофон недоступен. Проверь подключение")
            return
        self._state = State.RECORDING
        self._recording_timeout = self._loop.call_later(
            MAX_RECORDING_DURATION_S,
            self._on_recording_timeout,
        )
        if self._tray is not None:
            self._tray.set_state(State.RECORDING)
        self._set_status("Запись")

    def _on_recording_timeout(self) -> None:
        if self._state != State.RECORDING:
            return
        logger.warning(
            f"Recording reached the {MAX_RECORDING_DURATION_S // 60}-minute safety limit; stopping automatically"
        )
        self._queue.put_nowait("hotkey")

    async def _stop_and_process(self) -> None:
        """RECORDING -> PROCESSING: run full STT -> LLM -> paste pipeline."""
        if self._recording_timeout is not None:
            self._recording_timeout.cancel()
            self._recording_timeout = None
        self._state = State.PROCESSING
        self._cancel_requested = False
        self._side_effect_started = False
        if self._tray is not None:
            self._tray.set_state(State.PROCESSING)
        self._set_status("Распознаю речь")

        # Capture active window HWND NOW -- while original app is still foreground.
        # REC-04: capture at recording stop, not at paste time.
        self._target_hwnd = capture_active_window()
        logger.info(f"Recording stopped -- target window HWND: {self._target_hwnd}")

        try:
            t0 = _time.perf_counter()

            # Stop audio capture
            audio: npt.NDArray[np.int16] = await asyncio.to_thread(self._recorder.stop)
            if self._cancel_requested:
                return
            raw_duration_s = len(audio) / 16_000
            t_stop = _time.perf_counter()
            logger.info(
                f"Audio captured: {raw_duration_s:.2f}s, {len(audio) * 2} bytes "
                f"[{t_stop - t0:.2f}s to stop mic]"
            )

            trimmed_audio = trim_silence(audio)
            trimmed_duration_s = len(trimmed_audio) / 16_000
            max_amp = int(np.abs(audio).max()) if audio.size else 0
            trimmed_ms = (raw_duration_s - trimmed_duration_s) * 1000.0
            logger.info(
                f"Trim diagnostic: raw={raw_duration_s:.2f}s "
                f"trimmed={trimmed_duration_s:.2f}s "
                f"saved={trimmed_ms:.0f}ms max_amp={max_amp}"
            )
            if not len(trimmed_audio):
                logger.info("Audio is silence after trimming -- nothing to transcribe")
                self._set_status("Речь не обнаружена. Можно повторить запись")
                return

            # STT + LLM cleanup — batch STT (streaming Chirp 3 is slower)
            audio_bytes = trimmed_audio.tobytes()
            raw_text = await self._transcribe(audio_bytes)
            t_stt = _time.perf_counter()
            logger.info(f"Batch STT done [{t_stt - t_stop:.2f}s]")

            if not raw_text:
                logger.info("STT returned empty -- nothing to paste")
                self._set_status("Не удалось распознать речь. Можно повторить запись")
                return

            self.last_raw_text = raw_text
            self.last_text = raw_text
            self._last_target_hwnd = self._target_hwnd
            if self._cancel_requested:
                return

            command_body = extract_cypher_body(raw_text)
            if command_body is not None:
                command = parse_cypher_command(raw_text)
                if command is None and self._cypher_planner is not None:
                    command = await asyncio.to_thread(self._cypher_planner.plan, command_body)
                if self._cancel_requested:
                    return
                if command is None:
                    logger.warning("Cypher command not understood")
                    self._set_status("Команда не распознана. Текст доступен для копирования")
                    return
                self._side_effect_started = True
                self._set_status("Выполняю команду")
                command_result = await asyncio.to_thread(self._cypher.execute, command)
                if command_result:
                    self.last_text = command_result
                    await self._deliver_text(command_result, self._target_hwnd)
                else:
                    self._set_status("Команда завершена")
                t_end = _time.perf_counter()
                logger.info(
                    f"CYPHER TOTAL: {t_end - t0:.2f}s "
                    f"(mic:{t_stop - t0:.2f} stt:{t_stt - t_stop:.2f} cmd:{t_end - t_stt:.2f})"
                )
                return

            cleanup_mode = self._resolve_cleanup_mode(trimmed_duration_s, raw_text)
            self._set_status("Оформляю текст")
            logger.info(
                f"Cleanup mode: {cleanup_mode} "
                f"(selected={self.mode}, speech={trimmed_duration_s:.2f}s, chars={len(raw_text)})"
            )

            if cleanup_mode == "full":
                clean_text = await asyncio.to_thread(self._llm.clean, raw_text)
                if not clean_text.strip():
                    clean_text = fast_clean(raw_text)
                    logger.warning("Gemini returned empty -- fell back to fast_clean")
                t_llm = _time.perf_counter()
                logger.info(f"Gemini cleanup [{t_llm - t_stt:.2f}s]")
            elif cleanup_mode == "fast":
                clean_text = fast_clean(raw_text)
                t_llm = _time.perf_counter()
                logger.info(f"Fast cleanup [{t_llm - t_stt:.3f}s]")
            else:
                clean_text = await asyncio.to_thread(self._llm_local.clean, raw_text)
                if not clean_text.strip():
                    clean_text = fast_clean(raw_text)
                t_llm = _time.perf_counter()
                logger.info(f"Local cleanup [{t_llm - t_stt:.2f}s]")

            # Paste into saved window
            self.last_text = clean_text
            if self._cancel_requested:
                return
            if self._log_transcripts:
                logger.debug(f"CLEANED text ({cleanup_mode}): {clean_text!r}")
            self._side_effect_started = True
            self._set_status("Отправляю вставку")
            await self._deliver_text(clean_text, self._target_hwnd)
            t_end = _time.perf_counter()
            logger.info(
                f"PIPELINE TOTAL: {t_end - t0:.2f}s "
                f"(mic:{t_stop - t0:.2f} stt:{t_stt - t_stop:.2f} "
                f"llm:{t_llm - t_stt:.2f} paste:{t_end - t_llm:.2f})"
            )

        except Exception as exc:
            logger.error(f"Pipeline error: {exc}")
            self._set_status("Ошибка обработки. Последний доступный текст можно скопировать")
        finally:
            self._state = State.IDLE
            if self._tray is not None:
                self._tray.set_state(State.IDLE)
            if self._cancel_requested:
                self._set_status("Отменено. Готов к записи; последний текст доступен в меню")
            else:
                self._set_status(self.status)
            logger.info("State: IDLE -- ready for next recording")

    async def _transcribe(self, audio_bytes: bytes) -> str:
        """Delegate transcription to the active STT provider.

        Local mode is whisper-only: local, free, offline. We no longer race
        Cloud Chirp on every utterance — that billed GCP on each dictation and
        was the source of mid-word splits ("пол ная") from joining Chirp result
        fragments. Cloud STT stays only as an explicit opt-in fallback when
        whisper returns nothing (rare), so local-first privacy is the default.

        Cloud mode (stt_provider='cloud') uses Chirp directly; raises
        RuntimeError if selected without GCP credentials.
        """
        if self.stt_provider == "local":
            local_text = await self._stt_whisper.recognize(audio_bytes)
            if not local_text and not self._cancel_requested and self._cloud_fallback_enabled and self._stt is not None:
                logger.warning("Local STT empty -- falling back to cloud once")
                return await self._stt.recognize(audio_bytes)
            return local_text
        if self._stt is None:
            raise RuntimeError(
                "Cloud STT selected but GCP credentials not configured. "
                "Set GOOGLE_APPLICATION_CREDENTIALS and GCP_PROJECT_ID in .env, "
                "or switch to local provider."
            )
        return await self._stt.recognize(audio_bytes)

    def shutdown(self) -> None:
        """Enqueue a shutdown event to stop the run() loop."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "shutdown")

    async def finish_pending(self) -> None:
        """Drain workers without cancelling to_thread and orphaning side effects."""
        self._cancel_processing()
        if self._processing_task is not None:
            await asyncio.shield(self._processing_task)
        if self._state == State.RECORDING:
            await asyncio.to_thread(self._recorder.stop)
            self._state = State.IDLE

    def close(self) -> None:
        """Release long-lived clients owned by the controller."""
        if self._recording_timeout is not None:
            self._recording_timeout.cancel()
            self._recording_timeout = None
        self._stt_whisper.shutdown()
        self._cypher.close()

    def warmup_local_stt(self) -> None:
        """Kick off local STT warmup/server bootstrap."""
        self._stt_whisper.warmup()

