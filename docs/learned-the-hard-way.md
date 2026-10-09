# Learned the Hard Way — VoiceType

> Lookup-рецепты по симптомам. Формат: **симптом → причина → фикс → источник**.
> Сначала grep сюда по симптому, потом копай.

---

## 1. Два процесса `pythonw.exe -m voice_type.main` (НЕ баг)

**Симптом.** В диспетчере/`wmic` всегда висят два воркера `-m voice_type.main`:
один из `.venv\Scripts\pythonw.exe`, второй из системного
`C:\Users\User\AppData\Local\Programs\Python\Python312\pythonw.exe`. Системный
«респаунится» через ~12с после kill — кажется, что есть второй скрытый лаунчер.

**Причина.** Второго лаунчера НЕТ. Это **один логический инстанс**:

- `.venv\Scripts\pythonw.exe` — это **redirector-style venv launcher** (создан так,
  что делает `CreateProcess` базового интерпретатора вместо загрузки in-process).
  Он спавнит `Python312\pythonw.exe` (тот самый `home` из `.venv\pyvenv.cfg`)
  дочерним процессом — и **этот child крутит `main()`**, а трамплин висит родителем.
- В `wmic` оба показывают `-m voice_type.main` в commandline и parent→child связь
  с разницей ~12мс. Это launcher + worker, а не два конкурента.
- «Респаун за 12с» — это легитимный watchdog `scripts/voicetype.vbs` (цикл 30с,
  ловит ~на 12-й секунде своего тика), а не мистический лаунчер.

**Как проверить (доказательства).**
```bash
# 1. Родословная: системный воркер — child .venv-воркера, разница ~12мс
MSYS_NO_PATHCONV=1 wmic process where "name='pythonw.exe'" get processid,parentprocessid,commandline,creationdate /format:csv

# 2. Убей ТОЛЬКО Python312-child при мёртвом watchdog → .venv-трамплин умрёт сам, respawn'а НЕТ
# 3. Один чистый запуск .venv pythonw → ровно 2 процесса, parent→child
MSYS_NO_PATHCONV=1 cmd /c start "" ".venv\Scripts\pythonw.exe" -m voice_type.main

# 4. В логе на каждый запуск РОВНО один "Config loaded" + один "Hotkey registered".
#    "registration failed" — единичные транзиенты при гонке respawn, не steady state.
grep -c "Config loaded\|Hotkey registered\|registration failed" runtime/voicetype.log
```

**Фикс.** Вреда нет (хоткей регает один воркер, оба читают один `.env`, трамплин ест
пару МБ idle) — **по умолчанию НЕ чинить**. Если нужен ровно 1 python-процесс:
пересоздать venv стандартным `python -m venv` (его `python.exe` грузит базовый
интерпретатор in-process, без child). Инвазивно — переустановка deps + pywin32 +
whisper-обвязка. Делать только по явному запросу.

**Источник.** Cortex diary 067/068, сессия 2026-06-02.

---

## 2. Англ-слова в русской речи пишутся кириллицей (code-switching, предел модели)

**Симптом.** Whisper пишет английские термины в русской речи кириллицей:
«роу»=raw, «Выспера»=whisper, «эйджент»=agent.

**Причина.** Code-switching — предел STT-модели на смешанной речи. Чистый whisper
не знает, что слово надо латиницей.

**Фикс (частичный, вероятностный).** `VOICETYPE_WHISPER_PROMPT` в `.env` — список терминов
нуджит модель к латинице. **Подтверждено рабочим** (2026-06-02): термины ИЗ списка
(`Opus`, `Sonnet`) легли латиницей, термин НЕ из списка (`respawn`) — кириллицей.
Это нудж, не гарантия: даже слово из списка может промахнуться вероятностно
(«Whisper» был в списке и всё равно вышел «Выспера»). Держи актуальный список живых
терминов. Старое имя `VOICETYPE_VOCAB_BIAS` больше не читается кодом.

**Источник.** Cortex diary 067/068, сессия 2026-06-02.

---

## 3. После обновления AMD-драйвера whisper крашит GPU → откат на CPU (~35с вместо ~0.3с)

**Симптом.** Транскрипция стала «вечной» (~35-42с на запись). В `runtime/voicetype.log`:
```
whisper-server unavailable — falling back to CLI
whisper-cli GPU failed (code 3221226505)   ← 0xC0000409, дважды
CLI GPU failed twice, falling back to CPU
whisper-cli CPU done in 34.33s
```
Прямой прогон `whisper-cli -dev 0` падал на старте Vulkan с
`GGML_ASSERT(prev != ggml_uncaught_exception) failed` (старый бинарь) либо тихо
на первой аллокации VRAM (свежий бинарь, EXIT=5, не доходя до `Vulkan0 total size`).

