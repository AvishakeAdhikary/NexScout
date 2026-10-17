"""Referral suggestions (R-JOB-5): only from relationships the user allowed for referrals.

A relationship is matched to an employer by the same organization normalization the catalog
uses. Relationships without referral permission are never suggested; the caller only learns how
many exist, so the UI can say where to change the permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexscout.domain.mindmap import normalize_org

_LABELS = {
    "current_employee": "works there now",
    "former_employee": "used to work there",
    "authorized_referrer": "has agreed to refer you",
    "alumnus": "is an alumnus",
    "colleague": "is a colleague",
    "mentor": "is your mentor",
    "supervisor": "was your supervisor",
    "collaborator": "is a collaborator",
    "co_author": "is a co-author",
    "researcher": "is a researcher there",
}


@dataclass(frozen=True)
class ReferralSuggestion:
    affiliation_id: str
    person_name: str
    organization: str
    relationship_type: str
    role: str | None
    reason: str


def _key(name: str) -> str:
    return normalize_org(name) or name.strip().lower()


def suggest_referrals(
    employer: str, affiliations: list[dict[str, Any]]
) -> tuple[list[ReferralSuggestion], int]:
    """(suggestions, number of matching relationships without referral permission)."""
    target = _key(employer)
    out: list[ReferralSuggestion] = []
    hidden = 0
    for a in affiliations:
        if not a.get("person_name") or _key(str(a["organization"])) != target:
            continue  # only people at this employer can refer
        if not a.get("may_use_for_referral"):
            hidden += 1
            continue
        what = _LABELS.get(str(a["relationship_type"]), str(a["relationship_type"]))
        status = " (former)" if a.get("status") == "former" else ""
        out.append(
            ReferralSuggestion(
                affiliation_id=str(a["id"]),
                person_name=str(a["person_name"]),
                organization=str(a["organization"]),
                relationship_type=str(a["relationship_type"]),
                role=a.get("role"),
                reason=f"{a['person_name']} {what} at {a['organization']}{status}, and you "
                "allowed NexScout to suggest asking them for a referral.",
            )
        )
    order = {"authorized_referrer": 0, "current_employee": 1}
    out.sort(key=lambda s: (order.get(s.relationship_type, 2), s.person_name))
    return out, hidden
