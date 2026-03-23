"""VoiceType entry point.

Startup sequence:
    1. Load config from .env (exits 1 if config invalid — SYS-03)
    2. Check microphone access (exits 1 with clear error if denied — SYS-02)
    3. Start AppController with asyncio event loop
    4. Start hotkey listener in daemon thread
    5. Run asyncio loop until Ctrl+C (KeyboardInterrupt)

Phase 1 note:
    No system tray icon in Phase 1 — this is added in Phase 2 (SYS-01, REC-03).
    App runs in terminal with loguru output to stdout.
    pystray is installed but not used yet.

Threading model:
    - Main thread: asyncio event loop (controller.run())
    - Daemon thread: pynput hotkey listener (HotkeyListener)
    - PortAudio callback thread: managed by sounddevice internally

    This is the simplest correct threading model for Phase 1.
    Phase 2 adds pystray in a third daemon thread via run_detached().
"""
from __future__ import annotations

import asyncio
import sys

from loguru import logger

from voice_type.audio import MicrophoneError, check_microphone_access
from voice_type.config import load_config
from voice_type.controller import AppController


def main() -> None:
    """Entry point for `uv run voice-type` or `python -m voice_type.main`."""

    # Step 1: Load configuration — exits 1 on bad config (SYS-03)
    config = load_config()
    logger.info(f"Config loaded — hotkey: {config.hotkey}, project: {config.gcp_project_id}")

    # Step 2: Microphone access check — exits 1 with clear instructions (SYS-02)
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

    # Step 4: Create controller and start hotkey listener
    controller = AppController(config, loop)
    controller.start_hotkey_listener()

    logger.info(f"VoiceType ready — press {config.hotkey} to start/stop recording")
    logger.info("Press Ctrl+C to quit")

    # Step 5: Run until Ctrl+C
    try:
        loop.run_until_complete(controller.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down")
    finally:
        controller.stop_hotkey_listener()
        loop.close()
        logger.info("VoiceType stopped")


if __name__ == "__main__":
    main()
