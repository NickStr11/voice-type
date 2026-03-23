# Pitfalls Research

**Domain:** Voice-to-text desktop app (Windows 11, Python, Google Cloud STT V2 + Gemini Flash, global hotkeys, clipboard paste)
**Researched:** 2026-03-23
**Confidence:** HIGH (audio/hotkey: HIGH from official issues + confirmed bugs; paste timing: HIGH from Superwhisper production reports; GCP: HIGH from official docs + live issue tracker)

---

## Critical Pitfalls

### Pitfall 1: Paste lands in wrong window — transcription steals focus

**What goes wrong:**
The app processes audio, writes text to clipboard, then sends Ctrl+V — but during the ~1-2 seconds of STT + LLM processing, the user has already switched windows (clicked elsewhere, Alt+Tabbed). Ctrl+V pastes into whatever is focused now, not what was focused when recording stopped.

**Why it happens:**
Developers test by holding still while waiting. Real users don't. The active window at hotkey-release time and at paste time are different entities. Nothing in `pyperclip.copy()` + `pyautogui.hotkey('ctrl','v')` saves a reference to the original window — it just fires at whatever has focus at paste time.

**How to avoid:**
1. At hotkey release (recording stop), immediately capture a handle to the foreground window: `hwnd = win32gui.GetForegroundWindow()`.
2. Before pasting, restore focus to that handle: `win32gui.SetForegroundWindow(hwnd)`, then add a 50ms sleep, then send Ctrl+V.
3. If the target window is gone (closed), surface a tray notification with the transcribed text rather than silently pasting nowhere.

**Warning signs:**
- During manual testing, text appears in wrong app intermittently.
- Works fine when tested slowly, breaks when tested quickly.
- Superwhisper (production) has documented this as a reported bug in their Windows beta.

**Phase to address:** Phase 1 (core paste loop). Must be built correctly from day one — retrofitting is painful because it changes the paste sequence contract.

---

### Pitfall 2: Chirp 2 latency spikes in non-us-central1 regions

**What goes wrong:**
Chirp 2 is only GA in `us-central1`, `asia-southeast1`, and `europe-west4`. Using `global` endpoint or `europe-west4` from Russia results in either connection failures or latency of 3-8 seconds instead of <500ms, completely breaking the "feels instant" requirement.

**Why it happens:**
Developers initialize `SpeechClient()` without specifying a regional endpoint, which routes to the global endpoint. The global endpoint does not support Chirp 2 (V2 API requires explicit regional routing via `ClientOptions(api_endpoint="REGION-speech.googleapis.com")`).

**How to avoid:**
- Hardcode `us-central1-speech.googleapis.com` as the endpoint — it has the best latency from Eastern Europe in practice.
- Test round-trip time to the endpoint on first run and log it. If >1500ms, warn in the tray.
- Never use `SpeechClient()` without `ClientOptions`.

**Warning signs:**
- `google.api_core.exceptions.InvalidArgument` or silent fallback to V1 model.
- Transcription works but takes 4-6 seconds.
- Loglines showing `global-speech.googleapis.com` instead of regional.

**Phase to address:** Phase 1 (STT integration). Bake regional endpoint config in from the start, not after noticing slowness.

---

### Pitfall 3: Windows microphone permission silently crashes audio

**What goes wrong:**
`sounddevice` opens a PortAudio stream and crashes with `PortAudioError: Error opening InputStream` with no clear message that microphone permission is the cause. On a fresh Windows 11 install or after a privacy settings reset, Python processes don't have microphone access. The error looks like a device or driver issue, not a permissions issue.

**Why it happens:**
Windows 11 Privacy Settings → Microphone requires explicit opt-in per-app. Python.exe is not an app in the traditional sense, so the permission often defaults to denied. PortAudio talks to WASAPI which checks the permission at stream open time and returns `-9999 (unanticipated host error)` without explaining why.

**How to avoid:**
- On first launch, run a permission check: attempt to open a 0.1s test stream and catch `PortAudioError`. If it fails, launch a dialog (or tray notification) with exact instructions: Settings → Privacy → Microphone → enable "Let desktop apps access your microphone".
- Include this as a setup wizard step, not a runtime crash.

