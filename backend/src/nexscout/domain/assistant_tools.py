"""The AI assistant's tools: a fixed allow-list, checked by plain code (ADR-0020).

The model only *proposes* a tool call as JSON. `parse_call` decides whether it is one of these
tools with valid arguments; anything else is refused before any code runs. Every tool maps to
a use case the screens already use. None of them submits, sends, approves, pays, deletes or
attests: those stay on their screens, behind the user's own approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class FindApplicationsArgs(_Args):
    q: str | None = Field(default=None, max_length=200)


class TopMatchesArgs(_Args):
    academic: bool = False
    q: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


class OpportunityArgs(_Args):
    opportunity_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


class StartDraftArgs(_Args):
    doc_type: Literal[
        "resume", "academic_cv", "cover_letter", "sop", "research_proposal", "inquiry_email"
    ]
    opportunity_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")


class AddReminderArgs(_Args):
    title: str = Field(min_length=1, max_length=200)
    due_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    starts_work: bool = False  # starts a run or writes a row: done at most once (side effect)


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec(
            "needs_you", "What needs the user's attention now (approvals, questions).", NoArgs
        ),
        ToolSpec("upcoming_deadlines", "Deadlines and reminders in the next 30 days.", NoArgs),
        ToolSpec(
            "find_applications",
            "The user's applications and their status, optionally matching a text.",
            FindApplicationsArgs,
        ),
        ToolSpec(
            "top_matches",
            "The best-fitting opportunities found so far (jobs, or PhD positions with "
            "academic=true), optionally matching a text.",
            TopMatchesArgs,
        ),
        ToolSpec(
            "opportunity_details",
            "One opportunity: requirements, deadline, the fit estimate and its reasons.",
            OpportunityArgs,
        ),
        ToolSpec("profile_gaps", "What the user's confirmed profile is missing.", NoArgs),
        ToolSpec(
            "start_search",
            "Search the user's enabled sources for new opportunities (runs in the background).",
            NoArgs,
            starts_work=True,
        ),
        ToolSpec(
            "start_research",
            "Research one opportunity's pages: requirements, people, deadlines (background).",
            OpportunityArgs,
            starts_work=True,
        ),
        ToolSpec(
            "start_draft",
            "Draft a document from the confirmed profile (background). The user reviews it.",
            StartDraftArgs,
            starts_work=True,
        ),
        ToolSpec(
            "add_reminder",
            "Add a reminder for the user on a date.",
            AddReminderArgs,
            starts_work=True,
        ),
    )
}

# Never tools, whatever the model asks. Listed so the refusal can say why.
BLOCKED = frozenset(
    {
        "submit",
        "submit_application",
        "send",
        "send_email",
        "approve",
        "decide_approval",
        "delete",
        "pay",
        "attest",
        "sign_in",
    }
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    spec: ToolSpec


class Refused(ValueError):
    """The proposed call isn't allowed or its arguments are invalid (told to the model)."""


def parse_call(name: object, args: object) -> ToolCall:
    if not isinstance(name, str) or not name:
        raise Refused("No tool name was given.")
    if name in BLOCKED or any(word in name for word in ("submit", "approve", "delete", "pay")):
        raise Refused(
            f"“{name}” is never available: submitting, sending, approving, paying and deleting "
            "happen only on their own screens, with the user's approval."
        )
    spec = TOOLS.get(name)
    if spec is None:
        raise Refused(f"There is no tool called “{name}”. Use one of: {', '.join(TOOLS)}.")
    try:
        parsed = spec.args.model_validate(args if isinstance(args, dict) else {})
    except ValidationError as exc:
        raise Refused(f"Invalid arguments for {name}: {exc.errors()[0]['msg']}") from exc
    return ToolCall(name, parsed.model_dump(), spec)


def tool_catalog() -> list[dict[str, Any]]:
    """For the prompt: name, what it does, and its arguments' JSON schema."""
    return [
        {"name": t.name, "description": t.description, "args": t.args.model_json_schema()}
        for t in TOOLS.values()
    ]
