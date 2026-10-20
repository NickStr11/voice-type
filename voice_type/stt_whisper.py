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
- Current runtime build is whisper.cpp v1.9.1 (Vulkan, MinGW); server no_context
  is already on by default, so there is no -nc CLI flag here.
- GGML_NO_BACKTRACE=1 is required for the MinGW build on this machine.
- _VULKAN_ENV is injected into both server and CLI subprocesses to survive an
  AMD driver update that broke Vulkan; see docs/learned-the-hard-way.md §3.
  Rebuild recipe: scripts/build-whisper-vulkan.ps1.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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
# Cold model uploads can exceed 25s after boot even when Vulkan is healthy.
# Give startup enough headroom instead of killing it just before it is ready.
_SERVER_READY_TIMEOUT_S = 60.0
# When the caller has a cloud fallback, a cold or stuck server is not worth
# waiting a full minute for: give it this long, then let the cloud answer while
# the server keeps loading for the next dictation.
_FAST_FAIL_READY_WAIT_S = 15.0
_CLI_TIMEOUT_S = 60.0

_TEMP_AUDIO_PREFIXES = ("audio_", "server_audio_")
_TEMP_OUTPUT_SUFFIXES = (".wav", ".json", ".txt", ".srt", ".vtt", ".csv", ".lrc")

# Wall-clock gap watcher: if more than _RESUME_POLL_S + _RESUME_GAP_S of real
# time elapses between ticks, the machine was suspended (sleep/hibernate). The
# whisper-server's Vulkan device is invalidated across resume (first /inference
# then 500s — see docs/learned-the-hard-way.md §4). Keep it out of ordinary
# sleep transitions by stopping it after idle, and discard it after a resume gap.
_RESUME_POLL_S = 30.0
_RESUME_GAP_S = 90.0


def cleanup_stale_temp_files(directory: Path | None = None) -> int:
    """Remove audio/transcript artifacts left behind by a crashed worker."""
    target = directory or _WHISPER_DIR
    if not target.exists():
        return 0

    removed = 0
    for path in target.iterdir():
        if (
            not path.is_file()
            or not path.name.startswith(_TEMP_AUDIO_PREFIXES)
            or path.suffix.lower() not in _TEMP_OUTPUT_SUFFIXES
        ):
            continue
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning(f"Could not remove stale VoiceType temp file {path.name}: {exc}")

    if removed:
        logger.info(f"Removed {removed} stale VoiceType temp file(s)")
    return removed


def _cleanup_cli_outputs(out_base: str) -> None:
    """Remove every output format whisper-cli may leave next to its input."""
    for suffix in _TEMP_OUTPUT_SUFFIXES:
        if suffix == ".wav":
            continue
        try:
            Path(f"{out_base}{suffix}").unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"Could not remove whisper-cli temp output {out_base}{suffix}: {exc}")

# Vulkan workarounds for AMD RX 7800 XT after a driver update (2026-06-08):
# - VK_LOADER_LAYERS_DISABLE=~implicit~ — overlay/capture implicit layers
#   (Bandicam, RenderDoc, Steam overlay, AMD switchable-graphics) crashed
#   whisper on the first VRAM allocation. Disabling them only for our own
#   subprocess leaves those tools working everywhere else.
# - GGML_VK_DISABLE_COOPMAT=1 — KHR_coopmat matmul path crashes during compute
#   on this driver; the fallback path runs fine (~1.2s vs ~35s CPU).
# See docs/learned-the-hard-way.md §3.
_VULKAN_ENV = {
    "VK_LOADER_LAYERS_DISABLE": "~implicit~",
    "GGML_VK_DISABLE_COOPMAT": "1",
}

# whisper.cpp hard-wraps long transcriptions at a fixed column width, inserting a
# literal '\n' wherever the line hits the limit — frequently mid-word
# ("тво\nему", "репози\nтории"). Downstream cleanup turns every '\n' into a
# space, so the wrap surfaces as a mid-word space in the pasted text. A '\n'
# flanked by letters on both sides is always such a wrap → splice it out so the
# word rejoins. Every other '\n' (next to a space, digit, or punctuation) is a
# real boundary and is left for the normal whitespace-collapse downstream.
_MIDWORD_WRAP = re.compile(r"(?<=[^\W\d_])\n(?=[^\W\d_])")


