"""Gemini-based L2 planner for Cypher commands.

Fast regex parsing remains L1. This planner is only used when:
- utterance has an explicit Cypher prefix
- rule parser could not map it to an existing safe command

The planner is intentionally narrow:
- returns one existing safe capability only
- no arbitrary shell, no file deletion, no system-destructive actions
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Final, cast

from google import genai
from google.genai import types
from loguru import logger

from voice_type.cypher import CommandKind, CypherCommand, is_sensitive_app_target, normalize_open_url

_MODEL_DEFAULT: Final[str] = "gemini-2.5-flash"
_TIMEOUT_S: Final[float] = 4.0
_ALLOWED_KINDS: Final[set[str]] = {
    "open_app",
    "open_url",
    "refresh_apps",
    "telegram_read_last_messages",
    "telegram_search_messages",
    "telegram_saved_messages",
    "telegram_send_message",
    "telegram_send_screenshot",
    "web_search",
    "none",
}
_SAVED_MESSAGES_MARKERS: Final[tuple[str, ...]] = (
    "saved messages",
    "saved message",
    "сохраненные сообщения",
    "сохранённые сообщения",
    "избранное",
    "мне",
)
_JSON_RE: Final[re.Pattern[str]] = re.compile(r"\{.*\}", re.DOTALL)
_PROMPT_TEMPLATE: Final[str] = """Ты маршрутизатор голосовых команд для Windows-ассистента Cypher.

Разрешенные команды:
- open_app: открыть локальное приложение
- open_url: открыть конкретный URL в браузере
- web_search: поиск в интернете
- refresh_apps: обновить индекс приложений
- telegram_read_last_messages: прочитать последние сообщения в Telegram Web
- telegram_search_messages: найти сообщения в Telegram Web по тексту
- telegram_saved_messages: открыть Saved Messages в Telegram Web
- telegram_send_message: отправить сообщение в Telegram Web
- telegram_send_screenshot: сделать скрин экрана и отправить в Telegram Web
- none: если запрос опасный, неподдерживаемый или неоднозначный

Строгие правила:
1. Возвращай ТОЛЬКО JSON, без markdown и пояснений.
2. Не придумывай новые kind.
3. Не выполняй опасные действия: delete, remove, format, powershell, shell, registry, shutdown, buy.
4. Для telegram_send_message:
   - value = имя чата
   - message = текст сообщения
5. Для telegram_read_last_messages:
   - value = имя чата
   - count = сколько последних сообщений прочитать, по умолчанию 5
6. Для telegram_search_messages:
   - value = имя чата
   - message = текст запроса для поиска
5. Для telegram_send_screenshot:
   - value = имя чата
   - если пользователь говорит "мне" или про сохраненные сообщения, value = "Saved Messages"
7. Для telegram_saved_messages:
   - value = "Saved Messages"
8. Для refresh_apps:
   - value = "refresh"
9. Для open_url:
   - value = полный URL с https://
10. Если пользователь просит открыть сайт/веб-версию Telegram, это open_url.
11. Если это похоже на обычную диктовку, верни none.

Примеры:
{{"kind":"open_app","value":"steam"}}
{{"kind":"web_search","value":"цена на iphone 16"}}
{{"kind":"telegram_read_last_messages","value":"Adam","count":5}}
{{"kind":"telegram_search_messages","value":"Adam","message":"аптека"}}
{{"kind":"telegram_saved_messages","value":"Saved Messages"}}
{{"kind":"telegram_send_message","value":"Adam","message":"привет, я подъеду через 15 минут"}}
{{"kind":"telegram_send_screenshot","value":"Saved Messages"}}
{{"kind":"refresh_apps","value":"refresh"}}
{{"kind":"none"}}

