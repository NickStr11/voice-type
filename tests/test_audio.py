"""Tests for voice_type.audio — AudioRecorder and check_microphone_access.

These tests use mocks so no real microphone hardware is required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import threading
import time

import numpy as np
import pytest

from voice_type.audio import (
    AudioRecorder,
    MicrophoneError,
    check_microphone_access,
    SAMPLE_RATE,
    CHANNELS,
    DTYPE,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestAudioConstants:
    def test_sample_rate_is_16000(self) -> None:
        assert SAMPLE_RATE == 16_000

    def test_channels_is_1(self) -> None:
        assert CHANNELS == 1

    def test_dtype_is_int16(self) -> None:
        assert DTYPE == "int16"


# ---------------------------------------------------------------------------
# check_microphone_access
# ---------------------------------------------------------------------------

class TestCheckMicrophoneAccess:
    def test_succeeds_when_stream_opens(self) -> None:
        """No exception raised when InputStream opens cleanly."""
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)

        with patch("sounddevice.InputStream", return_value=mock_stream):
            # Should not raise
            check_microphone_access()

    def test_raises_microphone_error_on_permission_denied_9999(self) -> None:
        """PortAudio error -9999 becomes MicrophoneError with privacy settings path."""
        import sounddevice as sd

        err = sd.PortAudioError("Error opening InputStream: [Errno -9999] Unanticipated host error")

        with patch("sounddevice.InputStream", side_effect=err):
            with pytest.raises(MicrophoneError) as exc_info:
                check_microphone_access()

        msg = str(exc_info.value)
        assert "permission denied" in msg.lower() or "Permission denied" in msg
        assert "Privacy" in msg or "Privacy & Security" in msg

    def test_raises_microphone_error_on_unanticipated_host_error_text(self) -> None:
        """'unanticipated host error' text (no code) also triggers permission message."""
        import sounddevice as sd

        err = sd.PortAudioError("unanticipated host error")

        with patch("sounddevice.InputStream", side_effect=err):
            with pytest.raises(MicrophoneError) as exc_info:
                check_microphone_access()

        assert "Privacy" in str(exc_info.value)

    def test_raises_microphone_error_on_other_port_audio_error(self) -> None:
        """Other PortAudioError codes raise MicrophoneError with device-check message."""
        import sounddevice as sd

        err = sd.PortAudioError("Error opening InputStream: [Errno -9998] Invalid number of channels")

        with patch("sounddevice.InputStream", side_effect=err):
            with pytest.raises(MicrophoneError) as exc_info:
                check_microphone_access()

        msg = str(exc_info.value)
        # Should NOT say "permission denied" — different error
        assert "permission" not in msg.lower() or "another app" in msg.lower()
        # Should say something about checking microphone/device
        assert "microphone" in msg.lower() or "device" in msg.lower() or "app" in msg.lower()

    def test_uses_correct_stream_parameters(self) -> None:
        """check_microphone_access opens stream with samplerate=16000, channels=1, dtype=int16."""
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)

        with patch("sounddevice.InputStream", return_value=mock_stream) as mock_input_stream:
            check_microphone_access()

        mock_input_stream.assert_called_once()
        kwargs = mock_input_stream.call_args.kwargs
        assert kwargs.get("samplerate") == 16_000
        assert kwargs.get("channels") == 1
        assert kwargs.get("dtype") == "int16"


# ---------------------------------------------------------------------------
# AudioRecorder state guards
# ---------------------------------------------------------------------------

class TestAudioRecorderStateGuards:
    def test_stop_without_start_raises_runtime_error(self) -> None:
        """stop() on a fresh recorder raises RuntimeError."""
        r = AudioRecorder()
        with pytest.raises(RuntimeError, match="without a prior start"):
            r.stop()

    def test_double_start_raises_runtime_error(self) -> None:
        """Calling start() twice raises RuntimeError."""
        mock_stream = MagicMock()
        mock_stream.start = MagicMock()

        with patch("sounddevice.InputStream", return_value=mock_stream):
            r = AudioRecorder()
            r.start()
            with pytest.raises(RuntimeError, match="already recording"):
                r.start()

        # Clean up
        with patch("sounddevice.InputStream", return_value=mock_stream):
            mock_stream.stop = MagicMock()
            mock_stream.close = MagicMock()
            r._stream = mock_stream
            r._chunks = []
            r._stream = None  # force stop path to not crash


# ---------------------------------------------------------------------------
# AudioRecorder start/stop with mock stream
# ---------------------------------------------------------------------------

class TestAudioRecorderStartStop:
    def _make_mock_stream(self) -> MagicMock:
        s = MagicMock()
        s.start = MagicMock()
        s.stop = MagicMock()
        s.close = MagicMock()
        return s

    def test_start_opens_stream_with_correct_params(self) -> None:
        """start() calls InputStream with samplerate=16000, channels=1, dtype=int16."""
        mock_stream = self._make_mock_stream()

        with patch("sounddevice.InputStream", return_value=mock_stream) as mock_cls:
            r = AudioRecorder()
            r.start()

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args.kwargs
        assert kwargs.get("samplerate") == 16_000
        assert kwargs.get("channels") == 1
        assert kwargs.get("dtype") == "int16"
        assert kwargs.get("device") is None
        mock_stream.start.assert_called_once()

    def test_stop_returns_empty_array_when_no_callbacks_fired(self) -> None:
        """stop() with no audio data returns empty int16 array."""
        mock_stream = self._make_mock_stream()

        with patch("sounddevice.InputStream", return_value=mock_stream):
            r = AudioRecorder()
            r.start()

        result = r.stop()

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_stop_returns_int16_array_with_correct_dtype(self) -> None:
        """stop() returns array with dtype=numpy.int16."""
        mock_stream = self._make_mock_stream()
        captured_callback: list = []

        def fake_input_stream(**kwargs):  # type: ignore[misc]
            captured_callback.append(kwargs.get("callback"))
            return mock_stream

        with patch("sounddevice.InputStream", side_effect=fake_input_stream):
            r = AudioRecorder()
            r.start()

        # Simulate callback firing with some fake audio data
        callback = captured_callback[0]
        fake_chunk = np.zeros((1024, 1), dtype=np.int16)
        callback(fake_chunk, 1024, None, MagicMock())

        result = r.stop()

        assert result.dtype == np.int16

    def test_stop_concatenates_multiple_chunks(self) -> None:
        """stop() concatenates all chunks from multiple callbacks into one array."""
        mock_stream = self._make_mock_stream()
        captured_callback: list = []

        def fake_input_stream(**kwargs):  # type: ignore[misc]
            captured_callback.append(kwargs.get("callback"))
            return mock_stream

        with patch("sounddevice.InputStream", side_effect=fake_input_stream):
            r = AudioRecorder()
            r.start()

        callback = captured_callback[0]
        # Simulate 3 callbacks with known data
        chunk1 = np.array([[1], [2], [3]], dtype=np.int16)  # shape (3, 1)
        chunk2 = np.array([[4], [5]], dtype=np.int16)        # shape (2, 1)
        chunk3 = np.array([[6]], dtype=np.int16)             # shape (1, 1)

        callback(chunk1, 3, None, MagicMock())
        callback(chunk2, 2, None, MagicMock())
        callback(chunk3, 1, None, MagicMock())

        result = r.stop()

        # Should be flattened: [1, 2, 3, 4, 5, 6]
        assert result.dtype == np.int16
        assert len(result) == 6
        np.testing.assert_array_equal(result, np.array([1, 2, 3, 4, 5, 6], dtype=np.int16))

    def test_tobytes_produces_linear16_bytes(self) -> None:
        """The returned array's .tobytes() produces correct LINEAR16 byte sequence."""
        mock_stream = self._make_mock_stream()
        captured_callback: list = []

        def fake_input_stream(**kwargs):  # type: ignore[misc]
            captured_callback.append(kwargs.get("callback"))
            return mock_stream

        with patch("sounddevice.InputStream", side_effect=fake_input_stream):
            r = AudioRecorder()
            r.start()

        callback = captured_callback[0]
        # Known value: int16 value 256 = 0x0100 in little-endian = bytes 00 01
        chunk = np.array([[256]], dtype=np.int16)
        callback(chunk, 1, None, MagicMock())

        result = r.stop()
        raw_bytes = result.tobytes()

        # int16 little-endian: 256 = 0x0100 → b'\x00\x01'
        assert raw_bytes == b"\x00\x01"

    def test_callback_copies_indata(self) -> None:
        """Callback must copy indata to avoid ring buffer aliasing."""
        mock_stream = self._make_mock_stream()
        captured_callback: list = []

        def fake_input_stream(**kwargs):  # type: ignore[misc]
            captured_callback.append(kwargs.get("callback"))
            return mock_stream

        with patch("sounddevice.InputStream", side_effect=fake_input_stream):
            r = AudioRecorder()
            r.start()

        callback = captured_callback[0]
        chunk = np.array([[100], [200]], dtype=np.int16)
        callback(chunk, 2, None, MagicMock())

        # Mutate original — if copied correctly, stored chunk should be unchanged
        chunk[0, 0] = 999

        result = r.stop()
        # First sample should still be 100, not 999
        assert result[0] == 100

    def test_start_translates_permission_error_9999(self) -> None:
        """PortAudioError -9999 in start() raises MicrophoneError with privacy path."""
        import sounddevice as sd

        err = sd.PortAudioError("[Errno -9999] Unanticipated host error")

        with patch("sounddevice.InputStream", side_effect=err):
            r = AudioRecorder()
            with pytest.raises(MicrophoneError) as exc_info:
                r.start()

        assert "Privacy" in str(exc_info.value)
