"""URL resolution against sites.yaml base_urls."""

from __future__ import annotations

from nexscout.enrichment import detail


def _reset_cache() -> None:
    detail._BASE_URL_CACHE = None


def test_absolute_urls_pass_through() -> None:
    _reset_cache()
    assert detail.resolve_relative_url("https://example.com/x", "Anything") == "https://example.com/x"


def test_relative_url_resolved_from_packaged_sites_yaml() -> None:
    _reset_cache()
    # "Job Bank Canada" is in the shipped sites.yaml.
    out = detail.resolve_relative_url("/jobs/123", "Job Bank Canada")
    assert out.startswith("https://www.jobbank.gc.ca/")
    assert out.endswith("/jobs/123")


def test_unknown_site_leaves_url_unchanged() -> None:
    _reset_cache()
    assert detail.resolve_relative_url("/jobs/x", "Nobody") == "/jobs/x"


def test_skip_sites_constant() -> None:
    assert "glassdoor" in detail.SKIP_SITES
    assert "google" in detail.SKIP_SITES
    assert "Workopolis" in detail.SKIP_SITES


def test_http_error_classification() -> None:
    assert detail.is_permanent_http_error(404)
    assert detail.is_permanent_http_error(410)
    assert detail.is_permanent_http_error(451)
    assert not detail.is_permanent_http_error(500)
    assert detail.is_transient_http_error(429)
    assert detail.is_transient_http_error(503)
    assert not detail.is_transient_http_error(404)


def test_site_delay_defaults() -> None:
    assert detail.site_delay("RemoteOK") == 3.0
    assert detail.site_delay("Hacker News Jobs") == 1.0
    assert detail.site_delay(None) == detail.DEFAULT_DELAY
