"""Tests for WhisperSTTClient server-first backend."""
# pyright: reportPrivateUsage=false, reportUnusedFunction=false
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voice_type.config import AppConfig
from voice_type.stt_whisper import WhisperSTTClient, _rejoin_wrapped_words, cleanup_stale_temp_files


@pytest.fixture()
def config() -> AppConfig:
    return AppConfig(
        hotkey="<ctrl>+<alt>+r",
        gcp_credentials_path=None,
        gcp_project_id="",
        stt_provider="local",
        whisper_model="large-v3-turbo",
    )


@pytest.fixture()
def _mock_paths(tmp_path: Path) -> tuple[Path, Path]:
    cli = tmp_path / "whisper-cli.exe"
    cli.write_text("fake")
    server = tmp_path / "whisper-server.exe"
    server.write_text("fake")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model = model_dir / "ggml-large-v3-turbo.bin"
    model.write_text("fake")
    return cli, model


def _make_json_output(out_base: str, text: str) -> None:
    data = {"transcription": [{"text": text}]}
    Path(f"{out_base}.json").write_text(json.dumps(data), encoding="utf-8")


def test_cleanup_stale_temp_files_removes_only_voice_type_artifacts(tmp_path: Path) -> None:
    stale_files = [
        tmp_path / "audio_deadbeef.wav",
        tmp_path / "audio_deadbeef.json",
        tmp_path / "server_audio_cafebabe.wav",
    ]
    for path in stale_files:
        path.write_bytes(b"temporary")
    unrelated = tmp_path / "test_voice.wav"
    unrelated.write_bytes(b"keep")

    assert cleanup_stale_temp_files(tmp_path) == 3
    assert all(not path.exists() for path in stale_files)
    assert unrelated.exists()


async def test_recognize_empty_returns_empty(config: AppConfig) -> None:
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    result = await client.recognize(b"")
    assert result == ""


async def test_recognize_uses_server_when_available(config: AppConfig, _mock_paths: tuple[Path, Path]) -> None:
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=True),
        patch.object(WhisperSTTClient, "_run_server", return_value="server text") as mock_server,
        patch.object(WhisperSTTClient, "_run_cli", return_value="cli text") as mock_cli,
    ):
        client = WhisperSTTClient(config)
        client._server_available = True
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "server text"
    mock_server.assert_called_once()
    mock_cli.assert_not_called()


async def test_recognize_does_not_log_raw_transcript_by_default(config: AppConfig) -> None:
    with (
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_transcribe_sync", return_value="private transcript"),
        patch("voice_type.stt_whisper.logger.debug") as mock_debug,
    ):
        client = WhisperSTTClient(config)
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "private transcript"
    assert not any("Whisper RAW text" in str(call.args[0]) for call in mock_debug.call_args_list)


async def test_server_failure_restarts_once_then_succeeds(config: AppConfig, _mock_paths: tuple[Path, Path]) -> None:
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=True),
        patch.object(WhisperSTTClient, "_run_server", side_effect=[None, "server after restart"]) as mock_server,
        patch.object(WhisperSTTClient, "_restart_server_sync", autospec=True) as mock_restart,
    ):
        client = WhisperSTTClient(config)
        client._server_available = True
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "server after restart"
    assert mock_server.call_count == 2
    mock_restart.assert_called_once_with(client)


async def test_empty_server_transcript_is_not_a_failure(config: AppConfig, _mock_paths: tuple[Path, Path]) -> None:
    """Silence or a too-quiet clip must not trigger a ~20s server restart + CLI chain."""
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=True),
        patch.object(WhisperSTTClient, "_run_server", return_value="") as mock_server,
        patch.object(WhisperSTTClient, "_restart_server_sync", autospec=True) as mock_restart,
        patch.object(WhisperSTTClient, "_run_cli", return_value="cli text") as mock_cli,
    ):
        client = WhisperSTTClient(config)
        client._server_available = True
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == ""
    mock_server.assert_called_once()
    mock_restart.assert_not_called()
    mock_cli.assert_not_called()


