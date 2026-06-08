"""Tests for the static-HTML dashboard export (``web.export``)."""

from __future__ import annotations

from typing import Any

from nexscout.web.export import render_static_dashboard
from nexscout.web.routes.dashboard import _score_distribution_svg


def _stats(distribution: dict[int, int] | None = None) -> dict[str, Any]:
    return {
        "total": 12,
        "by_site": {"greenhouse": 8, "lever": 4},
        "pending_detail": 2,
        "with_description": 10,
        "detail_errors": 0,
        "scored": 9,
        "unscored": 1,
        "score_distribution": distribution if distribution is not None else {7: 2, 8: 4, 9: 3},
        "tailored": 5,
        "untailored_eligible": 1,
        "tailor_exhausted": 0,
        "with_cover_letter": 2,
        "cover_exhausted": 0,
        "applied": 1,
        "apply_errors": 0,
        "ready_to_apply": 4,
    }


def test_render_static_dashboard_no_external_assets() -> None:
    html = render_static_dashboard(_stats(), [])
    assert "<!doctype html>" in html
    assert "<style>" in html
    assert "<script>" in html
    assert "https://" not in html  # No external CSS/JS includes.
    assert 'src="http' not in html
    assert 'href="http' not in html


def test_render_static_dashboard_renders_counters() -> None:
    html = render_static_dashboard(_stats(), [])
    for label in ("Total", "Scored", "Applied", "Apply errors", "Ready to apply"):
        assert label in html
    assert "<svg" in html  # inline SVG chart
    assert ">12<" in html  # the Total = 12 value


def test_render_static_dashboard_renders_job_cards() -> None:
    jobs = [
        {
            "id": 1,
            "url": "https://example.com/a",
            "title": "Engineer A",
            "site": "greenhouse",
            "location": "Remote",
            "fit_score": 9,
            "apply_status": "applied",
            "discovered_at": "2025-01-01",
            "applied_at": "2025-01-02",
        },
        {
            "id": 2,
            "url": "https://example.com/b",
            "title": "Engineer B",
            "site": "lever",
            "location": "SF",
            "fit_score": 7,
            "apply_status": None,
            "discovered_at": "2025-01-03",
        },
    ]
    html = render_static_dashboard(_stats(), jobs)
    assert "Engineer A" in html
    assert "Engineer B" in html
    assert "9/10" in html
    assert "Jobs at fit_score" in html


def test_render_static_dashboard_handles_empty_distribution() -> None:
    """Score-distribution chart renders gracefully on zero scored jobs."""
    stats = _stats({})
    html = render_static_dashboard(stats, [])
    assert "no scored jobs yet" in html


def test_score_distribution_svg_empty() -> None:
    svg = _score_distribution_svg({})
    assert "<svg" in svg
    assert "no scored jobs yet" in svg


def test_score_distribution_svg_non_empty() -> None:
    svg = _score_distribution_svg({5: 1, 6: 2, 7: 4, 8: 3})
    assert "<svg" in svg
    assert "<rect" in svg
    # Score labels appear in axis text.
    for s in ("5", "6", "7", "8"):
        assert f">{s}<" in svg


def test_render_static_dashboard_escapes_html() -> None:
    jobs = [
        {
            "id": 1,
            "url": "https://x.com/<a>",
            "title": "<script>x</script>",
            "site": "greenhouse",
            "location": "",
            "fit_score": 8,
            "apply_status": None,
        }
    ]
    html = render_static_dashboard(_stats(), jobs)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
