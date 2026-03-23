"""AppController — state machine that orchestrates recording lifecycle.

State machine:
    IDLE → (hotkey) → RECORDING → (hotkey) → PROCESSING → IDLE
                                                ↑
                              (hotkey during PROCESSING is ignored)

Thread safety:
    on_hotkey() is called from pynput's listener thread via
    loop.call_soon_threadsafe(). All state transitions happen inside
    the asyncio event loop — no locks needed for state itself.

Phase 1 scope:
    This controller captures audio and the active window HWND, then logs
    the result. STT → LLM → paste pipeline is added in Phase 2 by
    extending _process() with the actual pipeline calls.
"""
from __future__ import annotations

import asyncio
import sys
from enum import Enum, auto
from typing import Optional

import numpy.typing as npt
import numpy as np
from loguru import logger

from voice_type.audio import AudioRecorder, MicrophoneError
from voice_type.config import AppConfig
from voice_type.hotkey import HotkeyListener
from voice_type.window import capture_active_window


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()


class AppController:
    """Orchestrates the recording lifecycle.

    Usage (from main.py):
        loop = asyncio.new_event_loop()
        controller = AppController(config, loop)
        controller.start_hotkey_listener()
        loop.run_until_complete(controller.run())
    """

    def __init__(self, config: AppConfig, loop: asyncio.AbstractEventLoop) -> None:
        self._config = config
        self._loop = loop
        self._state = State.IDLE
        self._recorder = AudioRecorder()
        self._hotkey_listener = HotkeyListener(config, self._on_hotkey_from_thread)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        # HWND captured at recording stop — passed to Phase 2 paste service
        self._target_hwnd: int = 0

    def start_hotkey_listener(self) -> None:
        """Start the pynput hotkey listener in a daemon thread.

        Call before loop.run_until_complete(controller.run()).
        """
        self._hotkey_listener.start()
        logger.info(f"Hotkey listener started — hotkey: {self._config.hotkey}")

    def stop_hotkey_listener(self) -> None:
        """Stop the hotkey listener. Safe to call multiple times."""
        self._hotkey_listener.stop()

    def _on_hotkey_from_thread(self) -> None:
        """Callback fired from pynput's listener thread.

        Bridges the pynput thread to the asyncio event loop via
        call_soon_threadsafe — the only safe way to enqueue work
        from a non-asyncio thread into an asyncio loop.
        """
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "hotkey")

    async def run(self) -> None:
        """Main event loop — process hotkey events until shutdown.

        Exits when a "shutdown" event is enqueued (e.g. on Ctrl+C in main.py).
        """
        logger.info(f"Controller running — state: {self._state.name}")
        while True:
            event = await self._queue.get()
            if event == "shutdown":
                logger.info("Shutdown signal received")
                break
            if event == "hotkey":
                await self._handle_hotkey()

    async def _handle_hotkey(self) -> None:
        """Process a hotkey event according to current state."""
        if self._state == State.IDLE:
            await self._start_recording()
        elif self._state == State.RECORDING:
            await self._stop_and_process()
        elif self._state == State.PROCESSING:
            # Ignore hotkey while processing — prevents double-recording
            logger.debug("Hotkey ignored — currently processing")

    async def _start_recording(self) -> None:
        """IDLE → RECORDING: open mic stream, update state."""
        logger.info("Recording started")
        try:
            # Recording runs in asyncio.to_thread to avoid blocking the event loop.
            # AudioRecorder.start() opens the stream (fast) and returns immediately;
            # the audio callback fires on PortAudio's own thread.
            await asyncio.to_thread(self._recorder.start)
        except MicrophoneError as exc:
            logger.error(f"Cannot start recording: {exc}")
            # Stay in IDLE — do not transition
            return
        self._state = State.RECORDING

    async def _stop_and_process(self) -> None:
        """RECORDING → PROCESSING: stop mic, capture HWND, process audio."""
        self._state = State.PROCESSING

        # Capture active window HWND NOW — while original app is still foreground.
        # This is REC-04: capture at recording stop, not at paste time.
        # If user switches windows during STT processing, we still paste into the
        # original window by restoring focus via SetForegroundWindow in Phase 2.
        self._target_hwnd = capture_active_window()
        logger.info(f"Recording stopped — target window HWND: {self._target_hwnd}")

        try:
            audio: npt.NDArray[np.int16] = await asyncio.to_thread(self._recorder.stop)
        except Exception as exc:
            logger.error(f"Error stopping recorder: {exc}")
            self._state = State.IDLE
            return

        sample_count = len(audio)
        duration_s = sample_count / 16_000
        audio_bytes = audio.tobytes()
        logger.info(
            f"Audio captured: {sample_count} samples, "
            f"{duration_s:.2f}s, {len(audio_bytes)} bytes — "
            f"ready for STT (Phase 2)"
        )

        # Phase 2 will replace this block with:
        #   raw_text = await stt_client.recognize(audio_bytes)
        #   clean_text = await llm_client.clean(raw_text)
        #   await paste_service.paste(clean_text, self._target_hwnd)
        logger.info(
            f"[Phase 1 stub] Would paste into HWND {self._target_hwnd}. "
            "STT + LLM + paste not yet implemented."
        )

        self._state = State.IDLE
        logger.info("State: IDLE — ready for next recording")

    def shutdown(self) -> None:
        """Enqueue a shutdown event to stop the run() loop."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, "shutdown")