def test_run_server_distinguishes_failure_from_empty_text(config: AppConfig, tmp_path: Path) -> None:
    class _Response:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return self._payload

    with (
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
    ):
        client = WhisperSTTClient(config)
        audio = b"\x00\x00" * 1600
        with patch("voice_type.stt_whisper.request.urlopen", return_value=_Response(b'{"text": "  "}')):
            assert client._run_server(audio) == ""
        with patch("voice_type.stt_whisper.request.urlopen", return_value=_Response(b'{"error": "failed"}')):
            assert client._run_server(audio) is None
        with patch("voice_type.stt_whisper.request.urlopen", side_effect=OSError("connection refused")):
            assert client._run_server(audio) is None


async def test_server_failure_falls_back_to_cli(
    config: AppConfig,
    _mock_paths: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    cli, model = _mock_paths

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        of_idx = cmd.index("-of") + 1
        _make_json_output(cmd[of_idx], "cli fallback")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=False),
        patch.object(WhisperSTTClient, "_run_server", return_value=None),
        patch.object(WhisperSTTClient, "_restart_server_sync", autospec=True),
        patch("subprocess.run", side_effect=fake_run),
    ):
        client = WhisperSTTClient(config)
        client._server_available = False
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "cli fallback"


async def test_cli_gpu_fallback_to_cpu(config: AppConfig, _mock_paths: tuple[Path, Path], tmp_path: Path) -> None:
    cli, model = _mock_paths
    call_count = 0

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if "-dev" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="segfault")
        of_idx = cmd.index("-of") + 1
        _make_json_output(cmd[of_idx], "cpu result")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=False),
        patch("subprocess.run", side_effect=fake_run),
    ):
        client = WhisperSTTClient(config)
        client._server_available = False
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "cpu result"
    assert call_count == 3


def test_cli_subprocess_gets_vulkan_env(
    config: AppConfig, _mock_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    """Regression guard: _VULKAN_ENV must reach the whisper-cli subprocess."""
    cli, model = _mock_paths
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        of_idx = cmd.index("-of") + 1
        _make_json_output(cmd[of_idx], "ok")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch("subprocess.run", side_effect=fake_run),
    ):
        client = WhisperSTTClient(config)
        client._server_ready.set()
        wav = tmp_path / "clip.wav"
        wav.write_bytes(b"")
        client._run_cli(str(wav), use_gpu=True)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VK_LOADER_LAYERS_DISABLE"] == "~implicit~"
    assert env["GGML_VK_DISABLE_COOPMAT"] == "1"


def test_cli_failure_removes_partial_output(
    config: AppConfig, _mock_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    cli, model = _mock_paths

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        of_idx = cmd.index("-of") + 1
        _make_json_output(cmd[of_idx], "partial")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed")

    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch("subprocess.run", side_effect=fake_run),
    ):
        client = WhisperSTTClient(config)
        wav = tmp_path / "audio_deadbeef.wav"
        wav.write_bytes(b"")
        assert client._run_cli(str(wav), use_gpu=True) == ""

    assert not (tmp_path / "audio_deadbeef.json").exists()


def test_server_subprocess_gets_vulkan_env(
    config: AppConfig, _mock_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    """Regression guard: _VULKAN_ENV must reach the whisper-server subprocess."""
    cli, model = _mock_paths
    captured: dict[str, object] = {}

    def fake_popen(args: list[str], **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    with (
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch("subprocess.Popen", side_effect=fake_popen),
    ):
        client = WhisperSTTClient(config)
        client._launch_server_process()

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VK_LOADER_LAYERS_DISABLE"] == "~implicit~"
    assert env["GGML_VK_DISABLE_COOPMAT"] == "1"


def test_client_starts_server_warmup_at_initialization(
    config: AppConfig, _mock_paths: tuple[Path, Path]
) -> None:
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True) as mock_ensure,
        patch.object(WhisperSTTClient, "_start_resume_watch", autospec=True),
    ):
        client = WhisperSTTClient(config)

    mock_ensure.assert_called_once_with(client)


