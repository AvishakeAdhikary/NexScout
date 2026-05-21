"""Tests for ``apply.policy`` — manual_ats / blocked_sites / blocked_sso."""

from __future__ import annotations

from pathlib import Path

from nexscout.apply.policy import (
    ApplyPolicy,
    _host,
    _host_matches,
    load_policy,
    policy_from_dict,
)


def test_load_policy_real_sites_yaml_has_entries() -> None:
    """The packaged sites.yaml exists and feeds load_policy with some content."""
    pol = load_policy()
    # We don't know the exact list, but the load should succeed without error.
    assert isinstance(pol, ApplyPolicy)
    assert isinstance(pol.blocked_sites, list)


def test_load_policy_missing_file_returns_empty(tmp_path: Path) -> None:
    pol = load_policy(str(tmp_path / "no.yaml"))
    assert pol.manual_ats == []
    assert pol.blocked_sites == []
    assert pol.blocked_url_patterns == []
    assert pol.blocked_sso == []


def test_policy_from_dict_round_trip() -> None:
    raw = {
        "manual_ats": ["foo.com", "bar.io"],
        "blocked": {"sites": ["glassdoor"], "url_patterns": ["%blocked%"]},
        "blocked_sso": ["okta.com"],
    }
    pol = policy_from_dict(raw)
    assert pol.manual_ats == ["foo.com", "bar.io"]
    assert pol.blocked_sites == ["glassdoor"]
    assert pol.blocked_url_patterns == ["%blocked%"]
    assert pol.blocked_sso == ["okta.com"]


def test_is_manual_ats_matches_host_and_subdomains() -> None:
    pol = ApplyPolicy(manual_ats=["example.com"])
    assert pol.is_manual_ats("https://example.com/jobs/1")
    assert pol.is_manual_ats("https://www.example.com/jobs/1")
    assert pol.is_manual_ats("https://x.y.example.com/jobs")
    assert not pol.is_manual_ats("https://other.com/jobs")
    assert not pol.is_manual_ats(None)
    assert not pol.is_manual_ats("")


def test_is_blocked_site_case_insensitive() -> None:
    pol = ApplyPolicy(blocked_sites=["Glassdoor"])
    assert pol.is_blocked_site("glassdoor")
    assert pol.is_blocked_site("GLASSDOOR")
    assert not pol.is_blocked_site("greenhouse")
    assert not pol.is_blocked_site(None)
    assert not pol.is_blocked_site("")


def test_is_blocked_sso() -> None:
    pol = ApplyPolicy(blocked_sso=["okta.com", "auth0.com"])
    assert pol.is_blocked_sso("https://login.okta.com")
    assert pol.is_blocked_sso("https://okta.com/sso")
    assert not pol.is_blocked_sso("https://google.com")
    assert not pol.is_blocked_sso(None)


def test_host_helpers() -> None:
    assert _host("https://Foo.example.com/path") == "foo.example.com"
    assert _host("not a url") == ""
    assert _host_matches("a.foo.com", "foo.com") is True
    assert _host_matches("foo.com", ".foo.com") is True
    assert _host_matches("other.com", "foo.com") is False
    assert _host_matches("", "foo.com") is False
    assert _host_matches("foo.com", "") is False
