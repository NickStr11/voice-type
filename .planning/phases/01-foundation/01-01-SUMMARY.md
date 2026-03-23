---
phase: 01-foundation
plan: 01
subsystem: infra
tags: [python, uv, pyproject, sounddevice, pynput, pystray, google-cloud-speech, google-genai, python-dotenv, config]

# Dependency graph
requires: []
provides:
  - pyproject.toml with all 10 runtime deps pinned and resolved
  - voice_type Python package skeleton
  - AppConfig frozen dataclass loaded from .env via python-dotenv
  - load_config() with fail-fast validation on missing/invalid GCP credentials
  - .env.example template with all configurable variables documented
  - .gitignore protecting .env and *.json service account keys
affects: [02, 03, 04]

# Tech tracking
tech-stack:
  added:
    - sounddevice==0.5.5 (microphone capture)
    - pynput==1.8.1 (global hotkeys)
    - pystray==0.19.5 (system tray icon)
    - Pillow==12.1.1 (tray icon rendering)
    - pywin32==311 (clipboard + paste simulation)
    - google-cloud-speech==2.37.0 (STT V2 / Chirp 2)
    - google-genai==1.68.0 (Gemini Flash text cleanup)
    - loguru>=0.7 (logging)
    - python-dotenv>=1.0 (env config)
    - numpy>=1.24 (audio buffer handling)
  patterns:
    - AppConfig as frozen dataclass — immutable config passed through the app
    - load_config() fails fast with sys.exit(1) and clear error messages — misconfigured app never starts silently
    - .env loaded relative to config.py's parent.parent (project root) — works in both dev and installed modes
    - *.json excluded from git globally — protects GCP service account keys

key-files:
  created:
    - pyproject.toml
    - uv.lock
    - voice_type/__init__.py
    - voice_type/config.py
    - .env.example
    - .gitignore
  modified: []

key-decisions:
  - "uv.lock committed to repo — reproducible installs, dep conflicts caught early"
  - "AppConfig is frozen dataclass not pydantic — zero extra deps, sufficient for config"
  - "Hotkey default is <ctrl>+<alt>+r — avoids Win+key interception per PITFALLS.md research"
  - "*.json in .gitignore — blanket block on service account keys; exceptions added explicitly"

patterns-established:
  - "Fail-fast config: sys.exit(1) with actionable error messages if required env vars missing"
  - "Config module is self-executable: `uv run python -m voice_type.config` as smoke-test"

requirements-completed: [SYS-03]

# Metrics
duration: 2min
completed: 2026-03-23
---

# Phase 01 Plan 01: Project Scaffold and Configuration Summary

**pyproject.toml with 10 runtime deps (sounddevice, pynput, pystray, Pillow, pywin32, Google STT V2, Gemini), AppConfig frozen dataclass with fail-fast GCP credentials validation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-23T14:48:56Z
- **Completed:** 2026-03-23T14:51:27Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- All 10 runtime dependencies pinned and resolved via uv sync (51 packages total including transitive deps)
- AppConfig frozen dataclass that loads from .env and fails immediately with clear messages if GOOGLE_APPLICATION_CREDENTIALS or GCP_PROJECT_ID is missing or points to non-existent file
- Hotkey configurable via VOICETYPE_HOTKEY env var, defaults to `<ctrl>+<alt>+r` (avoids Win+key interception per pitfalls research)
- .gitignore with blanket *.json block to prevent GCP service account key commits

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pyproject.toml and package scaffold** - `cd5ab6c` (chore)
2. **Task 2: Create AppConfig with validation and .env.example** - `51e6452` (feat)

## Files Created/Modified
- `pyproject.toml` - Project dependencies, uv config, pyright/ruff tool config
- `uv.lock` - Locked dependency tree (51 packages)
- `voice_type/__init__.py` - Package marker
- `voice_type/config.py` - AppConfig dataclass + load_config() with fail-fast validation
- `.env.example` - Template for user secrets with inline documentation
- `.gitignore` - Protects .env and *.json from git

## Decisions Made
- AppConfig as frozen dataclass (not pydantic) — zero extra deps, config doesn't need validators beyond what's already written
- `*.json` blanket-excluded from git — protects service account keys even if accidentally placed in project root; explicit exceptions can be added as needed
- Hotkey default `<ctrl>+<alt>+r` per PITFALLS.md: Win+key combinations are intercepted by Windows shell before pynput sees them

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

**External services require manual configuration before the app can run:**
1. Create a GCP service account with Speech-to-Text V2 permissions
2. Download the JSON key and note its path
3. Copy `.env.example` to `.env`, fill in `GOOGLE_APPLICATION_CREDENTIALS` and `GCP_PROJECT_ID`
4. Verify: `uv run python -m voice_type.config` should print config values and exit 0

## Next Phase Readiness
- AppConfig is ready to import in all subsequent modules
- All runtime dependencies installed — audio, hotkey, tray, STT, Gemini modules can start using them
- No blockers for Phase 01-02 (audio recording subsystem)

## Self-Check: PASSED

All files exist at expected paths. Both task commits (cd5ab6c, 51e6452) verified in git log.

---
*Phase: 01-foundation*
*Completed: 2026-03-23*