**Warning signs:**
- `PortAudioError` with code `-9999` or `Device unavailable`.
- Works in one environment (dev machine), fails silently for fresh installs.
- Antivirus can also block PortAudio — similar symptoms.

**Phase to address:** Phase 1 (audio recording). Must be the first thing tested on a fresh Windows 11 VM, not after packaging.

---

### Pitfall 4: pynput hotkey conflicts and suppress trap

**What goes wrong:**
Two separate traps:
1. `suppress=True` on the keyboard listener blocks ALL keyboard input for the entire OS — Alt+Tab, typing, everything stops working until the listener is released.
2. pynput `GlobalHotKeys` can conflict with system-reserved hotkeys (Win+key combinations). Windows intercepts these at a lower level before pynput sees them.

For this project: using Win+key as the recording trigger may silently fail or be intercepted by Windows before pynput's hook fires.

**Why it happens:**
pynput uses `SetWindowsHookExW(WH_KEYBOARD_LL)` — a low-level keyboard hook. `suppress=True` suppresses ALL events in the hook chain. Win+key combinations are often consumed by the shell (explorer.exe) before the hook chain is reached.

**How to avoid:**
- Use `keyboard` library instead of pynput for the hotkey, or use `ctypes` `RegisterHotKey` (Win32 API) which is the correct mechanism for system-wide hotkeys. `RegisterHotKey` gets first dibs before window hooks.
- Never use `suppress=True` globally — use `win32_event_filter` for selective suppression of only the recording hotkey.
- Default hotkey should avoid Win+key. Use Ctrl+Alt+R or similar, let user configure.
- Listener callbacks must be non-blocking (dispatch to a queue, handle in a separate thread).

**Warning signs:**
- Hotkey works in testing but stops working when specific apps (games, browsers, Telegram) are in focus.
- Pressing the hotkey freezes keyboard for 1-2 seconds.
- Win+key hotkey stops working after Windows updates.

**Phase to address:** Phase 1 (hotkey system). Architecture decision — RegisterHotKey vs hook — must be made before any other feature is built.

---

### Pitfall 5: Gemini Flash hanging indefinitely on text cleanup step

**What goes wrong:**
Gemini 2.x Flash (and 2.5 Flash) intermittently hang at the socket level without returning an error or triggering Python's timeout mechanisms. Standard `requests.Timeout` does not catch this — the socket stays open, the call blocks forever, and the app appears frozen with no feedback to the user.

**Why it happens:**
Confirmed active bug in `googleapis/python-genai`: under load, the API stops returning 503 and instead holds the connection open without responding. Python's default `socket.timeout` does not trigger because the socket is technically "connected." This behavior has been observed specifically with structured output requests and with 2.5 Flash thinking mode (which is on by default).

**How to avoid:**
- Wrap every Gemini call with a `concurrent.futures.ThreadPoolExecutor` + `Future.result(timeout=8)` — this provides a hard wall-clock timeout that works even when socket stays open.
- Disable thinking explicitly: `generation_config={"thinking_config": {"thinking_budget": 0}}` — it's enabled by default in 2.5 Flash and adds 1-3s latency.
- Keep the cleanup prompt minimal (under 50 tokens input/output) — structured output mode has higher failure rates.
- Have a fallback: if Gemini times out, paste raw STT output without cleanup rather than blocking indefinitely.

**Warning signs:**
- App hangs at "processing" step with no tray update.
- Works in unit tests (mocked) but hangs in integration tests under load.
- Gemini API dashboard shows requests in flight that never complete.

**Phase to address:** Phase 1 (LLM cleanup). Timeout wrapper and fallback path must be part of initial implementation, not added after first production hang.

---

### Pitfall 6: Clipboard clobbering the user's existing content

**What goes wrong:**
The paste flow overwrites whatever is already in the clipboard. User copies a URL, triggers a voice note, text pastes correctly — but their URL is gone. This is a significant UX regression that makes the tool feel hostile for daily use.

