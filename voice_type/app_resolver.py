"""Windows app discovery and fuzzy resolution for Cypher."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from loguru import logger
from rapidfuzz import fuzz, process

LaunchKind = Literal["path", "shortcut", "shell"]

_PROJECT_ROOT = Path(__file__).parent.parent
_RUNTIME_DIR = _PROJECT_ROOT / "runtime"
_DEFAULT_CACHE_PATH = _RUNTIME_DIR / "cypher_app_index.json"
_DEFAULT_CACHE_TTL_S = 3600.0
_SCORE_CUTOFF = 72.0

_START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]
_APP_PATHS_KEYS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
]
_SKIP_NAMES = (
    "uninstall",
    "update",
    "readme",
    "help",
    "license",
    "website",
)
_QUERY_STOPWORDS = {
    "мне",
    "пожалуйста",
    "плиз",
    "please",
    "открой",
    "запусти",
    "включи",
    "зайди",
    "перейди",
    "for",
    "me",
    "app",
    "application",
    "приложение",
    "приложуху",
    "прогу",
    "программу",
    "программку",
    "desktop",
    "десктоп",
    "site",
    "сайт",
    "launcher",
    "games",
    "game",
    "игру",
    "игра",
    "игры",
    "свой",
    "свою",
    "мой",
    "моя",
    "мою",
    "там",
    "конкретно",
    "library",
    "библиотека",
    "библиотеку",
}
_QUERY_ALIASES = {
    "гугл хром": "google chrome",
    "визуал студио код": "visual studio code",
    "вижуал студио код": "visual studio code",
    "вс код": "vs code",
    "стим": "steam",
    "телега": "telegram",
    "телегу": "telegram",
    "телеграм": "telegram",
    "телеграмм": "telegram",
    "тг": "telegram",
    "дискорд": "discord",
    "ноушен": "notion",
    "спотифай": "spotify",
    "ватсап": "whatsapp",
    "вотсап": "whatsapp",
    "хром": "chrome",
    "эдж": "edge",
    "эйдж": "edge",
    "ворд": "word",
    "эксель": "excel",
    "поверпойнт": "powerpoint",
    "пауэрпоинт": "powerpoint",
    "тимс": "teams",
    "аутлук": "outlook",
}


@dataclass(frozen=True)
class AppEntry:
    label: str
    launch_kind: LaunchKind
    launch_target: str
    source: str
    search_terms: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedApp:
    label: str
    launch_kind: LaunchKind
    launch_target: str
    source: str
    score: float


@dataclass
class _MergedEntry:
    label: str
    launch_kind: LaunchKind
    launch_target: str
    source: str
    search_terms: set[str]


class AppResolver:
    """Build and query an index of launchable Windows apps."""

    def __init__(
        self,
        cache_path: Path | None = None,
        cache_ttl_s: float = _DEFAULT_CACHE_TTL_S,
    ) -> None:
        self._cache_path = cache_path or _DEFAULT_CACHE_PATH
        self._cache_ttl_s = cache_ttl_s
        self._entries: list[AppEntry] | None = None

    def resolve(self, query: str) -> ResolvedApp | None:
        """Resolve a spoken app name to the best launch target."""
        normalized = _normalize_for_match(query)
        if not normalized:
            return None

        normalized = _normalize_query(normalized)
        if not normalized:
            return None

        entries = self._ensure_index()
        exact = self._resolve_exact(normalized, entries)
        if exact is not None:
            return exact

        token_exact = self._resolve_token_exact(normalized, entries)
        if token_exact is not None:
            return token_exact

        choices = [(term, entry) for entry in entries for term in entry.search_terms]
        if not choices:
            return None

        match = process.extractOne(
            normalized,
            [term for term, _ in choices],
            scorer=fuzz.WRatio,
            score_cutoff=_SCORE_CUTOFF,
        )
        if match is None:
            logger.info(f"AppResolver: no match for '{normalized}'")
            return None

        _, score, index = match
        entry = choices[index][1]
        logger.info(
            f"AppResolver: '{normalized}' -> '{entry.label}' "
            f"(score={score:.1f}, source={entry.source})"
        )
        return ResolvedApp(
            label=entry.label,
            launch_kind=entry.launch_kind,
            launch_target=entry.launch_target,
            source=entry.source,
            score=float(score),
        )

    def refresh(self, force: bool = True) -> int:
        """Refresh the app index and persist the cache."""
        if not force and self._entries is not None:
            return len(self._entries)
        self._entries = self._build_index()
        self._save_cache(self._entries)
        logger.info(f"AppResolver refreshed: {len(self._entries)} entries")
        return len(self._entries)

    def _ensure_index(self) -> list[AppEntry]:
        if self._entries is not None:
            return self._entries

        cached = self._load_cache()
        if cached is not None:
            self._entries = cached
            logger.info(f"AppResolver cache loaded: {len(self._entries)} entries")
            return self._entries

        self._entries = self._build_index()
        self._save_cache(self._entries)
        logger.info(f"AppResolver index built: {len(self._entries)} entries")
        return self._entries

    def _resolve_exact(self, normalized: str, entries: list[AppEntry]) -> ResolvedApp | None:
        for entry in entries:
            if normalized in entry.search_terms:
                return ResolvedApp(
                    label=entry.label,
                    launch_kind=entry.launch_kind,
                    launch_target=entry.launch_target,
                    source=entry.source,
                    score=100.0,
                )
        return None

    def _resolve_token_exact(self, normalized: str, entries: list[AppEntry]) -> ResolvedApp | None:
        tokens = [token for token in normalized.split() if token]
        if not tokens:
            return None

        candidates: list[tuple[int, AppEntry]] = []
        for entry in entries:
            overlap = sum(1 for token in tokens if token in entry.search_terms)
            if overlap:
                candidates.append((overlap, entry))

        if not candidates:
            return None

        overlap, entry = max(
            candidates,
            key=lambda item: (
                item[0],
                _launch_kind_priority(item[1].launch_kind, item[1].launch_target),
                -len(item[1].label),
            ),
        )
        score = 95.0 if overlap == len(tokens) else 88.0
        logger.info(
            f"AppResolver token match: '{normalized}' -> '{entry.label}' "
            f"(overlap={overlap}, source={entry.source})"
        )
        return ResolvedApp(
            label=entry.label,
            launch_kind=entry.launch_kind,
            launch_target=entry.launch_target,
            source=entry.source,
            score=score,
        )

    def _load_cache(self) -> list[AppEntry] | None:
        if not self._cache_path.exists():
            return None
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"AppResolver cache read failed: {exc}")
            return None

        if not isinstance(raw, dict):
            return None
        raw_dict = cast(dict[str, object], raw)

        generated_at_raw: object = raw_dict.get("generated_at", 0.0)
        generated_at = (
            float(generated_at_raw)
            if isinstance(generated_at_raw, (int, float, str))
            else 0.0
        )
        if time.time() - generated_at > self._cache_ttl_s:
            return None

        entries_payload: object = raw_dict.get("entries", [])
        if not isinstance(entries_payload, list):
            return None
        entries_raw = cast(list[object], entries_payload)

        entries: list[AppEntry] = []
        for item in entries_raw:
            if not isinstance(item, dict):
                continue
            item_dict = cast(dict[str, object], item)
            launch_kind_obj = item_dict.get("launch_kind")
            raw_terms_obj = item_dict.get("search_terms")
            if not isinstance(launch_kind_obj, str) or launch_kind_obj not in {"path", "shortcut", "shell"}:
                continue
            if not isinstance(raw_terms_obj, list):
                continue
            raw_terms = cast(list[object], raw_terms_obj)
            launch_kind = cast(LaunchKind, launch_kind_obj)
            try:
                entries.append(
                    AppEntry(
                        label=str(item_dict.get("label", "")),
                        launch_kind=launch_kind,
                        launch_target=str(item_dict.get("launch_target", "")),
                        source=str(item_dict.get("source", "")),
                        search_terms=tuple(str(term) for term in raw_terms),
                    )
                )
            except Exception:
                continue
        return entries or None

    def _save_cache(self, entries: list[AppEntry]) -> None:
        self._cache_path.parent.mkdir(exist_ok=True)
        payload = {
            "generated_at": time.time(),
            "entries": [asdict(entry) for entry in entries],
        }
        self._cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_index(self) -> list[AppEntry]:
        merged: dict[tuple[LaunchKind, str], _MergedEntry] = {}
        for entry in self._discover_start_menu_entries():
            _merge_entry(merged, entry)
        for entry in self._discover_app_paths_entries():
            _merge_entry(merged, entry)
        for entry in self._discover_start_apps_entries():
            _merge_entry(merged, entry)

        return [
            AppEntry(
                label=item.label,
                launch_kind=item.launch_kind,
                launch_target=item.launch_target,
                source=item.source,
                search_terms=tuple(sorted(item.search_terms)),
            )
            for item in merged.values()
            if item.search_terms
        ]

    def _discover_start_menu_entries(self) -> list[AppEntry]:
        entries: list[AppEntry] = []
        for base_dir in _START_MENU_DIRS:
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*.lnk"):
                if _should_skip(path.stem):
                    continue
                entries.append(
                    AppEntry(
                        label=path.stem,
                        launch_kind="shortcut",
                        launch_target=str(path),
                        source="start-menu",
                        search_terms=tuple(_build_search_terms(path.stem, path.stem)),
                    )
                )
        return entries

    def _discover_app_paths_entries(self) -> list[AppEntry]:
        entries: list[AppEntry] = []
        for root, subkey in _APP_PATHS_KEYS:
            try:
                key = winreg.OpenKey(root, subkey)
            except OSError:
                continue
            with key:
                index = 0
                while True:
                    try:
                        value_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, value_name) as app_key:
                            target, _ = winreg.QueryValueEx(app_key, "")
                    except OSError:
                        continue
                    if not isinstance(target, str):
                        continue
                    target_path = Path(target.strip())
                    label = target_path.stem or Path(value_name).stem
                    if _should_skip(label):
                        continue
                    entries.append(
                        AppEntry(
                            label=label,
                            launch_kind="path",
                            launch_target=str(target_path),
                            source="app-paths",
                            search_terms=tuple(_build_search_terms(label, target_path.stem)),
                        )
                    )
        return entries

    def _discover_start_apps_entries(self) -> list[AppEntry]:
        entries: list[AppEntry] = []
        command = (
            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            logger.warning(f"AppResolver Get-StartApps failed: {exc}")
            return entries

        if result.returncode != 0 or not result.stdout.strip():
            return entries

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning(f"AppResolver Get-StartApps JSON parse failed: {exc}")
            return entries

        items: list[dict[str, object]]
        if isinstance(raw, list):
            raw_list = cast(list[object], raw)
            items = [cast(dict[str, object], item) for item in raw_list if isinstance(item, dict)]
        elif isinstance(raw, dict):
            items = [cast(dict[str, object], raw)]
        else:
            return entries
        for item in items:
            name = str(item.get("Name", "")).strip()
            app_id = str(item.get("AppID", "")).strip()
            if not name or not app_id or _should_skip(name):
                continue
            if app_id.startswith(("http://", "https://")):
                continue
            entries.append(
                AppEntry(
                    label=name,
                    launch_kind="shell",
                    launch_target=app_id,
                    source="start-apps",
                    search_terms=tuple(_build_search_terms(name, app_id)),
                )
            )
        return entries


def _merge_entry(merged: dict[tuple[LaunchKind, str], _MergedEntry], entry: AppEntry) -> None:
    key = (entry.launch_kind, entry.launch_target)
    if key not in merged:
        merged[key] = _MergedEntry(
            label=entry.label,
            launch_kind=entry.launch_kind,
            launch_target=entry.launch_target,
            source=entry.source,
            search_terms=set(entry.search_terms),
        )
        return

    item = merged[key]
    item.search_terms.update(entry.search_terms)


def _should_skip(name: str) -> bool:
    normalized = _normalize_for_match(name)
    return not normalized or any(token in normalized for token in _SKIP_NAMES)


def _build_search_terms(*values: str) -> set[str]:
    terms: set[str] = set()
    for value in values:
        normalized = _normalize_for_match(value)
        if not normalized:
            continue
        terms.add(normalized)
        terms.add(normalized.replace(" ", ""))
        for token in normalized.split():
            if len(token) >= 3:
                terms.add(token)
    return terms


def _normalize_for_match(value: str) -> str:
    cleaned = value.casefold()
    cleaned = re.sub(r"\.(?:exe|lnk|url)$", "", cleaned)
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    cleaned = re.sub(r"[^0-9a-zа-яё\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_query(value: str) -> str:
    normalized = value
    for alias, canonical in sorted(_QUERY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(
            rf"(?<!\w){re.escape(alias)}(?!\w)",
            canonical,
            normalized,
        )
    tokens = [token for token in normalized.split() if token not in _QUERY_STOPWORDS]
    return " ".join(tokens).strip()


def _launch_kind_priority(launch_kind: LaunchKind, launch_target: str) -> int:
    if launch_target.startswith(("http://", "https://")):
        return 0
    if launch_kind == "path":
        return 3
    if launch_kind == "shortcut":
        return 2
    return 1
