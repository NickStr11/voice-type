# Phase 3: Local Whisper STT Backend — Research

**Researched:** 2026-03-28
**Domain:** faster-whisper, CTranslate2, pystray menu, asyncio threading
**Confidence:** HIGH

## Summary

Phase 3 adds faster-whisper (large-v3, CTranslate2) as a second STT backend alongside the existing Google Cloud Chirp 3 client. The user selects the active provider (Local / Cloud) from the tray menu, persisting the choice across recordings. Model downloads automatically on first use (~3 GB for large-v3 float16) from HuggingFace Hub.

The architecture fits cleanly into the existing pattern: a new `WhisperSTTClient` module mirrors the existing `STTClient` interface (`async recognize(audio_bytes: bytes) -> str`), and the controller holds both clients, delegating to whichever provider is selected. The tray menu gains a "STT Provider" submenu with radio-button items. No new threads or event loop changes are required.

The main risk is **<2s latency on CPU**: large-v3 on CPU (int8) is ~2.5× real-time, meaning a 5-second utterance takes ~12s. GPU (CUDA) is required to meet the 2s SLA for longer inputs. The alternative is `large-v3-turbo` (809M params, ~1.6 GB, ~6× faster than full large-v3), which gets CPU latency to a feasible range for short dictation clips.

**Primary recommendation:** Implement `WhisperSTTClient` with `large-v3-turbo` as the default model name (not `large-v3` as originally stated in phase goal). Use `compute_type="int8"` on CPU and `"float16"` when CUDA is available. Expose model choice via `.env` so user can override to `large-v3` for max accuracy.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| faster-whisper | 1.2.1 | CTranslate2-based Whisper inference | 4× faster than openai/whisper, numpy array input, language auto-detect |
| ctranslate2 | 4.7.1 | Inference engine (transitive dep) | Already installed globally; uv add pulls it |

**Verified:** `pip show faster-whisper` on this machine returns 1.2.1 (2025-10-31). Not yet in project venv — needs `uv add`.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| huggingface-hub | 1.7.2 | Model download from HF Hub | Auto-used by WhisperModel on first load |
| onnxruntime | (transitive) | Silero VAD for vad_filter | Already pulled by faster-whisper |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| large-v3-turbo | large-v3 | large-v3: +accuracy, 2× larger (3 GB), significantly slower on CPU |
| large-v3-turbo | distil-whisper-large-v3 | distil: faster but lower accuracy on Russian |
| large-v3-turbo | medium | medium: much faster but noticeable accuracy drop for Russian |

**Installation:**
```bash
uv add faster-whisper==1.2.1
```

No CUDA-specific packages needed for CPU-only mode. For GPU (optional), user needs CUDA 12+ and cuDNN 9 pre-installed — cannot be pip-installed cleanly on Windows (requires system CUDA toolkit).

**Version verification:**
```bash
pip show faster-whisper   # 1.2.1, released 2025-10-31
```

---

## Architecture Patterns

### Recommended Project Structure

```
voice_type/
├── stt.py              # Existing: Google Cloud STTClient (unchanged)
├── stt_whisper.py      # NEW: WhisperSTTClient (faster-whisper)
├── controller.py       # Modified: add stt_provider field, delegate to active client
├── tray.py             # Modified: add "STT Provider" submenu
└── config.py           # Modified: add whisper_model, stt_provider fields
```

### Pattern 1: Shared STTClient Interface

Both clients expose the same async method so controller can call either without branching:

```python
# Source: mirrors existing voice_type/stt.py interface
class WhisperSTTClient:
    async def recognize(self, audio_bytes: bytes) -> str: ...
```

Controller holds both and delegates:
```python
# controller.py
async def _transcribe(self, audio_bytes: bytes) -> str:
    if self.stt_provider == "local":
        return await self._stt_whisper.recognize(audio_bytes)
    return await self._stt.recognize(audio_bytes)
```

### Pattern 2: Lazy Model Loading

