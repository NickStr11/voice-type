"""Tests for Cypher command parsing and execution."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import quote_plus

import pytest

from voice_type.app_resolver import ResolvedApp
from voice_type.cypher import (
    AppLaunchSpec,
    CypherCommand,
    CypherExecutor,
    extract_cypher_body,
    parse_cypher_command,
)


def test_extract_cypher_body_requires_prefix() -> None:
    assert extract_cypher_body("просто диктовка") is None
    assert extract_cypher_body("Сайфер, открой телеграм") == "открой телеграм"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Сайфер, найди цену на iphone 16",
            CypherCommand(
                kind="web_search",
                value="цену на iphone 16",
                spoken_target="цену на iphone 16",
            ),
        ),
        (
            "Сайфер, погугли как открыть порт в windows",
            CypherCommand(
                kind="web_search",
                value="как открыть порт в windows",
                spoken_target="как открыть порт в windows",
            ),
        ),
        (
            "Сайфер, открой яндекс музыке",
            CypherCommand(
                kind="open_url",
                value="https://music.yandex.ru/home",
                spoken_target="яндекс музыке",
            ),
        ),
        (
            "Сайфер, открой телегу",
            CypherCommand(kind="open_app", value="телегу", spoken_target="телегу"),
        ),
        (
            "Сайфер, открой пожалуйста приложение телеграм",
            CypherCommand(kind="open_app", value="телеграм", spoken_target="телеграм"),
        ),
        (
            "Сайфер, открой приложение телеграм и потом открой мои saved messages",
            CypherCommand(kind="open_app", value="телеграм", spoken_target="телеграм"),
        ),
        (
            "Сайфер, открой мне телегу и конкретно сохраненные сообщения",
            CypherCommand(
                kind="telegram_saved_messages",
                value="телегу",
                spoken_target="телегу",
            ),
        ),
        (
            "Сайфер, напиши в телеграм Adam: привет из VoiceType",
            CypherCommand(
                kind="telegram_send_message",
                value="Adam",
                spoken_target="Adam",
                message="привет из VoiceType",
            ),
        ),
        (
            "Сайфер, отправь Адаму что я подъеду через 15 минут",
            CypherCommand(
                kind="telegram_send_message",
                value="Адаму",
                spoken_target="Адаму",
                message="я подъеду через 15 минут",
            ),
        ),
        (
            "Сайфер, зайди в сохраненные сообщения, сделай скрин экрана и отправь мне",
            CypherCommand(
                kind="telegram_send_screenshot",
                value="Saved Messages",
                spoken_target="Saved Messages",
            ),
        ),
        (
            "Сайфер, скинь скрин экрана в телеграм мне",
            CypherCommand(
                kind="telegram_send_screenshot",
                value="Saved Messages",
                spoken_target="Saved Messages",
            ),
        ),
        (
            "Сайфер, запусти вс код",
            CypherCommand(kind="open_app", value="вс код", spoken_target="вс код"),
        ),
        (
            "Сайфер, включи стим",
            CypherCommand(kind="open_app", value="стим", spoken_target="стим"),
        ),
        (
            "Сайфер, открой github.com",
            CypherCommand(kind="open_url", value="https://github.com", spoken_target="github.com"),
        ),
    ],
)
def test_parse_cypher_command(text: str, expected: CypherCommand) -> None:
    assert parse_cypher_command(text) == expected


def test_parse_cypher_command_extracts_embedded_url_from_noisy_open_phrase() -> None:
    assert parse_cypher_command("Cypher, open me a browser and specifically open avito.ru") == CypherCommand(
        kind="open_url",
        value="https://avito.ru",
        spoken_target="me a browser and specifically open avito.ru",
    )


def test_parse_cypher_command_keeps_english_fallback() -> None:
    assert parse_cypher_command("Cypher, open site telegram") == CypherCommand(
        kind="open_url",
        value="https://web.telegram.org/a/",
        spoken_target="telegram",
    )


def test_parse_cypher_command_rejects_unknown_prefixed_command() -> None:
    assert parse_cypher_command("Сайфер, удали все файлы") is None


@pytest.mark.parametrize("target", ["powershell", "terminal", "cmd", "registry editor"])
def test_executor_rejects_sensitive_app_targets(target: str) -> None:
    command = CypherCommand(kind="open_app", value=target, spoken_target=target)
    with pytest.raises(PermissionError, match="refused"):
        CypherExecutor().execute(command)


def test_parse_cypher_command_refresh_apps() -> None:
    assert parse_cypher_command("Сайфер, обнови список приложений") == CypherCommand(
        kind="refresh_apps",
        value="refresh",
        spoken_target="список приложений",
    )


def test_parse_cypher_command_can_explicitly_open_site_in_russian() -> None:
    assert parse_cypher_command("Сайфер, открой сайт телега") == CypherCommand(
        kind="open_url",
        value="https://web.telegram.org/a/",
        spoken_target="телега",
    )


def test_executor_web_search_opens_browser() -> None:
    command = CypherCommand(
        kind="web_search",
        value="цена на steam deck",
        spoken_target="цена на steam deck",
    )
    with patch("voice_type.cypher.webbrowser.open") as mock_open:
        CypherExecutor().execute(command)
    mock_open.assert_called_once()
    expected_query = quote_plus("цена на steam deck")
    assert f"https://www.google.com/search?q={expected_query}" in mock_open.call_args.args[0]


def test_executor_prefers_executable_for_known_app() -> None:
    command = CypherCommand(kind="open_app", value="вс код", spoken_target="вс код")
    with (
        patch("voice_type.cypher.shutil.which", return_value=r"C:\bin\code.cmd"),
        patch("voice_type.cypher.subprocess.Popen") as mock_popen,
    ):
        CypherExecutor().execute(command)

    mock_popen.assert_called_once()
    assert mock_popen.call_args.args[0] == [r"C:\bin\code.cmd"]


def test_executor_uses_existing_path_when_executable_missing() -> None:
    command = CypherCommand(kind="open_app", value="вс код", spoken_target="вс код")
    fake_path = Path(r"C:\Users\User\AppData\Local\Programs\Microsoft VS Code\Code.exe")
    app_aliases = {
        "вс код": AppLaunchSpec(
            label="VS Code",
            executable="code",
            path=fake_path,
        )
    }
    with (
        patch("voice_type.cypher._APP_ALIASES", app_aliases),
        patch("voice_type.cypher.shutil.which", return_value=None),
        patch.object(Path, "exists", return_value=True),
        patch("voice_type.cypher.os.startfile") as mock_startfile,
    ):
        CypherExecutor().execute(command)

    mock_startfile.assert_called_once_with(str(fake_path))


def test_executor_uses_uri_fallback_for_telegram() -> None:
    command = CypherCommand(kind="open_app", value="телега", spoken_target="телегу")
    app_aliases = {
        "телега": AppLaunchSpec(
            label="Telegram",
            uri="telegram:",
            web_fallback="https://web.telegram.org/a/",
        )
    }
    with (
        patch("voice_type.cypher._APP_ALIASES", app_aliases),
        patch("voice_type.cypher.shutil.which", return_value=None),
        patch("voice_type.cypher.os.startfile") as mock_startfile,
    ):
        CypherExecutor().execute(command)
    mock_startfile.assert_called_once_with("telegram:")


def test_executor_prefers_existing_path_over_uri() -> None:
    command = CypherCommand(kind="open_app", value="телега", spoken_target="телегу")
    fake_path = Path(r"C:\Users\User\AppData\Roaming\Telegram Desktop\Telegram.exe")
    app_aliases = {
        "телега": AppLaunchSpec(
            label="Telegram",
            path=fake_path,
            uri="telegram:",
            web_fallback="https://web.telegram.org/a/",
        )
    }
    with (
        patch("voice_type.cypher._APP_ALIASES", app_aliases),
        patch("voice_type.cypher.shutil.which", return_value=None),
        patch.object(Path, "exists", return_value=True),
        patch("voice_type.cypher.os.startfile") as mock_startfile,
    ):
        CypherExecutor().execute(command)

    mock_startfile.assert_called_once_with(str(fake_path))


def test_executor_uses_app_resolver_for_unknown_app() -> None:
    command = CypherCommand(kind="open_app", value="стим", spoken_target="стим")
    resolved = ResolvedApp(
        label="Steam",
        launch_kind="shortcut",
        launch_target=r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Steam.lnk",
        source="start-menu",
        score=98.0,
    )
    with patch("voice_type.cypher.os.startfile") as mock_startfile:
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = resolved
        executor = CypherExecutor(app_resolver=mock_resolver)
        executor.execute(command)

    mock_resolver.resolve.assert_called_once_with("стим")
    mock_startfile.assert_called_once_with(resolved.launch_target)


def test_executor_opens_telegram_saved_messages() -> None:
    telegram_web = MagicMock()
    command = CypherCommand(
        kind="telegram_saved_messages",
        value="телегу",
        spoken_target="телегу",
    )
    executor = CypherExecutor(telegram_web=telegram_web)

    executor.execute(command)

    telegram_web.open_saved_messages.assert_called_once_with()


def test_executor_sends_telegram_message() -> None:
    telegram_web = MagicMock()
    command = CypherCommand(
        kind="telegram_send_message",
        value="Adam",
        spoken_target="Adam",
        message="привет из VoiceType",
    )
    executor = CypherExecutor(telegram_web=telegram_web)

    executor.execute(command)

    telegram_web.send_message.assert_called_once_with("Adam", "привет из VoiceType")


def test_executor_closes_internal_telegram_web_after_send() -> None:
    command = CypherCommand(
        kind="telegram_send_message",
        value="Adam",
        spoken_target="Adam",
        message="привет",
    )
    with patch("voice_type.cypher.TelegramWebExecutor") as mock_executor_cls:
        telegram_web = mock_executor_cls.return_value
        executor = CypherExecutor()

        executor.execute(command)

    telegram_web.send_message.assert_called_once_with("Adam", "привет")
    telegram_web.close.assert_called_once_with()


def test_executor_sends_telegram_screenshot() -> None:
    telegram_web = MagicMock()
    screenshot_path = Path(r"D:\runtime\screens\screen-1.png")
    command = CypherCommand(
        kind="telegram_send_screenshot",
        value="Saved Messages",
        spoken_target="Saved Messages",
    )
    executor = CypherExecutor(telegram_web=telegram_web)

    with patch("voice_type.cypher.capture_screen_png", return_value=screenshot_path) as mock_capture:
        executor.execute(command)

    mock_capture.assert_called_once()
    telegram_web.send_image.assert_called_once_with("Saved Messages", screenshot_path)


def test_executor_refreshes_app_index() -> None:
    command = CypherCommand(kind="refresh_apps", value="refresh", spoken_target="список приложений")
    with patch("voice_type.cypher.AppResolver") as mock_resolver_cls:
        mock_resolver = mock_resolver_cls.return_value
        executor = CypherExecutor(app_resolver=mock_resolver)
        executor.execute(command)

    mock_resolver.refresh.assert_called_once_with(force=True)


def test_executor_close_closes_telegram_web() -> None:
    telegram_web = MagicMock()
    executor = CypherExecutor(telegram_web=telegram_web)

    executor.close()

    telegram_web.close.assert_called_once_with()


def test_parse_cypher_command_matches_control_panel_alias_simple() -> None:
    assert parse_cypher_command("Cypher, open control panel") == CypherCommand(
        kind="open_app",
        value="control panel",
        spoken_target="control panel",
    )


def test_executor_opens_control_panel_from_system_alias_simple() -> None:
    command = CypherCommand(kind="open_app", value="control panel", spoken_target="control panel")
    fake_path = Path(r"C:\Windows\System32\control.exe")
    app_aliases = {
        "control panel": AppLaunchSpec(
            label="Control Panel",
            path=fake_path,
        )
    }
    with (
        patch("voice_type.cypher._APP_ALIASES", app_aliases),
        patch("voice_type.cypher.shutil.which", return_value=None),
        patch.object(Path, "exists", return_value=True),
        patch("voice_type.cypher.os.startfile") as mock_startfile,
    ):
        CypherExecutor().execute(command)

    mock_startfile.assert_called_once_with(str(fake_path))


def test_parse_cypher_command_reads_last_messages() -> None:
    assert parse_cypher_command("Cypher, read last 3 messages in telegram Saved Messages") == CypherCommand(
        kind="telegram_read_last_messages",
        value="Saved Messages",
        spoken_target="Saved Messages",
        count=3,
    )


def test_parse_cypher_command_searches_messages() -> None:
    assert parse_cypher_command("Cypher, search telegram Saved Messages for аптеку") == CypherCommand(
        kind="telegram_search_messages",
        value="Saved Messages",
        spoken_target="Saved Messages",
        message="аптеку",
    )


def test_executor_reads_last_telegram_messages() -> None:
    telegram_web = MagicMock()
    telegram_web.read_last_messages.return_value = ["первое", "второе"]
    command = CypherCommand(
        kind="telegram_read_last_messages",
        value="Saved Messages",
        spoken_target="Saved Messages",
        count=2,
    )
    executor = CypherExecutor(telegram_web=telegram_web)

    result = executor.execute(command)

    telegram_web.read_last_messages.assert_called_once_with("Saved Messages", 2)
    assert result == "первое\n\nвторое"


def test_executor_searches_telegram_messages() -> None:
    telegram_web = MagicMock()
    telegram_web.search_messages.return_value = ["про аптеку", "ещё про аптеку"]
    command = CypherCommand(
        kind="telegram_search_messages",
        value="Saved Messages",
        spoken_target="Saved Messages",
        message="аптеку",
    )
    executor = CypherExecutor(telegram_web=telegram_web)

    result = executor.execute(command)

    telegram_web.search_messages.assert_called_once_with("Saved Messages", "аптеку")
    assert result == "про аптеку\n\nещё про аптеку"
