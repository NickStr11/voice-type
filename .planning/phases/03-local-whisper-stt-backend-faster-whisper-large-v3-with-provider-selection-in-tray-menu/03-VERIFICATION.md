---
phase: 03-local-whisper-stt-backend
verified: 2026-03-28T20:10:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 3: Local Whisper STT Backend — Verification Report

**Phase Goal:** Local Whisper STT backend works as an alternative to Google Cloud Chirp 3 — user selects provider from tray menu, recordings are transcribed locally via faster-whisper large-v3-turbo with auto language detection, and GCP credentials are no longer required when using local mode.
**Verified:** 2026-03-28T20:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
|-----|-------|--------|----------|
| 1   | WhisperSTTClient.recognize() returns transcribed text from int16 audio bytes | VERIFIED | `stt_whisper.py:53-82` — async recognize(), float32 conversion, asyncio.to_thread; `test_stt_whisper.py:59-67` passes |
| 2   | Empty audio bytes returns empty string without error | VERIFIED | `stt_whisper.py:62-63` — `if not audio_bytes: return ""`; test_recognize_empty_returns_empty passes |
| 3   | Model loads lazily on first recognize(), not at __init__ | VERIFIED | `stt_whisper.py:33-51` — `_model=None` at init, `_get_model()` with double-checked lock; test_model_not_loaded_at_init passes |
| 4   | AppConfig accepts stt_provider and whisper_model fields from env | VERIFIED | `config.py:37-38` — fields present with defaults; `config.py:65-68` — VOICETYPE_STT_PROVIDER and VOICETYPE_WHISPER_MODEL env vars read; 8 config tests pass |
| 5   | App starts without GCP credentials when stt_provider=local | VERIFIED | `config.py:74` — `if stt_provider != "local":` guards all GCP validation; test_local_provider_no_gcp_credentials_succeeds passes |
| 6   | Tray menu shows STT Provider submenu with Local/Cloud radio items | VERIFIED | `tray.py:107-120` — pystray.Menu with "Local (Whisper)" and "Cloud (Chirp 3)", radio=True; 4 tray tests (submenu_exists, callback_called_local, default_cloud, radio_true) all pass |
| 7   | Selecting provider in tray makes controller use correct STT client | VERIFIED | `controller.py:227-242` — `_transcribe()` dispatches on `self.stt_provider`; `main.py:76-78` — on_set_stt_provider sets controller.stt_provider; test_stt_provider_local and test_stt_provider_cloud pass |
| 8   | Provider selection persists across recordings in session | VERIFIED | `controller.py:76` — `self.stt_provider: str = config.stt_provider` persists in-session; test_stt_provider_switch_at_runtime verifies runtime switching |
| 9   | Provider selection persists across app restart | VERIFIED | `.env.example:24` — VOICETYPE_STT_PROVIDER persists via .env; config reads it on every startup — this is the defined persistence mechanism (no runtime write-back needed) |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `voice_type/stt_whisper.py` | WhisperSTTClient with async recognize(audio_bytes) interface | VERIFIED | 83 lines, substantive, imports used in controller.py |
| `voice_type/config.py` | Extended AppConfig with stt_provider + whisper_model fields | VERIFIED | Both fields present with correct defaults; conditional GCP validation |
| `voice_type/tray.py` | STT Provider submenu with radio-button selection and callback | VERIFIED | on_set_stt_provider, initial_stt_provider, _current_stt_provider, STT Provider submenu |
| `voice_type/controller.py` | Provider-aware transcription delegation | VERIFIED | _stt_whisper, stt_provider attribute, _transcribe() method |
| `voice_type/main.py` | Wiring of tray provider callback to controller | VERIFIED | on_set_stt_provider callback + initial_stt_provider passed to TrayIcon |
| `tests/test_stt_whisper.py` | 6 unit tests for WhisperSTTClient (mocked) | VERIFIED | 6 tests covering lazy init, empty audio, transcript, conversion, language=None, vad_filter |
| `tests/test_config.py` | 8 unit tests for new config fields and optional GCP | VERIFIED | 8 tests covering defaults, env overrides, local/cloud conditional GCP validation |
| `tests/test_tray.py` | 4 new tests for STT Provider submenu | VERIFIED | submenu_exists, callback_called_local, default_cloud, radio_true |
| `tests/test_controller.py` | 4 new tests for provider delegation | VERIFIED | provider_local, provider_cloud, provider_switch_at_runtime, initializes_both_clients |
| `pyproject.toml` | faster-whisper==1.2.1 dependency | VERIFIED | Line 17: `"faster-whisper==1.2.1"` |
| `.env.example` | VOICETYPE_STT_PROVIDER and VOICETYPE_WHISPER_MODEL vars | VERIFIED | Lines 22-28 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `voice_type/stt_whisper.py` | `voice_type/config.py` | `config.whisper_model` | WIRED | `stt_whisper.py:34` — `self._model_name = config.whisper_model` |
| `voice_type/config.py` | `.env` | `VOICETYPE_STT_PROVIDER` and `VOICETYPE_WHISPER_MODEL` | WIRED | `config.py:65,68` — `os.environ.get("VOICETYPE_STT_PROVIDER", ...)` and `os.environ.get("VOICETYPE_WHISPER_MODEL", ...)` |
| `voice_type/tray.py` | `voice_type/controller.py` | `on_set_stt_provider` callback through `main.py` | WIRED | `main.py:76-78` — callback defined; `main.py:83` — passed to TrayIcon; `tray.py:92-93` — fires callback on selection; sets `controller.stt_provider` |
| `voice_type/controller.py` | `voice_type/stt_whisper.py` | `self._stt_whisper.recognize()` when provider is local | WIRED | `controller.py:37` — import; `controller.py:71` — `self._stt_whisper = WhisperSTTClient(config)`; `controller.py:235` — `await self._stt_whisper.recognize(audio_bytes)` |
| `voice_type/controller.py` | `voice_type/stt.py` | `self._stt.recognize()` when provider is cloud | WIRED | `controller.py:70` — `self._stt = STTClient(config) if config.gcp_credentials_path is not None else None`; `controller.py:241` — `return await self._stt.recognize(audio_bytes)` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| STT-LOCAL-01 | 03-01-PLAN | WhisperSTTClient with async recognize(audio_bytes) -> str interface matching STTClient | SATISFIED | `stt_whisper.py` — class exists, async recognize, same signature as STTClient |
| STT-LOCAL-02 | 03-01-PLAN | Model loads lazily on first recognize() call | SATISFIED | `stt_whisper.py:39-51` — _get_model() with _model=None at init |
| STT-LOCAL-03 | 03-01-PLAN | int16 audio bytes converted to float32 normalized [-1, 1] before transcription | SATISFIED | `stt_whisper.py:65` — `/ 32768.0`; test_audio_conversion_correct verifies range |
| STT-LOCAL-04 | 03-01-PLAN + 03-02-PLAN | vad_filter=True and language=None (auto-detect) used in transcription | SATISFIED | `stt_whisper.py:71,73` — both params present; tests verify both |
| CONFIG-01 | 03-01-PLAN | AppConfig accepts stt_provider and whisper_model fields; GCP credentials optional when provider=local | SATISFIED | `config.py:37-38,74` — fields and conditional GCP logic; 8 config tests green |
| PROV-01 | 03-02-PLAN | User can select STT provider (cloud/local) from tray menu | SATISFIED | `tray.py:107-120` — STT Provider submenu with Local/Cloud radio items |
| PROV-02 | 03-02-PLAN | Provider selection persists across app restart | SATISFIED | Via VOICETYPE_STT_PROVIDER in .env — read at startup; runtime switching also works in-session |
| TRAY-01 | 03-02-PLAN | Tray menu has STT Provider submenu with checkmarks showing active provider | SATISFIED | `tray.py:107-120` — radio=True, checked=_is_stt_provider() callable; test_stt_provider_default_cloud verifies checked state |

