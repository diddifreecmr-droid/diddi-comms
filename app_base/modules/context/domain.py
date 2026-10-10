from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ExternalName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]


class TaskReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_service: ExternalName
    task_type: ExternalName
    task_id: UUID


class CommunicationParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: ExternalName
    phone_e164: str | None = Field(default=None, description="Returned only when call policy needs it.")


class CommunicationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskReference
    state: str
    version: int = Field(ge=0)
    participants: list[CommunicationParticipant]
    messaging_allowed: bool
    calling_allowed: bool
    closes_at: datetime | None = None

    def participant_user_ids(self) -> set[UUID]:
        return {participant.user_id for participant in self.participants}
