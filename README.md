# VoiceType

Push-to-talk dictation for Windows — press a hotkey, speak, and clean text
appears in whatever window was focused. Includes **Cypher**, an optional
voice assistant for launching apps, web search, and Telegram automation.

- 🎙️ **Global hotkey** — toggle recording from anywhere, paste into the active window.
- 🧠 **Two STT backends** — local **Whisper** (GPU, fully offline) or cloud **Google Chirp 3**.
- ✨ **Smart cleanup** — regex (0 ms), local LLM (Ollama), or Gemini, picked automatically.
- 🤖 **Cypher voice agent** — say "Cypher, open VS Code" / "Cypher, send a screenshot to Telegram".
- 🟢 **System tray** — switch backends and cleanup modes on the fly.
- ♻️ **Autostart watchdog** — survives logoff/crash, keeps itself alive.

> Windows only (uses Win32 `RegisterHotKey`, `pywin32`, and the system tray).
> Russian + English speech are supported out of the box.

---

## How it works

```
hotkey ──▶ record mic ──▶ hotkey ──▶ STT ──▶ cleanup ──▶ paste into active window
                                      │
                          ┌───────────┴───────────┐
                          │                       │
                   local Whisper            Google Chirp 3
                   (whisper.cpp, GPU)       (Cloud STT v2)
```

The window that is focused **when you stop recording** is the paste target —
so you can start talking, tab away, and the text still lands in the right place.

If a transcript starts with the wake word **"Cypher"** (or "Сайфер"), it is
routed to the Cypher command parser instead of being pasted.

---

## Requirements

- **Windows 10/11**
- **Python 3.12+**
- [**uv**](https://docs.astral.sh/uv/) (package manager)
- A working microphone
- For **local STT**: a GPU + a [whisper.cpp](https://github.com/ggml-org/whisper.cpp) build (see [Local STT setup](#local-stt-setup-whisper))
- For **cloud STT / Gemini cleanup**: a Google Cloud project with the Speech-to-Text and Vertex AI APIs enabled

You only need *one* STT backend. Local is fully offline and free; cloud is
zero-setup on the machine but needs GCP credentials.

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

## Configuration

All settings live in `.env` (copied from `.env.example`). `.env` is gitignored —
**never commit it**.

| Variable | Required | Default | Description |
|---|---|---|---|
| `VOICETYPE_STT_PROVIDER` | no | `cloud` | `local` (Whisper) or `cloud` (Chirp 3) |
| `VOICETYPE_HOTKEY` | no | `<ctrl>+<alt>+r` | Recording toggle hotkey |
| `VOICETYPE_WHISPER_MODEL` | no | `large-v3-turbo` | Model name (local only); file `ggml-<name>.bin` |
| `GOOGLE_APPLICATION_CREDENTIALS` | for cloud | — | Path to GCP service-account JSON |
| `GCP_PROJECT_ID` | for cloud | — | GCP project ID |
| `VOICETYPE_STT_REGION` | no | `us` | Cloud STT regional endpoint prefix |
| `VOICETYPE_CYPHER_PLANNER` | no | `off` | `gemini` enables the L2 natural-language command planner |
| `VOICETYPE_CYPHER_PLANNER_MODEL` | no | `gemini-2.5-flash` | Planner model |

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
3. Set `VOICETYPE_STT_PROVIDER=local` in `.env` and run.

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

> Tip: customize the dictation **vocabulary bias** for your own jargon (product
> names, acronyms) in `voice_type/stt_whisper.py` (`_encode_multipart`, the
> `prompt` field). It helps Whisper spell your terms consistently and survive
> ru↔en code-switching.

---

## Cloud STT setup (Google Chirp 3)

1. Create a Google Cloud project and enable **Cloud Speech-to-Text** and
   **Vertex AI** APIs.
2. Create a service account, grant it Speech-to-Text + Vertex AI access, and
   download its JSON key.
3. In `.env`:
   ```
   VOICETYPE_STT_PROVIDER=cloud
   GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/your/gcp-key.json
   GCP_PROJECT_ID=your-project-id
   ```

Chirp 3 handles `ru-RU` + `en-US` and short-form/code-switching well. When you
run in `local` mode **with** cloud also configured, VoiceType races both
backends in parallel and prefers the cloud result, degrading gracefully to the
local transcript if the cloud call fails.

---

## Text cleanup modes

Selectable from the tray (or forced via the tray menu):

| Mode | Engine | Latency | Notes |
|---|---|---|---|
| **Auto** (default) | picks per-utterance | — | short/finished → fast, long/unfinished → full |
| **Fast** | regex | ~0 ms | filler removal, punctuation, paragraphs — fully offline |
| **Local** | Ollama (`qwen2.5:1.5b`) | ~0.3 s | needs [Ollama](https://ollama.com/) running on `:11434` |
| **Full** | Gemini 2.5 Flash (Vertex AI) | ~1.5–3 s | best polish, needs GCP creds |

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
`VOICETYPE_CYPHER_PLANNER=gemini`, an optional Gemini planner (L2) maps freer
phrasings onto the **same** safe command set — it can never invent new actions.

**Telegram automation** drives Telegram Web via a Playwright-controlled browser
with a persistent profile under `runtime/playwright/` (gitignored). Log in once:

```bash
uv run python scripts/telegram_web_smoke.py
```

Scan the QR / log in in the window that opens; the session is reused afterwards.
Playwright browsers install with `uv run playwright install chromium`.

---

## Autostart (optional)

`scripts/voicetype.vbs` is a tiny watchdog: it launches `pythonw -m
voice_type.main` hidden, checks every 30 s, and relaunches the worker if it
dies. To run VoiceType at logon, create a shortcut to `voicetype.vbs` in your
Startup folder (`shell:startup`).

`scripts/restart.bat` kills and relaunches the worker manually (resolves the
repo root relative to itself, so it works wherever the repo is checked out).

---

## Development

```bash
uv run pytest        # 140 tests
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
├── llm.py             # Gemini cleanup (Vertex AI)
├── llm_local.py       # Ollama cleanup
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
