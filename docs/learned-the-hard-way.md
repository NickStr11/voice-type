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

**Фикс (частичный, вероятностный).** `VOICETYPE_VOCAB_BIAS` в `.env` — список терминов
нуджит модель к латинице. **Подтверждено рабочим** (2026-06-02): термины ИЗ списка
(`Opus`, `Sonnet`) легли латиницей, термин НЕ из списка (`respawn`) — кириллицей.
Это нудж, не гарантия: даже слово из списка может промахнуться вероятностно
(«Whisper» был в списке и всё равно вышел «Выспера»). Держи актуальный список живых
терминов; мёртвые (Chirp/Vertex/Ollama) — выкидывай.

**Источник.** Cortex diary 067/068, сессия 2026-06-02.
