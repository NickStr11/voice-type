"""Local Whisper STT backend via whisper.cpp server with CLI fallback.

Primary path:
- whisper-server.exe with Vulkan GPU on AMD RX 7800 XT.
- Model stays resident in memory, so hot requests are ~200-300ms instead of
  ~1.3s via subprocess-per-request CLI.
- Server starts in the background and stays on 127.0.0.1:8178.

Fallback path:
- whisper-cli.exe with Vulkan GPU, retry once.
- If GPU fails, final fallback is CPU (--no-gpu).

Notes:
- Current runtime build is whisper.cpp v1.8.4; server no_context is already on
  by default, so there is no -nc CLI flag here.
- GGML_NO_BACKTRACE=1 is required for the MinGW build on this machine.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import BinaryIO
from urllib import request

from loguru import logger

from voice_type.config import AppConfig

_PROJECT_ROOT = Path(__file__).parent.parent
_WHISPER_DIR = _PROJECT_ROOT / "runtime" / "whisper-cpp"
_CLI_EXE = _WHISPER_DIR / "whisper-cli.exe"
_SERVER_EXE = _WHISPER_DIR / "whisper-server.exe"
_MODEL_DIR = _WHISPER_DIR / "model"
_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 8178
_SERVER_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"
_SERVER_TIMEOUT_S = 60.0
_SERVER_READY_TIMEOUT_S = 25.0


class WhisperSTTClient:
    """Local Whisper STT backend with server-first strategy."""

    def __init__(self, config: AppConfig) -> None:
        self._model_name = config.whisper_model
        self._model_path = _MODEL_DIR / f"ggml-{self._model_name}.bin"
        self._server_ready = threading.Event()
        self._server_lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._server_process: subprocess.Popen[bytes] | None = None
        self._server_managed = False
        self._server_available = False
        self._server_stdout_handle: BinaryIO | None = None
        self._server_stderr_handle: BinaryIO | None = None
        self._server_start_error: str | None = None

        if not _SERVER_EXE.exists() or not self._model_path.exists():
            self._server_ready.set()
            logger.warning("Whisper server unavailable at startup — CLI fallback only")
        else:
            self._ensure_server_background()

        logger.info(f"WhisperSTTClient ready (model={self._model_name}, server preferred)")

    def warmup(self) -> None:
        """Ensure server startup is in progress."""
        self._ensure_server_background()

    def _ensure_server_background(self) -> None:
        if self._server_ready.is_set() and self._server_available:
            return

        with self._server_lock:
            if self._server_thread is not None and self._server_thread.is_alive():
                return
            self._server_ready.clear()
            self._server_thread = threading.Thread(
                target=self._start_server_worker,
                name="whisper-server-start",
                daemon=True,
            )
            self._server_thread.start()

    def _start_server_worker(self) -> None:
        try:
            if self._server_healthcheck():
                self._server_available = True
                self._server_managed = False
                self._server_start_error = None
                logger.info("Whisper server already running — reusing existing process")
                return

            if not _SERVER_EXE.exists():
                self._server_start_error = f"whisper-server.exe not found at {_SERVER_EXE}"
                logger.warning(self._server_start_error)
                return
            if not self._model_path.exists():
                self._server_start_error = f"Whisper model not found at {self._model_path}"
                logger.warning(self._server_start_error)
                return

            process = self._launch_server_process()
            self._server_process = process
            self._server_managed = True
            deadline = time.perf_counter() + _SERVER_READY_TIMEOUT_S

            while time.perf_counter() < deadline:
                if process.poll() is not None:
                    self._server_start_error = f"whisper-server exited early with code {process.returncode}"
                    logger.error(self._server_start_error)
                    return
                if self._server_healthcheck():
                    self._server_available = True
                    self._server_start_error = None
                    logger.info("Whisper server ready")
                    return
                time.sleep(0.25)

            self._server_start_error = "whisper-server did not become healthy in time"
            logger.error(self._server_start_error)
            self._stop_server_process()
        finally:
            self._server_ready.set()

    def _launch_server_process(self) -> subprocess.Popen[bytes]:
        stdout_path = _WHISPER_DIR / "whisper-server.out.log"
        stderr_path = _WHISPER_DIR / "whisper-server.err.log"
        self._server_stdout_handle = open(stdout_path, "ab")
        self._server_stderr_handle = open(stderr_path, "ab")

        env = {
            **os.environ,
            "PATH": f"{_WHISPER_DIR};{os.environ.get('PATH', '')}",
            "GGML_NO_BACKTRACE": "1",
        }
        args = [
            str(_SERVER_EXE),
            "-m",
            str(self._model_path),
            "-bs",
            "1",
            "-bo",
            "1",
            "-dev",
            "0",
            "-t",
            "4",
            "--host",
            _SERVER_HOST,
            "--port",
            str(_SERVER_PORT),
        ]
        logger.info("Starting whisper-server in background")
        return subprocess.Popen(
            args,
            cwd=_WHISPER_DIR,
            env=env,
            stdout=self._server_stdout_handle,
            stderr=self._server_stderr_handle,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    def _stop_server_process(self) -> None:
        process = self._server_process
        self._server_process = None
        self._server_available = False

        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        if self._server_stdout_handle is not None:
            try:
                self._server_stdout_handle.close()
            except Exception:
                pass
            self._server_stdout_handle = None

        if self._server_stderr_handle is not None:
            try:
                self._server_stderr_handle.close()
            except Exception:
                pass
            self._server_stderr_handle = None

    def _server_healthcheck(self) -> bool:
        try:
            with request.urlopen(f"{_SERVER_URL}/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def _restart_server_sync(self) -> None:
        with self._server_lock:
            self._server_ready.clear()
            self._stop_server_process()
            self._server_managed = False
            self._server_start_error = None
            self._start_server_worker()

    def _run_server(self, audio_bytes: bytes) -> str:
        wav_path = _WHISPER_DIR / f"server_audio_{uuid.uuid4().hex[:8]}.wav"
        try:
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(audio_bytes)

            boundary = f"----VoiceTypeBoundary{uuid.uuid4().hex}"
            body = self._encode_multipart(boundary, wav_path)
            req = request.Request(
                f"{_SERVER_URL}/inference",
                data=body,
                method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

            t0 = time.perf_counter()
            with request.urlopen(req, timeout=_SERVER_TIMEOUT_S) as response:
                payload = response.read()
            elapsed = time.perf_counter() - t0
            data = json.loads(payload.decode("utf-8", errors="replace"))
            text = str(data.get("text", "")).strip()
            logger.info(f"whisper-server done in {elapsed:.2f}s")
            return text
        except Exception as exc:
            logger.warning(f"whisper-server request failed: {exc}")
            return ""
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass

    def _encode_multipart(self, boundary: str, wav_path: Path) -> bytes:
        parts: list[bytes] = []
        fields = {
            "temperature": "0.0",
            "temperature_inc": "0.2",
            "response_format": "json",
            "language": "auto",
            # Vocabulary bias — Whisper conditions decoding on this text, so
            # the terms below survive ru<->en code-switching and get spelled
            # consistently. Customize with your own jargon (product names,
            # acronyms, names you dictate often). Keep it under ~350 chars /
            # ~50 tokens — that is Whisper's prompt context window.
            "prompt": (
                "VoiceType, Cypher, Whisper, Telegram, GitHub, Python, "
                "CUDA, ROCm, Vulkan, GGUF, API, SDK, LLM"
            ),
        }

        for name, value in fields.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )

        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{wav_path.name}"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + wav_path.read_bytes()
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)

    def _run_cli(self, wav_path: str, use_gpu: bool = True) -> str:
        """Run whisper-cli.exe and return transcribed text."""
        out_base = wav_path.replace(".wav", "")
        cmd = [
            str(_CLI_EXE),
            "-m",
            str(self._model_path),
            "-f",
            wav_path,
            "-l",
            "auto",
            "--no-timestamps",
            "-t",
            "4",
            "-bo",
            "1",
            "-bs",
            "1",
            "-oj",
            "-of",
            out_base,
        ]
        if use_gpu:
            cmd.extend(["-dev", "0"])
        else:
            cmd.append("--no-gpu")

        env = {**os.environ, "GGML_NO_BACKTRACE": "1"}
        t0 = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            gpu_label = "GPU" if use_gpu else "CPU"
            logger.error(f"whisper-cli {gpu_label} timed out after {elapsed:.1f}s")
            return ""
        except OSError as exc:
            logger.error(f"whisper-cli failed to start: {exc}")
            return ""
        elapsed = time.perf_counter() - t0

        if result.returncode != 0:
            gpu_label = "GPU" if use_gpu else "CPU"
            logger.error(f"whisper-cli {gpu_label} failed (code {result.returncode}, {elapsed:.1f}s)")
            return ""

        logger.info(f"whisper-cli {'GPU' if use_gpu else 'CPU'} done in {elapsed:.2f}s")

        json_path = Path(f"{out_base}.json")
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return " ".join(seg.get("text", "").strip() for seg in data.get("transcription", [])).strip()
            finally:
                json_path.unlink(missing_ok=True)
        return ""

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        if self._server_thread is not None:
            self._server_ready.wait(timeout=_SERVER_READY_TIMEOUT_S)

        if self._server_available and self._server_healthcheck():
            text = self._run_server(audio_bytes)
            if text:
                return text

            logger.warning("whisper-server failed once, restarting and retrying once")
            self._restart_server_sync()
            if self._server_available and self._server_healthcheck():
                text = self._run_server(audio_bytes)
                if text:
                    return text

        if self._server_start_error:
            logger.warning(f"whisper-server unavailable — falling back to CLI ({self._server_start_error})")
        else:
            logger.warning("whisper-server unavailable — falling back to CLI")

        if not _CLI_EXE.exists():
            raise FileNotFoundError(
                f"whisper-cli.exe not found at {_CLI_EXE}. "
                "Download whisper.cpp Vulkan build to runtime/whisper-cpp/"
            )
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Model not found at {self._model_path}. "
                f"Download ggml-{self._model_name}.bin to {_MODEL_DIR}/"
            )

        wav_path = str(_WHISPER_DIR / f"audio_{uuid.uuid4().hex[:8]}.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)

        try:
            for attempt in range(2):
                text = self._run_cli(wav_path, use_gpu=True)
                if text:
                    return text
                if attempt == 0:
                    logger.warning("CLI GPU attempt 1 failed, retrying GPU...")

            logger.warning("CLI GPU failed twice, falling back to CPU")
            return self._run_cli(wav_path, use_gpu=False)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    async def recognize(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

        text = await asyncio.to_thread(self._transcribe_sync, audio_bytes)
        logger.info(f"Whisper STT result: {len(text)} chars")
        return text

    def shutdown(self) -> None:
        self._stop_server_process()
