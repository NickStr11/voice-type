---
phase: 3
slug: local-whisper-stt-backend
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-28
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_stt_whisper.py -x -q` |
| **Full suite command** | `uv run pytest -x -q` |
| **Estimated runtime** | ~3 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_stt_whisper.py -x -q`
- **After every plan wave:** Run `uv run pytest -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | STT-LOCAL-01 | unit | `uv run pytest tests/test_stt_whisper.py::test_recognize_returns_transcript -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | STT-LOCAL-02 | unit | `uv run pytest tests/test_stt_whisper.py::test_recognize_empty_returns_empty -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | STT-LOCAL-03 | unit | `uv run pytest tests/test_stt_whisper.py::test_audio_conversion_correct -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | STT-LOCAL-04 | unit | `uv run pytest tests/test_stt_whisper.py::test_model_not_loaded_at_init -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | PROV-01 | unit | `uv run pytest tests/test_controller.py::test_stt_provider_local -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | PROV-02 | unit | `uv run pytest tests/test_controller.py::test_stt_provider_cloud -x` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 1 | TRAY-01 | unit | `uv run pytest tests/test_tray.py::test_stt_provider_submenu -x` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 1 | CONFIG-01 | unit | `uv run pytest tests/test_config.py::test_stt_provider_config -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_stt_whisper.py` — stubs for STT-LOCAL-01 through STT-LOCAL-04
- [ ] `tests/test_config.py` — stubs for CONFIG-01
- [ ] `faster-whisper==1.2.1` added to pyproject.toml — `uv add faster-whisper==1.2.1`

*(Existing `tests/test_controller.py` and `tests/test_tray.py` need new test functions added, not new files.)*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Model auto-downloads on first use | STT-LOCAL-03 | Requires network + ~1.6GB download | Run VoiceType, select Local provider, record — verify model downloads to `~/.cache/huggingface/hub` |
| Tray radio buttons visually correct | TRAY-01 | Visual UI check | Right-click tray → STT Provider → verify radio selection works |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