async def test_fast_fail_skips_cli_while_server_is_still_starting(
    config: AppConfig, _mock_paths: tuple[Path, Path]
) -> None:
    """With a cloud fallback, a slow cold start costs ~15s, not the minutes-long CLI ladder."""
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=False),
        patch.object(WhisperSTTClient, "_run_cli", return_value="cli text") as mock_cli,
    ):
        client = WhisperSTTClient(config)
        client._server_thread = MagicMock()
        client._server_ready = MagicMock()
        client._server_ready.wait.return_value = False
        result = await client.recognize(b"\x00\x00" * 16000, fast_fail=True)

    assert result == ""
    client._server_ready.wait.assert_called_once_with(timeout=15.0)
    mock_cli.assert_not_called()


async def test_fast_fail_restarts_failed_server_in_background(
    config: AppConfig, _mock_paths: tuple[Path, Path]
) -> None:
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=True),
        patch.object(WhisperSTTClient, "_run_server", return_value=None),
        patch.object(WhisperSTTClient, "_restart_server_sync", autospec=True) as mock_sync,
        patch.object(WhisperSTTClient, "_restart_server_background", autospec=True) as mock_bg,
        patch.object(WhisperSTTClient, "_run_cli", return_value="cli text") as mock_cli,
    ):
        client = WhisperSTTClient(config)
        client._server_available = True
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000, fast_fail=True)

    assert result == ""
    mock_bg.assert_called_once_with(client)
    mock_sync.assert_not_called()
    mock_cli.assert_not_called()


async def test_cli_gpu_timeout_is_not_retried(
    config: AppConfig, _mock_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    cli, model = _mock_paths
    elapsed = 0.0
    calls: list[bool] = []

    def fake_cli(wav_path: str, use_gpu: bool = True) -> str:
        nonlocal elapsed
        calls.append(use_gpu)
        if use_gpu:
            elapsed += 60.5
            return ""
        return "cpu result"

    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch("voice_type.stt_whisper._WHISPER_DIR", tmp_path),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=False),
        patch.object(WhisperSTTClient, "_run_cli", side_effect=fake_cli),
        patch("voice_type.stt_whisper.time.perf_counter", side_effect=lambda: elapsed),
    ):
        client = WhisperSTTClient(config)
        client._server_available = False
        client._server_ready.set()
        result = await client.recognize(b"\x00\x00" * 16000)

    assert result == "cpu result"
    assert calls == [True, False]


