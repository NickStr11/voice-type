# VoiceType

Push-to-talk dictation for Windows — press a hotkey, speak, and clean text
appears in whatever window was focused. Includes **Cypher**, an optional
voice assistant for launching apps, web search, and Telegram automation.

- 🎙️ **Global hotkey** — toggle recording from anywhere, paste into the active window.
- 🧠 **Local Whisper STT** — GPU, fully offline, free (cloud Chirp 3 is an optional fallback).
- ✨ **Smart cleanup** — instant regex offline, or Gemini paragraphs/lists with a **free** API key.
- 🤖 **Cypher voice agent** — say "Cypher, open VS Code" / "Cypher, send a screenshot to Telegram".
- 🟢 **System tray** — switch backends and cleanup modes on the fly.
- ♻️ **Autostart watchdog** — survives logoff/crash, keeps itself alive.

> Windows only (uses Win32 `RegisterHotKey`, `pywin32`, and the system tray).
> Russian + English speech are supported out of the box.

---

## How it works

```
hotkey ─▶ record mic ─▶ hotkey ─▶ Whisper STT (local) ─▶ cleanup ─▶ paste into active window
                                                            │
                                              ┌─────────────┴─────────────┐
                                       short utterance              long dictation
                                       regex (0 ms, offline)        Gemini (free key) ─┐
                                                                                       │
                                                          no key → regex fallback ◀─────┘
```

Transcription runs **locally** with Whisper by default — your audio never
leaves the machine. Long dictations are then tidied into paragraphs and lists
by Gemini (only the short transcript is sent, never the audio). With no API key
set, VoiceType runs **fully offline** and falls back to a fast regex cleanup.

The window that is focused **when you stop recording** is the paste target —
so you can start talking, tab away, and the text still lands in the right place.

While processing, additional recording hotkeys are ignored. Right-click the
tray icon for **Отменить обработку**, **Скопировать последний текст**, or
**Повторить вставку в прежнее окно**. Cancellation suppresses a result that has
not yet been pasted; an in-flight recognition/cleanup request finishes in the
background before the next recording can start. An already started paste or
Cypher action cannot be undone by cancellation.

The last recognized/cleaned text stays in memory until VoiceType exits. Retry
targets the original window; use Copy to place the text somewhere else.
The status reports that the paste shortcut was sent, rather than claiming the
destination accepted it. Unsupported clipboard formats are left untouched and
the text remains available through Copy. Paragraphs and meaningful words are
preserved by local cleanup and paste.

If a transcript starts with the wake word **"Cypher"** (or "Сайфер"), it is
routed to the Cypher command parser instead of being pasted.

---

## Requirements