Команда: {command}
"""


class GeminiCypherPlanner:
    """Gemini planner that maps natural Cypher utterances to safe commands."""

    def __init__(
        self,
        project: str,
        model: str = _MODEL_DEFAULT,
        location: str = "us-central1",
    ) -> None:
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model
        logger.info(f"Cypher planner ready — model: {model}, timeout: {_TIMEOUT_S}s, project: {project}")

    def plan(self, command_body: str) -> CypherCommand | None:
        """Plan a natural language Cypher command into one safe existing command."""
        if not command_body.strip():
            return None

        prompt = _PROMPT_TEMPLATE.format(command=command_body.strip())

        def _sync_call() -> str:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            return (response.text or "").strip()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_sync_call)
        try:
            raw = future.result(timeout=_TIMEOUT_S)
            command = command_from_planner_json(raw)
            if command is not None:
                logger.info(f"Cypher planner matched: {command.kind} -> {command.spoken_target}")
            else:
                logger.info("Cypher planner returned no safe command")
            return command
        except concurrent.futures.TimeoutError:
            logger.warning(f"Cypher planner timed out after {_TIMEOUT_S}s")
            return None
        except Exception as exc:
            logger.warning(f"Cypher planner error: {exc}")
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def command_from_planner_json(raw_text: str) -> CypherCommand | None:
    payload_text = _extract_json(raw_text)
    if payload_text is None:
        return None

    data = json.loads(payload_text)
    if not isinstance(data, dict):
        return None
    data_map = cast(dict[str, object], data)

    raw_kind = data_map.get("kind")
    if not isinstance(raw_kind, str):
        return None
    kind = raw_kind.strip()
    if kind not in _ALLOWED_KINDS or kind == "none":
        return None

    if kind == "refresh_apps":
        return CypherCommand(kind="refresh_apps", value="refresh", spoken_target="список приложений")

    raw_value = data_map.get("value", "")
    value = raw_value.strip() if isinstance(raw_value, str) else ""

    if kind == "telegram_saved_messages":
        return CypherCommand(kind="telegram_saved_messages", value="Saved Messages", spoken_target="Saved Messages")

    if kind == "telegram_send_screenshot":
        target = _normalize_saved_messages(value)
        if not target:
            return None
        return CypherCommand(kind="telegram_send_screenshot", value=target, spoken_target=target)

    if kind == "telegram_send_message":
        raw_message = data_map.get("message", "")
        message = raw_message.strip() if isinstance(raw_message, str) else ""
        target = _normalize_saved_messages(value)
        if not target or not message:
            return None
        return CypherCommand(
            kind="telegram_send_message",
            value=target,
            spoken_target=target,
            message=message,
        )

    if kind == "telegram_read_last_messages":
        target = _normalize_saved_messages(value)
        raw_count = data_map.get("count", 5)
        if isinstance(raw_count, str):
            try:
                count = int(raw_count.strip())
            except ValueError:
                count = 5
        elif isinstance(raw_count, int):
            count = raw_count
        else:
            count = 5
        if not target:
            return None
        return CypherCommand(
            kind="telegram_read_last_messages",
            value=target,
            spoken_target=target,
            count=max(1, min(count, 20)),
        )

    if kind == "telegram_search_messages":
        raw_message = data_map.get("message", "")
        message = raw_message.strip() if isinstance(raw_message, str) else ""
        target = _normalize_saved_messages(value)
        if not target or not message:
            return None
        return CypherCommand(
            kind="telegram_search_messages",
            value=target,
            spoken_target=target,
            message=message,
        )

    if not value:
        return None

    if kind == "open_url":
        url = normalize_open_url(value)
        if url is None:
            return None
        return CypherCommand(kind="open_url", value=url, spoken_target=url)

    if kind == "open_app" and is_sensitive_app_target(value):
        return None

    allowed_kind = cast(CommandKind, kind)
    return CypherCommand(kind=allowed_kind, value=value, spoken_target=value)


def _extract_json(raw_text: str) -> str | None:
    candidate = raw_text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate
    match = _JSON_RE.search(candidate)
    if match is None:
        return None
    return match.group(0)


def _normalize_saved_messages(value: str) -> str:
    if not value:
        return ""
    normalized = value.casefold()
    if any(marker in normalized for marker in _SAVED_MESSAGES_MARKERS):
        return "Saved Messages"
    return value
