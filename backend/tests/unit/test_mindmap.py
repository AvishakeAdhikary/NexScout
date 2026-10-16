from nexscout.domain.mindmap import FactInput, build_mindmap, diff_snapshots, normalize_org
from nexscout.domain.profile import Section


def _f(fid: str, section: Section, data: dict, label: str = "x") -> FactInput:  # type: ignore[type-arg]
    return FactInput(
        id=fid,
        section=section,
        label=label,
        data=data,
        status="extracted",
        is_private=False,
        evidence_count=1,
    )


def test_nodes_are_facts_with_provenance_and_stable_keys() -> None:
    facts = [_f("e1", Section.EMPLOYMENT, {"title": "Eng", "organization": "Acme"}, "Eng at Acme")]
    mm = build_mindmap(facts, "Ada")
    keys = {n.key for n in mm.nodes}
    assert {"candidate", "section:employment", "fact:e1"} <= keys
    node = next(n for n in mm.nodes if n.key == "fact:e1")
    assert (node.fact_id, node.status, node.evidence_count) == ("e1", "extracted", 1)
    assert build_mindmap(facts, "Ada").nodes[2].key == node.key  # deterministic


def test_shared_organization_nodes_are_derived_and_only_when_shared() -> None:
    facts = [
        _f("e1", Section.EMPLOYMENT, {"title": "Intern", "organization": "Acme GmbH"}),
        _f("e2", Section.EMPLOYMENT, {"title": "Engineer", "organization": "ACME"}),
        _f("d1", Section.EDUCATION, {"institution": "Uni A"}),
    ]
    mm = build_mindmap(facts, "Ada")
    orgs = [n for n in mm.nodes if n.kind == "organization"]
    assert [o.key for o in orgs] == ["org:acme"]
    assert orgs[0].status == "derived"
    org_edges = [e for e in mm.edges if e.kind == "at_organization"]
    assert {e.source for e in org_edges} == {"fact:e1", "fact:e2"}
    assert all(e.derived and e.basis for e in org_edges)


def test_chronology_and_skill_mentions_are_marked_derived() -> None:
    facts = [
        _f("e2", Section.EMPLOYMENT, {"title": "B", "organization": "Y", "start": "2021"}),
        _f(
            "e1",
            Section.EMPLOYMENT,
            {
                "title": "A",
                "organization": "X",
                "start": "2018",
                "description": "Built Python services",
            },
        ),
        _f("s1", Section.SKILL, {"name": "Python"}),
        _f("s2", Section.SKILL, {"name": "C"}),  # must not match "services" etc.
    ]
    mm = build_mindmap(facts, "Ada")
    chrono = [(e.source, e.target) for e in mm.edges if e.kind == "followed_by"]
    assert chrono == [("fact:e1", "fact:e2")]
    mentions = [(e.source, e.target) for e in mm.edges if e.kind == "mentions_skill"]
    assert mentions == [("fact:e1", "fact:s1")]
    assert all(e.derived for e in mm.edges if e.kind in ("followed_by", "mentions_skill"))


def test_normalize_org() -> None:
    assert normalize_org("The Acme Corp.") == normalize_org("acme") == "acme"


def test_snapshot_diff() -> None:
    old = [
        {
            "id": "a",
            "section": "skill",
            "label": "SQL",
            "data": {"name": "SQL"},
            "is_private": False,
        },
        {"id": "b", "section": "skill", "label": "Go", "data": {"name": "Go"}, "is_private": False},
    ]
    new = [
        {
            "id": "a",
            "section": "skill",
            "label": "SQL",
            "data": {"name": "SQL", "level": "expert"},
            "is_private": True,
        },
        {
            "id": "c",
            "section": "skill",
            "label": "Rust",
            "data": {"name": "Rust"},
            "is_private": False,
        },
    ]
    d = diff_snapshots(old, new)
    assert [x["id"] for x in d.added] == ["c"]
    assert [x["id"] for x in d.removed] == ["b"]
    assert d.changed == [
        {"id": "a", "section": "skill", "label": "SQL", "fields": ["level", "is_private"]}
    ]
