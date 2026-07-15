# Whisper Resident Warmup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep VoiceType's Vulkan Whisper server warm during ordinary idle time and proactively replace it after a real suspend/resume gap.

**Architecture:** `WhisperSTTClient` owns the server lifecycle. Construction starts background warmup, ordinary watcher ticks leave the server alone, and a detected resume gap performs a synchronized stop/start through the existing `_restart_server_sync()` path. Recording-start warmup remains as an idempotent safety net.

**Tech Stack:** Python 3.12, asyncio, threading, whisper.cpp Vulkan, pytest, Ruff, Pyright, Windows PowerShell.

## Global Constraints

- Preserve `MAX_RECORDING_DURATION_S = 15 * 60`.
- Preserve stale temporary audio/output cleanup.
- Preserve server retry, Vulkan CLI retry, and final CPU fallback.
- Do not stage or commit pre-existing dirty implementation files as a bundle.

---

### Task 1: Lock the desired server lifecycle with failing tests

**Files:**
- Modify: `tests/test_stt_whisper.py:268-341`
- Test: `tests/test_stt_whisper.py`

**Interfaces:**
- Consumes: `WhisperSTTClient.__init__()`, `_ensure_server_background()`, `_resume_watch_loop()`, `_restart_server_sync()`.
- Produces: regression tests for eager startup warmup, resume restart, and normal-idle retention.

- [ ] **Step 1: Add the eager-warmup regression test**

```python
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
```

- [ ] **Step 2: Change the resume test to require proactive restart**

```python
def test_resume_watch_restarts_server_on_sleep_gap(config: AppConfig) -> None:
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    client._stop_watch = MagicMock()
    client._stop_watch.is_set.side_effect = [False, False, True]
    times = iter([1000.0, 6000.0])
    with (
        patch("voice_type.stt_whisper.time.time", side_effect=lambda: next(times)),
        patch.object(client, "_restart_server_sync") as mock_restart,
    ):
        client._resume_watch_loop()
    mock_restart.assert_called_once_with()
```

- [ ] **Step 3: Make the normal-interval test assert no restart and remove the two idle-stop tests**

```python
def test_resume_watch_ignores_normal_interval(config: AppConfig) -> None:
    with patch.object(WhisperSTTClient, "_ensure_server_background", autospec=True):
        client = WhisperSTTClient(config)
    client._stop_watch = MagicMock()
    client._stop_watch.is_set.side_effect = [False, False, True]
    times = iter([1000.0, 1030.0])
    with (
        patch("voice_type.stt_whisper.time.time", side_effect=lambda: next(times)),
        patch.object(client, "_restart_server_sync") as mock_restart,
    ):
        client._resume_watch_loop()
    mock_restart.assert_not_called()
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```powershell
uv run pytest -q tests/test_stt_whisper.py -k "initialization or resume_watch"
```

Expected: eager warmup and resume restart fail because current construction is lazy and resume only stops the server.

---

### Task 2: Implement the resident lifecycle minimally

**Files:**
- Modify: `voice_type/stt_whisper.py:48-57`
- Modify: `voice_type/stt_whisper.py:131-163`
- Modify: `voice_type/stt_whisper.py:315-354`
- Modify: `voice_type/stt_whisper.py:507-512`
- Test: `tests/test_stt_whisper.py`

**Interfaces:**
- Consumes: existing `_ensure_server_background()` and `_restart_server_sync()` lifecycle primitives.
- Produces: eager resident server startup and proactive resume recovery without ordinary idle shutdown.

- [ ] **Step 1: Start warmup during construction**

```python
if not _SERVER_EXE.exists() or not self._model_path.exists():
    self._server_ready.set()
    logger.warning("Whisper server unavailable at startup — CLI fallback only")
else:
    self._ensure_server_background()
    self._start_resume_watch()
```

- [ ] **Step 2: Replace resume cleanup with proactive synchronized restart**

```python
if gap > _RESUME_POLL_S + _RESUME_GAP_S:
    logger.info(
        "Detected %.0fs wall-clock gap (system resume) — restarting "
        "whisper-server to rebuild the Vulkan context",
        gap,
    )
    try:
        self._restart_server_sync()
    except Exception as exc:  # noqa: BLE001 — watcher must never die
        logger.warning("Resume restart failed: %s", exc)
```

- [ ] **Step 3: Remove ordinary idle shutdown state and behavior**

Delete `_SERVER_IDLE_TIMEOUT_S`, `_last_server_activity`, `_stop_idle_server()`, the normal-tick call to `_stop_idle_server()`, and the `_last_server_activity` assignment in `_transcribe_sync()`. Keep `_ensure_server_background()` in `_transcribe_sync()` and `warmup()` so repeated requests remain safe.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
uv run pytest -q tests/test_stt_whisper.py
```

Expected: all Whisper lifecycle tests pass.

- [ ] **Step 5: Run the controller regression tests**

Run:

```powershell
uv run pytest -q tests/test_controller.py
```

Expected: recording-start warmup and the 15-minute safety limit remain green.

---

### Task 3: Verify and activate the fixed runtime

**Files:**
- Modify: `D:/code/2026/3/nickCodex-READY/memory/diary/2026-07-15-voicetype-cold-start-latency-diagnosis.md` after live verification.
- Do not modify VoiceType source during this task.

**Interfaces:**
- Consumes: the updated `WhisperSTTClient` lifecycle.
- Produces: tested local runtime with a resident Vulkan server and a durable verification note.

- [ ] **Step 1: Run the complete quality gate**

Run:

```powershell
uv run pytest -q
uv run ruff check voice_type tests
uv run pyright voice_type
```

Expected: all tests pass, Ruff reports no errors, and Pyright reports zero errors.

- [ ] **Step 2: Restart VoiceType through its existing resilience script**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ensure-running.ps1 -RestartWorker
```

Do not manually create an additional worker or watchdog.

Expected: one logical VoiceType worker, registered hotkey, and a managed `whisper-server.exe` process.

- [ ] **Step 3: Verify health and Vulkan device**

Run:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8178/health -TimeoutSec 5
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|whisper' -and $_.CommandLine -match 'voice_type|whisper-server' }
Get-Content -Encoding UTF8 -Tail 200 runtime/whisper-cpp/whisper-server.err.log
```

Expected: health `200`, `whisper-server.exe` remains alive, and the current log selects device `0`, AMD Radeon RX 7800 XT, with `using Vulkan0 backend`.

- [ ] **Step 4: Verify the server survives ordinary idle**

Wait slightly over 120 seconds while polling the existing health endpoint, then verify the same server PID and health `200`. This is a condition-based check; stop early only on failure.

- [ ] **Step 5: Record the outcome without bundling unrelated changes**

Append live timings, PID-retention evidence, and test counts to the existing diagnosis diary. Leave the pre-existing dirty VoiceType implementation files uncommitted unless the user separately requests a scoped integration commit.