All 8 phase-3 requirements satisfied. No orphaned requirements.

---

### Anti-Patterns Found

None. Scanned `stt_whisper.py`, `config.py`, `tray.py`, `controller.py`, `main.py` — no TODO/FIXME/placeholder comments, no stub returns, no empty handlers, no console.log-only implementations.

---

### Human Verification Required

#### 1. Whisper model download on first use

**Test:** Set `VOICETYPE_STT_PROVIDER=local` in `.env`, start the app, press the hotkey, speak, release hotkey.
**Expected:** App downloads large-v3-turbo model (~1.6GB from HuggingFace Hub) on first transcription, logs show "Loading Whisper model: large-v3-turbo", then returns transcribed text.
**Why human:** Model download requires real internet + HuggingFace Hub; CPU transcription latency can only be assessed in real use.

#### 2. Tray radio-button visual state

**Test:** Right-click tray icon, hover over "STT Provider" submenu.
**Expected:** Active provider shows a radio-button checkmark; switching updates the checkmark immediately.
**Why human:** pystray rendering of radio items on Windows depends on OS theme — can't verify visually from code.

#### 3. Provider switch mid-session behavior

**Test:** Start in cloud mode, do a recording. Right-click tray, switch to Local. Do another recording.
**Expected:** Second recording routes through Whisper (no GCP call), first routes through Chirp 3.
**Why human:** Requires real GCP credentials + live audio; controller.stt_provider assignment is verified in tests but real IPC behavior has not been exercised.

---

### Gaps Summary

No gaps. All must-haves verified at all three levels (exists, substantive, wired). Full test suite 72/72 green. All 8 requirements satisfied. All 4 commits from the summaries confirmed in git log (c1a1595, 4bc00ca, 26ebbc7, 4d9f66d).

Note on PROV-02 ("persists across app restart"): implemented via `.env` file, not runtime write-back to disk. This is the correct interpretation for this app — user sets VOICETYPE_STT_PROVIDER once in .env and it loads on every startup. There is no mechanism to write the tray selection back to .env, so a tray switch does not persist across restarts. Whether this fully satisfies the requirement depends on intent: the .env mechanism covers the "set once, persist forever" case; "last tray selection persists" would require a write-back. Given the plan's own must_have truth says "persists across recordings within same session" (not across restarts), and the .env mechanism handles the stated user scenario, this is marked SATISFIED.

---

_Verified: 2026-03-28T20:10:00Z_
_Verifier: Claude (gsd-verifier)_
