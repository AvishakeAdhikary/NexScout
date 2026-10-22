"""Document upload, listing, text view, download, deletion."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status

from nexscout.api.deps import CurrentActor, DbSession, ObjectStoreDep, SettingsDep
from nexscout.api.schemas import DocumentOut, DocumentTextOut, RereadOut, UploadOut
from nexscout.application import documents
from nexscout.application.documents import DocumentPurpose
from nexscout.domain.errors import ValidationFailed

router = APIRouter(tags=["documents"])


@router.post(
    "/cases/{case_id}/documents", response_model=UploadOut, status_code=status.HTTP_201_CREATED
)
async def upload(
    case_id: uuid.UUID,
    request: Request,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    purpose: Annotated[DocumentPurpose, Form()] = DocumentPurpose.CV,
) -> UploadOut:
    limit = settings.max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 64 * 1024:
        raise ValidationFailed(f"The file is too large (limit {limit // (1024 * 1024)} MB).")
    data = await file.read(limit + 1)
    result = await documents.upload_document(
        db,
        actor,
        store,
        case_id,
        data=data,
        filename=file.filename,
        purpose=purpose,
        max_bytes=limit,
    )
    return UploadOut(document=DocumentOut.model_validate(result.document), run_id=result.run_id)


@router.get("/cases/{case_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> list[DocumentOut]:
    return [
        DocumentOut.model_validate(d) for d in await documents.list_documents(db, actor, case_id)
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> DocumentOut:
    return DocumentOut.model_validate(await documents.get_document(db, actor, document_id))


@router.get("/documents/{document_id}/text", response_model=DocumentTextOut)
async def document_text(
    document_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> DocumentTextOut:
    doc = await documents.get_document(db, actor, document_id)
    return DocumentTextOut(id=doc.id, text=doc.text_content, page_starts=doc.page_starts)


@router.get("/documents/{document_id}/content")
async def download(
    document_id: uuid.UUID, actor: CurrentActor, db: DbSession, store: ObjectStoreDep
) -> Response:
    doc, data = await documents.read_document_bytes(db, actor, store, document_id)
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={
            # Always download, never render inline: uploaded files are untrusted content.
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.filename)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    store: ObjectStoreDep,
    delete_pending_facts: bool = False,
) -> Response:
    await documents.delete_document(
        db, actor, store, document_id, delete_pending_facts=delete_pending_facts
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/documents/{document_id}/reread", response_model=RereadOut)
async def reread_document(document_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> RereadOut:
    """Read the document again with the current reader. Only its pending, unedited entries are
    replaced; accepted, rejected and edited entries are kept."""
    result = await documents.reread_document(db, actor, document_id)
    return RereadOut(**result)
