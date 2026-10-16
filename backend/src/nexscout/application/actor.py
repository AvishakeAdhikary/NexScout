"""The authenticated principal passed into every use case."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: uuid.UUID
    session_id: uuid.UUID
    ip: str | None = None
    request_id: str | None = None
