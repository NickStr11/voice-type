"""AppController — state machine that orchestrates the full recording pipeline.

State machine:
    IDLE -> (hotkey) -> RECORDING -> (hotkey) -> PROCESSING -> IDLE
                                                  ^
                                (hotkey during PROCESSING is ignored)

Thread safety:
    on_hotkey() is called from pynput's listener thread via
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
from typing import Optional

import numpy as np
import numpy.typing as npt
from loguru import logger

from voice_type.audio import AudioRecorder, MicrophoneError
from voice_type.config import AppConfig
from voice_type.hotkey import HotkeyListener
from voice_type.llm import LLMClient
from voice_type.paste import PasteService
from voice_type.states import State
from voice_type.stt import STTClient
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
        tray: Optional[TrayIcon] = None,
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
        self._stt = STTClient(config)
        self._llm = LLMClient()
        self._paste = PasteService()

    def start_hotkey_listener(self) -> None:
        """Start the pynput hotkey listener in a daemon thread."""
        self._hotkey_listener.start()
        logger.info(f"Hotkey listener started -- hotkey: {self._config.hotkey}")

    def stop_hotkey_listener(self) -> None:
        """Stop the hotkey listener. Safe to call multiple times."""
        self._hotkey_listener.stop()

    def _on_hotkey_from_thread(self) -> None:
        """Callback fired from pynput's listener thread.

        Bridges the pynput thread to the asyncio event loop via
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
            # Stop audio capture
            audio: npt.NDArray[np.int16] = await asyncio.to_thread(self._recorder.stop)
            audio_bytes = audio.tobytes()
            duration_s = len(audio) / 16_000
            logger.info(f"Audio: {duration_s:.2f}s, {len(audio_bytes)} bytes")

            # STT -- async coroutine (already runs to_thread internally)
            raw_text = await self._stt.recognize(audio_bytes)
            if not raw_text:
                logger.info("STT returned empty transcript -- nothing to paste")
                return

            # LLM cleanup -- sync with internal wall-clock timeout; run in thread
            clean_text = await asyncio.to_thread(self._llm.clean, raw_text)
            # Safety guard: if LLM returned empty string, use raw STT text
            if not clean_text.strip():
                clean_text = raw_text
                logger.warning("LLM returned empty text -- using raw STT output")

            # Paste into saved window
            await asyncio.to_thread(self._paste.paste, clean_text, self._target_hwnd)

        except Exception as exc:
            logger.error(f"Pipeline error: {exc}")
        finally:
            self._state = State.IDLE
            if self._tray is not None:
                self._tray.set_state(State.IDLE)
            logger.info("State: IDLE -- ready for next recording")

    def shutdown(self) -> None:
        """Enqueue a shutdown event to stop the run() loop."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "shutdown")