**Причина (две независимые).**
1. **Implicit Vulkan-слои** (Bandicam, RenderDoc, Steam overlay, AMD switchable-graphics)
   автоинжектятся в КАЖДОЕ Vulkan-приложение и крашат whisper на первой аллокации VRAM.
   Видно в `vulkaninfo --summary` → раздел *Instance Layers*. Сам `vulkaninfo` при этом
   живой — обманчиво «Vulkan ок».
2. **KHR_coopmat** (cooperative-matrix matmul) на новом драйвере крашит уже на вычислениях
   (проходит аллокацию, падает в инференсе, EXIT=9).

Старый бинарь (март, ggml `C:\Users\jerry\...`) не лечится одними env — нужен свежий билд.

**Фикс (применён 2026-06-08, без отката драйвера).**
1. Пересобрать whisper.cpp с Vulkan под новый драйвер — **одной командой**:
   `pwsh -File scripts/build-whisper-vulkan.ps1` (качает w64devkit+ninja в `runtime/build/`,
   клонит whisper.cpp на пиннутый тег, собирает `-G Ninja -DGGML_VULKAN=ON -DBUILD_SHARED_LIBS=ON`,
   бэкапит старые бинари → `backup-pre-YYYY-MM-DD/`, ставит новые в `runtime/whisper-cpp/`).
   Билд самодостаточный (static libstdc++). Версии whisper.cpp/w64devkit — параметры скрипта.
2. Прокинуть в env обоих процессов (`stt_whisper.py`, константа `_VULKAN_ENV`):
   ```
   VK_LOADER_LAYERS_DISABLE=~implicit~   # гасим оверлей-слои ТОЛЬКО для нашего процесса
   GGML_VK_DISABLE_COOPMAT=1             # обходим битый coopmat
   ```
**Результат.** GPU снова горячий: server `/inference` ~0.7с (было 35-42с CPU).

**Диагностика-чеклист на будущее (тот же симптом).**
- `grep "GPU failed\|server unavailable\|CPU done" runtime/voicetype.log` — подтвердить откат на CPU.
- `grep "whisper-server done" runtime/voicetype.log | tail` — когда GPU работал в последний раз (ищи регрессию по времени).
- `whisper-cli -dev 0` напрямую на `test.wav` — изолировать GPU от пайплайна.
- `vulkaninfo --summary` → *Instance Layers*: ищи implicit оверлеи (Bandicam/RenderDoc/Steam).
- Тумблеры по одному: `VK_LOADER_LAYERS_DISABLE=~implicit~`, `GGML_VK_DISABLE_COOPMAT=1`, `-nfa`.

**Источник.** Cortex session 2026-06-08 (драйвер RX 7800 XT обновился между утром и вечером).

---

## 4. После выхода из сна первая запись медленная / «STT ушёл на проц»

**Симптом.** После выхода из спящего режима первая транскрипция тормозит (~20-25с),
выглядит как откат на CPU. В `runtime/voicetype.log` (gap во времени = сон):
```
whisper-server request failed: HTTP Error 500: Internal Server Error
whisper-server failed once, restarting and retrying once
Starting whisper-server in background
Whisper server ready                  # ~19с: перезагрузка модели в VRAM
whisper-server done in 2.15s          # GPU снова работает (НЕ 'CPU done in 34s')
```

**Причина.** whisper-server переживает сон (HTTP-слой жив, `/health` отвечает 200),
но его **Vulkan-device инвалидируется при resume** → первый `/inference` падает с 500.
Это НЕ откат на CPU — авто-рестарт сервера лечит, но рестарт = перезагрузка 1.6GB
модели в VRAM (~19с), и поэтому ПЕРВАЯ запись после сна медленная. Дальше всё быстро.

**Фикс (обновлён 2026-07-15).** Сервер прогревается в фоне при старте приложения
и остаётся резидентным. Попытка 2026-07-13 выгружать его после 120с простоя
откатана: каждая первая диктовка после паузы платила 11-17с холодного старта, а
idle-watcher мог убить сервер прямо во время прогрева. Wall-clock gap-детектор
после настоящего resume останавливает переживший сон процесс и сразу прогревает
новый (`_restart_server_sync()`). Запись ждёт `_server_ready` до 60с (холодный
старт после загрузки системы бывает 25-38с). Реактивный путь (500 → restart)
оставлен как подстраховка.

**Почему gap-детектор, а не `WM_POWERBROADCAST`.** Native power-event требует скрытого
окна + message pump; gap-детектор — ~25 строк, без win32 и без message loop.
`time.time()` (wall clock) тикает во время сна → gap виден; `time.monotonic()` на
Windows во сне может не тикать, поэтому именно `time.time()`.

**Источник.** Cortex session 2026-06-08 (тот же box, после фикса §3).
