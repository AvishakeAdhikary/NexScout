"""Referral suggestions never use a relationship without referral permission."""

from nexscout.domain.referrals import suggest_referrals


def _a(i: str, person: str | None, org: str, rel: str, allowed: bool) -> dict[str, object]:
    return {
        "id": i,
        "person_name": person,
        "organization": org,
        "relationship_type": rel,
        "role": None,
        "status": "current",
        "may_use_for_referral": allowed,
    }


def test_matches_employer_by_normalized_name_and_permission() -> None:
    affs = [
        _a("1", "Zoe", "The ACME Ltd.", "colleague", True),
        _a("2", "Ann", "acme gmbh", "authorized_referrer", True),
        _a("3", "Bob", "Acme", "current_employee", False),
        _a("4", None, "Acme", "former_employee", True),
        _a("5", "Cy", "Initech", "mentor", True),
    ]
    out, hidden = suggest_referrals("Acme GmbH", affs)
    assert [s.person_name for s in out] == ["Ann", "Zoe"]  # agreed referrers first
    assert hidden == 1
    assert "has agreed to refer you" in out[0].reason


def test_nothing_without_relationships() -> None:
    assert suggest_referrals("Acme", []) == ([], 0)
