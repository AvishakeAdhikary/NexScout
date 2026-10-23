"""The AI assistant's tool allow-list: plain code decides, whatever the model proposes."""

import pytest

from nexscout.domain.assistant_tools import BLOCKED, TOOLS, Refused, parse_call
from nexscout.domain.skill_discovery import verify_proposals


@pytest.mark.parametrize(
    "name", ["submit_application", "submit", "approve", "decide_approval", "delete", "pay"]
)
def test_consequential_actions_are_never_tools(name: str) -> None:
    with pytest.raises(Refused, match="never available"):
        parse_call(name, {})


def test_no_allowed_tool_can_submit_send_approve_pay_or_delete() -> None:
    for name in TOOLS:
        assert not any(word in name for word in ("submit", "send", "approve", "pay", "delete"))
    assert not BLOCKED & set(TOOLS)


def test_unknown_tools_and_bad_arguments_are_refused() -> None:
    with pytest.raises(Refused, match="no tool called"):
        parse_call("run_shell", {})
    with pytest.raises(Refused, match="Invalid arguments"):
        parse_call("opportunity_details", {"opportunity_id": "../../etc"})
    with pytest.raises(Refused, match="Invalid arguments"):
        parse_call("needs_you", {"extra": 1})  # unknown arguments aren't passed through
    call = parse_call("top_matches", {"academic": True, "limit": 3})
    assert call.args == {"academic": True, "q": None, "limit": 3}
    assert not call.spec.starts_work
    assert parse_call("start_search", {}).spec.starts_work


def test_suggested_skills_must_be_in_the_users_own_text() -> None:
    sources = {
        "fact:1": "Machine Learning Engineer at Lumen Robotics · Fine-tune models with PyTorch.",
        "document:2": "Built the kiosk service in Python and Docker.",
    }
    kept, dropped = verify_proposals(
        [
            {"name": "PyTorch", "quote": "fine-tune models with  PyTorch", "source_id": "fact:1"},
            {"name": "Docker", "quote": "in Python and Docker.", "source_id": "document:2"},
            {"name": "Kubernetes", "quote": "with Kubernetes", "source_id": "document:2"},
            {"name": "Rust", "quote": "Built the kiosk service", "source_id": "document:2"},
            {"name": "Python", "quote": "in Python and Docker.", "source_id": "document:9"},
            {"name": "Python", "quote": "in Python and Docker.", "source_id": "document:2"},
            {
                "name": "A very long sentence that is not a skill at all, really",
                "quote": "x",
                "source_id": "fact:1",
            },
            {"name": "docker", "quote": "Python and Docker", "source_id": "document:2"},
        ],
        sources,
        existing_skills=[{"name": "Python"}],
    )
    assert [k.name for k in kept] == ["PyTorch", "Docker"]
    reasons = {d["name"]: d["reason"] for d in dropped}
    assert reasons["Kubernetes"] == "its quote isn't in the cited text"
    assert reasons["Rust"] == "the quote doesn't mention it"
    assert reasons["docker"] == "you already have it"  # proposed twice: once is enough
    assert "you already have it" in [d["reason"] for d in dropped if d["name"] == "Python"]
    assert "cites a source that isn't yours" in [d["reason"] for d in dropped]
