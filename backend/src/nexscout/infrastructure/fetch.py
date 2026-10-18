"""SSRF-safe fetching of public web pages for research (SECURITY.md: SSRF / metadata access).

- http(s) only, no credentials in URLs, a fixed small set of text content types.
- Every connection is made to an IP address that was checked *at connect time* (custom network
  backend), so DNS rebinding between a check and the connect can't reach private networks.
  TLS still verifies the certificate for the original host name (SNI uses the URL host).
- Redirects are followed manually (max 5) and each hop is checked again.
- Size and time caps; robots.txt is respected; one request per host per second.

Fetched content is untrusted data. Callers store it and quote from it; it is never treated as
instructions.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx

from nexscout.infrastructure.security.urls import is_blocked_ip

USER_AGENT = "NexScoutResearch/0.1 (personal research assistant; respects robots.txt)"
ROBOTS_AGENT = "NexScoutResearch"
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
MAX_TEXT_CHARS = 200_000


class FetchBlocked(Exception):
    """The address is not allowed (private network, metadata, bad scheme, robots.txt)."""


class FetchFailed(Exception):
    """The page could not be fetched (network error, status, size, type)."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    title: str | None
    text: str
    links: list[tuple[str, str]]  # (anchor text, absolute href)
    sha256: str
    size: int
    fetched_at: datetime


