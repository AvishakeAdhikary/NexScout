"""Telegram delivery channel for OpenClaw notifications.

NexScout speaks to the Telegram Bot API directly (no external OpenClaw
binary is needed) and emits one message per pending question, manual
CAPTCHA alert, or apply summary.

The channel is enabled when both ``TELEGRAM_BOT_TOKEN`` and
``TELEGRAM_CHAT_ID`` are present in the environment (or passed
explicitly). HTTP delivery uses :mod:`httpx` with bounded retries:

* 3 attempts, 2/4/8 second exponential back-off on network errors and
  HTTP 5xx responses.
* HTTP 429 honours the JSON ``parameters.retry_after`` value (or
  ``Retry-After`` header) when present.

Tests inject an ``httpx.MockTransport`` via the ``transport`` kwarg so
network access is never required.
"""

from __future__ import annotations

import logging
import os
import time
from html import escape
from typing import Any

import httpx

log = logging.getLogger(__name__)

#: Telegram Bot API base URL (formatted with the bot token).
_API_BASE = "https://api.telegram.org/bot{token}"

#: Retry plan for transient failures (seconds between attempts).
_RETRY_BACKOFF: tuple[float, ...] = (2.0, 4.0, 8.0)


class TelegramChannel:
    """Sync Telegram delivery channel used by the OpenClaw integration."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        sleep: Any = time.sleep,
    ) -> None:
        self._bot_token = bot_token or ""
        self._chat_id = chat_id or ""
        self._transport = transport
        self._timeout = timeout
        self._sleep = sleep

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> TelegramChannel | None:
        """Build from ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID``.

        Returns ``None`` when either env var is missing so callers can
        gracefully skip delivery.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            return None
        return cls(bot_token=token, chat_id=chat_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token) and bool(self._chat_id)

    @property
    def chat_id(self) -> str:
        return self._chat_id

    # ------------------------------------------------------------------
    # Low-level send (single message)
    # ------------------------------------------------------------------

    def send(
        self,
        text: str,
        *,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """POST a message to Telegram. Returns ``True`` on HTTP 200."""
        if not self.enabled:
            log.debug("telegram: channel disabled, dropping message")
            return False

        url = _API_BASE.format(token=self._bot_token) + "/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        for attempt, backoff in enumerate((*_RETRY_BACKOFF, None), start=1):
            try:
                with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                    resp = client.post(url, json=payload)
            except httpx.HTTPError as e:
                log.warning("telegram: network error on attempt %d: %s", attempt, e)
                if backoff is None:
                    return False
                self._sleep(backoff)
                continue

            if resp.status_code == 200:
                return True

            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp)
                if backoff is None:
                    log.warning("telegram: 429 with no retries left")
                    return False
                wait = retry_after if retry_after is not None else backoff
                log.info("telegram: 429 received, sleeping %.1fs (attempt %d)", wait, attempt)
                self._sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                log.warning("telegram: HTTP %d on attempt %d", resp.status_code, attempt)
                if backoff is None:
                    return False
                self._sleep(backoff)
                continue

            # 4xx (other) → not retriable.
            log.warning(
                "telegram: HTTP %d (non-retriable): %s",
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
        """Format a pending question as a Telegram message and deliver it."""
        lines = [
            "<b>NexScout — pending question</b>",
            f"<b>Q{question_id}</b>: {escape(question)}",
        ]
        if job_url:
            lines.append(f'Job: <a href="{escape(job_url, quote=True)}">{escape(job_url)}</a>')
        lines.append("")
        lines.append(f"Reply with <code>/answer {question_id} &lt;your reply&gt;</code>")
        return self.send("\n".join(lines))

    def send_captcha_alert(
        self,
        job_url: str,
        job_title: str | None = None,
    ) -> bool:
        """Notify the user that a job needs manual CAPTCHA solving."""
        header = "<b>NexScout — manual CAPTCHA required</b>"
        title_line = f"<b>{escape(job_title)}</b>" if job_title else ""
        link = f'<a href="{escape(job_url, quote=True)}">{escape(job_url)}</a>'
        body = [
            header,
            title_line,
            f"Job: {link}",
            "",
            "Solve the CAPTCHA in your own browser, then resume the application.",
        ]
        return self.send("\n".join(line for line in body if line))

    def send_apply_summary(self, summary: dict[str, Any]) -> bool:
        """Send a one-shot tick / apply summary."""
        lines = ["<b>NexScout — apply summary</b>"]
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
                lines.append(f"{escape(key)}: <code>{escape(str(summary[key]))}</code>")
        if "errors" in summary:
            errs = summary["errors"]
            n = len(errs) if isinstance(errs, list) else int(errs or 0)
            lines.append(f"errors: <code>{n}</code>")
        return self.send("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Read ``retry_after`` from the Telegram 429 response, else ``Retry-After`` header."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        params = body.get("parameters")
        if isinstance(params, dict):
            ra = params.get("retry_after")
            if isinstance(ra, int | float):
                return float(ra)
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            return None
    return None


__all__ = ["TelegramChannel"]