**Why it happens:**
`pyperclip.copy(text)` + `Ctrl+V` is the simplest implementation. It replaces the clipboard without restoring it. Most developers notice this late because during testing they don't have anything meaningful in the clipboard.

**How to avoid:**
1. Save existing clipboard content before setting it: `original = pyperclip.paste()`.
2. Set new content, send Ctrl+V, then restore: `pyperclip.copy(original)` after a 100ms delay (enough for paste to register).
3. For rich content (images, file references) that pyperclip can't restore, skip restoration and surface a tray notification: "Clipboard replaced with transcription."

**Warning signs:**
- User reports "you destroyed my clipboard" in first week of real use.
- No complaints in testing because tester knows to expect it.

**Phase to address:** Phase 1. Simple to implement correctly from the start, painful to explain to users later.

---

### Pitfall 7: Audio device index hardcoded or assumed default

**What goes wrong:**
`sounddevice.rec()` with no device argument uses whatever PortAudio considers the "default" — which changes when the user plugs in a headset, connects to a meeting, or unplugs a USB mic. The device index returned by `sounddevice.query_devices()` is not stable across plugs.

Additionally, requesting stereo recording from a mono microphone crashes with `PortAudioError: Invalid number of channels [-9998]`.

**How to avoid:**
- Always record mono (`channels=1`) regardless of device capabilities — speech recognition does not benefit from stereo and mono avoids the channels error entirely.
- Use default device (`device=None`) but wrap stream open in try/except; on failure, query devices and log what's available.
- Expose microphone selection in settings (Phase 2) but default to "system default" in Phase 1.
- Sample rate: use 16000 Hz (what Google STT expects) and let PortAudio do resampling only if necessary — better to record at native rate and resample than to force 16000 if the device rejects it.

**Warning signs:**
- Works on dev machine, fails on user's machine with USB mic or Bluetooth headset.
- `channels` parameter causes PortAudioError on first run.

**Phase to address:** Phase 1.

---

### Pitfall 8: pystray icon must run on main thread but so does everything else

**What goes wrong:**
`pystray.Icon.run()` is blocking and must be called from the main thread for platform independence (macOS requirement bleeds into the documented API). If you also need a hotkey listener and audio processing loop, you face a threading deadlock: tray needs main, hotkey needs non-blocking callbacks, audio can't block the tray.

**Why it happens:**
The pystray docs say main-thread only but then qualify "Windows is safe to thread." Developers see the caveat and thread it — which works until they need to port or until a Windows update changes COM apartment threading rules.

**How to avoid:**
- On Windows specifically: run pystray in a daemon thread, run hotkey listener in another daemon thread, run main thread as an orchestrator with a message queue.
- Use `pystray.Icon.run_detached()` — it starts the icon in its own thread and returns immediately, letting your main thread do other work.
- All cross-thread communication via `queue.Queue` — never call GUI elements from audio/hotkey threads.

**Warning signs:**
- App hangs on startup.
- Tray icon appears but is unresponsive.
- Works when run from terminal but hangs when launched as a background process.