def _check_url(url: str) -> httpx.URL:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchBlocked("Only http(s) addresses with a host name can be read.")
    if parts.username or parts.password:
        raise FetchBlocked("Addresses must not contain a username or password.")
    return httpx.URL(url)


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Resolves the host itself, refuses blocked addresses, and connects to the checked IP."""

    def __init__(self, *, allow_private: bool) -> None:
        self._inner = httpcore.AnyIOBackend()
        self._allow_private = allow_private

    async def _resolve(self, host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"Can't resolve host {host!r}") from exc
        return [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore interface)
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        ips = await self._resolve(host)
        if not ips or any(is_blocked_ip(ip, self._allow_private) for ip in ips):
            raise FetchBlocked("That address points to a restricted network location.")
        return await self._inner.connect_tcp(
            str(ips[0]),
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore interface)
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise FetchBlocked("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, *, allow_private: bool) -> None:
        super().__init__(trust_env=False)
        # httpx has no public hook for the network backend; swap the pool it built (covered by
        # tests/unit/test_fetch.py, which fails if this stops pinning).
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            network_backend=_PinnedBackend(allow_private=allow_private),
            max_connections=10,
        )


class _TextExtractor(HTMLParser):
    """Readable text with block structure kept as lines, list items as "- ", plus links."""

    _BLOCK: ClassVar[frozenset[str]] = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "br",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "table",
            "header",
            "footer",
            "main",
            "dd",
            "dt",
            "blockquote",
        }
    )
    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "noscript", "template", "svg", "head"}
    )

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title: str | None = None
        self._skip = 0
        self._in_title = False
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._href = urljoin(self.base_url, href) if href else None
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK or tag == "li":
            self.parts.append("\n")
        elif tag == "a" and self._href:
            text = " ".join("".join(self._anchor).split())
            if text and self._href.startswith(("http://", "https://")):
                self.links.append((text, self._href))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data.strip()
            return
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        out: list[str] = []
        for line in lines:
            if line in ("", "-"):
                if out and out[-1] != "":
                    out.append("")
                continue
            out.append(line)
        return "\n".join(out).strip()[:MAX_TEXT_CHARS]


def html_to_text(html: str, base_url: str = "") -> tuple[str | None, str, list[tuple[str, str]]]:
    parser = _TextExtractor(base_url)
    parser.feed(html)
    parser.close()
    return (parser.title or None), parser.text(), parser.links


class SafeFetcher:
    def __init__(
        self,
        *,
        allow_private: bool = False,
        timeout_s: float = 20.0,
        max_bytes: int = 5 * 1024 * 1024,
        max_redirects: int = 5,
        respect_robots: bool = True,
        min_interval_s: float = 1.0,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.user_agent = user_agent
        self.allow_private = allow_private
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.respect_robots = respect_robots
        self.min_interval_s = min_interval_s
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=_PinnedTransport(allow_private=self.allow_private),
            timeout=self.timeout_s,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,text/plain;q=0.9"},
        )

    async def _pace(self, host: str) -> None:
        async with self._lock:
            wait = self._last.get(host, 0.0) + self.min_interval_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def _get(self, client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, bytes, str]:
        """GET with manual, re-checked redirects. Returns (response, body, final url)."""
        return await self._send(client, "GET", url)

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, bytes, str]:
        """One request with manual, re-checked redirects (a redirected POST continues as GET,
        like a browser). Returns (response, body, final url)."""
        current = url
        for _ in range(self.max_redirects + 1):
            target = _check_url(current)
            await self._pace(target.host)
            try:
                async with client.stream(method, target, content=content, headers=headers) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        current = urljoin(str(target), resp.headers["location"])
                        method, content = "GET", None
                        continue
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise FetchFailed("The page is larger than the size limit.")
                    return resp, bytes(body), str(target)
            except FetchBlocked:
                raise
            except httpx.TimeoutException as exc:
                raise FetchFailed("The site took too long to respond.") from exc
            except httpx.HTTPError as exc:
                if isinstance(exc.__cause__, FetchBlocked) or isinstance(
                    exc.__context__, FetchBlocked
                ):
                    raise FetchBlocked(str(exc.__cause__ or exc.__context__)) from exc
                raise FetchFailed("Couldn't connect to the site (network error).") from exc
        raise FetchFailed("Too many redirects.")

    async def _allowed_by_robots(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp, body, _ = await self._get(client, f"{origin}/robots.txt")
                if 400 <= resp.status_code < 500:
                    parser = None  # no robots.txt: everything allowed (RFC 9309 §2.3.1.3)
                elif resp.status_code >= 500:
                    parser = RobotFileParser()
                    parser.parse(["User-agent: *", "Disallow: /"])  # unreachable: assume no
                else:
                    assert parser is not None
                    parser.parse(body.decode("utf-8", errors="replace").splitlines())
            except FetchFailed:
                parser = RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
            self._robots[origin] = parser
        robots = self._robots[origin]
        return robots is None or robots.can_fetch(ROBOTS_AGENT, url)

    async def robots_allows(self, url: str) -> bool | None:
        """robots.txt verdict for NexScout on `url`; None when it couldn't be checked."""
        try:
            _check_url(url)
            async with self._client() as client:
                return await self._allowed_by_robots(client, url)
        except (FetchBlocked, FetchFailed):
            return None

    async def request(
        self,
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool | None = None,
    ) -> tuple[int, dict[str, str], bytes, str]:
        """Any public HTTP request (APIs, feeds, pages) with the same SSRF, size and pacing
        guards. Returns (status, headers, body, final url). Robots are checked when
        `check_robots` (default: this fetcher's `respect_robots`)."""
        _check_url(url)
        robots = self.respect_robots if check_robots is None else check_robots
        async with self._client() as client:
            if robots and not await self._allowed_by_robots(client, url):
                raise FetchBlocked(
                    "The site's robots.txt asks automated tools not to read this page."
                )
            resp, body, final_url = await self._send(
                client, method, url, content=content, headers=headers
            )
        return resp.status_code, dict(resp.headers), body, final_url

    async def fetch(self, url: str) -> FetchResult:
        _check_url(url)
        async with self._client() as client:
            if self.respect_robots and not await self._allowed_by_robots(client, url):
                raise FetchBlocked(
                    "The site's robots.txt asks automated tools not to read this page."
                )
            resp, body, final_url = await self._get(client, url)
        if resp.status_code >= 400:
            raise FetchFailed(f"The site answered with HTTP {resp.status_code}.")
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in TEXT_TYPES:
            raise FetchFailed(f"Unsupported content type: {content_type or 'unknown'}.")
        decoded = body.decode(resp.encoding or "utf-8", errors="replace")
        if content_type == "text/plain":
            title, text, links = None, decoded[:MAX_TEXT_CHARS], list[tuple[str, str]]()
        else:
            title, text, links = html_to_text(decoded, final_url)
        return FetchResult(
            url=url,
            final_url=final_url,
            status=resp.status_code,
            content_type=content_type,
            title=title,
            text=text,
            links=links,
            sha256=hashlib.sha256(body).hexdigest(),
            size=len(body),
            fetched_at=datetime.now(UTC),
        )
