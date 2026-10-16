"""Preferences, social/profile links, and the affiliation relationship table."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.domain.errors import ConcurrencyConflict, Conflict, NotFound, ValidationFailed
from nexscout.domain.preferences import Preferences, normalize_profile_url
from nexscout.domain.profile import check_partial_date
from nexscout.infrastructure.db.models import Affiliation, CasePreferences, SocialProfile

RELATIONSHIP_TYPES = frozenset(
    {
        "alumnus",
        "former_employee",
        "current_employee",
        "researcher",
        "collaborator",
        "co_author",
        "supervisor",
        "mentor",
        "colleague",
        "association_member",
        "authorized_referrer",
        "other",
    }
)


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'value'}: {e['msg']}" for e in exc.errors()
    )


# ----------------------------------------------------------------------------- preferences
async def get_preferences(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID
) -> tuple[Preferences, int]:
    await get_case(session, actor, case_id)
    row = await session.get(CasePreferences, case_id)
    if row is None or row.owner_user_id != actor.user_id:
        return Preferences(), 0
    return Preferences.model_validate(row.data), row.version


async def put_preferences(
    session: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    data: dict[str, Any],
    expected_version: int,
) -> tuple[Preferences, int]:
    await get_case(session, actor, case_id)
    try:
        prefs = Preferences.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed(f"Invalid preferences: {_validation_message(exc)}") from exc
    payload = prefs.model_dump(mode="json")
    row = await session.get(CasePreferences, case_id)
    if row is None:
        if expected_version != 0:
            raise ConcurrencyConflict("Preferences were changed elsewhere. Reload and try again.")
        row = CasePreferences(case_id=case_id, owner_user_id=actor.user_id, data=payload)
        session.add(row)
        await session.flush()
    else:
        result = await session.execute(
            update(CasePreferences)
            .where(
                CasePreferences.case_id == case_id,
                CasePreferences.owner_user_id == actor.user_id,
                CasePreferences.version == expected_version,
            )
            .values(data=payload, version=CasePreferences.version + 1)
            .returning(CasePreferences.version)
        )
        if result.scalar_one_or_none() is None:
            raise ConcurrencyConflict("Preferences were changed elsewhere. Reload and try again.")
        await session.refresh(row)
    record_audit(
        session,
        "preferences.updated",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={
            "sensitive_set": bool(
                prefs.sensitive.work_authorization or prefs.sensitive.veteran_status
            )
        },
    )
    return prefs, row.version


# ------------------------------------------------------------------------- social profiles
async def list_social_profiles(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID
) -> list[SocialProfile]:
    await get_case(session, actor, case_id)
    return list(
        await session.scalars(
            select(SocialProfile)
            .where(SocialProfile.case_id == case_id, SocialProfile.owner_user_id == actor.user_id)
            .order_by(SocialProfile.created_at)
        )
    )


async def add_social_profile(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, *, url: str, label: str | None
) -> SocialProfile:
    await get_case(session, actor, case_id)
    try:
        normalized, kind = normalize_profile_url(url)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    row = SocialProfile(
        owner_user_id=actor.user_id,
        case_id=case_id,
        kind=kind.value,
        url=normalized,
        label=(label or "").strip()[:120] or None,
    )
    session.add(row)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise Conflict("This link is already on your profile.") from exc
    return row


async def delete_social_profile(session: AsyncSession, actor: Actor, link_id: uuid.UUID) -> None:
    row = await session.scalar(
        select(SocialProfile).where(
            SocialProfile.id == link_id, SocialProfile.owner_user_id == actor.user_id
        )
    )
    if row is None:
        raise NotFound("Link not found.")
    await session.delete(row)


# ---------------------------------------------------------------------------- affiliations
AFFILIATION_FIELDS = (
    "person_name",
    "organization",
    "relationship_type",
    "role",
    "start_date",
    "end_date",
    "status",
    "evidence",
    "notes",
    "may_use_in_applications",
    "may_use_for_referral",
)


def _clean_affiliation(values: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in AFFILIATION_FIELDS:
            continue
        if isinstance(value, str):
            value = value.strip() or None
        out[key] = value
    if (not partial or "organization" in out) and not out.get("organization"):
        raise ValidationFailed("Organization is required.")
    needs_type = "relationship_type" in out or not partial
    if needs_type and out.get("relationship_type") not in RELATIONSHIP_TYPES:
        raise ValidationFailed("Choose a valid relationship type.")
    if "status" in out and out["status"] not in {"current", "former", "unknown"}:
        raise ValidationFailed("Status must be current, former, or unknown.")
    for key in ("start_date", "end_date"):
        if key in out:
            try:
                out[key] = check_partial_date(out[key], allow_present=key == "end_date")
            except ValueError as exc:
                raise ValidationFailed(f"{key}: {exc}") from exc
    for key, limit in (
        ("person_name", 200),
        ("organization", 300),
        ("role", 200),
        ("evidence", 2000),
        ("notes", 2000),
    ):
        if isinstance(out.get(key), str) and len(out[key]) > limit:
            raise ValidationFailed(f"{key} must be at most {limit} characters.")
    for key in ("may_use_in_applications", "may_use_for_referral"):
        if key in out and not isinstance(out[key], bool):
            raise ValidationFailed(f"{key} must be true or false.")
    return out


async def list_affiliations(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID
) -> list[Affiliation]:
    await get_case(session, actor, case_id)
    return list(
        await session.scalars(
            select(Affiliation)
            .where(Affiliation.case_id == case_id, Affiliation.owner_user_id == actor.user_id)
            .order_by(Affiliation.created_at)
        )
    )


async def create_affiliation(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, values: dict[str, Any]
) -> Affiliation:
    await get_case(session, actor, case_id)
    clean = _clean_affiliation(values, partial=False)
    row = Affiliation(owner_user_id=actor.user_id, case_id=case_id, **clean)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    record_audit(
        session,
        "affiliation.created",
        actor_user_id=actor.user_id,
        target_type="affiliation",
        target_id=row.id,
        ip=actor.ip,
        request_id=actor.request_id,
    )
    return row


async def _get_affiliation(
    session: AsyncSession, actor: Actor, affiliation_id: uuid.UUID
) -> Affiliation:
    row = await session.scalar(
        select(Affiliation).where(
            Affiliation.id == affiliation_id, Affiliation.owner_user_id == actor.user_id
        )
    )
    if row is None:
        raise NotFound("Relationship not found.")
    return row


async def update_affiliation(
    session: AsyncSession,
    actor: Actor,
    affiliation_id: uuid.UUID,
    *,
    expected_version: int,
    values: dict[str, Any],
) -> Affiliation:
    row = await _get_affiliation(session, actor, affiliation_id)
    clean = _clean_affiliation(values, partial=True)
    if not clean:
        return row
    result = await session.execute(
        update(Affiliation)
        .where(
            Affiliation.id == affiliation_id,
            Affiliation.owner_user_id == actor.user_id,
            Affiliation.version == expected_version,
        )
        .values(**clean, version=Affiliation.version + 1)
        .returning(Affiliation.id)
    )
    if result.scalar_one_or_none() is None:
        raise ConcurrencyConflict("This relationship was changed elsewhere. Reload and try again.")
    record_audit(
        session,
        "affiliation.updated",
        actor_user_id=actor.user_id,
        target_type="affiliation",
        target_id=affiliation_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"fields": sorted(clean)},
    )
    await session.refresh(row)
    return row


async def delete_affiliation(
    session: AsyncSession, actor: Actor, affiliation_id: uuid.UUID
) -> None:
    row = await _get_affiliation(session, actor, affiliation_id)
    await session.delete(row)
    record_audit(
        session,
        "affiliation.deleted",
        actor_user_id=actor.user_id,
        target_type="affiliation",
        target_id=affiliation_id,
        ip=actor.ip,
        request_id=actor.request_id,
    )
