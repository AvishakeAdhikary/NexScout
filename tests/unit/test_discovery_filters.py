"""Location accept/reject filter tests."""

from __future__ import annotations

from nexscout.discovery.jobspy import location_passes


def test_remote_keywords_always_pass() -> None:
    assert location_passes("Remote, US")
    assert location_passes("Work from home")
    assert location_passes("Anywhere")
    assert location_passes("Distributed")


def test_accept_match() -> None:
    assert location_passes("Toronto, ON", accept=["Toronto", "Vancouver"]) is True


def test_reject_non_remote() -> None:
    assert location_passes("Berlin, Germany", reject_non_remote=["germany", "india"]) is False
    # Remote signal wins.
    assert location_passes("Remote - Berlin, Germany", reject_non_remote=["germany"]) is True


def test_unknown_passes() -> None:
    assert location_passes("Mars, Solar System") is True


def test_empty_location_passes() -> None:
    assert location_passes(None) is True
    assert location_passes("") is True