def _rejoin_wrapped_words(text: str) -> str:
    """Repair whisper.cpp mid-word line wraps so the pasted text has no gaps."""
    return _MIDWORD_WRAP.sub("", text)


class WhisperSTTClient:
    """Local Whisper STT backend with server-first strategy."""

    def __init__(self, config: AppConfig) -> None:
        self._model_name = config.whisper_model
        self._prompt = config.whisper_prompt
        self._log_transcripts = config.log_transcripts
        self._model_dir = config.whisper_model_dir or _MODEL_DIR
        self._model_path = self._model_dir / f"ggml-{self._model_name}.bin"
        self._server_ready = threading.Event()
        self._server_lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._server_process: subprocess.Popen[bytes] | None = None
        self._server_managed = False
        self._server_available = False
        self._server_stdout_handle: BinaryIO | None = None
        self._server_stderr_handle: BinaryIO | None = None
        self._server_start_error: str | None = None
        self._stop_watch = threading.Event()
        self._resume_watch_thread: threading.Thread | None = None
        # Consecutive times STT fell all the way back to CPU (both GPU attempts
        # failed). >0 means the GPU/Vulkan hot path is currently dead — see
        # _note_cpu_fallback / docs/learned-the-hard-way.md §3.
        self._cpu_fallback_streak = 0

        if not _SERVER_EXE.exists() or not self._model_path.exists():
            self._server_ready.set()
            logger.warning("Whisper server unavailable at startup — CLI fallback only")
        else:
            self._ensure_server_background()
            self._start_resume_watch()

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
            **_VULKAN_ENV,
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
        self._server_managed = False

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

    def _restart_server_background(self) -> None:
        """Kill the server and reload it off the dictation path."""
        with self._server_lock:
            self._stop_server_process()
            self._server_start_error = None
        self._ensure_server_background()

    def _start_resume_watch(self) -> None:
        if self._resume_watch_thread is not None:
            return
        self._resume_watch_thread = threading.Thread(
            target=self._resume_watch_loop,
            name="whisper-resume-watch",
            daemon=True,
        )
        self._resume_watch_thread.start()

    def _resume_watch_loop(self) -> None:
        """Detect resume-from-sleep and rebuild the Vulkan server context."""
        last = time.time()
        while not self._stop_watch.is_set():
            self._stop_watch.wait(_RESUME_POLL_S)
            if self._stop_watch.is_set():
                break
            now = time.time()
            gap = now - last
            last = now
            if gap > _RESUME_POLL_S + _RESUME_GAP_S:
                logger.info(
                    f"Detected {gap:.0f}s wall-clock gap (system resume) — restarting "
                    "whisper-server to rebuild the Vulkan context"
                )
                try:
                    self._restart_server_sync()
                except Exception as exc:  # noqa: BLE001 — watcher must never die
                    logger.warning(f"Resume restart failed: {exc}")

    def _run_server(self, audio_bytes: bytes) -> str | None:
        """Transcribe via the resident server.

        Returns the text — possibly "" for silence or a too-quiet clip — or None
        when the request itself failed. Only None means the server is unhealthy;
        treating an empty transcript as a failure used to restart the server
        (~20s model reload) and then run the slow CLI chain on silent clips.
        """
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
            if "error" in data and "text" not in data:
                logger.warning(f"whisper-server returned error: {str(data['error'])[:160]}")
                return None
            text = str(data.get("text", "")).strip()
            logger.info(f"whisper-server done in {elapsed:.2f}s")
            return text
        except Exception as exc:
            logger.warning(f"whisper-server request failed: {exc}")
            return None
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
            # Vocabulary bias — Whisper conditions decoding on this text, so the
            # listed terms survive ru<->en code-switching and get spelled
            # consistently. Configurable via VOICETYPE_WHISPER_PROMPT (see
            # config.AppConfig.whisper_prompt). Keep it under ~350 chars /
            # ~50 tokens — that is Whisper's prompt context window.
            "prompt": self._prompt,
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

        env = {**os.environ, "GGML_NO_BACKTRACE": "1", **_VULKAN_ENV}
        t0 = time.perf_counter()
        try:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_CLI_TIMEOUT_S,
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
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return " ".join(seg.get("text", "").strip() for seg in data.get("transcription", [])).strip()
            return ""
        finally:
            _cleanup_cli_outputs(out_base)

    def _note_gpu_alive(self) -> None:
        """GPU/Vulkan path produced a result — clear any CPU-fallback streak."""
        if self._cpu_fallback_streak:
            logger.info(f"GPU STT path recovered after {self._cpu_fallback_streak} CPU fallback(s)")
            self._cpu_fallback_streak = 0

    def _note_cpu_fallback(self) -> None:
        """Both GPU attempts failed; record + loudly flag the degraded state once."""
        self._cpu_fallback_streak += 1
        if self._cpu_fallback_streak == 1:
            logger.error(
                "GPU STT path dead — running on CPU (~35s/clip vs ~0.3s hot). "
                "Likely an AMD driver update broke Vulkan; see docs/learned-the-hard-way.md §3."
            )
        else:
            logger.debug(f"STT still on CPU (streak={self._cpu_fallback_streak})")

    def _transcribe_sync(self, audio_bytes: bytes, fast_fail: bool = False) -> str:
        """Transcribe locally: resident server, then whisper-cli GPU, then CPU.

        fast_fail=True means the caller has a cloud fallback. Then a server that
        is still loading or has just failed is not worth the CLI ladder: every
        CLI attempt reloads the 1.6 GB model, so when the server is slow (cold
        disk or a stalled GPU after resume) the ladder only adds minutes. Return
        "" instead and keep the server (re)loading in the background.
        """
        self._ensure_server_background()
        if self._server_thread is not None:
            wait_s = _FAST_FAIL_READY_WAIT_S if fast_fail else _SERVER_READY_TIMEOUT_S
            self._server_ready.wait(timeout=wait_s)

        if self._server_available and self._server_healthcheck():
            text = self._run_server(audio_bytes)
            if text is not None:
                self._note_gpu_alive()
                return text

            if fast_fail:
                logger.warning("whisper-server failed — restarting in background, using cloud fallback")
                self._restart_server_background()
                return ""

            logger.warning("whisper-server failed once, restarting and retrying once")
            self._restart_server_sync()
            if self._server_available and self._server_healthcheck():
                text = self._run_server(audio_bytes)
                if text is not None:
                    self._note_gpu_alive()
                    return text

        if fast_fail:
            state = self._server_start_error or "still starting"
            logger.warning(f"whisper-server unavailable ({state}) — skipping CLI, using cloud fallback")
            return ""

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
                f"Download ggml-{self._model_name}.bin to {self._model_dir}/"
            )

        wav_path = str(_WHISPER_DIR / f"audio_{uuid.uuid4().hex[:8]}.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)

        try:
            for attempt in range(2):
                t0 = time.perf_counter()
                text = self._run_cli(wav_path, use_gpu=True)
                if text:
                    self._note_gpu_alive()
                    return text
                if time.perf_counter() - t0 >= _CLI_TIMEOUT_S:
                    # A hang is not a transient crash: a second GPU run would
                    # just burn another minute on the same stall.
                    logger.warning("CLI GPU timed out — skipping GPU retry")
                    break
                if attempt == 0:
                    logger.warning("CLI GPU attempt 1 failed, retrying GPU...")

            logger.warning("CLI GPU failed twice, falling back to CPU")
            self._note_cpu_fallback()
            return self._run_cli(wav_path, use_gpu=False)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    async def recognize(self, audio_bytes: bytes, fast_fail: bool = False) -> str:
        if not audio_bytes:
            return ""

        text = await asyncio.to_thread(self._transcribe_sync, audio_bytes, fast_fail)
        logger.info(f"Whisper STT result: {len(text)} chars")
        if self._log_transcripts:
            logger.debug(f"Whisper RAW text: {text!r}")
        return _rejoin_wrapped_words(text)

    def shutdown(self) -> None:
        self._stop_watch.set()
        self._stop_server_process()