**Phase to address:** Phase 1 (architecture). Threading model must be established before writing any feature code.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip window focus capture at recording stop | Simpler paste logic | Text pastes into wrong window under real use | Never — fix from day one |
| Use global endpoint instead of regional for Chirp 2 | No config needed | Silent fallback to wrong model or high latency | Never |
| `suppress=True` on pynput listener | Easy hotkey suppression | Freezes all keyboard input OS-wide | Never |
| No clipboard restore | 10 lines less code | Destroys user's clipboard on every use | Never in production |
| Gemini call without timeout | Simpler async flow | App hangs indefinitely on API issue | Never — always wrap |
| Hardcode `channels=2` | Familiar stereo default | Crashes on mono-only microphones | Never |
| Skip microphone permission check | Less startup logic | Silent crashes look like driver bugs | OK for local dev, not for any shared usage |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Google Cloud STT V2 | Use `SpeechClient()` without regional endpoint | `SpeechClient(client_options=ClientOptions(api_endpoint="us-central1-speech.googleapis.com"))` |
| Google Cloud STT V2 | Use `global` endpoint or V1 model ID with V2 client | Model ID must be `chirp_2`, endpoint must be regional |
| Gemini Flash | Use default `gemini-2.5-flash` without disabling thinking | Explicit `thinking_budget: 0` saves 1-3s per call |
| Gemini Flash | Rely on network timeout to catch hangs | Socket stays open — use `concurrent.futures` with wall-clock timeout |
| pynput hotkeys | Register Win+key combination | Windows shell intercepts before pynput hook; use Ctrl+Alt+key or Win32 `RegisterHotKey` |
| pyperclip + Ctrl+V | Fire immediately after `copy()` | Add 50ms sleep to allow clipboard propagation before sending Ctrl+V |
| sounddevice | Record with `channels=2` | Always use `channels=1` for speech; stereo fails on mono-only mics |
| pywin32 SetForegroundWindow | Call it and immediately send keystrokes | Add 50ms sleep — window needs time to actually get focus before keystrokes register |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Sending full audio file to STT (no VAD) | Long silences pad audio, increasing STT processing time | Implement silence trimming or VAD before sending | Any utterance with >1s trailing silence |
| Gemini cleanup on every transcription | Adds 500-2000ms always, even for already-clean text | Make cleanup conditional (short utterances, pure dictation may not need it) or run in parallel with paste | Every transcription |
| Recording in high sample rate (48kHz) | Larger audio upload, slower network transfer | Record at 16kHz natively (Google STT native rate) | Always |
| Buffering full recording before sending | Latency = full recording duration + STT time | Use streaming recognition (send chunks during recording) | Recordings >3 seconds |
| Creating new STT client per request | Connection setup overhead ~200-500ms | Reuse persistent client instance | Every request |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| GOOGLE_APPLICATION_CREDENTIALS path in code | Service account key committed to repo | Use env variable or ADC (application default credentials); never hardcode path |
| Service account key in project root | Key accidentally committed | Store in `~/.config/` or use ADC via `gcloud auth application-default login` |
| Transcribed text logged to disk | Voice content persists unintentionally | Never log transcription content by default; opt-in history only |
| API key in config file tracked by git | Credentials exposed | `.gitignore` for all `.env` and credential files; use `git-secrets` pre-commit hook |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No visual feedback during processing | User doesn't know if app heard them; speaks again, gets double input | Tray icon animates during recording AND processing — two distinct states |
| Paste happens with no confirmation | Hard to tell if it worked; confusing in terminals/IDEs | Brief tray tooltip "Pasted: first 30 chars..." for 2 seconds after paste |
| Hotkey activates while user is typing | Accidentally starts recording mid-sentence | Detect if modifier key (Ctrl/Shift) is already held; add configurable hold-to-activate minimum duration |
| Error shows nothing | API failure = silent no-paste, user confused | All error states must surface in tray as tooltip notification |
| Russian/English mismatch | Model transcribes Russian as garbled Latin or vice versa | Use `language_codes: ["ru-RU", "en-US"]` multi-language in Chirp 2 (it supports this natively) |

---

## "Looks Done But Isn't" Checklist

