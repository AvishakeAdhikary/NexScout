"""HTTP request/response schemas (the public API contract)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from nexscout.domain.cases import MAX_CASE_DESCRIPTION, MAX_CASE_NAME, CareerPath, CaseStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class RegisterRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    display_name: str = Field(max_length=120)


class LoginRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str


class SessionOut(ApiModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class CaseCreate(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_CASE_NAME)
    description: str | None = Field(default=None, max_length=MAX_CASE_DESCRIPTION)
    career_path: CareerPath = CareerPath.UNDECIDED


class CaseUpdate(ApiModel):
    version: int = Field(ge=1, description="Version you last read (optimistic concurrency).")
    name: str | None = Field(default=None, min_length=1, max_length=MAX_CASE_NAME)
    description: str | None = Field(default=None, max_length=MAX_CASE_DESCRIPTION)
    career_path: CareerPath | None = None
    status: CaseStatus | None = None


class CaseOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    career_path: CareerPath
    status: CaseStatus
    version: int
    created_at: datetime
    updated_at: datetime


class HealthOut(ApiModel):
    status: str


class ReadyOut(ApiModel):
    status: str
    database: str
    migrations: str
