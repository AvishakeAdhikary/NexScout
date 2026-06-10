"""Static-HTML dashboard export (§17.2).

Produces a single self-contained ``.html`` file with:

* Header stat cards.
* Score-distribution chart as inline SVG (no D3 / Chart.js).
* By-site table.
* One card per job at ``fit_score >= 5``.
* Tiny vanilla JS for client-side text search across job titles + sites.

The output references no external CSS or JS — safe to commit, email, or
attach to a bug report.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from .routes.dashboard import _score_distribution_svg

_CSS = """
:root {
  --bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0; --text: #1e293b;
  --muted: #64748b; --accent: #f59e0b; --accent-text: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155; --text: #e2e8f0;
    --muted: #94a3b8; --accent: #f59e0b; --accent-text: #1e293b;
  }
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
       margin: 0; padding: 24px; color: var(--text); background: var(--bg);
       max-width: 1100px; margin-left: auto; margin-right: auto; }
h1 { margin: 0 0 4px; font-size: 1.75rem; }
h2 { margin: 28px 0 8px; font-size: 1.15rem; }
.muted { color: var(--muted); font-size: 12px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
         gap: 12px; margin: 16px 0; }
.card { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; background: var(--surface);
        box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.card h3 { margin: 0 0 4px; font-size: 12px; color: var(--muted); font-weight: 600; }
.card p { margin: 0; font-size: 24px; font-weight: 700; color: var(--text); }
table { border-collapse: collapse; width: 100%; margin: 12px 0; background: var(--surface);
        border-radius: 12px; overflow: hidden; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--bg); font-weight: 600; font-size: 13px; color: var(--muted); }
.jobs { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 12px; }
.job { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: var(--surface); }
.job .score { display: inline-block; padding: 2px 10px; border-radius: 999px;
              background: var(--accent); color: var(--accent-text); font-weight: 700; font-size: 12px; }
.job strong { display: block; margin: 6px 0 2px; }
.job .meta { font-size: 12px; color: var(--muted); margin: 4px 0; }
.job a { color: var(--accent); text-decoration: none; word-break: break-all; }
.search { width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
          font-size: 14px; margin-bottom: 16px; background: var(--surface); color: var(--text); }
.score-dist { max-width: 480px; display: block; }
"""

_JS = """
(function () {
  var input = document.getElementById('q');
  if (!input) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll('.job'));
  input.addEventListener('input', function (e) {
    var needle = (e.target.value || '').toLowerCase();
    cards.forEach(function (c) {
      var hay = (c.getAttribute('data-search') || '').toLowerCase();
      c.style.display = (!needle || hay.indexOf(needle) >= 0) ? '' : 'none';
    });
  });
}());
"""


def _job_card(row: dict[str, Any]) -> str:
    title = escape(row.get("title") or row.get("url") or "Untitled")
    url = escape(row.get("url") or "", quote=True)
    site = escape(row.get("site") or "")
    location = escape(row.get("location") or "")
    fit = row.get("fit_score") or 0
    status = escape(row.get("apply_status") or "pending")
    discovered = escape(row.get("discovered_at") or "")
    search_blob = " ".join(
        str(v) for v in (row.get("title"), row.get("site"), row.get("location"), row.get("url")) if v
    )
    return (
        f'<article class="job" data-search="{escape(search_blob, quote=True)}">'
        f'<span class="score">{fit}/10</span> '
        f"<strong>{title}</strong>"
        f'<div class="meta">{site} &middot; {location} &middot; {status}</div>'
        f'<div class="meta">Discovered: {discovered}</div>'
        f'<a href="{url}">{url}</a>'
        f"</article>"
    )


def _stat_card(label: str, value: Any) -> str:
    return f'<div class="card"><h3>{escape(label)}</h3><p>{escape(str(value))}</p></div>'


def _by_site_table(by_site: dict[str, int]) -> str:
    if not by_site:
        return "<p>No jobs yet.</p>"
    rows = "".join(
        f"<tr><td>{escape(site or '(unknown)')}</td><td>{count}</td></tr>"
        for site, count in sorted(by_site.items(), key=lambda kv: -kv[1])
    )
    return f"<table><thead><tr><th>Site</th><th>Count</th></tr></thead><tbody>{rows}</tbody></table>"


def render_static_dashboard(stats: dict[str, Any], jobs: list[dict[str, Any]]) -> str:
    """Render the dashboard as a single self-contained HTML string."""
    now = datetime.now().isoformat(timespec="seconds")
    counters = "".join(
        _stat_card(label, stats.get(key, 0))
        for label, key in (
            ("Total", "total"),
            ("Scored", "scored"),
            ("Tailored", "tailored"),
            ("Applied", "applied"),
            ("Apply errors", "apply_errors"),
            ("Ready to apply", "ready_to_apply"),
            ("Pending detail", "pending_detail"),
            ("With description", "with_description"),
        )
    )
    chart = _score_distribution_svg(stats.get("score_distribution") or {})
    by_site = _by_site_table(stats.get("by_site") or {})
    job_cards = "".join(_job_card(j) for j in jobs)

    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        "<title>NexScout — Static Dashboard</title>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        "<h1>NexScout — Static Dashboard</h1>"
        "<p>NexScout finds jobs that match you, writes a tailored résumé for each, "
        "and applies for you automatically. This is a snapshot you can save or share.</p>"
        f'<p class="muted">Generated {escape(now)}. Self-contained — no external assets.</p>'
        f'<section class="stats">{counters}</section>'
        "<h2>Score distribution</h2>"
        f'<div class="score-chart">{chart}</div>'
        "<h2>By source</h2>"
        f"{by_site}"
        f"<h2>Jobs at fit_score &ge; 5 ({len(jobs)})</h2>"
        '<input id="q" class="search" type="search" placeholder="Filter by title, site, location…">'
        f'<div class="jobs">{job_cards or "<p>No jobs yet.</p>"}</div>'
        f"<script>{_JS}</script>"
        "</body></html>"
    )


__all__ = ["render_static_dashboard"]
