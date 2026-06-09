"""Discord delivery channel for OpenClaw notifications.

NexScout speaks to Discord directly (no external OpenClaw binary is
needed) and emits one message per pending question, manual CAPTCHA
alert, or apply summary.

The channel is enabled when ``DISCORD_WEBHOOK_URL`` is present (the
preferred path) *or* when both ``DISCORD_BOT_TOKEN`` and
``DISCORD_CHANNEL_ID`` are present in the environment (or passed
explicitly). HTTP delivery uses :mod:`httpx` with bounded retries:

* 3 attempts, 2/4/8 second exponential back-off on network errors and
  HTTP 5xx responses.
* HTTP 429 honours the JSON ``retry_after`` value (in seconds, as
  Discord returns it) or the ``Retry-After`` header when present.

Webhook delivery returns HTTP 204 (No Content) on success; bot delivery
returns HTTP 200. Both are treated as success.

Messages are Discord-markdown formatted (``**bold**``, plain URLs, and
inline ``code``). Unlike Telegram, Discord uses markdown rather than
HTML, so no escaping is performed.

Tests inject an ``httpx.MockTransport`` via the ``transport`` kwarg so
network access is never required.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

#: Discord REST API base URL for bot-mode message delivery.
_API_BASE = "https://discord.com/api/v10/channels/{channel_id}/messages"

#: Retry plan for transient failures (seconds between attempts).
_RETRY_BACKOFF: tuple[float, ...] = (2.0, 4.0, 8.0)


class DiscordChannel:
    """Sync Discord delivery channel used by the OpenClaw integration."""

    def __init__(
        self,
        webhook_url: str | None = None,
        bot_token: str | None = None,
        channel_id: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        sleep: Any = time.sleep,
    ) -> None:
        self._webhook_url = webhook_url or ""
        self._bot_token = bot_token or ""
        self._channel_id = channel_id or ""
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> DiscordChannel | None:
        """Build from ``DISCORD_WEBHOOK_URL`` or bot token + channel id.

        Webhook mode is preferred: if ``DISCORD_WEBHOOK_URL`` is set the
        channel uses it. Otherwise both ``DISCORD_BOT_TOKEN`` and
        ``DISCORD_CHANNEL_ID`` must be present. Returns ``None`` when no
        usable credentials are configured so callers can gracefully skip
        delivery.
        """
        webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if webhook:
            return cls(webhook_url=webhook)
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
        if token and channel_id:
            return cls(bot_token=token, channel_id=channel_id)
        return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url) or (bool(self._bot_token) and bool(self._channel_id))

    @property
    def channel_id(self) -> str:
        return self._channel_id

    # ------------------------------------------------------------------
    # Low-level send (single message)
    # ------------------------------------------------------------------

    def send(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> bool:
        """POST a message to Discord. Returns ``True`` on success.

        The ``parse_mode`` and ``disable_web_page_preview`` kwargs are
        accepted for interface compatibility with the Telegram channel
        but ignored — Discord uses markdown and has no equivalent.
        """
        if not self.enabled:
            log.debug("discord: channel disabled, dropping message")
            return False

        if self._webhook_url:
            url = self._webhook_url
            headers: dict[str, str] = {}
        else:
            url = _API_BASE.format(channel_id=self._channel_id)
            headers = {"Authorization": f"Bot {self._bot_token}"}
        payload = {"content": text}

        for attempt, backoff in enumerate((*_RETRY_BACKOFF, None), start=1):
            try:
                with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e:
                log.warning("discord: network error on attempt %d: %s", attempt, e)
                if backoff is None:
                    return False
                self._sleep(backoff)
                continue

            # Webhooks return 204 (No Content); bot API returns 200.
            if resp.status_code in (200, 204):
                return True

            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp)
                if backoff is None:
                    log.warning("discord: 429 with no retries left")
                    return False
                wait = retry_after if retry_after is not None else backoff
                log.info("discord: 429 received, sleeping %.1fs (attempt %d)", wait, attempt)
                self._sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                log.warning("discord: HTTP %d on attempt %d", resp.status_code, attempt)
                if backoff is None:
                    return False
                self._sleep(backoff)
                continue

            # 4xx (other) → not retriable.
            log.warning(
                "discord: HTTP %d (non-retriable): %s",
                resp.status_code,
                resp.text[:200],
            )
            return False

        return False

    # ------------------------------------------------------------------
    # High-level helpers (formatting)
    # ------------------------------------------------------------------

    def send_question(
        self,
        question_id: int,
        question: str,
        job_url: str | None = None,
    ) -> bool:
        """Format a pending question as a Discord message and deliver it."""
        lines = [
            "**NexScout — pending question**",
            f"**Q{question_id}**: {question}",
        ]
        if job_url:
            lines.append(f"Job: {job_url}")
        lines.append("")
        lines.append(f"Reply with `/answer {question_id} <your reply>`")
        return self.send("\n".join(lines))

    def send_captcha_alert(
        self,
        job_url: str,
        job_title: str | None = None,
    ) -> bool:
        """Notify the user that a job needs manual CAPTCHA solving."""
        header = "**NexScout — manual CAPTCHA required**"
        title_line = f"**{job_title}**" if job_title else ""
        body = [
            header,
            title_line,
            f"Job: {job_url}",
            "",
            "Solve the CAPTCHA in your own browser, then resume the application.",
        ]
        return self.send("\n".join(line for line in body if line))

    def send_apply_summary(self, summary: dict[str, Any]) -> bool:
        """Send a one-shot tick / apply summary."""
        lines = ["**NexScout — apply summary**"]
        for key in (
            "discovered",
            "enriched",
            "scored",
            "tailored",
            "rendered",
            "applied",
            "questions_surfaced",
        ):
            if key in summary:
                lines.append(f"{key}: `{summary[key]}`")
        if "errors" in summary:
            errs = summary["errors"]
            n = len(errs) if isinstance(errs, list) else int(errs or 0)
            lines.append(f"errors: `{n}`")
        return self.send("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Read ``retry_after`` (seconds) from a Discord 429, else ``Retry-After`` header."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        ra = body.get("retry_after")
        if isinstance(ra, (int, float)):
            return float(ra)
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            return None
    return None


__all__ = ["DiscordChannel"]
