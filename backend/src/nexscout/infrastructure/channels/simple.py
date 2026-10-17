"""Outbound-only channels: signed webhook (n8n, Zapier, your own bot), Slack incoming webhook,
and email over SMTP. Actions appear as links to the app (the app enforces login)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

import httpx

from nexscout.infrastructure.channels.base import (
    ChannelError,
    OutboundMessage,
    SendResult,
    check_response,
    plain_text,
)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """`X-NexScout-Signature: sha256=<hex>` over "<timestamp>.<body>" (replay-resistant)."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


class WebhookAdapter:
    kind = "webhook"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        payload = {
            "event": msg.event,
            "title": msg.title,
            "body": msg.body,
            "link": msg.link,
            "actions": [{"label": a.label, "url": a.url} for a in msg.actions if a.url],
            "sent_at": int(time.time()),
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-NexScout-Timestamp": ts,
            "X-NexScout-Signature": sign(secrets["signing_secret"], ts, body),
            "User-Agent": "NexScout-Webhook/1",
        }
        try:
            resp = await client.post(secrets["url"], content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ChannelError(f"Webhook unreachable: {type(exc).__name__}") from exc
        await check_response(resp, "Webhook")
        return SendResult(resp.headers.get("X-Request-Id"))


class SlackAdapter:
    kind = "slack"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        text = plain_text(msg)
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{msg.title}*\n{msg.body}"[:2900]},
            }
        ]
        if msg.link:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in NexScout"},
                            "url": msg.link,
                        }
                    ],
                }
            )
        try:
            resp = await client.post(secrets["webhook_url"], json={"text": text, "blocks": blocks})
        except httpx.HTTPError as exc:
            raise ChannelError(f"Slack unreachable: {type(exc).__name__}") from exc
        await check_response(resp, "Slack")
        return SendResult(None)


class EmailAdapter:
    kind = "email"

    async def send(
        self,
        client: httpx.AsyncClient,
        config: dict[str, Any],
        secrets: dict[str, str],
        msg: OutboundMessage,
    ) -> SendResult:
        em = EmailMessage()
        em["Subject"] = f"[NexScout] {msg.title}"[:200]
        em["From"] = config["from_address"]
        em["To"] = config["to_address"]
        em.set_content(
            plain_text(msg) + "\n\n-- \nYou get this because you added this address "
            "in NexScout (Settings > Notifications)."
        )

        def deliver() -> str:
            host, port = config["smtp_host"], int(config.get("smtp_port", 587))
            ctx = ssl.create_default_context()
            if config.get("security", "starttls") == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
            with server:
                if config.get("security", "starttls") == "starttls":
                    server.starttls(context=ctx)
                if config.get("username"):
                    server.login(config["username"], secrets.get("password", ""))
                server.send_message(em)
            return str(em.get("Message-ID") or "")

        try:
            return SendResult(await asyncio.to_thread(deliver) or None)
        except smtplib.SMTPAuthenticationError as exc:
            raise ChannelError("The email server rejected the login.", transient=False) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise ChannelError(f"Email not sent: {type(exc).__name__}") from exc