- [ ] **Paste flow:** Verified window focus is restored from saved hwnd, not assumed — test by Alt-Tabbing during processing delay
- [ ] **Microphone permission:** Tested on fresh Windows 11 VM with no prior Python microphone grant
- [ ] **Hotkey:** Tested while browser, Telegram, VS Code, and a game are each in focus — not just from a test script
- [ ] **Clipboard restore:** Verified original clipboard content survives a transcription cycle
- [ ] **Gemini timeout:** Verified app does not hang when Gemini call is killed with `socket.close()` in a mock
- [ ] **Regional endpoint:** Verified client config shows `us-central1-speech.googleapis.com` in logs, not global
- [ ] **Chirp 2 language:** Verified `language_codes: ["ru-RU", "en-US"]` — not `language_code` (singular, wrong V2 param name)
- [ ] **Mono audio:** Verified `channels=1` in all recording paths
- [ ] **Thread safety:** Verified tray, hotkey, audio, API all communicate via queue — no direct cross-thread calls

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Focus loss on paste — discovered in production | MEDIUM | Add hwnd capture at recording stop, restore before paste; 1-2 hour fix but requires testing all window types |
| Wrong regional endpoint — app slow | LOW | Config change + redeploy; no logic changes needed |
| Gemini hangs — app freezing | MEDIUM | Add concurrent.futures wrapper around Gemini call; 2-3 hours including timeout tuning |
| Clipboard clobber discovered by users | LOW | 20 lines of save/restore; 30 minutes to implement and test |
| Hotkey not working in some apps | HIGH | May require switching from pynput to Win32 RegisterHotKey; touches core architecture |
| Microphone permission crash | LOW | Add permission check + tray notification; isolated startup code |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Paste lands in wrong window | Phase 1 — Core paste loop | Test: start recording, Alt+Tab to notepad during processing, verify text lands in original app |
| Chirp 2 regional endpoint | Phase 1 — STT integration | Log active endpoint; measure round-trip time; verify <1s for recording <3s |
| Windows microphone permission crash | Phase 1 — Audio recording | Test on fresh Windows 11 VM with all Python microphone permissions revoked |
| pynput suppress trap / hotkey conflicts | Phase 1 — Hotkey system | Test while Telegram, Chrome, VS Code each have focus; verify no keyboard freeze |
| Gemini Flash hanging indefinitely | Phase 1 — LLM cleanup | Mock socket hang; verify app surfaces tray error and pastes raw STT output within 8s |
| Clipboard clobbering | Phase 1 — Paste | Copy a URL, trigger transcription, verify URL restored after paste |
| Audio device index / channels error | Phase 1 — Audio recording | Test with USB mic, Bluetooth headset, built-in mic; all should work without code changes |
| pystray main-thread deadlock | Phase 1 — App architecture | Verify tray remains responsive during 3-second mock STT delay |

---

## Sources

- [sounddevice microphone permission issue on Windows](https://github.com/spatialaudio/python-sounddevice/issues/293) — confirmed PortAudio permission crash
- [sounddevice invalid channels error](https://github.com/spatialaudio/python-sounddevice/issues/244) — stereo on mono device
- [pynput suppress traps all keyboard input](https://github.com/moses-palmer/pynput/issues/232) — confirmed global suppress bug
- [pynput suppress selective issue](https://github.com/moses-palmer/pynput/issues/170) — win32_event_filter limitations
- [pynput listener cannot be restarted](https://pynput.readthedocs.io/en/latest/keyboard.html) — threading.Thread restart constraint
- [Chirp 2 latency/region issue](https://github.com/livekit/agents/issues/4417) — us-central1 latency spike; EU connection failures
- [Chirp 2 official docs — available regions](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2) — us-central1, asia-southeast1, europe-west4 only
- [Gemini python-genai socket stall bug](https://github.com/googleapis/python-genai/issues/1893) — indefinite hang instead of 503
- [Gemini 2.0 latency/structured output](https://github.com/googleapis/python-genai/issues/1586) — structured output causes unexpected latency
- [pystray threading on Windows](https://github.com/moses-palmer/pystray/issues/94) — run() blocking behavior, run_detached workaround
- [Superwhisper clipboard interference issue](https://github.com/openai/codex/issues/11103) — production evidence of clipboard conflict
- [Superwhisper Windows paste not working](https://feedback.superwhisper.com/board/p/windows-version) — production evidence of Win paste failures
- [PyInstaller onefile resource path issues](https://pyinstaller.org/en/stable/when-things-go-wrong.html) — packaging gotchas
- [Google Cloud STT regional endpoints](https://cloud.google.com/speech-to-text/docs/endpoints) — official endpoint configuration

---
*Pitfalls research for: Voice-to-text desktop app (Windows 11, Python, Google Cloud STT V2 / Gemini Flash)*
*Researched: 2026-03-23*
