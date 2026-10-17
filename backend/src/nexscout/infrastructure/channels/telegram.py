"""Telegram via the official Bot API (https://core.telegram.org/bots/api).

Outbound: `sendMessage` with inline keyboard buttons. Inbound: long polling with `getUpdates`
(no public URL needed). The user pairs by sending `/start <code>` to their own bot; only that
chat can act afterwards.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

import httpx

from nexscout.infrastructure.channels.base import (
    ChannelError,
    OutboundMessage,
    SendResult,
    check_response,
    link_is_public,
)

API = "https://api.telegram.org"


def _url(token: str, method: str) -> str:
    return f"{API}/bot{token}/{method}"


async def call(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    payload: dict[str, Any],
    wait: float = 20.0,
) -> Any:
    try:
        resp = await client.post(_url(token, method), json=payload, timeout=wait)
    except httpx.HTTPError as exc:
        raise ChannelError(f"Telegram unreachable: {type(exc).__name__}") from exc
    data = await check_response(resp, "Telegram")
    if not data.get("ok", False):
        raise ChannelError(
            f"Telegram error: {data.get('description', 'unknown')}"[:200], transient=False
        )
    return data.get("result")


class TelegramAdapter:
    kind = "telegram"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        chat_id = config.get("chat_id")
        if not chat_id:
            raise ChannelError("This Telegram channel isn't paired yet.", transient=False)
        return await self.send_to(client, secrets["bot_token"], chat_id, msg)

    async def send_to(
        self, client: httpx.AsyncClient, token: str, chat_id: Any, msg: OutboundMessage
    ) -> SendResult:
        text = f"<b>{html.escape(msg.title)}</b>"
        if msg.body:
            text += f"\n\n{html.escape(msg.body)}"
        if msg.reply_hint:
            text += f"\n\n<i>{html.escape(msg.reply_hint)}</i>"
        rows: list[list[dict[str, str]]] = []
        buttons = [{"text": a.label[:32], "callback_data": a.token} for a in msg.actions if a.token]
        if buttons:
            rows.append(buttons)
        if msg.link and link_is_public(msg.link):
            rows.append([{"text": "Open in NexScout", "url": msg.link}])
        elif msg.link:
            text += f"\n\nOpen in NexScout: {html.escape(msg.link)}"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if rows:
            payload["reply_markup"] = {"inline_keyboard": rows}
        elif msg.reply_hint:
            # Questions: Telegram opens a reply box, so the answer quotes this message.
            payload["reply_markup"] = {
                "force_reply": True,
                "input_field_placeholder": "Your answer",
            }
        result = await call(client, token, "sendMessage", payload)
        return SendResult(str(result.get("message_id")) if isinstance(result, dict) else None)


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    kind: str  # "text" | "callback"
    chat_id: str
    user_id: str
    text: str = ""
    callback_id: str | None = None
    data: str | None = None
    message_id: str | None = None
    reply_to: str | None = None


def parse_updates(result: list[dict[str, Any]]) -> list[TelegramUpdate]:
    out: list[TelegramUpdate] = []
    for u in result:
        uid = int(u.get("update_id", 0))
        if cq := u.get("callback_query"):
            m = cq.get("message") or {}
            out.append(
                TelegramUpdate(
                    uid,
                    "callback",
                    str((m.get("chat") or {}).get("id", "")),
                    str((cq.get("from") or {}).get("id", "")),
                    callback_id=str(cq.get("id")),
                    data=cq.get("data"),
                    message_id=str(m.get("message_id", "")),
                )
            )
        elif m := u.get("message"):
            if (m.get("chat") or {}).get("type") != "private":
                continue  # only direct messages with the user's own bot
            reply = (m.get("reply_to_message") or {}).get("message_id")
            out.append(
                TelegramUpdate(
                    uid,
                    "text",
                    str(m["chat"]["id"]),
                    str((m.get("from") or {}).get("id", "")),
                    text=str(m.get("text") or "")[:4000],
                    message_id=str(m.get("message_id")),
                    reply_to=str(reply) if reply else None,
                )
            )
    return out


async def get_updates(
    client: httpx.AsyncClient, token: str, offset: int, wait_s: int = 20
) -> list[TelegramUpdate]:
    result = await call(
        client,
        token,
        "getUpdates",
        {"offset": offset, "timeout": wait_s, "allowed_updates": ["message", "callback_query"]},
        wait=wait_s + 10,
    )
    return parse_updates(result or [])


async def answer_callback(
    client: httpx.AsyncClient, token: str, callback_id: str, text: str
) -> None:
    await call(
        client, token, "answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]}
    )


async def clear_buttons(
    client: httpx.AsyncClient, token: str, chat_id: str, message_id: str
) -> None:
    await call(
        client,
        token,
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": {"inline_keyboard": []},
        },
    )


async def get_me(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    result = await call(client, token, "getMe", {})
    return result if isinstance(result, dict) else {}
