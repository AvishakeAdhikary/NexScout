"""SafeFetcher: SSRF blocking at connect time, re-checked redirects, robots.txt, caps, parsing."""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed, SafeFetcher, html_to_text

PAGE = """<html><head><title>PhD in Trustworthy NLP</title><style>p{}</style></head>
<body><nav><a href="/">Home</a></nav>
<h1>PhD in Trustworthy NLP</h1>
<p>Application deadline: 1 December 2026.</p>
<script>alert('x')</script>
<p>Required documents:</p><ul><li>CV</li><li>Two reference letters</li></ul>
<p>Supervisor: <a href="/people/beispiel">Prof. Dr. Jana Beispiel</a></p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def _send(
        self,
        code: int,
        body: bytes,
        ctype: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        match self.path:
            case "/robots.txt":
                self._send(200, b"User-agent: *\nDisallow: /private\n", "text/plain")
            case "/page":
                self._send(200, PAGE.encode())
            case "/private/page":
                self._send(200, PAGE.encode())
            case "/to-metadata":
                self._send(302, b"", headers={"Location": "http://169.254.169.254/latest/"})
            case "/to-page":
                self._send(301, b"", headers={"Location": "/page"})
            case "/loop":
                self._send(302, b"", headers={"Location": "/loop"})
            case "/big":
                self._send(200, b"<p>" + b"x" * 50_000 + b"</p>")
            case "/pdf":
                self._send(200, b"%PDF-1.4", "application/pdf")
            case _:
                self._send(404, b"not found")


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _local(**kw: Any) -> SafeFetcher:
    # Tests reach a server on 127.0.0.1, so private networks must be allowed explicitly here.
    return SafeFetcher(allow_private=True, min_interval_s=0, **kw)


async def test_private_and_loopback_blocked_by_default(server: str) -> None:
    fetcher = SafeFetcher(min_interval_s=0)
    for url in (f"{server}/page", "http://localhost/", "http://10.0.0.1/", "http://[::1]/"):
        with pytest.raises(FetchBlocked):
            await fetcher.fetch(url)


async def test_metadata_always_blocked_even_when_private_allowed() -> None:
    with pytest.raises(FetchBlocked):
        await _local(respect_robots=False).fetch("http://169.254.169.254/latest/meta-data/")


async def test_redirect_to_metadata_is_rechecked(server: str) -> None:
    with pytest.raises(FetchBlocked):
        await _local(respect_robots=False).fetch(f"{server}/to-metadata")


async def test_host_is_checked_when_connecting_not_just_before(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public-looking name that resolves to loopback (DNS rebinding) is refused at connect."""
    real = asyncio.BaseEventLoop.getaddrinfo

    async def fake(self: asyncio.BaseEventLoop, host: Any, *args: Any, **kw: Any) -> Any:
        if host == "rebind.attacker.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        return await real(self, host, *args, **kw)

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    port = server.rsplit(":", 1)[1]
    with pytest.raises(FetchBlocked):
        await SafeFetcher(min_interval_s=0, respect_robots=False).fetch(
            f"http://rebind.attacker.test:{port}/page"
        )


async def test_bad_schemes_and_credentials_blocked() -> None:
    fetcher = SafeFetcher(min_interval_s=0)
    for url in ("file:///etc/passwd", "ftp://example.com/x", "http://user:pw@example.com/"):
        with pytest.raises(FetchBlocked):
            await fetcher.fetch(url)


async def test_reads_page_text_title_and_links(server: str) -> None:
    res = await _local().fetch(f"{server}/to-page")
    assert res.status == 200
    assert res.final_url.endswith("/page")
    assert res.title == "PhD in Trustworthy NLP"
    assert "Application deadline: 1 December 2026." in res.text.splitlines()
    assert "- Two reference letters" in res.text.splitlines()
    assert "alert" not in res.text
    assert "p{}" not in res.text
    assert ("Prof. Dr. Jana Beispiel", f"{server}/people/beispiel") in res.links
    assert len(res.sha256) == 64


async def test_robots_txt_respected(server: str) -> None:
    with pytest.raises(FetchBlocked, match="robots"):
        await _local().fetch(f"{server}/private/page")


async def test_caps_and_failures(server: str) -> None:
    with pytest.raises(FetchFailed, match="size limit"):
        await _local(max_bytes=1_000).fetch(f"{server}/big")
    with pytest.raises(FetchFailed, match="content type"):
        await _local().fetch(f"{server}/pdf")
    with pytest.raises(FetchFailed, match="Too many redirects"):
        await _local().fetch(f"{server}/loop")
    with pytest.raises(FetchFailed, match="404"):
        await _local().fetch(f"{server}/nothing-here")


def test_html_to_text_keeps_structure() -> None:
    title, text, links = html_to_text(PAGE, "https://uni.example/x")
    assert title == "PhD in Trustworthy NLP"
    assert text.splitlines()[0] == "Home"
    assert links[-1] == ("Prof. Dr. Jana Beispiel", "https://uni.example/people/beispiel")
