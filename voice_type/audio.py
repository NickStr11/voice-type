"""Audio capture subsystem for VoiceType.

Records microphone input at 16kHz mono int16 — the native format for
the app's Google Cloud STT path. No resampling needed.

Key design decisions:
- channels=1 always: stereo recording fails with PortAudioError -9998 on
  mono-only microphones. Speech recognition has no benefit from stereo.
- device=None: use system default. Stable across mic changes (USB/BT/built-in).
  User sets preferred mic in Windows Sound settings, app follows.
- 0.1s permission check on startup: Windows 11 silently denies mic access.
  PortAudio returns -9999 (unanticipated host error) with no explanation.
  We translate this to actionable instructions before the user tries to record.
"""
from __future__ import annotations

import threading

import numpy as np
import numpy.typing as npt
import sounddevice as sd  # type: ignore[import-untyped]
from loguru import logger

SAMPLE_RATE: int = 16_000
CHANNELS: int = 1
DTYPE: str = "int16"
# Blocksize=0 lets PortAudio choose optimal buffer size for the device.
# Explicit blocksize causes "invalid frames per buffer" on some WASAPI devices.
BLOCKSIZE: int = 0
SILENCE_THRESHOLD: int = 200
SILENCE_PADDING_MS: int = 120


class MicrophoneError(Exception):
    """Raised when the microphone cannot be opened."""


def trim_silence(
    audio: npt.NDArray[np.int16],
    threshold: int = SILENCE_THRESHOLD,
    padding_ms: int = SILENCE_PADDING_MS,
) -> npt.NDArray[np.int16]:
    """Trim leading and trailing silence with a conservative amplitude gate.

    Returns an empty array if nothing crosses the threshold. Padding keeps
    plosive consonants and short breaths near the cut points.
    """
    if audio.size == 0:
        return audio

    active = np.flatnonzero(np.abs(audio) >= threshold)
    if active.size == 0:
        return np.zeros(0, dtype=np.int16)

    pad_samples = int(SAMPLE_RATE * padding_ms / 1000)
    start = max(int(active[0]) - pad_samples, 0)
    end = min(int(active[-1]) + pad_samples + 1, audio.size)
    return audio[start:end]


def check_microphone_access() -> None:
    """Attempt to open a brief test stream to verify microphone access.

    Call this once at app startup, before showing the tray icon.
    Raises MicrophoneError with human-readable instructions on failure.

    Raises:
        MicrophoneError: If microphone access is denied or unavailable.
    """
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
        ):
            # Successfully opened — mic is accessible. Read nothing.
            pass
    except sd.PortAudioError as exc:
        # Error code -9999 is PortAudio's "unanticipated host error" —
        # on Windows 11, this is the symptom of microphone permission denial.
        err_str = str(exc)
        if "-9999" in err_str or "unanticipated host error" in err_str.lower():
            raise MicrophoneError(
                "Microphone permission denied.\n"
                "To fix: Settings → Privacy & Security → Microphone\n"
                "        → enable 'Let desktop apps access your microphone'"
            ) from exc
        raise MicrophoneError(
            f"Could not open microphone: {exc}\n"
            "Check that a microphone is connected and not used exclusively "
            "by another app (e.g. a video call)."
        ) from exc


class AudioRecorder:
    """Captures audio from the default microphone as a numpy int16 array.

    Usage:
        recorder = AudioRecorder()
        recorder.start()
        # ... time passes while user speaks ...
        audio: np.ndarray = recorder.stop()
        audio_bytes: bytes = audio.tobytes()  # ready for GCP STT LINEAR16

    """

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[npt.NDArray[np.int16]] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        """Open the microphone stream and begin buffering audio.

        Raises:
            RuntimeError: If recording is already in progress.
            MicrophoneError: If the mic cannot be opened (translates PortAudioError).
        """
        with self._lock:
            if self._stream is not None:
                raise RuntimeError("AudioRecorder.start() called while already recording")
            self._chunks = []

        def _callback(
            indata: npt.NDArray[np.int16],
            frames: int,
            time: object,  # sd.CallbackFlags doesn't export well
            status: sd.CallbackFlags,
        ) -> None:
            # Copy is essential — indata is a view into PortAudio's ring buffer.
            with self._lock:
                self._chunks.append(indata.copy())

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCKSIZE,
                device=None,
                callback=_callback,
            )
            stream.start()
        except sd.PortAudioError as exc:
            err_str = str(exc)
            if "-9999" in err_str or "unanticipated host error" in err_str.lower():
                raise MicrophoneError(
                    "Microphone permission denied.\n"
                    "To fix: Settings → Privacy & Security → Microphone\n"
                    "        → enable 'Let desktop apps access your microphone'"
                ) from exc
            raise MicrophoneError(
                f"Could not start recording: {exc}"
            ) from exc

        with self._lock:
            self._stream = stream

    def stop(self) -> npt.NDArray[np.int16]:
        """Stop recording and return all captured audio as a contiguous array.

        Returns:
            numpy array of int16 samples at 16kHz mono.
            Shape: (N,) where N = total samples captured.
            Call .tobytes() to get LINEAR16 bytes for GCP STT.

        Raises:
            RuntimeError: If recording was never started.
        """
        with self._lock:
            if self._stream is None:
                raise RuntimeError("AudioRecorder.stop() called without a prior start()")
            stream = self._stream

        # PortAudio teardown is best-effort: even if stop()/close() raise
        # (driver state, device disconnect mid-record, USB hot-unplug), we
        # MUST clear our internal pointers so the next start() works.
        # Otherwise the recorder gets wedged into a "already recording"
        # state and every subsequent toggle fails.
        try:
            stream.stop()
        except Exception as exc:
            logger.warning(f"PortAudio stop() raised, ignoring: {exc}")
        try:
            stream.close()
        except Exception as exc:
            logger.warning(f"PortAudio close() raised, ignoring: {exc}")

        with self._lock:
            self._stream = None
            chunks = list(self._chunks)
            self._chunks = []

        if not chunks:
            # Edge case: stopped immediately after start, before any callback fired.
            return np.zeros(0, dtype=np.int16)

        # concatenate along axis 0; each chunk shape is (frames, 1) → flatten to (N,)
        combined: npt.NDArray[np.int16] = np.concatenate(chunks, axis=0).flatten()
        return combined
