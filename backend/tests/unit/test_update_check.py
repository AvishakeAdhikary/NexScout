"""M16: the version check reads only a version-shaped tag, caches it, and never nags dev builds."""

import json
from typing import Any

import pytest

from nexscout.application import updates
from nexscout.infrastructure.fetch import FetchFailed
from tests.conftest import make_settings


class FakeGitHub:
    def __init__(self, status: int = 200, body: Any = None, fail: bool = False) -> None:
        self.status, self.body, self.fail, self.calls = status, body, fail, 0

    async def request(
        self, method: str, url: str, **_: Any
    ) -> tuple[int, dict[str, str], bytes, str]:
        self.calls += 1
        assert url == "https://api.github.com/repos/AvishakeAdhikary/NexScout/releases/latest"
        if self.fail:
            raise FetchFailed("Couldn't connect to the site (network error).")
        return self.status, {}, json.dumps(self.body).encode(), url


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    updates._cache.clear()


def _use(monkeypatch: pytest.MonkeyPatch, fake: FakeGitHub) -> None:
    real = updates.fetch_latest
    monkeypatch.setattr(updates, "fetch_latest", lambda repo: real(repo, fake))  # type: ignore[arg-type]


async def test_newer_release_is_reported_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub(
        body={
            "tag_name": "v2.3.0",
            "html_url": "https://github.com/AvishakeAdhikary/NexScout/releases/tag/v2.3.0",
        }
    )
    _use(monkeypatch, fake)
    settings = make_settings(update_check=True)
    info = await updates.version_info(settings, current="2.2.0")
    assert (info.latest, info.update_available) == ("2.3.0", True)
    assert info.url is not None
    assert info.url.endswith("/tag/v2.3.0")
    same = await updates.version_info(settings, current="2.3.0")
    assert same.update_available is False
    assert fake.calls == 1  # cached
    dev = await updates.version_info(settings, current="0.1.0-dev")
    assert dev.update_available is False  # a development build never nags


@pytest.mark.parametrize(
    "fake",
    [
        FakeGitHub(fail=True),
        FakeGitHub(status=403, body={"message": "rate limited"}),
        FakeGitHub(body={"tag_name": "<script>", "html_url": "https://evil.example"}),
    ],
)
async def test_failures_and_odd_answers_are_quiet(
    monkeypatch: pytest.MonkeyPatch, fake: FakeGitHub
) -> None:
    _use(monkeypatch, fake)
    info = await updates.version_info(make_settings(update_check=True), current="2.2.0")
    assert (info.latest, info.update_available, info.url) == (None, False, None)


async def test_foreign_release_url_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeGitHub(body={"tag_name": "v9.0.0", "html_url": "https://evil.example/x"}))
    info = await updates.version_info(make_settings(update_check=True), current="2.2.0")
    assert info.url == "https://github.com/AvishakeAdhikary/NexScout/releases/latest"


async def test_opt_out_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub(body={"tag_name": "v9.0.0"})
    _use(monkeypatch, fake)
    info = await updates.version_info(make_settings(update_check=False), current="2.2.0")
    assert (info.update_available, fake.calls) == (False, 0)
