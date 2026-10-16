"""`document_ingestion` (system workflow, started by an upload): read the file in an isolated
subprocess, then save text and pending profile entries. Both steps are safe to re-run."""

from __future__ import annotations

import uuid
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import select

from nexscout.agent_runtime.context import RunContext
from nexscout.agent_runtime.registry import WorkflowSpec, register, tracked
from nexscout.application.documents import read_document_text, save_extraction
from nexscout.infrastructure.db.models import Document
from nexscout.infrastructure.ingestion.parsers import ParsedText


class State(TypedDict, total=False):
    result: dict[str, Any]


async def _document(ctx: RunContext) -> Document:
    async with ctx.tenant() as s:
        doc = await s.scalar(
            select(Document).where(Document.id == uuid.UUID(str(ctx.params["document_id"])))
        )
    if doc is None:
        raise LookupError("The document was deleted before it could be read.")
    return doc


async def read_and_save(state: State, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx = runtime.context
    step = ctx.extras.get("current_step")
    doc = await _document(ctx)
    await ctx.note(step, f"Reading “{doc.filename}”.")
    parsed, error = await read_document_text(ctx.store, doc)  # no transaction held here
    async with ctx.tenant() as s:
        fresh = await s.get(Document, doc.id)
        if fresh is None:
            raise LookupError("The document was deleted before it could be read.")
        created = await save_extraction(s, ctx.owner_user_id, fresh, parsed, error)
        status = fresh.parse_status
    if error:
        await ctx.note(step, f"Couldn't read the text: {error}")
    else:
        await ctx.note(step, f"Found {created} possible profile entries to review.")
    return {
        "result": {
            "document_id": str(doc.id),
            "parse_status": status,
            "facts_created": created,
            "error": error,
            "pages": _pages(parsed),
        }
    }


def _pages(parsed: ParsedText | None) -> int | None:
    return parsed.page_count if parsed else None


def build() -> StateGraph[State, RunContext, Any, Any]:
    g: StateGraph[State, RunContext, Any, Any] = StateGraph(State, context_schema=RunContext)
    g.add_node("read_and_save", cast(Any, tracked("read_and_save", read_and_save)))
    g.add_edge(START, "read_and_save")
    g.add_edge("read_and_save", END)
    return g


SPEC = register(
    WorkflowSpec(
        kind="document_ingestion",
        title="Read an uploaded document",
        description="Reads the text of an uploaded file and finds possible profile entries.",
        build=build,
        user_startable=False,
    )
)