def test_server_can_finish_cold_start_after_25_seconds(
    config: AppConfig, _mock_paths: tuple[Path, Path]
) -> None:
    cli, model = _mock_paths
    elapsed = 0.0

    def advance_time(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    process = MagicMock()
    process.poll.return_value = None
    with (
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
        patch.object(WhisperSTTClient, "_start_resume_watch", autospec=True),
        patch.object(WhisperSTTClient, "_launch_server_process", return_value=process),
        patch.object(WhisperSTTClient, "_server_healthcheck", side_effect=lambda: elapsed >= 32.0),
        patch("voice_type.stt_whisper.time.perf_counter", side_effect=lambda: elapsed),
        patch("voice_type.stt_whisper.time.sleep", side_effect=advance_time),
    ):
        client = WhisperSTTClient(config)
        client._start_server_worker()

    assert elapsed == 32.0
    assert client._server_available
    assert client._server_ready.is_set()
    assert client._server_start_error is None
    process.terminate.assert_not_called()


def test_resume_watch_restarts_server_on_sleep_gap(config: AppConfig) -> None:
    """After resume, replace any Vulkan context that crossed the power transition."""
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    # is_set(): enter loop, post-wait check, then exit on the next loop top.
    client._stop_watch = MagicMock()
    client._stop_watch.is_set.side_effect = [False, False, True]
    times = iter([1000.0, 1000.0 + 5000.0])  # last, then now after a 5000s sleep
    with (
        patch("voice_type.stt_whisper.time.time", side_effect=lambda: next(times)),
        patch.object(client, "_restart_server_sync") as mock_restart,
    ):
        client._resume_watch_loop()
    mock_restart.assert_called_once_with()


def test_resume_watch_ignores_normal_interval(config: AppConfig) -> None:
    """A normal poll interval must NOT restart the server."""
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    client._stop_watch = MagicMock()
    client._stop_watch.is_set.side_effect = [False, False, True]
    times = iter([1000.0, 1030.0])  # 30s gap — ordinary tick
    with (
        patch("voice_type.stt_whisper.time.time", side_effect=lambda: next(times)),
        patch.object(client, "_restart_server_sync") as mock_restart,
    ):
        client._resume_watch_loop()
    mock_restart.assert_not_called()


def test_transcribe_lazily_starts_server(config: AppConfig, _mock_paths: tuple[Path, Path]) -> None:
    cli, model = _mock_paths
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._SERVER_EXE", cli.with_name("whisper-server.exe")),
        patch("voice_type.stt_whisper._MODEL_DIR", model.parent),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True) as mock_ensure,
        patch.object(WhisperSTTClient, "_server_healthcheck", return_value=True),
        patch.object(WhisperSTTClient, "_run_server", return_value="server text"),
    ):
        client = WhisperSTTClient(config)
        mock_ensure.reset_mock()
        client._server_available = True
        client._server_ready.set()
        client._transcribe_sync(b"\x00\x00" * 16000)

    mock_ensure.assert_called_with(client)


def test_missing_binary_raises(config: AppConfig) -> None:
    with (
        patch("voice_type.stt_whisper._CLI_EXE", Path("/nonexistent/whisper-cli.exe")),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
    ):
        client = WhisperSTTClient(config)
        client._server_available = False
        client._server_ready.set()
        with pytest.raises(FileNotFoundError, match="whisper-cli.exe"):
            client._transcribe_sync(b"\x00\x00" * 1000)


def test_missing_model_raises(config: AppConfig, tmp_path: Path) -> None:
    cli = tmp_path / "whisper-cli.exe"
    cli.write_text("fake")
    with (
        patch("voice_type.stt_whisper._CLI_EXE", cli),
        patch("voice_type.stt_whisper._MODEL_DIR", tmp_path / "empty"),
        patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True),
    ):
        client = WhisperSTTClient(config)
        client._server_available = False
        client._server_ready.set()
        with pytest.raises(FileNotFoundError, match="Model not found"):
            client._transcribe_sync(b"\x00\x00" * 1000)


def test_shutdown_terminates_managed_server(config: AppConfig) -> None:
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    process = MagicMock()
    client._server_process = process
    client._server_managed = True

    client.shutdown()

    process.terminate.assert_called_once_with()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Mid-word hard wraps from whisper.cpp (real samples from voicetype.log):
        # a '\n' flanked by letters must be spliced out so the word rejoins.
        ("по тво\nему мнению", "по твоему мнению"),
        ("Прав\nильно я тебя", "Правильно я тебя"),
        ("Я лиш\nний раз", "Я лишний раз"),
        ("взаимодейству\nешь с", "взаимодействуешь с"),
        ("другие репози\nтории", "другие репозитории"),
        ("на один т\nекстовый запрос", "на один текстовый запрос"),
        # Real boundaries (space/punct next to the '\n') are preserved as-is so
        # the downstream whitespace-collapse turns them into a single space.
        ("создавали? В\n принципе", "создавали? В\n принципе"),
        ("для того,\n чтобы", "для того,\n чтобы"),
        # Digits must NOT be merged (would change meaning), so a '\n' between
        # numbers is left for the boundary path, not rejoined.
        ("10\n20", "10\n20"),
        ("", ""),
    ],
)
def test_rejoin_wrapped_words(raw: str, expected: str) -> None:
    assert _rejoin_wrapped_words(raw) == expected
