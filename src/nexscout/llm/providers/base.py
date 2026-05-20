"""Provider protocol — every LLM backend implements ``chat``."""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class Message(TypedDict, total=False):
    role: str
    content: str


@runtime_checkable
class Provider(Protocol):
    """Common chat-completion interface."""

    name: str

    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Send a list of messages and return the assistant text."""
        ...
