from __future__ import annotations

import pytest

from voice_type.cypher import CypherCommand
from voice_type.cypher_planner import command_from_planner_json


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            '{"kind":"refresh_apps","value":"refresh"}',
            CypherCommand(kind="refresh_apps", value="refresh", spoken_target="список приложений"),
        ),
        (
            '{"kind":"telegram_saved_messages","value":"anything"}',
            CypherCommand(kind="telegram_saved_messages", value="Saved Messages", spoken_target="Saved Messages"),
        ),
        (
            '{"kind":"telegram_send_message","value":"мне","message":"привет"}',
            CypherCommand(
                kind="telegram_send_message",
                value="Saved Messages",
                spoken_target="Saved Messages",
                message="привет",
            ),
        ),
        (
            '{"kind":"telegram_send_screenshot","value":"сохраненные сообщения"}',
            CypherCommand(
                kind="telegram_send_screenshot",
                value="Saved Messages",
                spoken_target="Saved Messages",
            ),
        ),
        (
            '{"kind":"telegram_read_last_messages","value":"Adam","count":3}',
            CypherCommand(
                kind="telegram_read_last_messages",
                value="Adam",
                spoken_target="Adam",
                count=3,
            ),
        ),
        (
            '{"kind":"telegram_search_messages","value":"мне","message":"аптека"}',
            CypherCommand(
                kind="telegram_search_messages",
                value="Saved Messages",
                spoken_target="Saved Messages",
                message="аптека",
            ),
        ),
        (
            '{"kind":"web_search","value":"цена на iphone 16"}',
            CypherCommand(
                kind="web_search",
                value="цена на iphone 16",
                spoken_target="цена на iphone 16",
            ),
        ),
    ],
)
def test_command_from_json(payload: str, expected: CypherCommand) -> None:
    assert command_from_planner_json(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        '{"kind":"none"}',
        '{"kind":"delete_everything","value":"C:\\\\"}',
        '{"kind":"telegram_send_message","value":"Adam"}',
        '{"kind":"open_app","value":""}',
        '{"kind":"open_url","value":"file:///C:/Windows/System32/cmd.exe"}',
        '{"kind":"open_url","value":"ms-settings:"}',
        '{"kind":"open_app","value":"powershell"}',
        '{"kind":"open_app","value":"terminal"}',
        'not json',
    ],
)
def test_command_from_json_rejects_invalid_payloads(payload: str) -> None:
    assert command_from_planner_json(payload) is None