- **Windows 10/11**
- **Python 3.12+**
- [**uv**](https://docs.astral.sh/uv/) (package manager)
- A working microphone
- A GPU + a [whisper.cpp](https://github.com/ggml-org/whisper.cpp) build for local STT (see [Local STT setup](#local-stt-setup-whisper))
- *(optional)* a **free** [Gemini API key](https://aistudio.google.com/apikey) for LLM cleanup

Everything runs offline with just Whisper. Add a free Gemini key only if you
want polished paragraph/list formatting on long dictations.

---

## Install

```bash
git clone https://github.com/NickStr11/voice-type.git
cd voice-type
uv sync
cp .env.example .env   # then edit .env
```

Run it:

```bash
uv run voice-type
# or
uv run python -m voice_type.main
```

A colored dot appears in the system tray: 🟢 idle · 🔴 recording · 🟡 processing.
Press the hotkey (default **Ctrl+Alt+R**) to start, press again to stop.

---

## Text cleanup with Gemini (free API key)

Whisper gives you the words; Gemini turns a long, rambly dictation into clean
paragraphs and lists (it is a *formatter*, not an editor — it keeps your words).
This is **optional and free** for normal use:

1. Open **<https://aistudio.google.com/apikey>** and click **Create API key**
   (no credit card required).
2. Paste it into `.env`:
   ```
   GEMINI_API_KEY=AIza...your-key...
   ```
3. Restart VoiceType. Done.

**Cost:** practically nothing. Your **audio stays local** — only the short
transcript is sent for cleanup (a few hundred tokens per dictation). The free
tier has a small daily request quota **per model** (20/day for
`gemini-2.5-flash` as of 2026-10), so VoiceType rotates through a chain of
models (`VOICETYPE_GEMINI_MODELS`). A model that runs out is paused until its
quota resets instead of being retried. Short utterances skip Gemini entirely
and use the instant offline regex pass.

**No key?** VoiceType still works fully offline — cleanup falls back to the
regex pass (filler removal, punctuation, paragraph splitting). And if Gemini
ever times out or errors, you still get your raw words.

> Advanced: if you'd rather run Gemini through **Vertex AI** (service account /
> GCP credits) instead of an AI Studio key, set `GCP_PROJECT_ID` +
> `GOOGLE_APPLICATION_CREDENTIALS` and leave `GEMINI_API_KEY` empty. When both
> are present, `GEMINI_API_KEY` wins.

---

## Configuration

All settings live in `.env` (copied from `.env.example`). `.env` is gitignored —
**never commit it**.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | no | — | Free AI Studio key — enables Gemini cleanup. Empty = offline regex cleanup |
| `VOICETYPE_GEMINI_MODELS` | no | `gemini-2.5-flash-lite,gemini-3.5-flash-lite,gemini-2.5-flash` | Cleanup model chain, tried in order. A model that hits its quota is paused until the API says it resets |
| `VOICETYPE_STT_PROVIDER` | no | `local` | `local` (Whisper, offline) or `cloud` (Chirp 3) |
| `VOICETYPE_CLOUD_FALLBACK` | no | `0` | If `1`, local mode retries empty Whisper results with cloud STT. Audio may leave the machine |
| `VOICETYPE_HOTKEY` | no | `<ctrl>+<alt>+r` | Recording toggle hotkey |
| `VOICETYPE_WHISPER_MODEL` | no | `large-v3-turbo` | Model name (local); file `ggml-<name>.bin` |
| `VOICETYPE_WHISPER_PROMPT` | no | neutral list | Comma-separated vocabulary bias — your jargon, for consistent spelling |
| `VOICETYPE_LOG_LEVEL` | no | `INFO` | File log level |
| `VOICETYPE_LOG_TRANSCRIPTS` | no | `0` | If `1`, writes raw/cleaned dictated text to logs for debugging |
| `VOICETYPE_CYPHER_PLANNER` | no | `off` | `gemini` enables the L2 natural-language command planner (needs GCP) |
| `VOICETYPE_CYPHER_PLANNER_MODEL` | no | `gemini-2.5-flash` | Planner model |
| `GOOGLE_APPLICATION_CREDENTIALS` | advanced | — | GCP service-account JSON — for cloud STT or Vertex cleanup |
| `GCP_PROJECT_ID` | advanced | — | GCP project ID |
| `VOICETYPE_STT_REGION` | no | `us` | Cloud STT regional endpoint prefix |

Config is validated at startup — a misconfigured app prints a clear error and
exits instead of failing silently. GCP credentials are only required when
`STT_PROVIDER=cloud` **or** the Cypher Gemini planner is enabled.

Supported hotkey combos in the current build:
`<ctrl>+<alt>+r`, `<ctrl>+<alt>+v`, `<ctrl>+<shift>+r`, `<ctrl>+<shift>+<space>`.

---

## Local STT setup (Whisper)

Local transcription runs [whisper.cpp](https://github.com/ggml-org/whisper.cpp).
A resident `whisper-server.exe` keeps the model in memory, so hot requests take
~200–300 ms instead of ~1.3 s per cold subprocess. If the server is unavailable
it falls back to `whisper-cli.exe`, and finally to CPU.

These binaries and the model are **not** in the repo (they are large and
gitignored). Set them up once:

```
runtime/whisper-cpp/
├── whisper-server.exe
├── whisper-cli.exe
├── <ggml + backend DLLs from the release>
└── model/
    └── ggml-large-v3-turbo.bin
```

1. **Get a whisper.cpp build** for your GPU backend (see below) — grab a
   prebuilt release from the [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases)
   or build it yourself. Drop `whisper-server.exe`, `whisper-cli.exe`, and the
   accompanying DLLs into `runtime/whisper-cpp/`.
2. **Download a model** into `runtime/whisper-cpp/model/`. Models live on
   [Hugging Face](https://huggingface.co/ggerganov/whisper.cpp). The filename
   must be `ggml-<VOICETYPE_WHISPER_MODEL>.bin`, e.g. `ggml-large-v3-turbo.bin`.
3. `VOICETYPE_STT_PROVIDER=local` is the default — just run.

### Choosing a GPU backend (Vulkan / CUDA / CPU)

whisper.cpp ships separate builds per backend. VoiceType is backend-agnostic —
it just runs whatever binaries you drop into `runtime/whisper-cpp/`. The launch
flags (`-dev 0` to select GPU device 0, `-t 4` threads) are the same across
backends, so **switching backend = swapping the binaries**.

- **Vulkan** (default, works on AMD / Intel / NVIDIA): download the
  `whisper-...-vulkan-x64.zip` release. Broadest hardware support.
- **CUDA** (NVIDIA only, usually fastest on NVIDIA): download the
  `whisper-...-cublas-...-x64.zip` (cuBLAS/CUDA) release that matches your CUDA
  toolkit version, **or** build with CUDA enabled:

  ```bash
  git clone https://github.com/ggml-org/whisper.cpp
  cd whisper.cpp
  cmake -B build -DGGML_CUDA=1
  cmake --build build --config Release
  ```

  Copy the resulting `whisper-server.exe`, `whisper-cli.exe`, and the CUDA
  runtime DLLs (`cudart*.dll`, `cublas*.dll`, `ggml-cuda.dll`, …) into
  `runtime/whisper-cpp/`. Make sure the [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)
  is installed and on `PATH`. No code or config change is needed — `-dev 0`
  picks the first CUDA device automatically.
- **CPU only**: download the plain CPU release. Slower, but zero GPU
  dependencies. VoiceType already falls back to CPU (`--no-gpu`) if the GPU path
  fails.

> Tip: set **`VOICETYPE_WHISPER_PROMPT`** in `.env` to a comma-separated list of
> your own jargon (product names, acronyms, English terms you dictate). Whisper
> conditions decoding on it, so those words get spelled consistently and survive
> ru↔en code-switching. Measurably closes the gap to cloud STT on mixed speech.

---

## Advanced: cloud STT (Google Chirp 3)

Local Whisper is the default. If you'd rather transcribe with Google's Chirp 3
(strong on `ru-RU` + `en-US` code-switching), enable cloud STT:

1. Create a Google Cloud project and enable the **Cloud Speech-to-Text** API.
2. Create a service account, grant it Speech-to-Text access, and download its
   JSON key.
3. In `.env`:
   ```
   VOICETYPE_STT_PROVIDER=cloud
   GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/your/gcp-key.json
   GCP_PROJECT_ID=your-project-id
   ```

In the default `local` mode, cloud STT is **not** used. If you explicitly set
`VOICETYPE_CLOUD_FALLBACK=1`, VoiceType uses cloud STT as a one-shot fallback
when local Whisper returns nothing (only when GCP credentials are configured).

---

## Text cleanup modes

Selectable from the tray (or forced via the tray menu):

| Mode | Engine | Latency | Notes |
|---|---|---|---|
| **Auto** (default) | picks per-utterance | — | short → fast (regex); long → Gemini if a key is set, else fast |
| **Fast** | regex | ~0 ms | filler removal, punctuation, paragraphs — fully offline |
| **Full** | Gemini 2.5 Flash | ~2–3 s | best polish; needs `GEMINI_API_KEY` (free) or Vertex creds |
| **Local** | Ollama | ~varies | optional; needs [Ollama](https://ollama.com/) on `:11434`. Small models may rephrase — prefer Fast or Full |

All cleanup engines fail open: on timeout or error you still get your raw words.

---

## Cypher — voice assistant

Prefix an utterance with the wake word **"Cypher"** / **"Сайфер"** to run a
command instead of dictating. Cypher is intentionally narrow and safe — it
executes only a fixed allowlist, with **no shell pass-through** and no
arbitrary code execution.

Examples:

- *"Cypher, open VS Code"* — launch a local app (fuzzy app-name resolver)
- *"Cypher, open youtube.com"* — open a URL
- *"Cypher, search for the price of an iPhone"* — web search
- *"Cypher, read the last 5 messages in <chat>"* — Telegram Web
- *"Cypher, send a screenshot to Saved Messages"* — screenshot → Telegram Web
- *"Cypher, write <chat>: I'll be there in 15 minutes"* — send a Telegram message

A fast deterministic regex parser handles the common phrasings (L1). If you set
`VOICETYPE_CYPHER_PLANNER=gemini` (requires GCP / Vertex), an optional Gemini
planner (L2) maps freer phrasings onto the **same** safe command set — it can
never invent new actions.

**Telegram automation** drives Telegram Web via a Playwright-controlled browser
with a persistent profile under `runtime/playwright/` (gitignored). Log in once:

```bash
uv run python scripts/telegram_web_smoke.py
```

Scan the QR / log in in the window that opens; the session is reused afterwards.
Playwright browsers install with `uv run playwright install chromium`.

---

## Autostart (optional)

`scripts/watchdog.ps1` is a tiny watchdog: it launches `pythonw -m
voice_type.main` hidden, checks every 30 s, and relaunches the worker if it
dies. To run VoiceType at logon, install current-user autostart. This writes
both a Startup shortcut and an `HKCU\...\Run\VoiceType` fallback; the watchdog
uses a mutex, so duplicate logon triggers do not create duplicate watchdogs.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-startup-link.ps1
```

`scripts/restart.bat` kills and relaunches the worker manually (resolves the
repo root relative to itself, so it works wherever the repo is checked out).

To inspect login triggers and running workers/watchdogs:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/audit-autostart.ps1
```

Optional stronger resume hook: if Windows sleep/resume still kills the tray
worker or the watchdog and Task Scheduler creation is allowed on your account,
install the resilience tasks. They run an idempotent guard at logon and after
`Microsoft-Windows-Power-Troubleshooter` resume events:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-resilience-tasks.ps1
```

If it reports duplicate login triggers (`HKCU Run` + `Startup` link), remove the
Startup link safely with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/audit-autostart.ps1 -RemoveStartupLinkIfRunKeyExists
```

---

## Development

```bash
uv run pytest        # 177 tests
uv run ruff check .  # lint
uv run pyright       # type-check (strict)
```

### Project layout

```
voice_type/
├── main.py            # entry point, startup sequence, threading model
├── controller.py      # async state machine: record → STT → cleanup → paste
├── config.py          # .env loading + fail-fast validation
├── audio.py           # mic capture (sounddevice), silence trimming
├── hotkey.py          # Win32 RegisterHotKey listener
├── stt.py             # cloud STT (Google Chirp 3 / Speech v2)
├── stt_whisper.py     # local STT (whisper.cpp server + CLI fallback)
├── llm.py             # Gemini cleanup (AI Studio key or Vertex AI)
├── llm_local.py       # Ollama cleanup (optional)
├── cleanup.py         # regex fast-clean (filler removal, paragraphs)
├── paste.py           # paste into the captured foreground window
├── tray.py            # system tray icon + menus
├── cypher.py          # Cypher command parsing + safe executor (allowlist)
├── cypher_planner.py  # optional Gemini L2 command planner
├── app_resolver.py    # fuzzy local-app name resolution
├── telegram_web.py    # Telegram Web automation via Playwright
└── screen_capture.py  # screenshot helper
```

---

## License

[MIT](LICENSE)
