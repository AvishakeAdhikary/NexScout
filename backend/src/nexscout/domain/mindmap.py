"""Evidence-linked mind map built from *accepted* profile facts (spec §4.3).

- Every factual node is a profile fact (node key = "fact:<id>"), carrying its provenance status.
- Organization nodes are *derived* groupings of facts that name the same organization.
- Derived edges (e.g. "skill mentioned in this role") are marked `derived=True` with a
  human-readable `basis`, so the UI never presents them as proven facts.
- Node keys are stable across regenerations, so user layout overrides survive.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any

from nexscout.domain.profile import Section

ROOT_KEY = "candidate"

_ORG_FIELDS: dict[Section, str] = {
    Section.EDUCATION: "institution",
    Section.EMPLOYMENT: "organization",
    Section.RESEARCH: "organization",
    Section.VOLUNTEER: "organization",
    Section.LEADERSHIP: "organization",
    Section.MEMBERSHIP: "organization",
    Section.CERTIFICATION: "issuer",
    Section.AWARD: "issuer",
}
_TEXT_FIELDS = ("description", "title", "role", "name", "technologies")
_CHRONO_SECTIONS = (Section.EDUCATION, Section.EMPLOYMENT, Section.RESEARCH)


@dataclass(frozen=True)
class FactInput:
    id: str
    section: Section
    label: str
    data: dict[str, Any]
    status: str
    is_private: bool
    evidence_count: int = 0


@dataclass
class Node:
    key: str
    kind: str  # "candidate" | "section" | "fact" | "organization"
    label: str
    section: str | None = None
    fact_id: str | None = None
    status: str | None = None  # provenance for fact nodes; "derived" for groupings
    is_private: bool = False
    evidence_count: int = 0
    start: str | None = None
    end: str | None = None


@dataclass
class Edge:
    source: str
    target: str
    kind: str  # "has_section" | "has_entry" | "at_organization" | "followed_by" | "mentions_skill"
    derived: bool = False
    basis: str | None = None


@dataclass
class MindMap:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


_UNIVERSITY = re.compile(
    r"\b(universit(?:y|et|ät|aet|é|e|à|a|eit|y of)|yliopisto|uniwersytet|universidad)\b"
)


def normalize_org(name: str) -> str:
    """Key for grouping organization mentions: case, punctuation and legal forms ignored, and
    "university" in any language one word ("Lunds universitet" = "Lund University")."""
    n = re.sub(r"[^\w\s]", " ", name.lower())
    n = re.sub(
        r"\b(the|inc|ltd|llc|gmbh|plc|corp|corporation|co|kg|ag|sa|sas|sarl|bv|nv|limited"
        r"|ab|oy|oyj|as|asa|aps|spa|srl|publ)\b",
        " ",
        n,
    )
    if _UNIVERSITY.search(n):
        n = _UNIVERSITY.sub("university", n)
        # Scandinavian genitive before "university": "lunds" -> "lund", "göteborgs" -> "göteborg".
        n = re.sub(r"\b(\w{3,}?)s (university)\b", r"\1 \2", n)
    return re.sub(r"\s+", " ", n).strip()


def _fact_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _TEXT_FIELDS:
        value = data.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _mentions(text: str, skill: str) -> bool:
    s = skill.lower().strip()
    if len(s) < 2:
        return False
    return re.search(rf"(?<![\w+#]){re.escape(s)}(?![\w+#])", text) is not None


def _sort_key(f: FactInput) -> str:
    return str(f.data.get("start") or "")


def build_mindmap(facts: list[FactInput], candidate_label: str) -> MindMap:
    mm = MindMap()
    mm.nodes.append(Node(key=ROOT_KEY, kind="candidate", label=candidate_label))
    sections_present: list[Section] = []
    for f in facts:
        if f.section not in sections_present:
            sections_present.append(f.section)
    for section in sections_present:
        key = f"section:{section.value}"
        mm.nodes.append(Node(key=key, kind="section", label=section.value, section=section.value))
        mm.edges.append(Edge(ROOT_KEY, key, "has_section"))

    org_nodes: dict[str, Node] = {}
    for f in facts:
        key = f"fact:{f.id}"
        mm.nodes.append(
            Node(
                key=key,
                kind="fact",
                label=f.label,
                section=f.section.value,
                fact_id=f.id,
                status=f.status,
                is_private=f.is_private,
                evidence_count=f.evidence_count,
                start=f.data.get("start") or f.data.get("date") or f.data.get("year"),
                end=f.data.get("end"),
            )
        )
        mm.edges.append(Edge(f"section:{f.section.value}", key, "has_entry"))
        org_field = _ORG_FIELDS.get(f.section)
        org_name = f.data.get(org_field) if org_field else None
        if isinstance(org_name, str) and org_name.strip():
            norm = normalize_org(org_name)
            if norm:
                okey = f"org:{norm}"
                if okey not in org_nodes:
                    org_nodes[okey] = Node(
                        key=okey, kind="organization", label=org_name.strip(), status="derived"
                    )
                mm.edges.append(
                    Edge(
                        key,
                        okey,
                        "at_organization",
                        derived=True,
                        basis=f"Named in this entry as “{org_name.strip()}”.",
                    )
                )
    # Only show organization nodes that connect two or more entries; a single mention
    # adds no information beyond the entry itself.
    org_counts: dict[str, int] = {}
    for e in mm.edges:
        if e.kind == "at_organization":
            org_counts[e.target] = org_counts.get(e.target, 0) + 1
    shared = {k for k, n in org_counts.items() if n >= 2}
    mm.nodes.extend(n for k, n in org_nodes.items() if k in shared)
    mm.edges = [e for e in mm.edges if e.kind != "at_organization" or e.target in shared]

    # Chronology within each dated section.
    for section in _CHRONO_SECTIONS:
        dated = sorted(
            (f for f in facts if f.section is section and f.data.get("start")), key=_sort_key
        )
        for a, b in itertools.pairwise(dated):
            mm.edges.append(
                Edge(
                    f"fact:{a.id}",
                    f"fact:{b.id}",
                    "followed_by",
                    derived=True,
                    basis="Ordered by start date.",
                )
            )

    # Skills mentioned in experience entries (text match, derived).
    skills = [f for f in facts if f.section is Section.SKILL]
    contexts = [
        f
        for f in facts
        if f.section in (Section.EMPLOYMENT, Section.RESEARCH, Section.PROJECT, Section.EDUCATION)
    ]
    for ctx in contexts:
        text = _fact_text(ctx.data)
        for skill in skills:
            name = str(skill.data.get("name", ""))
            if _mentions(text, name):
                mm.edges.append(
                    Edge(
                        f"fact:{ctx.id}",
                        f"fact:{skill.id}",
                        "mentions_skill",
                        derived=True,
                        basis=f"“{name}” appears in this entry's text.",
                    )
                )
    return mm


# ----------------------------------------------------------------------------- snapshots
@dataclass
class SnapshotDiff:
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)  # {"id","label","fields":[...]}
    unchanged: int = 0


def diff_snapshots(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> SnapshotDiff:
    """Compare two snapshot fact lists by fact id."""
    before = {f["id"]: f for f in old}
    after = {f["id"]: f for f in new}
    diff = SnapshotDiff()
    for fid, f in after.items():
        if fid not in before:
            diff.added.append({"id": fid, "section": f["section"], "label": f["label"]})
            continue
        prev = before[fid]
        fields = sorted(
            k for k in set(prev["data"]) | set(f["data"]) if prev["data"].get(k) != f["data"].get(k)
        )
        if prev.get("is_private") != f.get("is_private"):
            fields.append("is_private")
        if fields:
            diff.changed.append(
                {"id": fid, "section": f["section"], "label": f["label"], "fields": fields}
            )
        else:
            diff.unchanged += 1
    for fid, f in before.items():
        if fid not in after:
            diff.removed.append({"id": fid, "section": f["section"], "label": f["label"]})
    return diff
