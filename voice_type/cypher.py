"""Cypher command parsing and execution for VoiceType.

MVP scope:
- Explicit wake phrase only ("Сайфер", "Cypher", etc.).
- Safe allowlist executors only: open app, open site, web search.
- No shell pass-through, no arbitrary tool execution.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar
from urllib.parse import quote_plus, urlparse

from loguru import logger

from voice_type.app_resolver import AppResolver, ResolvedApp
from voice_type.screen_capture import capture_screen_png
from voice_type.telegram_web import TelegramWebExecutor

T = TypeVar("T")

CommandKind = Literal[
    "open_app",
    "open_url",
    "refresh_apps",
    "telegram_read_last_messages",
    "telegram_search_messages",
    "telegram_saved_messages",
    "telegram_send_message",
    "telegram_send_screenshot",
    "web_search",
]

_APPDATA = Path(os.environ.get("APPDATA", ""))
_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))
_WINDIR = Path(os.environ.get("WINDIR", r"C:\Windows"))
_SYSTEM32 = _WINDIR / "System32"

_PREFIX_RE = re.compile(
    r"^\s*(?:cypher|cipher|сайфер|сифер)\s*[,!:\.-]?\s*(?P<body>.+?)\s*$",
    re.IGNORECASE,
)

_SEARCH_RE = re.compile(
    r"^(?:найди|поищи|погугли|загугли|search(?:\s+for)?)\s+(?:в интернете\s+)?(?P<query>.+)$",
    re.IGNORECASE,
)
_TELEGRAM_SEND_RE = re.compile(
    r"^(?:напиши|отправь|send)\s+"
    r"(?:(?:в\s+)?(?:телеграм(?:е)?|telegram)\s+)?"
    r"(?P<chat>.+?)"
    r"(?:\s*[:,-]\s*|\s+что\s+|\s+сообщение\s+|\s+message\s+)"
    r"(?P<message>.+)$",
    re.IGNORECASE,
)
_TELEGRAM_READ_LAST_RE = re.compile(
    r"^(?:прочитай|покажи|выведи|read|show)\s+"
    r"(?:(?:последн(?:ие|их)|last|recent)\s+)?(?:(?P<count>\d+)\s+)?(?:сообщени(?:я|й|е)|messages?)\s+"
    r"(?:в\s+)?(?:(?:телеграм(?:е)?|telegram)\s+)?(?:(?:чате?|chat)\s+)?(?P<chat>.+)$",
    re.IGNORECASE,
)
_TELEGRAM_SEARCH_RE = re.compile(
    r"^(?:найди|поищи|search)\s+"
    r"(?:в\s+)?(?:(?:телеграм(?:е)?|telegram)\s+)?(?:(?:чате?|chat)\s+)?(?P<chat>.+?)\s+"
    r"(?:сообщени(?:е|я)\s+)?(?:про|с текстом|по запросу|about|for)\s+(?P<query>.+)$",
    re.IGNORECASE,
)
_SCREENSHOT_MARKERS = ("скрин", "скриншот", "screenshot", "снимок экрана", "снимок", "экрана", "экран")
_SEND_MARKERS = ("отправ", "скинь", "пришли", "send")
_REFRESH_APPS_RE = re.compile(
    r"^(?:обнови|пересканируй|переиндексируй|refresh|rebuild)"
    r"(?:\s+(?:список|индекс|кэш))?\s+(?:приложений|apps?|applications?)$",
    re.IGNORECASE,
)

_OPEN_RE = re.compile(
    r"^(?:открой|запусти|включи|open|launch|зайди(?:\s+(?:в|на))?|перейди(?:\s+(?:в|на))?)\s+"
    r"(?P<target>.+)$",
    re.IGNORECASE,
)

_CLAUSE_SPLIT_RE = re.compile(
    r"\s+(?:и\s+потом|а\s+потом|и|потом|and\s+then|and|then)\s+"
    r"(?=(?:открой|запусти|включи|open|launch)\b)",
    re.IGNORECASE,
)
_EXPLICIT_SITE_RE = re.compile(r"^(?:сайт|веб(?:\s+сайт)?|страницу|site|web|browser)\s+", re.IGNORECASE)
_LEADING_POLITE_RE = re.compile(r"^(?:пожалуйста|плиз|please|давай|ну[-\s]?ка)\s+", re.IGNORECASE)
_LEADING_TARGET_TYPE_RE = re.compile(
    r"^(?:сайт|веб(?:\s+сайт)?|страницу|вкладку|site|web|browser|app|application|"
    r"приложение|приложуху|прогу|программу|программку|десктоп|desktop)\s+",
    re.IGNORECASE,
)
_LEADING_POSSESSIVE_RE = re.compile(r"^(?:мой|моя|мою|свой|свою|my)\s+", re.IGNORECASE)
_TELEGRAM_SAVED_MARKERS = (
    "saved messages",
    "saved message",
    "сохраненные сообщения",
    "сохранённые сообщения",
    "сохраненки",
    "сохраненку",
    "сохраненках",
    "избранное",
)
_TELEGRAM_MARKERS = ("telegram", "телеграм", "телега", "телегу", "тг")
_SAVED_MESSAGES_CHAT = "Saved Messages"
_EMBEDDED_URL_RE = re.compile(
    r"\b((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?)",
    re.IGNORECASE,
)
_SENSITIVE_APP_MARKERS = (
    "cmd",
    "command prompt",
    "powershell",
    "power shell",
    "terminal",
    "windows terminal",
    "registry editor",
    "regedit",
)

@dataclass(frozen=True)
class CypherCommand:
    kind: CommandKind
    value: str
    spoken_target: str
    message: str | None = None
    count: int | None = None


@dataclass(frozen=True)
class AppLaunchSpec:
    label: str
    executable: str | None = None
    path: Path | None = None
    uri: str | None = None
    web_fallback: str | None = None


_SITE_ALIASES: dict[str, str] = {
    "яндекс музыка": "https://music.yandex.ru/home",
    "яндекс музыку": "https://music.yandex.ru/home",
    "яндекс музыке": "https://music.yandex.ru/home",
    "yandex music": "https://music.yandex.ru/home",
    "телеграм": "https://web.telegram.org/a/",
    "телега": "https://web.telegram.org/a/",
    "телегу": "https://web.telegram.org/a/",
    "тг": "https://web.telegram.org/a/",
    "telegram": "https://web.telegram.org/a/",
    "ютуб": "https://www.youtube.com/",
    "youtube": "https://www.youtube.com/",
    "гитхаб": "https://github.com/",
    "github": "https://github.com/",
    "гугл": "https://www.google.com/",
    "google": "https://www.google.com/",
}

_APP_ALIASES: dict[str, AppLaunchSpec] = {
    "vs code": AppLaunchSpec(
        label="VS Code",
        executable="code",
        path=_LOCALAPPDATA / "Programs" / "Microsoft VS Code" / "Code.exe",
    ),
    "vscode": AppLaunchSpec(
        label="VS Code",
        executable="code",
        path=_LOCALAPPDATA / "Programs" / "Microsoft VS Code" / "Code.exe",
    ),
    "код": AppLaunchSpec(
        label="VS Code",
        executable="code",
        path=_LOCALAPPDATA / "Programs" / "Microsoft VS Code" / "Code.exe",
    ),
    "вс код": AppLaunchSpec(
        label="VS Code",
        executable="code",
        path=_LOCALAPPDATA / "Programs" / "Microsoft VS Code" / "Code.exe",
    ),
    "визуал студио код": AppLaunchSpec(
        label="VS Code",
        executable="code",
        path=_LOCALAPPDATA / "Programs" / "Microsoft VS Code" / "Code.exe",
    ),
    "телеграм": AppLaunchSpec(
        label="Telegram",
        path=_APPDATA / "Telegram Desktop" / "Telegram.exe",
        uri="telegram:",
        web_fallback="https://web.telegram.org/a/",
    ),
    "телега": AppLaunchSpec(
        label="Telegram",
        path=_APPDATA / "Telegram Desktop" / "Telegram.exe",
        uri="telegram:",
        web_fallback="https://web.telegram.org/a/",
    ),
    "телегу": AppLaunchSpec(
        label="Telegram",
        path=_APPDATA / "Telegram Desktop" / "Telegram.exe",
        uri="telegram:",
        web_fallback="https://web.telegram.org/a/",
    ),
    "тг": AppLaunchSpec(
        label="Telegram",
        path=_APPDATA / "Telegram Desktop" / "Telegram.exe",
        uri="telegram:",
        web_fallback="https://web.telegram.org/a/",
    ),
    "telegram": AppLaunchSpec(
        label="Telegram",
        path=_APPDATA / "Telegram Desktop" / "Telegram.exe",
        uri="telegram:",
        web_fallback="https://web.telegram.org/a/",
    ),
    "панель управления": AppLaunchSpec(
        label="Control Panel",
        path=_SYSTEM32 / "control.exe",
    ),
    "контрол панел": AppLaunchSpec(
        label="Control Panel",
        path=_SYSTEM32 / "control.exe",
    ),
    "control panel": AppLaunchSpec(
        label="Control Panel",
        path=_SYSTEM32 / "control.exe",
    ),
    "параметры": AppLaunchSpec(
        label="Settings",
        uri="ms-settings:",
    ),
    "settings": AppLaunchSpec(
        label="Settings",
        uri="ms-settings:",
    ),
    "загрузки": AppLaunchSpec(
        label="Downloads",
        path=Path.home() / "Downloads",
    ),
    "downloads": AppLaunchSpec(
        label="Downloads",
        path=Path.home() / "Downloads",
    ),
    "документы": AppLaunchSpec(
        label="Documents",
        path=Path.home() / "Documents",
    ),
    "documents": AppLaunchSpec(
        label="Documents",
        path=Path.home() / "Documents",
    ),
    "рабочий стол": AppLaunchSpec(
        label="Desktop",
        path=Path.home() / "Desktop",
    ),
    "desktop": AppLaunchSpec(
        label="Desktop",
        path=Path.home() / "Desktop",
    ),
}


def extract_cypher_body(text: str) -> str | None:
    """Return command body if the utterance starts with a Cypher prefix."""
    match = _PREFIX_RE.match(text)
    if match is None:
        return None
    body = match.group("body").strip()
    return body or None


def parse_cypher_command(text: str) -> CypherCommand | None:
    """Parse a prefixed utterance into a safe Cypher command."""
    body = extract_cypher_body(text)
    if body is None:
        return None

    if _REFRESH_APPS_RE.match(body):
        return CypherCommand(kind="refresh_apps", value="refresh", spoken_target="список приложений")

    telegram_send_match = _TELEGRAM_SEND_RE.match(body)
    if telegram_send_match is not None:
        chat = _normalize_chat_target(telegram_send_match.group("chat"))
        message = _normalize_message_text(telegram_send_match.group("message"))
        if chat and message:
            return CypherCommand(
                kind="telegram_send_message",
                value=chat,
                spoken_target=chat,
                message=message,
            )
        return None

    telegram_read_last_match = _TELEGRAM_READ_LAST_RE.match(body)
    if telegram_read_last_match is not None:
        chat = _normalize_chat_target(telegram_read_last_match.group("chat"))
        count_raw = telegram_read_last_match.group("count")
        count = int(count_raw) if count_raw else 5
        if chat:
            return CypherCommand(
                kind="telegram_read_last_messages",
                value=chat,
                spoken_target=chat,
                count=max(1, min(count, 20)),
            )
        return None

    telegram_search_match = _TELEGRAM_SEARCH_RE.match(body)
    if telegram_search_match is not None:
        chat = _normalize_chat_target(telegram_search_match.group("chat"))
        query = _normalize_message_text(telegram_search_match.group("query"))
        if chat and query:
            return CypherCommand(
                kind="telegram_search_messages",
                value=chat,
                spoken_target=chat,
                message=query,
            )
        return None

    search_match = _SEARCH_RE.match(body)
    if search_match is not None:
        query = _normalize_phrase(search_match.group("query"))
        if query:
            return CypherCommand(kind="web_search", value=query, spoken_target=query)
        return None

    screenshot_target = _parse_telegram_screenshot_target(body)
    if screenshot_target is not None:
        return CypherCommand(
            kind="telegram_send_screenshot",
            value=screenshot_target,
            spoken_target=screenshot_target,
        )

    open_match = _OPEN_RE.match(body)
    if open_match is None:
        return None

    raw_target = _primary_clause(open_match.group("target").strip())
    if _is_telegram_saved_messages_target(raw_target):
        spoken_target = _extract_telegram_target(raw_target)
        return CypherCommand(
            kind="telegram_saved_messages",
            value=spoken_target,
            spoken_target=spoken_target,
        )
    prefer_site = bool(_EXPLICIT_SITE_RE.match(raw_target))
    target = _normalize_phrase(raw_target)
    if not target:
        return None
    return _resolve_open_target(target, prefer_site=prefer_site)


class CypherExecutor:
    """Executes a small allowlist of Cypher commands."""

    def __init__(
        self,
        app_resolver: AppResolver | None = None,
        telegram_web: TelegramWebExecutor | None = None,
        screenshot_dir: Path | None = None,
    ) -> None:
        self._app_resolver = app_resolver or AppResolver()
        self._telegram_web = telegram_web
        self._screenshot_dir = screenshot_dir or (Path(__file__).resolve().parent.parent / "runtime" / "screenshots")

    def execute(self, command: CypherCommand) -> str | None:
        logger.info(f"Cypher execute: {command.kind} -> {command.spoken_target}")
        if command.kind == "open_url":
            url = normalize_open_url(command.value)
            if url is None:
                raise PermissionError(f"Cypher refused unsafe URL target: {command.value}")
            webbrowser.open(url, new=0, autoraise=True)
            return None
        if command.kind == "web_search":
            query = quote_plus(command.value)
            webbrowser.open(f"https://www.google.com/search?q={query}", new=0, autoraise=True)
            return None
        if command.kind == "refresh_apps":
            count = self._app_resolver.refresh(force=True)
            logger.info(f"Cypher app index refreshed: {count} entries")
            return None
        if command.kind == "telegram_saved_messages":
            self._open_telegram_saved_messages(command.value)
            return None
        if command.kind == "telegram_send_message":
            if not command.message:
                raise ValueError("telegram_send_message requires message text")
            message = command.message
            self._run_telegram_web(lambda telegram: telegram.send_message(command.value, message))
            return None
        if command.kind == "telegram_send_screenshot":
            screenshot_path = capture_screen_png(self._screenshot_dir)
            self._run_telegram_web(lambda telegram: telegram.send_image(command.value, screenshot_path))
            return None
        if command.kind == "telegram_read_last_messages":
            messages = self._run_telegram_web(
                lambda telegram: telegram.read_last_messages(command.value, command.count or 5)
            )
            return _format_telegram_messages(command.value, messages)
        if command.kind == "telegram_search_messages":
            if not command.message:
                raise ValueError("telegram_search_messages requires query text")
            query = command.message
            messages = self._run_telegram_web(
                lambda telegram: telegram.search_messages(command.value, query)
            )
            return _format_telegram_search_results(command.value, command.message, messages)
        if command.kind == "open_app":
            self._open_app(command.value)
            return None
        raise ValueError(f"Unsupported Cypher command kind: {command.kind}")

    def _open_app(self, target: str) -> None:
        if is_sensitive_app_target(target):
            raise PermissionError(f"Cypher refused sensitive app target: {target}")

        spec = _APP_ALIASES.get(target)
        if spec is not None and self._try_open_spec(spec):
            return

        resolved = self._app_resolver.resolve(target)
        if resolved is not None:
            if is_sensitive_app_target(resolved.label) or is_sensitive_app_target(resolved.launch_target):
                raise PermissionError(f"Cypher refused sensitive app target: {target}")
            self._launch_resolved(resolved)
            return

        raise FileNotFoundError(f"App launch target not found for query: {target}")

    def _open_telegram_saved_messages(self, target: str) -> None:
        self._run_telegram_web(lambda telegram: telegram.open_saved_messages())

    def _try_open_spec(self, spec: AppLaunchSpec) -> bool:
        if spec.executable is not None:
            resolved = shutil.which(spec.executable)
            if resolved is not None:
                _spawn_process([resolved])
                return True

        if spec.path is not None and spec.path.exists():
            os.startfile(str(spec.path))
            return True

        if spec.uri is not None:
            try:
                os.startfile(spec.uri)
                return True
            except OSError:
                logger.warning(f"Cypher app URI failed: {spec.uri}")

        if spec.web_fallback is not None:
            webbrowser.open(spec.web_fallback, new=0, autoraise=True)
            return True

        return False

    def _launch_resolved(self, resolved: ResolvedApp) -> None:
        logger.info(
            f"Cypher resolved app: {resolved.label} "
            f"(score={resolved.score:.1f}, source={resolved.source})"
        )
        if resolved.launch_kind in {"path", "shortcut"}:
            os.startfile(resolved.launch_target)
            return
        if resolved.launch_kind == "shell":
            _spawn_process(["explorer.exe", f"shell:AppsFolder\\{resolved.launch_target}"])
            return
        raise ValueError(f"Unsupported launch kind: {resolved.launch_kind}")

    def close(self) -> None:
        if self._telegram_web is not None:
            self._telegram_web.close()

    def _run_telegram_web(self, operation: Callable[[TelegramWebExecutor], T]) -> T:
        if self._telegram_web is not None:
            return operation(self._telegram_web)

        telegram_web = TelegramWebExecutor()
        try:
            return operation(telegram_web)
        finally:
            telegram_web.close()


def _resolve_open_target(target: str, prefer_site: bool = False) -> CypherCommand | None:
    app_alias = _match_alias(target, _APP_ALIASES)
    site_alias = _match_alias(target, _SITE_ALIASES)

    if prefer_site:
        url = _resolve_url_target(target, site_alias)
        if url is not None:
            return CypherCommand(kind="open_url", value=url, spoken_target=target)
        if app_alias is not None:
            return CypherCommand(kind="open_app", value=app_alias, spoken_target=target)
        return CypherCommand(kind="open_app", value=target, spoken_target=target)

    if app_alias is not None:
        return CypherCommand(kind="open_app", value=app_alias, spoken_target=target)

    url = _resolve_url_target(target, site_alias)
    if url is not None:
        return CypherCommand(kind="open_url", value=url, spoken_target=target)

    return CypherCommand(kind="open_app", value=target, spoken_target=target)


def _match_alias[T](target: str, aliases: dict[str, T]) -> str | None:
    normalized_target = target.casefold()
    for alias in sorted(aliases, key=len, reverse=True):
        if normalized_target == alias or normalized_target.startswith(alias + " "):
            return alias
    return None


def _primary_clause(value: str) -> str:
    return _CLAUSE_SPLIT_RE.split(value, maxsplit=1)[0].strip()


def _normalize_phrase(value: str) -> str:
    cleaned = value.strip().strip("\"' ")
    cleaned = re.sub(r"[.?!]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING_POLITE_RE.sub("", cleaned)
        cleaned = _LEADING_TARGET_TYPE_RE.sub("", cleaned)
        cleaned = _LEADING_POSSESSIVE_RE.sub("", cleaned)
    return cleaned.strip()


def _normalize_chat_target(value: str) -> str:
    cleaned = _normalize_phrase(value)
    cleaned = re.sub(
        r"^(?:in\s+)?(?:(?:телеграм(?:е)?|telegram)\s+)?(?:(?:в\s+)?(?:чате?|chat)\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:чату|чату\s+с|чат\s+с|диалогу\s+с|диалог\s+с|контакту)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _normalize_message_text(value: str) -> str:
    cleaned = value.strip().strip("\"' ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _parse_telegram_screenshot_target(body: str) -> str | None:
    normalized = body.casefold()
    if not any(marker in normalized for marker in _SCREENSHOT_MARKERS):
        return None
    if not any(marker in normalized for marker in _SEND_MARKERS):
        return None
    if not any(marker in normalized for marker in _TELEGRAM_MARKERS) and not any(
        marker in normalized for marker in _TELEGRAM_SAVED_MARKERS
    ) and "мне" not in normalized:
        return None

    if "мне" in normalized or any(marker in normalized for marker in _TELEGRAM_SAVED_MARKERS):
        return _SAVED_MESSAGES_CHAT

    chat_match = re.search(
        r"(?:в|в чат|чату|чат(?:у)?(?:\s+с)?|телеграм(?:е)?(?:\s+в)?)\s+(?P<chat>.+?)(?:\s+и\s+|$)",
        body,
        re.IGNORECASE,
    )
    if chat_match is None:
        return _SAVED_MESSAGES_CHAT

    chat = _normalize_chat_target(chat_match.group("chat"))
    return chat or _SAVED_MESSAGES_CHAT


def _resolve_url_target(target: str, site_alias: str | None) -> str | None:
    if site_alias is not None:
        return _SITE_ALIASES[site_alias]
    return normalize_open_url(target)


def _normalize_url(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith(("http://", "https://")):
        return candidate
    if "." in candidate and " " not in candidate:
        return f"https://{candidate}"
    match = _EMBEDDED_URL_RE.search(candidate)
    if match is not None:
        token = match.group(1).rstrip(".,!?;:")
        if token.startswith(("http://", "https://")):
            return token
        return f"https://{token}"
    return None


def normalize_open_url(value: str) -> str | None:
    candidate = value.strip()
    if "://" in candidate:
        raw_scheme = candidate.split(":", 1)[0].casefold()
        if raw_scheme not in {"http", "https"}:
            return None

    url = _normalize_url(value)
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return url


def is_sensitive_app_target(value: str) -> bool:
    normalized = _normalize_phrase(value).casefold()
    normalized = normalized.replace(".exe", "")
    return any(marker in normalized for marker in _SENSITIVE_APP_MARKERS)


def _format_telegram_messages(chat_name: str, messages: list[str]) -> str:
    if not messages:
        return f"В чате {chat_name} не видно сообщений."
    return "\n\n".join(messages)


def _format_telegram_search_results(chat_name: str, query: str, messages: list[str]) -> str:
    if not messages:
        return f"В чате {chat_name} ничего не найдено по запросу: {query}"
    return "\n\n".join(messages)


def _spawn_process(command: list[str]) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(command, creationflags=creationflags)


def _is_telegram_saved_messages_target(value: str) -> bool:
    normalized = value.casefold()
    has_telegram = any(marker in normalized for marker in _TELEGRAM_MARKERS)
    has_saved = any(marker in normalized for marker in _TELEGRAM_SAVED_MARKERS)
    return has_telegram and has_saved


def _extract_telegram_target(value: str) -> str:
    normalized = _normalize_phrase(value).casefold()
    for alias in ("телеграм", "телега", "телегу", "тг", "telegram"):
        if alias in normalized:
            return alias
    return "телеграм"
