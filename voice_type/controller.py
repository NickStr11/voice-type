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
from voice_type.hotkey import HotkeyListener
from voice_type.llm import LLMClient
from voice_type.llm_local import LocalLLMClient
from voice_type.paste import PasteService
from voice_type.states import State
from voice_type.stt import STTClient
from voice_type.stt_whisper import WhisperSTTClient
from voice_type.tray import TrayIcon
from voice_type.window import capture_active_window


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

        # Pipeline components -- initialized once, reused per recording
        self._stt = STTClient(config) if config.gcp_credentials_path is not None else None
        self._stt_whisper = WhisperSTTClient(config)
        self._llm = LLMClient(project=config.gcp_project_id)
        self._paste = PasteService()
        self._llm_local = LocalLLMClient()
        self.mode: str = "auto"  # "auto" | "fast" | "local" | "full"
        self.stt_provider: str = config.stt_provider  # "cloud" | "local"

    def _resolve_cleanup_mode(self, duration_s: float, raw_text: str) -> str:
        """Select cleanup mode for the current utterance."""
        if self.mode != "auto":
            return self.mode

        if duration_s <= 6.0 or len(raw_text) <= 220:
            return "fast"

        return "full"

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
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "hotkey")

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
                    break
                if event == "hotkey":
                    await self._handle_hotkey()
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

        try:
            await asyncio.to_thread(self._recorder.start)
        except MicrophoneError as exc:
            logger.error(f"Cannot start recording: {exc}")
            return
        self._state = State.RECORDING
        if self._tray is not None:
            self._tray.set_state(State.RECORDING)

    async def _stop_and_process(self) -> None:
        """RECORDING -> PROCESSING: run full STT -> LLM -> paste pipeline."""
        self._state = State.PROCESSING
        if self._tray is not None:
            self._tray.set_state(State.PROCESSING)

        # Capture active window HWND NOW -- while original app is still foreground.
        # REC-04: capture at recording stop, not at paste time.
        self._target_hwnd = capture_active_window()
        logger.info(f"Recording stopped -- target window HWND: {self._target_hwnd}")

        try:
            t0 = _time.perf_counter()

            # Stop audio capture
            audio: npt.NDArray[np.int16] = await asyncio.to_thread(self._recorder.stop)
            raw_duration_s = len(audio) / 16_000
            t_stop = _time.perf_counter()
            logger.info(
                f"Audio captured: {raw_duration_s:.2f}s, {len(audio) * 2} bytes "
                f"[{t_stop - t0:.2f}s to stop mic]"
            )

            trimmed_audio = trim_silence(audio)
            trimmed_duration_s = len(trimmed_audio) / 16_000
            if len(trimmed_audio) != len(audio):
                logger.info(f"Trimmed silence: {raw_duration_s:.2f}s -> {trimmed_duration_s:.2f}s")
            if not len(trimmed_audio):
                logger.info("Audio is silence after trimming -- nothing to transcribe")
                return

            # STT + LLM cleanup — batch STT (streaming Chirp 3 is slower)
            audio_bytes = trimmed_audio.tobytes()
            raw_text = await self._transcribe(audio_bytes)
            t_stt = _time.perf_counter()
            logger.info(f"Batch STT done [{t_stt - t_stop:.2f}s]")

            if not raw_text:
                logger.info("STT returned empty -- nothing to paste")
                return

            cleanup_mode = self._resolve_cleanup_mode(trimmed_duration_s, raw_text)
            logger.info(
                f"Cleanup mode: {cleanup_mode} "
                f"(selected={self.mode}, speech={trimmed_duration_s:.2f}s, chars={len(raw_text)})"
            )

            if cleanup_mode == "full":
                clean_text = await asyncio.to_thread(self._llm.clean, raw_text)
                if not clean_text.strip():
                    clean_text = raw_text
                    logger.warning("LLM returned empty -- using raw STT")
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
            await asyncio.to_thread(self._paste.paste, clean_text, self._target_hwnd)
            t_end = _time.perf_counter()
            logger.info(
                f"PIPELINE TOTAL: {t_end - t0:.2f}s "
                f"(mic:{t_stop - t0:.2f} stt:{t_stt - t_stop:.2f} "
                f"llm:{t_llm - t_stt:.2f} paste:{t_end - t_llm:.2f})"
            )

        except Exception as exc:
            logger.error(f"Pipeline error: {exc}")
        finally:
            self._state = State.IDLE
            if self._tray is not None:
                self._tray.set_state(State.IDLE)
            logger.info("State: IDLE -- ready for next recording")

    async def _transcribe(self, audio_bytes: bytes) -> str:
        """Delegate transcription to the active STT provider.

        Routes to WhisperSTTClient when stt_provider is 'local', or to
        STTClient when 'cloud'. Raises RuntimeError if cloud is selected
        but GCP credentials were not configured.
        """
        if self.stt_provider == "local":
            return await self._stt_whisper.recognize(audio_bytes)
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
