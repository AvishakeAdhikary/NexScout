"""Applications: create, track, fill in with the browser (approval before submit), resolve."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import Field

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep, SettingsDep
from nexscout.api.schemas import ApiModel, RunStartedOut
from nexscout.application import applications as apps
from nexscout.domain.state_machines import APPLICATION_MACHINE, ApplicationStatus
from nexscout.infrastructure.db.models import Application, ApplicationEvent

router = APIRouter(tags=["applications"])


class ApplicationIn(ApiModel):
    opportunity_id: uuid.UUID
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    apply_url: str | None = Field(default=None, max_length=2048)


class ApplicationPatch(ApiModel):
    version: int
    answers: dict[str, str] | None = None
    phone: str | None = Field(default=None, max_length=40)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)
    apply_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=5000)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class StatusIn(ApiModel):
    version: int
    status: str
    note: str | None = Field(default=None, max_length=2000)
    reference: str | None = Field(default=None, max_length=100)


class ResolveIn(ApiModel):
    submitted: bool
    reference: str | None = Field(default=None, max_length=100)


class ApplicationEventOut(ApiModel):
    id: uuid.UUID
    type: str
    from_status: str | None
    to_status: str | None
    actor: str
    message: str | None
    payload: dict[str, Any]
    has_screenshot: bool
    run_id: uuid.UUID | None
    created_at: datetime


class ApplicationOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    title: str
    organization: str
    status: str
    allowed_statuses: list[str]
    apply_url: str | None
    method: str
    document_ids: list[str]
    answers: dict[str, str]
    phone: str | None
    deadline: str | None
    notes: str | None
    blocker: str | None
    submitted_at: datetime | None
    evidence: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int


class ApplicationDetailOut(ApplicationOut):
    events: list[ApplicationEventOut]


def _out(a: Application) -> ApplicationOut:
    allowed = sorted(
        s.value
        for s in APPLICATION_MACHINE.allowed(ApplicationStatus(a.status))
        if s in apps.USER_TARGETS
    )
    evidence = {k: v for k, v in (a.evidence or {}).items() if k != "screenshot_key"}
    return ApplicationOut(
        id=a.id,
        case_id=a.case_id,
        opportunity_id=a.opportunity_id,
        title=a.title,
        organization=a.organization,
        status=a.status,
        allowed_statuses=allowed,
        apply_url=a.apply_url,
        method=a.method,
        document_ids=list(a.document_ids or []),
        answers=dict(a.answers or {}),
        phone=a.phone,
        deadline=a.deadline,
        notes=a.notes,
        blocker=a.blocker,
        submitted_at=a.submitted_at,
        evidence=evidence,
        created_at=a.created_at,
        updated_at=a.updated_at,
        version=a.version,
    )


def _event(e: ApplicationEvent) -> ApplicationEventOut:
    payload = {k: v for k, v in (e.payload or {}).items() if k not in ("screenshot_key", "digest")}
    return ApplicationEventOut(
        id=e.id,
        type=e.type,
        from_status=e.from_status,
        to_status=e.to_status,
        actor=e.actor,
        message=e.message,
        payload=payload,
        has_screenshot=bool((e.payload or {}).get("screenshot_key")),
        run_id=e.run_id,
        created_at=e.created_at,
    )


def _detail(view: apps.ApplicationView) -> ApplicationDetailOut:
    return ApplicationDetailOut(
        **_out(view.application).model_dump(), events=[_event(e) for e in view.events]
    )


@router.post(
    "/cases/{case_id}/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    case_id: uuid.UUID,
    body: ApplicationIn,
    actor: CurrentActor,
    db: DbSession,
    settings: SettingsDep,
) -> ApplicationOut:
    app = await apps.create_application(
        db,
        settings,
        actor,
        case_id,
        opportunity_id=body.opportunity_id,
        document_ids=body.document_ids,
        apply_url=body.apply_url,
    )
    return _out(app)


@router.get("/cases/{case_id}/applications", response_model=list[ApplicationOut])
async def list_applications(
    case_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    status: str | None = None,
    q: str | None = None,
    sort: str = "updated",
) -> list[ApplicationOut]:
    rows = await apps.list_applications(db, actor, case_id, status=status, q=q, sort=sort)
    return [_out(a) for a in rows]


class BulkStatusIn(ApiModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: str


class BulkResultOut(ApiModel):
    id: str
    ok: bool
    error: str | None


@router.post("/cases/{case_id}/applications/bulk-status", response_model=list[BulkResultOut])
async def bulk_status(
    case_id: uuid.UUID, body: BulkStatusIn, actor: CurrentActor, db: DbSession
) -> list[BulkResultOut]:
    results = await apps.bulk_status(db, actor, case_id, body.ids, body.status)
    return [BulkResultOut(**r) for r in results]


@router.get("/cases/{case_id}/applications/export.csv")
async def export_csv(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    data = await apps.export_csv(db, actor, case_id)
    return Response(
        content=data.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
async def get_application(
    application_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ApplicationDetailOut:
    return _detail(await apps.get_application(db, actor, application_id))


@router.patch("/applications/{application_id}", response_model=ApplicationDetailOut)
async def update_application(
    application_id: uuid.UUID,
    body: ApplicationPatch,
    actor: CurrentActor,
    db: DbSession,
    settings: SettingsDep,
) -> ApplicationDetailOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    view = await apps.update_application(
        db, settings, actor, application_id, version=body.version, changes=changes
    )
    return _detail(view)


@router.post("/applications/{application_id}/status", response_model=ApplicationDetailOut)
async def change_status(
    application_id: uuid.UUID, body: StatusIn, actor: CurrentActor, db: DbSession
) -> ApplicationDetailOut:
    view = await apps.change_status(
        db,
        actor,
        application_id,
        version=body.version,
        target=body.status,
        note=body.note,
        reference=body.reference,
    )
    return _detail(view)


@router.post("/applications/{application_id}/resolve", response_model=ApplicationDetailOut)
async def resolve(
    application_id: uuid.UUID, body: ResolveIn, actor: CurrentActor, db: DbSession
) -> ApplicationDetailOut:
    view = await apps.resolve_uncertain(
        db, actor, application_id, submitted=body.submitted, reference=body.reference
    )
    return _detail(view)


@router.post(
    "/applications/{application_id}/browser",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_browser(
    application_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> RunStartedOut:
    run = await apps.start_browser(db, actor, application_id)
    return RunStartedOut(run_id=run.id)


@router.get("/applications/{application_id}/events/{event_id}/screenshot")
async def event_screenshot(
    application_id: uuid.UUID,
    event_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
) -> Response:
    data = await apps.screenshot(db, actor, store, application_id, event_id)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
