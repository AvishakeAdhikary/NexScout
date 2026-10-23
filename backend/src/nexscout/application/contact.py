"""Contact details per case, and filling what the user already told NexScout into documents.

The details are the user's own; nothing here is generated. A CV's header is only offered as a
suggestion (`ContactView.suggested`) until the user saves it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.answers import answers_for
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.application.generated_documents import DocumentView, get_document, save_edit
from nexscout.domain.contact import ContactDetails, fill_placeholders, read_contact
from nexscout.domain.errors import ConcurrencyConflict, ValidationFailed
from nexscout.infrastructure.db.models import (
    CaseContact,
    Document,
    SocialProfile,
    User,
)

_CV_PURPOSES = ("cv", "resume")


@dataclass
class ContactView:
    data: ContactDetails
    version: int
    # Details found in the newest CV that differ from what is saved (suggestions only).
    suggested: dict[str, str] = field(default_factory=dict)
    suggested_from: str | None = None


@dataclass
class ApplicantDetails:
    """Everything a document or a form may use to say who the candidate is."""

    contact: ContactDetails
    name: str  # contact.full_name, else the account's display name
    email: str  # contact.email, else the account's email
    links: dict[str, str]  # profile kind -> url (first of each kind)
    saved: bool  # the user has saved contact details for this case


def _message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())


async def _row(s: AsyncSession, owner: uuid.UUID, case_id: uuid.UUID) -> CaseContact | None:
    row = await s.get(CaseContact, case_id)
    return row if row is not None and row.owner_user_id == owner else None


async def get_contact(s: AsyncSession, actor: Actor, case_id: uuid.UUID) -> ContactView:
    await get_case(s, actor, case_id)
    row = await _row(s, actor.user_id, case_id)
    data = ContactDetails.model_validate(row.data) if row else ContactDetails()
    view = ContactView(data, row.version if row else 0)
    cv = await s.scalar(
        select(Document)
        .where(
            Document.owner_user_id == actor.user_id,
            Document.case_id == case_id,
            Document.purpose.in_(_CV_PURPOSES),
            Document.text_content.is_not(None),
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    if cv is not None and cv.text_content:
        saved = data.model_dump()
        found = {k: v for k, v in read_contact(cv.text_content).items() if saved.get(k) != v}
        try:  # only suggest what would be accepted if saved
            ContactDetails.model_validate(found)
        except ValidationError:
            found = {}
        if found:
            view.suggested, view.suggested_from = found, cv.filename
    return view


async def put_contact(
    s: AsyncSession,
    actor: Actor,
    case_id: uuid.UUID,
    *,
    data: dict[str, Any],
    expected_version: int,
) -> ContactView:
    await get_case(s, actor, case_id)
    try:
        payload = ContactDetails.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        raise ValidationFailed(f"Invalid contact details: {_message(exc)}") from exc
    stale = "Your contact details were changed elsewhere. Reload and try again."
    row = await _row(s, actor.user_id, case_id)
    if row is None:
        if expected_version != 0:
            raise ConcurrencyConflict(stale)
        s.add(CaseContact(case_id=case_id, owner_user_id=actor.user_id, data=payload, version=1))
        await s.flush()
    else:
        result = await s.execute(
            update(CaseContact)
            .where(
                CaseContact.case_id == case_id,
                CaseContact.owner_user_id == actor.user_id,
                CaseContact.version == expected_version,
            )
            .values(data=payload, version=CaseContact.version + 1)
            .returning(CaseContact.version)
        )
        if result.scalar_one_or_none() is None:
            raise ConcurrencyConflict(stale)
        await s.refresh(row)
    record_audit(
        s,
        "contact.updated",
        actor_user_id=actor.user_id,
        target_type="case",
        target_id=case_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"fields": sorted(k for k, v in payload.items() if v)},  # which, never the values
    )
    return await get_contact(s, actor, case_id)


async def applicant_details(
    s: AsyncSession, owner: uuid.UUID, case_id: uuid.UUID
) -> ApplicantDetails:
    """Works in a request or in the worker (the session must already be bound to `owner`)."""
    row = await _row(s, owner, case_id)
    contact = ContactDetails.model_validate(row.data) if row else ContactDetails()
    user = await s.get(User, owner)
    links: dict[str, str] = {}
    for kind, url in (
        await s.execute(
            select(SocialProfile.kind, SocialProfile.url)
            .where(SocialProfile.owner_user_id == owner, SocialProfile.case_id == case_id)
            .order_by(SocialProfile.created_at)
        )
    ).all():
        links.setdefault(kind, url)
    return ApplicantDetails(
        contact=contact,
        name=contact.full_name or (user.display_name if user else "") or "",
        email=contact.email or (user.email if user else ""),
        links=links,
        saved=row is not None,
    )


async def fill_in_details(
    s: AsyncSession, owner: uuid.UUID, case_id: uuid.UUID, markdown: str
) -> str:
    """The text with every placeholder the user has already answered filled in: contact details
    and the answer bank. Unknown placeholders stay. Contact placeholders are filled only once
    the user saved contact details (the account email alone would make a CV without a phone)."""
    who = await applicant_details(s, owner, case_id)
    contact = (
        who.contact.model_copy(update={"full_name": who.name, "email": who.email or None})
        if who.saved
        else None
    )
    return fill_placeholders(
        markdown,
        contact=contact,
        name=who.name,
        links=who.links,
        answers=await answers_for(s, owner, case_id),
    )


async def fill_document(
    s: AsyncSession, actor: Actor, document_id: uuid.UUID
) -> tuple[DocumentView, int]:
    """Fill a generated document's known placeholders into a new version (the user asked for
    it; the values are theirs). Returns the document and how many placeholders were filled."""
    view = await get_document(s, actor, document_id)
    before = view.current
    filled = await fill_in_details(s, actor.user_id, view.document.case_id, before.markdown)
    count = len(before.placeholders) - filled.count("[[PLACEHOLDER:")
    if filled == before.markdown:
        return view, 0
    view = await save_edit(
        s, actor, document_id, markdown=filled, base_version=view.document.current_version
    )
    return view, max(count, 0)
