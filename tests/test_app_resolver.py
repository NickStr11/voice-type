"""Tests for AppResolver caching and fuzzy resolution."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from voice_type.app_resolver import AppEntry, AppResolver


def test_resolve_builds_cache_and_fuzzy_matches(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)

    start_menu_entries = [
        AppEntry(
            label="Steam",
            launch_kind="shortcut",
            launch_target=r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Steam.lnk",
            source="start-menu",
            search_terms=("steam",),
        )
    ]

    with (
        patch.object(resolver, "_discover_start_menu_entries", return_value=start_menu_entries),
        patch.object(resolver, "_discover_app_paths_entries", return_value=[]),
        patch.object(resolver, "_discover_start_apps_entries", return_value=[]),
    ):
        resolved = resolver.resolve("steem")

    assert resolved is not None
    assert resolved.label == "Steam"
    assert resolved.launch_kind == "shortcut"
    assert cache_path.exists()


def test_resolve_uses_fresh_cache_without_rebuild(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    payload = {
        "generated_at": time.time(),
        "entries": [
            {
                "label": "Steam",
                "launch_kind": "shortcut",
                "launch_target": r"C:\Steam.lnk",
                "source": "start-menu",
                "search_terms": ["steam"],
            }
        ],
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    with patch.object(resolver, "_build_index", side_effect=AssertionError("should not rebuild")):
        resolved = resolver.resolve("steam")

    assert resolved is not None
    assert resolved.launch_target == r"C:\Steam.lnk"


def test_resolve_ignores_polite_noise_and_prefers_exact_token(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    payload = {
        "generated_at": time.time(),
        "entries": [
            {
                "label": "Steam",
                "launch_kind": "shortcut",
                "launch_target": r"C:\Steam.lnk",
                "source": "start-menu",
                "search_terms": ["steam"],
            },
            {
                "label": "EA",
                "launch_kind": "shortcut",
                "launch_target": r"C:\EA.lnk",
                "source": "start-menu",
                "search_terms": ["ea", "games", "launcher"],
            },
        ],
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    resolved = resolver.resolve("мне steam")

    assert resolved is not None
    assert resolved.label == "Steam"


def test_resolve_supports_russian_spoken_app_name(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    payload = {
        "generated_at": time.time(),
        "entries": [
            {
                "label": "Steam",
                "launch_kind": "shortcut",
                "launch_target": r"C:\Steam.lnk",
                "source": "start-menu",
                "search_terms": ["steam"],
            }
        ],
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    resolved = resolver.resolve("стим")

    assert resolved is not None
    assert resolved.label == "Steam"


def test_resolve_supports_russian_telegram_alias(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    payload = {
        "generated_at": time.time(),
        "entries": [
            {
                "label": "Telegram",
                "launch_kind": "shortcut",
                "launch_target": r"C:\Telegram.lnk",
                "source": "start-menu",
                "search_terms": ["telegram"],
            }
        ],
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    resolved = resolver.resolve("открой мою телегу")

    assert resolved is not None
    assert resolved.label == "Telegram"


def test_resolve_prefers_real_app_over_support_link(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    payload = {
        "generated_at": time.time(),
        "entries": [
            {
                "label": "Steam",
                "launch_kind": "shortcut",
                "launch_target": r"C:\Steam.lnk",
                "source": "start-menu",
                "search_terms": ["steam"],
            },
            {
                "label": "Steam Support Center",
                "launch_kind": "shell",
                "launch_target": "http://support.steampowered.com/",
                "source": "start-apps",
                "search_terms": ["steam", "support", "center"],
            },
        ],
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    resolved = resolver.resolve("мой стим библиотека")

    assert resolved is not None
    assert resolved.label == "Steam"


def test_refresh_rebuilds_and_updates_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "apps.json"
    resolver = AppResolver(cache_path=cache_path, cache_ttl_s=3600)
    built_entries = [
        AppEntry(
            label="VS Code",
            launch_kind="path",
            launch_target=r"C:\Code.exe",
            source="app-paths",
            search_terms=("vs code", "code"),
        )
    ]

    with patch.object(resolver, "_build_index", return_value=built_entries):
        count = resolver.refresh(force=True)

    assert count == 1
    assert json.loads(cache_path.read_text(encoding="utf-8"))["entries"][0]["label"] == "VS Code"
