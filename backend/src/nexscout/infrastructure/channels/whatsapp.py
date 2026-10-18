"""WhatsApp via Meta's official WhatsApp Cloud API (Graph API).

NexScout never uses unofficial WhatsApp Web clients: they break WhatsApp's terms and get
numbers banned. Requirements (Meta's rules, not NexScout's): a WhatsApp Business app and phone
number id, an access token, the app secret (to verify webhooks), and for messages outside the
24-hour customer-service window an approved message template.

Outbound: interactive reply buttons (max 3, titles ≤ 20 chars) or a template.
Inbound: webhook (needs a public HTTPS URL, e.g. a tunnel). Every POST is verified with
`X-Hub-Signature-256` (HMAC-SHA256 of the raw body with the app secret) by the worker.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

from nexscout.infrastructure.channels.base import (
    ChannelError,
    OutboundMessage,
    SendResult,
    check_response,
    plain_text,
)

GRAPH = "https://graph.facebook.com"
DEFAULT_VERSION = "v23.0"


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


class WhatsAppAdapter:
    kind = "whatsapp"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        to = config.get("wa_id") or config.get("recipient")
        if not to:
            raise ChannelError("This WhatsApp channel isn't paired yet.", transient=False)
        return await self.send_to(client, config, secrets, str(to), msg)

    async def send_to(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        to: str,
        msg: OutboundMessage,
    ) -> SendResult:
        url = (
            f"{GRAPH}/{config.get('api_version', DEFAULT_VERSION)}/"
            f"{config['phone_number_id']}/messages"
        )
        text = plain_text(msg)[:1024]
        buttons = [a for a in msg.actions if a.token][:3]
        if config.get("template_name"):
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": config["template_name"],
                    "language": {"code": config.get("template_language", "en_US")},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": text[:1000]}]}
                    ],
                },
            }
        elif buttons:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.token, "title": b.label[:20]}}
                            for b in buttons
                        ]
                    },
                },
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text, "preview_url": False},
            }
        try:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {secrets['access_token']}"}
            )
        except httpx.HTTPError as exc:
            raise ChannelError("WhatsApp unreachable (network error or timeout).") from exc
        data = await check_response(resp, "WhatsApp")
        msgs = data.get("messages") or [{}]
        return SendResult(str(msgs[0].get("id")) if msgs[0].get("id") else None)


@dataclass(frozen=True)
class WhatsAppMessage:
    event_id: str
    from_id: str
    kind: str  # "button" | "text"
    text: str = ""
    button_id: str | None = None
    reply_to: str | None = None


def parse_webhook(payload: dict[str, Any]) -> list[WhatsAppMessage]:
    out: list[WhatsAppMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for m in value.get("messages", []) or []:
                ctx = (m.get("context") or {}).get("id")
                if m.get("type") == "interactive":
                    reply = (m.get("interactive") or {}).get("button_reply") or {}
                    out.append(
                        WhatsAppMessage(
                            str(m.get("id")),
                            str(m.get("from")),
                            "button",
                            button_id=reply.get("id"),
                            reply_to=ctx,
                        )
                    )
                elif m.get("type") == "button":  # template quick-reply
                    b = m.get("button") or {}
                    out.append(
                        WhatsAppMessage(
                            str(m.get("id")),
                            str(m.get("from")),
                            "button",
                            button_id=b.get("payload"),
                            reply_to=ctx,
                        )
                    )
                elif m.get("type") == "text":
                    out.append(
                        WhatsAppMessage(
                            str(m.get("id")),
                            str(m.get("from")),
                            "text",
                            text=str((m.get("text") or {}).get("body", ""))[:4000],
                            reply_to=ctx,
                        )
                    )
    return out
