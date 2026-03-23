"""VoiceType entry point -- Phase 2.

Startup sequence:
    1. Load config from .env (exits 1 if config invalid -- SYS-03)
    2. Check microphone access (exits 1 with clear error if denied -- SYS-02)
    3. Create asyncio event loop
    4. Create TrayIcon with quit callback (SYS-01)
    5. Create AppController with tray reference
    6. Start hotkey listener in daemon thread
    7. Start tray icon via run_detached() -- non-blocking
    8. Run asyncio loop until shutdown
    9. Clean shutdown: stop hotkey, stop tray, close loop

Threading model:
    - Main thread: asyncio event loop (controller.run())
    - Daemon thread: pynput hotkey listener (HotkeyListener)
    - Daemon thread: pystray icon (run_detached manages its own thread)
    - PortAudio callback thread: managed by sounddevice internally

Ctrl+C fix:
    Phase 1 had a cosmetic RuntimeError from asyncio Queue.get being
    cancelled mid-await on KeyboardInterrupt. Fix: wrap loop.run_until_complete
    in try/except KeyboardInterrupt, then call controller.shutdown() to
    enqueue the 'shutdown' event so controller.run() exits cleanly.
"""
from __future__ import annotations

import asyncio
import sys

from loguru import logger

from voice_type.audio import MicrophoneError, check_microphone_access
from voice_type.config import load_config
from voice_type.controller import AppController
from voice_type.tray import TrayIcon


def main() -> None:
    """Entry point for `uv run voice-type` or `python -m voice_type.main`."""

    # Step 1: Load configuration -- exits 1 on bad config (SYS-03)
    config = load_config()
    logger.info(f"Config loaded -- hotkey: {config.hotkey}, project: {config.gcp_project_id}")

    # Step 2: Microphone access check -- exits 1 with clear instructions (SYS-02)
    logger.info("Checking microphone access...")
    try:
        check_microphone_access()
        logger.info("Microphone: OK")
    except MicrophoneError as exc:
        logger.error(f"Microphone check failed:\n{exc}")
        sys.exit(1)

    # Step 3: Create asyncio event loop on the main thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Step 4: Create tray icon (SYS-01, REC-03)
    # on_quit enqueues 'shutdown' into the controller queue -- same path as Ctrl+C.
    # The lambda captures controller by reference; controller is created next.
    controller_ref: list[AppController] = []  # mutable container for forward reference

    def on_quit() -> None:
        if controller_ref:
            controller_ref[0].shutdown()

    tray = TrayIcon(on_quit=on_quit)

    # Step 5: Create controller with tray reference
    controller = AppController(config, loop, tray=tray)
    controller_ref.append(controller)

    # Step 6: Start hotkey listener in daemon thread
    controller.start_hotkey_listener()

    # Step 7: Start tray icon -- non-blocking, runs in its own daemon thread
    tray.run_detached()

    logger.info(f"VoiceType ready -- press {config.hotkey} to start/stop recording")
    logger.info("Tray icon active -- right-click tray icon to quit, or press Ctrl+C")

    # Step 8: Run until shutdown (Ctrl+C or tray quit)
    try:
        loop.run_until_complete(controller.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt -- shutting down")
        # Enqueue shutdown event so controller.run() exits cleanly
        # (avoids RuntimeError from Queue.get being interrupted mid-await)
        controller.shutdown()
    finally:
        # Step 9: Clean shutdown
        controller.stop_hotkey_listener()
        tray.stop()
        # Drain any remaining queued events before closing the loop
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
        logger.info("VoiceType stopped")


if __name__ == "__main__":
    main()
