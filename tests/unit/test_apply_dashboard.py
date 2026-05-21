"""Tests for the Rich-Live dashboard (``apply/dashboard.py``)."""

from __future__ import annotations

import io

from rich.console import Console

from nexscout.apply.dashboard import STATUS_PALETTE, LiveDashboard, WorkerState


def _console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def test_worker_state_elapsed_under_minute() -> None:
    s = WorkerState(worker_id=0)
    assert s.elapsed_str() == "—"
    import time as _t

    s.start_time = _t.monotonic() - 5.0
    out = s.elapsed_str()
    assert (out.endswith("s") and not out.endswith("0s")) or out == "5s"


def test_worker_state_elapsed_over_minute() -> None:
    s = WorkerState(worker_id=0)
    import time as _t

    s.start_time = _t.monotonic() - 75.0
    out = s.elapsed_str()
    assert "m" in out


def test_status_palette_covers_all_states() -> None:
    for k in ("starting", "idle", "applying", "applied", "failed", "expired", "captcha", "login_issue", "sso_required"):
        assert k in STATUS_PALETTE


def test_start_job_initialises_state() -> None:
    d = LiveDashboard(workers=2, console=_console())
    d.start_job(0, {"title": "Engineer", "site": "greenhouse", "fit_score": 8})
    s = d.workers[0]
    assert s.status == "starting"
    assert s.job_title == "Engineer"
    assert s.company == "greenhouse"
    assert s.score == 8


def test_tick_action_increments() -> None:
    d = LiveDashboard(workers=1, console=_console())
    d.start_job(0, {"title": "x", "site": "y"})
    d.tick_action(0, "navigate")
    d.tick_action(0, "click")
    assert d.workers[0].actions == 2
    assert d.workers[0].last_action == "click"
    assert d.workers[0].status == "applying"


def test_finish_job_status_transitions() -> None:
    d = LiveDashboard(workers=1, console=_console())
    d.start_job(0, {"title": "x", "site": "y"})
    d.finish_job(0, "APPLIED")
    assert d.workers[0].status == "applied"
    assert d.workers[0].jobs_applied == 1

    d.start_job(1, {"title": "x", "site": "y"})
    d.finish_job(1, "FAILED", reason="page_error")
    assert d.workers[1].status == "failed"
    assert d.workers[1].jobs_failed == 1

    d.start_job(2, {"title": "x", "site": "y"})
    d.finish_job(2, "CAPTCHA")
    assert d.workers[2].status == "captcha"

    d.start_job(3, {"title": "x", "site": "y"})
    d.finish_job(3, "EXPIRED")
    assert d.workers[3].status == "expired"

    d.start_job(4, {"title": "x", "site": "y"})
    d.finish_job(4, "LOGIN_ISSUE")
    assert d.workers[4].status == "login_issue"


def test_event_buffer_ring_eight() -> None:
    d = LiveDashboard(workers=1, console=_console())
    for i in range(20):
        d.add_event(f"evt {i}")
    assert len(d._events) == 8
    # Newest entries on the left (appendleft).
    assert "evt 19" in d._events[0]


def test_add_cost_accumulates() -> None:
    d = LiveDashboard(workers=1, console=_console())
    d.add_cost(0, 0.5)
    d.add_cost(0, 0.25)
    assert abs(d.workers[0].total_cost - 0.75) < 1e-9


def test_context_manager_lifecycle() -> None:
    d = LiveDashboard(workers=1, console=_console())
    with d as live:
        assert live is d
        d.start_job(0, {"title": "x", "site": "y"})
        d.tick_action(0, "navigate")
        d.finish_job(0, "APPLIED")
    # After exit, ``_live`` is reset.
    assert d._live is None


def test_render_handles_no_events() -> None:
    d = LiveDashboard(workers=2, console=_console())
    group = d._render()
    assert group is not None  # smoke test
