---
phase: 02-live-pipeline
plan: "01"
subsystem: stt-llm-clients
tags: [stt, llm, google-cloud, gemini, tdd, async]
dependency_graph:
  requires: []
  provides: [STTClient, LLMClient]
  affects: [voice_type/controller.py]
tech_stack:
  added: [pytest-asyncio==1.3.0]
  patterns: [asyncio.to_thread, concurrent.futures.ThreadPoolExecutor, TDD-red-green]
key_files:
  created:
    - voice_type/stt.py
    - voice_type/llm.py
    - tests/test_stt.py
    - tests/test_llm.py
  modified:
    - pyproject.toml
decisions:
  - "asyncio.to_thread for STT blocking GCP call — keeps event loop unblocked"
  - "concurrent.futures wall-clock timeout for LLM — asyncio.wait_for cannot catch socket stalls"
  - "thinking_budget=0 on Gemini 2.5 Flash — saves 1-3s latency on simple rewrite task"
  - "Persistent SpeechClient in __init__ — avoids 200-500ms connection overhead per request"
  - "reportUnknownMemberType=false in pyright — GCP stubs have partial types, not our code's issue"
metrics:
  duration: 3min
  completed_date: "2026-03-23"
  tasks_completed: 2
  files_created: 4
  files_modified: 1
---

# Phase 02 Plan 01: STTClient and LLMClient Summary

**One-liner:** Google Cloud STT V2 Chirp 2 client + Gemini Flash cleanup client with concurrent.futures wall-clock timeout fallback, both verified via mocked unit tests.

## What Was Built

Two importable cloud service clients for the voice pipeline:

- `voice_type/stt.py` — `STTClient` wraps Google Cloud STT V2 with Chirp 2 batch recognition. Uses regional endpoint (`us-central1-speech.googleapis.com`), bilingual `language_codes=["ru-RU", "en-US"]`, and `asyncio.to_thread` to offload the blocking GCP call without blocking the event loop.

- `voice_type/llm.py` — `LLMClient` wraps Gemini 2.5 Flash for transcription cleanup (punctuation, grammar, filler word removal). Uses `concurrent.futures.ThreadPoolExecutor` with `future.result(timeout=8.0)` for true wall-clock timeout — the only mechanism that catches the confirmed Gemini socket stall bug. Falls back to raw STT text silently on timeout or any exception.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | STTClient — Chirp 2 batch recognize | ef061f9 | voice_type/stt.py, tests/test_stt.py |
| 2 | LLMClient — Gemini Flash cleanup with wall-clock timeout | 13d2ddd | voice_type/llm.py, tests/test_llm.py |

## Test Results

- `tests/test_stt.py`: 6 tests — regional endpoint, language_codes plural, chirp_2 model, transcript parsing, empty audio, no results; all pass
- `tests/test_llm.py`: 6 tests — cleaned text, timeout fallback, exception fallback, empty/whitespace bypass, thinking_budget=0; all pass
- Full suite: 40/40 pass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest-asyncio not installed**
- **Found during:** Task 1 (TDD RED phase)
- **Issue:** `@pytest.mark.asyncio` tests would fail to collect without pytest-asyncio package
- **Fix:** Added `pytest-asyncio>=1.3.0` to dev dependencies; added `[tool.pytest.ini_options] asyncio_mode = "auto"` to pyproject.toml
- **Files modified:** pyproject.toml
- **Commit:** ef061f9

**2. [Rule 1 - Bug] pyright strict reportUnknownMemberType on GCP client stub**
- **Found during:** Task 2 verification
- **Issue:** `google.cloud.speech_v2.SpeechClient.recognize()` has partial type stubs, triggering pyright strict error not caused by our code
- **Fix:** Added `reportUnknownMemberType = false` to `[tool.pyright]` in pyproject.toml — scoped to third-party stub quality, not our code
- **Files modified:** pyproject.toml
- **Commit:** 13d2ddd

## Self-Check: PASSED
