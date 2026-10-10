from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.auth_deps import AuthenticatedUser, require_current_user
from app_base.core.database import get_session
from app_base.core.errors import ApiError
from app_base.modules.context.domain import TaskReference
from app_base.modules.conversations.application import EnsureTaskConversationService, SendMessageService
from app_base.modules.conversations.infra.repositories import MessageRepository

router = APIRouter(tags=["conversations"])


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: str
    owner_service: str
    task_type: str
    task_id: UUID
    state: str
    task_version: int
    closes_at: str | None = None
    created: bool


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    sequence: int
    sender_user_id: UUID
    client_message_id: str
    body: str
    moderation_status: str
    created: bool | None = None


@router.post(
    "/tasks/{owner_service}/{task_type}/{task_id}/conversation",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
)
async def ensure_task_conversation(
    owner_service: str,
    task_type: str,
    task_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    task = TaskReference(owner_service=owner_service, task_type=task_type, task_id=task_id)
    service = EnsureTaskConversationService(session)
    try:
        result = await service.ensure(
            task=task,
            actor_user_id=current_user.user_id,
            request_id=getattr(request.state, "request_id", None),
            idempotency_key=idempotency_key,
        )
    except PermissionError as exc:
        raise ApiError(403, str(exc), "User is not allowed to open this conversation.") from exc

    conversation = result.conversation
    return ConversationResponse(
        id=conversation.id,
        type=conversation.conversation_type,
        owner_service=conversation.owner_service,
        task_type=conversation.task_type,
        task_id=conversation.task_id,
        state=conversation.state,
        task_version=conversation.task_version,
        closes_at=conversation.closes_at.isoformat().replace("+00:00", "Z") if conversation.closes_at else None,
        created=result.created,
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    service = SendMessageService(session)
    try:
        result = await service.send(
            conversation_id=conversation_id,
            actor_user_id=current_user.user_id,
            client_message_id=payload.client_message_id,
            body=payload.body,
            request_id=getattr(request.state, "request_id", None),
            idempotency_key=idempotency_key,
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    except PermissionError as exc:
        raise ApiError(403, str(exc), "User is not allowed to send a message.") from exc
    except ValueError as exc:
        raise ApiError(422, str(exc), "Message payload is invalid.") from exc

    return _message_response(result.message, created=result.created)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    after_seq: int = 0,
    limit: int = 100,
    _current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    messages = await MessageRepository(session).list_after(
        conversation_id=conversation_id,
        after_sequence=max(after_seq, 0),
        limit=min(max(limit, 1), 200),
    )
    return [_message_response(message) for message in messages]


def _message_response(message, *, created: bool | None = None) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sequence=message.sequence,
        sender_user_id=message.sender_user_id,
        client_message_id=message.client_message_id,
        body=message.body,
        moderation_status=message.moderation_status,
        created=created,
    )