WhisperModel takes 3–10 seconds to load from disk on first use. Load lazily on first `recognize()` call, not at `__init__` time. Use a threading lock to prevent double-load if two calls race (won't happen in this app's single-recording flow, but safe practice):

```python
# Source: standard Python lazy singleton with lock
import threading

class WhisperSTTClient:
    def __init__(self, model_name: str, compute_type: str) -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info(f"Loading Whisper model: {self._model_name}")
                    self._model = WhisperModel(
                        self._model_name,
                        device="auto",
                        compute_type=self._compute_type,
                    )
        return self._model
```

### Pattern 3: Audio Conversion (int16 -> float32)

VoiceType audio is int16 numpy arrays. WhisperModel.transcribe() accepts numpy arrays but expects float32 normalized to [-1, 1]:

```python
# Source: verified against faster-whisper source + GitHub issue #1323
import numpy as np

def _to_float32(audio_bytes: bytes) -> np.ndarray:
    """Convert raw int16 bytes (16kHz mono) to float32 array for Whisper."""
    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0
```

No resampling needed — VoiceType already captures at 16kHz (Whisper's native rate).

### Pattern 4: Transcribe with Language Detection

```python
# Source: verified against faster_whisper/transcribe.py (v1.2.1) signatures
segments, info = model.transcribe(
    audio_float32,        # np.ndarray, float32, 16kHz
    language=None,        # None = auto-detect (same as Chirp 3 behavior)
    beam_size=5,          # default, good balance speed/accuracy
    vad_filter=True,      # skip silence segments (Silero VAD)
    vad_parameters={"min_silence_duration_ms": 300},
)
text = " ".join(seg.text.strip() for seg in segments)
```

`info.language` returns detected language code (e.g., `"ru"`, `"en"`).

**Warning:** `segments` is a generator. Iteration triggers inference. Exhaust fully before returning.

### Pattern 5: Tray Menu with Radio-Button Provider Selection

pystray 0.19.5 supports `radio=True` and callable `checked` for exclusive selection:

```python
# Source: pystray 0.19.5 docs — https://pystray.readthedocs.io/en/latest/usage.html
_stt_provider = "cloud"  # module-level state

def _set_provider(provider: str) -> Callable[[object], None]:
    def handler(_: object) -> None:
        nonlocal _stt_provider
        _stt_provider = provider
        if on_set_stt_provider:
            on_set_stt_provider(provider)
    return handler

stt_menu = pystray.Menu(
    pystray.MenuItem(
        "Local (Whisper)",
        _set_provider("local"),
        checked=lambda item: _stt_provider == "local",
        radio=True,
    ),
    pystray.MenuItem(
        "Cloud (Chirp 3)",
        _set_provider("cloud"),
        checked=lambda item: _stt_provider == "cloud",
        radio=True,
    ),
)

# Attach as submenu item in the main menu
pystray.MenuItem("STT Provider", stt_menu)
```

`icon.update_menu()` must be called when provider changes from outside menu callbacks (e.g., from controller code). Within menu callbacks themselves, pystray refreshes automatically.

### Anti-Patterns to Avoid

- **Sharing WhisperModel across threads without serialization:** The model has shared internal state; concurrent `transcribe()` calls produce non-deterministic output (confirmed in issue #1207). In this app, calls are already sequential (one recording at a time), but don't add parallelism.
- **Creating WhisperModel at import time:** 3–10s blocking load on startup — violates fast startup requirement. Always lazy-load.
- **Passing int16 bytes directly to transcribe():** Will produce garbage output or errors. Always convert to float32 / 32768.
- **Forgetting that `segments` is a generator:** `list(segments)` must be called to actually run inference. `for seg in segments: ...` also works.
- **Using `large-v3` with `compute_type="float16"` on CPU:** float16 is GPU-only. CPU must use `int8` or `int8_float16` (hybrid: weights int8, activations float16 for compatible CPUs) or `int16` / `float32`.
- **Using `compute_type="default"` on CPU:** Resolves to float32 — very slow. Always specify `int8` for CPU deployments.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Language detection | Custom language classifier | `language=None` in `transcribe()` | Whisper's built-in detection is state-of-the-art for bilingual Ru/En |
| Silence trimming | Manual VAD in Python | `vad_filter=True` + Silero VAD | Silero VAD outperforms amplitude thresholds |
| Model download | Custom HF download | `WhisperModel("large-v3-turbo")` | Auto-downloads, caches in `~/.cache/huggingface/hub`, resumes interrupted downloads |
| Audio decoding | ffmpeg subprocess | Pass numpy array directly | faster-whisper accepts float32 ndarray — no file I/O needed |
| Progress reporting during download | Custom tqdm wrap | HF Hub shows progress automatically via tqdm | tqdm progress is shown in terminal automatically |

**Key insight:** The existing audio pipeline (sounddevice -> int16 bytes) converts trivially to float32 with a single numpy operation. The only new work is: add lib, write the conversion, wrap in async, add tray items.

---

## Common Pitfalls

### Pitfall 1: CPU latency exceeds 2s SLA for longer utterances

**What goes wrong:** `large-v3` on CPU (int8) runs at ~2.5× real-time. A 5-second utterance takes ~12s. `large-v3-turbo` on CPU (int8) is ~6× faster than large-v3 overall; a 5-second clip takes ~3-4s. Still marginal for the 2s SLA.
**Why it happens:** Transformer inference is compute-heavy; CPU parallelism limited vs. GPU.
**How to avoid:** (a) Default to `large-v3-turbo` not `large-v3`. (b) Detect GPU at startup (`WhisperModel("...", device="auto")` auto-selects CUDA if available). (c) Warn in logs if CPU is used and model is large-v3 (not turbo).
**Warning signs:** First post-switch transcription takes >5s.

### Pitfall 2: Model cold-load blocks event loop

**What goes wrong:** `WhisperModel(...)` reads ~3 GB from disk and initializes CTranslate2 — takes 3–10s on first use. If called directly on the asyncio event loop, the tray freezes.
**Why it happens:** `WhisperModel.__init__` is blocking I/O + CPU.
**How to avoid:** Always load model via `asyncio.to_thread(self._get_model)` on first `recognize()` call. The loading message in the tray title or logs signals to user that the model is initializing.
**Warning signs:** Tray becomes unresponsive for several seconds on first local transcription.

### Pitfall 3: `segments` generator not fully consumed

**What goes wrong:** `segments, info = model.transcribe(...)` returns immediately. Inference only runs when you iterate. If you only call `next(segments)`, you get one segment and miss the rest.
**Why it happens:** CTranslate2 uses lazy decoding for memory efficiency.
**How to avoid:** Always `" ".join(seg.text.strip() for seg in segments)` — exhausts the generator fully.

### Pitfall 4: Config validation fails on GCP credentials when user switches to Local-only

**What goes wrong:** Current `load_config()` in `config.py` calls `sys.exit(1)` if `GOOGLE_APPLICATION_CREDENTIALS` is missing. If the app is run in local-only mode (no GCP), it fails at startup.
**Why it happens:** Original config assumed GCP was always required.
**How to avoid:** Make GCP credentials optional when `VOICETYPE_STT_PROVIDER=local`. Validate GCP config lazily (only when `STTClient` is actually used). Or warn instead of exit when provider is local.
**Warning signs:** `sys.exit(1)` at startup despite user having Whisper configured.

### Pitfall 5: compute_type mismatch on CPU

**What goes wrong:** `compute_type="float16"` on CPU raises a CTranslate2 error at model-load time. CPU-only hardware doesn't support float16 accumulation.
**Why it happens:** float16 requires CUDA tensor cores.
**How to avoid:** Use `device="auto"` + `compute_type="default"` to let CTranslate2 choose, OR explicitly use `int8` on CPU. Check `ctranslate2.get_cuda_device_count() > 0` to determine device.
**Warning signs:** `ctranslate2.OpError: float16 is not supported on CPU` at model init.

### Pitfall 6: HuggingFace Hub token needed for gated models

**What goes wrong:** Some model variants on HF Hub require authentication. `large-v3-turbo` from the `Systran/` namespace is public, so no token required. Community conversions (e.g., `deepdml/faster-whisper-large-v3-turbo-ct2`) are also public.
**Why it happens:** HF recently gated some models.
**How to avoid:** Use `WhisperModel("large-v3-turbo")` — resolves to the official Systran public repo, no auth needed.

---

## Code Examples

### Complete WhisperSTTClient (reference implementation)

```python
# Source: faster-whisper 1.2.1 API (verified signatures above)
from __future__ import annotations

import asyncio
import threading
from typing import Final

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger

from voice_type.config import AppConfig

_DEFAULT_MODEL: Final[str] = "large-v3-turbo"
_CPU_COMPUTE_TYPE: Final[str] = "int8"
_GPU_COMPUTE_TYPE: Final[str] = "float16"


class WhisperSTTClient:
    """Local Whisper STT backend via faster-whisper (CTranslate2).

    Model loads lazily on first recognize() call to avoid blocking startup.
    """

    def __init__(self, config: AppConfig) -> None:
        self._model_name = config.whisper_model  # default: "large-v3-turbo"
        self._model: WhisperModel | None = None
        self._lock = threading.Lock()
        logger.info(f"WhisperSTTClient ready (model={self._model_name}, load deferred)")

    def _get_model(self) -> WhisperModel:
        """Load model on first call. Thread-safe via double-checked lock."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info(f"Loading Whisper model: {self._model_name} ...")
                    self._model = WhisperModel(
                        self._model_name,
                        device="auto",
                        compute_type="default",  # CTranslate2 picks best for device
                    )
                    logger.info(f"Whisper model loaded: {self._model_name}")
        return self._model

    async def recognize(self, audio_bytes: bytes) -> str:
        """Transcribe int16 LINEAR16 bytes (16kHz mono) via local Whisper.

        Returns transcribed text, or empty string on silence/error.
        """
        if not audio_bytes:
            return ""

        audio_float32 = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        def _transcribe() -> str:
            model = self._get_model()  # load on first call (blocking, in thread)
            segments, info = model.transcribe(
                audio_float32,
                language=None,       # auto-detect Russian/English
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(seg.text.strip() for seg in segments)  # exhaust generator
            logger.info(f"Whisper detected language: {info.language} ({info.language_probability:.2f})")
            return text

        raw_text = await asyncio.to_thread(_transcribe)
        logger.info(f"Whisper STT result: {len(raw_text)} chars")
        return raw_text
```

### Provider Selection in Controller

```python
# controller.py modification
class AppController:
    def __init__(self, ...) -> None:
        ...
        self._stt = STTClient(config)              # existing Google Cloud client
        self._stt_whisper = WhisperSTTClient(config)
        self.stt_provider: str = config.stt_provider  # "cloud" | "local"

    async def _transcribe(self, audio_bytes: bytes) -> str:
        if self.stt_provider == "local":
            return await self._stt_whisper.recognize(audio_bytes)
        return await self._stt.recognize(audio_bytes)
```

### Config Extension

```python
# config.py additions to AppConfig dataclass
@dataclass(frozen=True)
class AppConfig:
    ...  # existing fields
    stt_provider: str = "cloud"          # "cloud" | "local"
    whisper_model: str = "large-v3-turbo"  # passed to WhisperModel()
```

`.env` additions:
```bash
VOICETYPE_STT_PROVIDER=cloud   # or: local
VOICETYPE_WHISPER_MODEL=large-v3-turbo
```

### Tray Menu with Radio Buttons

```python
# Source: pystray 0.19.5 docs — radio=True pattern
# tray.py modification — add STT provider submenu
_stt_provider_state: str  # tracks current selection

stt_submenu = pystray.Menu(
    pystray.MenuItem(
        "Local (Whisper)",
        _set_stt_provider("local"),
        checked=lambda item: self._current_stt_provider == "local",
        radio=True,
    ),
    pystray.MenuItem(
        "Cloud (Chirp 3)",
        _set_stt_provider("cloud"),
        checked=lambda item: self._current_stt_provider == "cloud",
        radio=True,
    ),
)

# Insert into main menu before SEPARATOR + Quit:
pystray.MenuItem("STT Provider", stt_submenu),
pystray.Menu.SEPARATOR,
...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| openai/whisper (PyTorch) | faster-whisper (CTranslate2) | 2023 | 4× faster, less VRAM |
| large-v3 as best model | large-v3-turbo available | Oct 2024 | 6× faster, ~same accuracy, half the size |
| CUDA 11 + cuDNN 8 | CUDA 12 + cuDNN 9 (ctranslate2 >=4.5.0) | 2024 | Requires CUDA 12 for GPU on latest ctranslate2 |

**Deprecated/outdated:**
- `openai/whisper` Python package: Still works but 4× slower than faster-whisper for same accuracy. Don't use.
- `compute_type="int8_float16"` on CPU: Invalid for CPU (float16 accumulation requires GPU). Use `int8` on CPU.

---

## Open Questions

1. **GPU availability on user's machine**
   - What we know: User has RX 7800 XT (AMD) — mentioned in `llm_local.py` comment. AMD GPUs use ROCm, not CUDA.
   - What's unclear: ctranslate2 4.x supports CUDA 12 (NVIDIA) and OpenCL (limited). ROCm support for ctranslate2 is experimental and Windows-only binaries are not officially distributed.
   - Recommendation: Default to `device="cpu"` with `compute_type="int8"`. Add log message at startup indicating GPU acceleration not available. Use `large-v3-turbo` to compensate for CPU speed.

2. **GCP credentials optional when provider=local**
   - What we know: Current `load_config()` exits on missing GCP credentials. GitHub release target requires no GCP setup.
   - What's unclear: Should validation be entirely skipped for `STTClient` when provider is local, or just degraded to a warning?
   - Recommendation: Make GCP credentials optional with a warning when `VOICETYPE_STT_PROVIDER=local`. `STTClient` raises `RuntimeError` on `recognize()` if called without credentials — controller never calls it in local mode.

3. **Model size for GitHub open-source release**
   - What we know: Phase goal says "large-v3 (~1.5GB)". Actual large-v3 is ~3 GB (float16 CTranslate2). Large-v3-turbo is ~1.6 GB.
   - What's unclear: Was "large-v3" in the phase description a loose reference, or is the planner intended to use the full large-v3 model?
   - Recommendation: Use `large-v3-turbo` as default. Expose `VOICETYPE_WHISPER_MODEL` env var so user can override to `large-v3` if they want max accuracy and have GPU.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_stt_whisper.py -x -q` |
| Full suite command | `uv run pytest -x -q` |

### Phase Requirements -> Test Map

| ID | Behavior | Test Type | Automated Command | File Exists? |
|----|----------|-----------|-------------------|-------------|
| STT-LOCAL-01 | WhisperSTTClient.recognize() returns string from int16 bytes | unit (mocked WhisperModel) | `pytest tests/test_stt_whisper.py::test_recognize_returns_transcript -x` | Wave 0 |
| STT-LOCAL-02 | Empty audio_bytes returns empty string | unit | `pytest tests/test_stt_whisper.py::test_recognize_empty_returns_empty -x` | Wave 0 |
| STT-LOCAL-03 | float32 conversion correct (int16 / 32768) | unit | `pytest tests/test_stt_whisper.py::test_audio_conversion_correct -x` | Wave 0 |
| STT-LOCAL-04 | Model loads lazily (not at __init__) | unit (mock) | `pytest tests/test_stt_whisper.py::test_model_not_loaded_at_init -x` | Wave 0 |
| PROV-01 | Controller uses local client when provider="local" | unit (mock both clients) | `pytest tests/test_controller.py::test_stt_provider_local -x` | Wave 0 |
| PROV-02 | Controller uses cloud client when provider="cloud" | unit (mock both clients) | `pytest tests/test_controller.py::test_stt_provider_cloud -x` | Wave 0 |
| TRAY-01 | Tray has STT provider submenu with radio items | unit (mock pystray) | `pytest tests/test_tray.py::test_stt_provider_submenu -x` | Wave 0 |
| CONFIG-01 | AppConfig loads stt_provider and whisper_model from env | unit | `pytest tests/test_config.py::test_stt_provider_config -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_stt_whisper.py -x -q`
- **Per wave merge:** `uv run pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_stt_whisper.py` — covers STT-LOCAL-01 through STT-LOCAL-04
- [ ] `tests/test_config.py` — covers CONFIG-01 (new file for config tests)
- [ ] `faster-whisper==1.2.1` added to pyproject.toml deps — `uv add faster-whisper==1.2.1`

*(Existing `tests/test_controller.py` and `tests/test_tray.py` need new test functions added, not new files.)*

---

## Sources

### Primary (HIGH confidence)

- faster-whisper 1.2.1 installed globally — `WhisperModel.__init__` and `transcribe` signatures inspected directly via `inspect.signature()`
- `pip show faster-whisper ctranslate2 huggingface-hub` — exact versions from local install
- pystray 0.19.5 docs — https://pystray.readthedocs.io/en/latest/usage.html — `radio=True` pattern verified

### Secondary (MEDIUM confidence)

- GitHub SYSTRAN/faster-whisper README — GPU installation, `device="auto"`, download_root behavior
- GitHub issue #1207 — thread safety: model not safe for concurrent calls without external lock
- GitHub issue #1030 — turbo v3 benchmarks: 2.7× faster than large-v3, better WER on librispeech
- faster-whisper source `transcribe.py` — VAD filter params, generator behavior, TranscriptionInfo fields

### Tertiary (LOW confidence)

- CPU latency estimates (~2.5× real-time for large-v3 on CPU): derived from benchmark data on i7-class hardware, not measured on user's specific machine
- AMD RX 7800 XT CTranslate2 support: based on known ecosystem state (ROCm not supported in ctranslate2 Windows wheels) — needs confirmation if user wants GPU acceleration

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified locally via `pip show`, API signatures inspected from installed package
- Architecture: HIGH — patterns derived from actual API signatures + pystray docs
- Pitfalls: MEDIUM — thread safety from GitHub issues, CPU latency from community benchmarks (not measured on user's hardware)

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (faster-whisper minor versions release frequently; re-verify if >30 days)

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STT-LOCAL-01 | faster-whisper WhisperSTTClient transcribes int16 bytes to text | WhisperModel.transcribe() accepts float32 ndarray; int16->float32 conversion: `/ 32768.0` |
| STT-LOCAL-02 | Language auto-detection (Russian + English) | `language=None` enables auto-detect; `info.language` returns ISO code |
| STT-LOCAL-03 | Model auto-download on first use | WhisperModel("large-v3-turbo") auto-downloads from HF Hub to `~/.cache/huggingface/hub` |
| STT-LOCAL-04 | Provider selection in tray menu (Local / Cloud) | pystray 0.19.5 supports `radio=True` + callable `checked` for exclusive selection |
| STT-LOCAL-05 | Provider persists as controller state (not just tray) | Controller.stt_provider field + on_set_stt_provider callback from tray |
| STT-LOCAL-06 | GCP credentials become optional when provider=local | AppConfig validation must not sys.exit on missing GCP creds if provider is local |
| STT-LOCAL-07 | Performance target: <2s for typical dictation clip | Use large-v3-turbo (not large-v3); device="auto" picks CUDA if available; CPU latency ~3-4s for 5s clip |
</phase_requirements>
