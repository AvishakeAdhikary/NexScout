"""M11 pure helpers: quiet hours, provider payload parsing, signatures, link handling."""

import hashlib
import hmac
from datetime import UTC, datetime
from types import SimpleNamespace

from nexscout.application.channels import _PAIR, in_quiet_hours
from nexscout.infrastructure.channels.base import ActionButton, OutboundMessage, link_is_public
from nexscout.infrastructure.channels.discord import parse_dispatch
from nexscout.infrastructure.channels.simple import sign
from nexscout.infrastructure.channels.telegram import parse_updates
from nexscout.infrastructure.channels.whatsapp import parse_webhook, verify_signature


def _ch(start: str | None, end: str | None, tz: str = "UTC") -> SimpleNamespace:
    return SimpleNamespace(quiet_start=start, quiet_end=end, timezone=tz)


def test_quiet_hours_same_day_and_overnight() -> None:
    noon = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    assert in_quiet_hours(_ch(None, None), noon) is None  # type: ignore[arg-type]
    assert in_quiet_hours(_ch("11:00", "13:00"), noon) == datetime(  # type: ignore[arg-type]
        2026, 10, 17, 13, 0, tzinfo=UTC
    )
    assert in_quiet_hours(_ch("13:00", "14:00"), noon) is None  # type: ignore[arg-type]
    late = datetime(2026, 10, 17, 23, 30, tzinfo=UTC)
    assert in_quiet_hours(_ch("22:00", "07:00"), late) == datetime(  # type: ignore[arg-type]
        2026, 10, 18, 7, 0, tzinfo=UTC
    )
    # The user's own time zone: 12:00 UTC is 17:30 in Kolkata.
    assert in_quiet_hours(_ch("17:00", "18:00", "Asia/Kolkata"), noon) is not None  # type: ignore[arg-type]


def test_pairing_message_formats() -> None:
    assert _PAIR.match("/start 1A2B3C4D")
    assert _PAIR.match("PAIR 1a2b3c4d")
    assert not _PAIR.match("/start 1A2B3C4D please")
    assert not _PAIR.match("pair 123")


def test_links_to_localhost_are_not_buttons() -> None:
    assert not link_is_public("http://localhost:3000/approve/x")
    assert not link_is_public("http://192.168.1.4:3000/")
    assert not link_is_public("http://example.com/")  # chat apps want HTTPS buttons
    assert link_is_public("https://nexscout.example.com/approve/x")


def test_webhook_signature_and_whatsapp_signature() -> None:
    body = b'{"a":1}'
    expected = hmac.new(b"s", b"123." + body, hashlib.sha256).hexdigest()
    assert sign("s", "123", body) == f"sha256={expected}"
    good = "sha256=" + hmac.new(b"app", body, hashlib.sha256).hexdigest()
    assert verify_signature("app", body, good)
    assert not verify_signature("app", body + b" ", good)
    assert not verify_signature("app", body, None)
    assert not verify_signature("app", body, "md5=abc")


def test_telegram_ignores_group_chats() -> None:
    ups = parse_updates(
        [
            {
                "update_id": 1,
                "message": {
                    "message_id": 5,
                    "chat": {"id": -9, "type": "group"},
                    "from": {"id": 1},
                    "text": "/start AAAAAAAA",
                },
            },
            {
                "update_id": 2,
                "message": {
                    "message_id": 6,
                    "chat": {"id": 7, "type": "private"},
                    "from": {"id": 7},
                    "text": "hi",
                    "reply_to_message": {"message_id": 3},
                },
            },
            {
                "update_id": 3,
                "callback_query": {
                    "id": "c",
                    "from": {"id": 7},
                    "data": "tok",
                    "message": {"message_id": 4, "chat": {"id": 7}},
                },
            },
        ]
    )
    assert [(u.update_id, u.kind) for u in ups] == [(2, "text"), (3, "callback")]
    assert ups[0].reply_to == "3"
    assert ups[1].data == "tok"


def test_discord_ignores_guild_and_bot_messages() -> None:
    assert (
        parse_dispatch("MESSAGE_CREATE", {"id": "1", "guild_id": "g", "author": {"id": "u"}})
        is None
    )
    assert parse_dispatch("MESSAGE_CREATE", {"id": "1", "author": {"id": "u", "bot": True}}) is None
    dm = parse_dispatch(
        "MESSAGE_CREATE",
        {
            "id": "1",
            "author": {"id": "u"},
            "content": "yes",
            "message_reference": {"message_id": "m"},
        },
    )
    assert dm is not None
    assert (dm.kind, dm.reply_to, dm.text) == ("text", "m", "yes")
    btn = parse_dispatch(
        "INTERACTION_CREATE",
        {
            "id": "i",
            "type": 3,
            "token": "t",
            "member": {"user": {"id": "u"}},
            "data": {"custom_id": "tok"},
        },
    )
    assert btn is not None
    assert (btn.kind, btn.user_id, btn.custom_id) == ("button", "u", "tok")


def test_whatsapp_parses_buttons_templates_and_text() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "a",
                                    "from": "1",
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {"id": "tok", "title": "Approve"}
                                    },
                                },
                                {
                                    "id": "b",
                                    "from": "1",
                                    "type": "button",
                                    "button": {"payload": "tok2"},
                                },
                                {
                                    "id": "c",
                                    "from": "1",
                                    "type": "text",
                                    "text": {"body": "answer"},
                                    "context": {"id": "wamid.q"},
                                },
                                {"id": "d", "from": "1", "type": "image"},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msgs = parse_webhook(payload)
    assert [(m.event_id, m.kind, m.button_id or m.text) for m in msgs] == [
        ("a", "button", "tok"),
        ("b", "button", "tok2"),
        ("c", "text", "answer"),
    ]
    assert msgs[2].reply_to == "wamid.q"


def test_outbound_message_defaults() -> None:
    msg = OutboundMessage("t", actions=[ActionButton("Approve", token="x")])
    assert msg.event == "info"
    assert msg.actions[0].style == "primary"
