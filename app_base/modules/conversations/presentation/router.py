from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.auth_deps import (
    AuthenticatedService,
    AuthenticatedUser,
    DelegatedOperator,
    require_current_user,
    require_delegated_operator,
    require_service_token,
)
from app_base.core.database import get_session
from app_base.core.errors import ApiError
from app_base.core.rate_limit import enforce_rate_limit, enforce_user_conversation_limits
from app_base.core.settings import settings
from app_base.modules.calls.application import CreateCallAttemptService, RecordCallClientResultService
from app_base.modules.context.domain import TaskReference
from app_base.modules.conversations.application import (
    EnsureTaskConversationService,
    MarkConversationReadService,
    MessageDeliveryService,
    SendMessageService,
    SupportCaseService,
)
from app_base.modules.conversations.backoffice import BackofficeConversationService
from app_base.modules.conversations.domain import (
    CommunicationAction,
    ConversationAccessPolicy,
    ConversationAccessSnapshot,
    ConversationState,
)
from app_base.modules.conversations.infra.repositories import (
    ConversationRepository,
    MessageDeliveryRepository,
    MessageRepository,
    SupportCaseRepository,
)
from app_base.modules.conversations.safety import ConversationSafetyService
from app_base.modules.support.factory import diddisupport_read_client
from app_base.modules.support.read_client import SupportMessageResponse as RemoteSupportMessage

router = APIRouter(tags=["conversations"])

SUPPORT_CASES_READ_SCOPE = "diddicomms:support-cases:read"
SUPPORT_CASES_WRITE_SCOPE = "diddicomms:support-cases:write"
SUPPORT_MESSAGES_WRITE_SCOPE = "diddicomms:messages:write"
BACKOFFICE_READ_SCOPE = "diddicomms:backoffice:read"
BACKOFFICE_WRITE_SCOPE = "diddicomms:backoffice:write"


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


class MarkConversationReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_seq: int = Field(ge=0)


class MarkConversationReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    read_seq: int


class DeliveryAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(delivered|read)$")


class DeliveryAcknowledgementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    message_id: UUID
    status: str
    changed: bool


class ConversationMuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    muted: bool


class ConversationMuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    muted: bool


class AbuseReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern=r"^(harassment|spam|unsafe|fraud|other)$")
    details: str | None = Field(default=None, max_length=500)


class AbuseReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    conversation_id: UUID
    message_id: UUID
    category: str
    status: str
    created: bool


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    sequence: int
    sender_user_id: UUID | str
    client_message_id: str
    body: str
    moderation_status: str
    delivery_status: str = "accepted"
    created: bool | None = None


class CallAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: UUID


class CallAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    conversation_id: UUID
    target_user_id: UUID
    status: str
    dial_action: dict[str, str]
    created: bool


class CallClientResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str = Field(pattern=r"^(started|cancelled|failed|unknown)$")


class OpenSupportCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    initial_message: str | None = Field(default=None, max_length=2000)
    priority: str = Field(default="normal", max_length=20)
    category: str = Field(default="general", min_length=1, max_length=80)
    origin_report_id: str | None = Field(default=None, max_length=120)
    owner_service: str | None = Field(default=None, max_length=80)
    task_type: str | None = Field(default=None, max_length=80)
    task_id: UUID | None = None


class SupportConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_service: str = Field(min_length=1, max_length=80)
    task_type: str = Field(min_length=1, max_length=80)
    task_id: UUID


class OpenSupportConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(default="general", min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=2000)
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    priority: str = Field(default="normal", max_length=20)
    origin_report_id: str | None = Field(default=None, max_length=120)
    context: SupportConversationContext | None = None


class SupportConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    support_case_id: UUID
    conversation_state: str
    case_status: str
    owner_service: str | None
    task_type: str | None
    task_id: UUID | None


class SupportCaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    requester_user_id: UUID
    owner_service: str | None
    task_type: str | None
    task_id: UUID | None
    subject: str
    status: str
    priority: str
    assigned_to_user_id: UUID | None
    projection_status: str = "synced"
    created_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None


class AssignSupportCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: UUID


class UpdateSupportPriorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: str = Field(min_length=1, max_length=20)


class ResolveSupportCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_note: str | None = Field(default=None, max_length=1000)


class AgentSupportMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_user_id: UUID
    client_message_id: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


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
        code = str(exc)
        if code == "ACTOR_NOT_TASK_PARTICIPANT":
            raise ApiError(404, "TASK_NOT_FOUND", "Task was not found.") from exc
        raise ApiError(403, code, "User is not allowed to open this conversation.") from exc

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
    await enforce_user_conversation_limits(
        request,
        operation="message",
        user_id=str(current_user.user_id),
        conversation_id=str(conversation_id),
        limit=settings.message_rate_limit_per_minute,
        window_seconds=60,
    )
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
        code = str(exc)
        if code in {"ACTOR_NOT_TASK_PARTICIPANT", "ACTOR_NOT_SUPPORT_PARTICIPANT"}:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.") from exc
        raise ApiError(403, code, "User is not allowed to send a message.") from exc
    except ValueError as exc:
        code = str(exc)
        raise ApiError(
            409 if code == "MESSAGE_IDEMPOTENCY_CONFLICT" else 422,
            code,
            "Message payload is invalid.",
        ) from exc

    return _message_response(result.message, created=result.created, delivery_status="accepted")


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    after_seq: int = 0,
    limit: int = 100,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    await _ensure_user_can_read_conversation(session, conversation_id=conversation_id, user_id=current_user.user_id)
    conversation = await ConversationRepository(session).find_by_id(conversation_id)
    if conversation is not None and conversation.conversation_type == "support":
        case = await SupportCaseRepository(session).find_by_conversation(conversation_id)
        if case is None:
            raise ApiError(404, "SUPPORT_CASE_NOT_FOUND", "Support case was not found.")
        messages = await diddisupport_read_client().list_user_visible_messages(case.external_case_id)
        return [
            _remote_support_message_response(message, conversation_id=conversation_id, sequence=index)
            for index, message in enumerate(messages, start=1)
            if index > max(after_seq, 0)
        ][: min(max(limit, 1), 200)]
    messages = await MessageRepository(session).list_after(
        conversation_id=conversation_id,
        after_sequence=max(after_seq, 0),
        limit=min(max(limit, 1), 200),
    )
    statuses = await MessageDeliveryRepository(session).statuses_for_messages([message.id for message in messages])
    return [
        _message_response(message, delivery_status=statuses.get(message.id, "accepted")) for message in messages
    ]


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=MarkConversationReadResponse,
)
async def mark_conversation_read(
    conversation_id: UUID,
    payload: MarkConversationReadRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> MarkConversationReadResponse:
    await _ensure_user_can_read_conversation(session, conversation_id=conversation_id, user_id=current_user.user_id)
    try:
        result = await MarkConversationReadService(session).mark(
            conversation_id=conversation_id,
            actor_user_id=current_user.user_id,
            read_sequence=payload.read_seq,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    return MarkConversationReadResponse(
        conversation_id=result.conversation_id,
        read_seq=result.read_sequence,
    )


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/delivery",
    response_model=DeliveryAcknowledgementResponse,
)
async def acknowledge_message_delivery(
    conversation_id: UUID,
    message_id: UUID,
    payload: DeliveryAcknowledgementRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeliveryAcknowledgementResponse:
    try:
        result = await MessageDeliveryService(session).acknowledge(
            conversation_id=conversation_id,
            message_id=message_id,
            recipient_user_id=current_user.user_id,
            status=payload.status,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Message was not found.") from exc
    except PermissionError as exc:
        raise ApiError(404, "MESSAGE_NOT_FOUND", "Message was not found.") from exc
    except ValueError as exc:
        raise ApiError(422, str(exc), "Delivery status is invalid.") from exc
    return DeliveryAcknowledgementResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        status=result.status,
        changed=result.changed,
    )


@router.put("/conversations/{conversation_id}/mute", response_model=ConversationMuteResponse)
async def set_conversation_muted(
    conversation_id: UUID,
    payload: ConversationMuteRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationMuteResponse:
    try:
        preference = await ConversationSafetyService(session).set_muted(
            conversation_id=conversation_id,
            user_id=current_user.user_id,
            muted=payload.muted,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    except PermissionError as exc:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.") from exc
    return ConversationMuteResponse(conversation_id=conversation_id, muted=preference.muted)


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/reports",
    response_model=AbuseReportResponse,
)
async def report_message_abuse(
    conversation_id: UUID,
    message_id: UUID,
    payload: AbuseReportRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> AbuseReportResponse:
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        result = await ConversationSafetyService(session).report_message(
            conversation_id=conversation_id,
            message_id=message_id,
            reporter_user_id=current_user.user_id,
            category=payload.category,
            details=payload.details,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Message was not found.") from exc
    except PermissionError as exc:
        raise ApiError(404, "MESSAGE_NOT_FOUND", "Message was not found.") from exc
    except ValueError as exc:
        code = str(exc)
        raise ApiError(409 if code.endswith("CONFLICT") else 422, code, "Report is invalid.") from exc
    return AbuseReportResponse(
        report_id=result.report.id,
        conversation_id=result.report.conversation_id,
        message_id=result.report.message_id,
        category=result.report.category,
        status=result.report.status,
        created=result.created,
    )


@router.post(
    "/backoffice/tasks/{owner_service}/{task_type}/{task_id}/conversation",
    response_model=ConversationResponse,
)
async def ensure_backoffice_task_conversation(
    owner_service: str,
    task_type: str,
    task_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    operator: DelegatedOperator = Depends(require_delegated_operator(required_scope=BACKOFFICE_READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    result = await BackofficeConversationService(session).ensure_conversation(
        task=TaskReference(owner_service=owner_service, task_type=task_type, task_id=task_id),
        operator=operator,
        idempotency_key=idempotency_key,
    )
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


@router.get(
    "/backoffice/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def list_backoffice_messages(
    conversation_id: UUID,
    after_seq: int = 0,
    limit: int = 100,
    operator: DelegatedOperator = Depends(require_delegated_operator(required_scope=BACKOFFICE_READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    try:
        messages = await BackofficeConversationService(session).list_messages(
            conversation_id=conversation_id,
            operator=operator,
            after_sequence=after_seq,
            limit=limit,
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    statuses = await MessageDeliveryRepository(session).statuses_for_messages([message.id for message in messages])
    return [
        _message_response(message, delivery_status=statuses.get(message.id, "accepted")) for message in messages
    ]


@router.post(
    "/backoffice/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
)
async def send_backoffice_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    operator: DelegatedOperator = Depends(require_delegated_operator(required_scope=BACKOFFICE_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        result = await BackofficeConversationService(session).send_message(
            conversation_id=conversation_id,
            operator=operator,
            client_message_id=payload.client_message_id,
            body=payload.body,
            idempotency_key=idempotency_key,
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    except PermissionError as exc:
        raise ApiError(403, str(exc), "Conversation does not accept Backoffice messages.") from exc
    except ValueError as exc:
        code = str(exc)
        raise ApiError(409 if code == "MESSAGE_IDEMPOTENCY_CONFLICT" else 422, code, "Message is invalid.") from exc
    return _message_response(result.message, created=result.created, delivery_status="accepted")


@router.post("/conversations/{conversation_id}/call-attempts", response_model=CallAttemptResponse)
async def create_call_attempt(
    conversation_id: UUID,
    payload: CallAttemptRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> CallAttemptResponse:
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    await enforce_user_conversation_limits(
        request,
        operation="call",
        user_id=str(current_user.user_id),
        conversation_id=str(conversation_id),
        limit=settings.call_rate_limit_per_five_minutes,
        window_seconds=300,
    )
    try:
        result = await CreateCallAttemptService(session).create(
            conversation_id=conversation_id,
            actor_user_id=current_user.user_id,
            target_user_id=payload.target_user_id,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    except PermissionError as exc:
        code = str(exc)
        if code == "ACTOR_NOT_TASK_PARTICIPANT":
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.") from exc
        raise ApiError(403, code, "User is not allowed to call this participant.") from exc
    except ValueError as exc:
        code = str(exc)
        status_code = 409 if code == "CALL_IDEMPOTENCY_CONFLICT" else 422
        raise ApiError(status_code, code, "Call request is invalid.") from exc
    return CallAttemptResponse(
        attempt_id=result.attempt.id,
        conversation_id=result.attempt.conversation_id,
        target_user_id=result.attempt.target_user_id,
        status=result.attempt.outcome,
        dial_action={"scheme": "tel", "value": f"tel:{result.target_phone_e164}"},
        created=result.created,
    )


@router.post("/backoffice/conversations/{conversation_id}/call-attempts", response_model=CallAttemptResponse)
async def create_backoffice_call_attempt(
    conversation_id: UUID,
    payload: CallAttemptRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    operator: DelegatedOperator = Depends(require_delegated_operator(required_scope=BACKOFFICE_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> CallAttemptResponse:
    """Authorize an audited external call on behalf of a support operator."""
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    try:
        result = await CreateCallAttemptService(session).create(
            conversation_id=conversation_id,
            actor_user_id=operator.operator_user_id,
            target_user_id=payload.target_user_id,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", operator.request_id),
            allow_delegated_operator=True,
            actor_service=operator.service.subject,
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Conversation was not found.") from exc
    except PermissionError as exc:
        raise ApiError(403, str(exc), "The operator is not allowed to call this participant.") from exc
    except ValueError as exc:
        code = str(exc)
        raise ApiError(409 if code == "CALL_IDEMPOTENCY_CONFLICT" else 422, code, "Call request is invalid.") from exc
    return CallAttemptResponse(
        attempt_id=result.attempt.id,
        conversation_id=result.attempt.conversation_id,
        target_user_id=result.attempt.target_user_id,
        status=result.attempt.outcome,
        dial_action={"scheme": "tel", "value": f"tel:{result.target_phone_e164}"},
        created=result.created,
    )


@router.post("/conversations/{conversation_id}/call-attempts/{attempt_id}/client-result")
async def record_call_client_result(
    conversation_id: UUID,
    attempt_id: UUID,
    payload: CallClientResultRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    try:
        attempt = await RecordCallClientResultService(session).record(
            attempt_id=attempt_id,
            actor_user_id=current_user.user_id,
            result=payload.result,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Call attempt was not found.") from exc
    except PermissionError as exc:
        raise ApiError(403, str(exc), "User is not allowed to update this call attempt.") from exc
    if attempt.conversation_id != conversation_id:
        raise ApiError(404, "CALL_ATTEMPT_NOT_FOUND", "Call attempt was not found.")
    return {"attempt_id": str(attempt.id), "conversation_id": str(conversation_id), "status": str(attempt.outcome)}


@router.post("/support/cases", response_model=SupportCaseResponse, status_code=status.HTTP_201_CREATED)
async def open_support_case(
    payload: OpenSupportCaseRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    if any([payload.owner_service, payload.task_type, payload.task_id]) and not all(
        [payload.owner_service, payload.task_type, payload.task_id]
    ):
        raise ApiError(422, "SUPPORT_TASK_REFERENCE_INCOMPLETE", "Support task reference is incomplete.")
    task = (
        TaskReference(
            owner_service=str(payload.owner_service),
            task_type=str(payload.task_type),
            task_id=payload.task_id,
        )
        if payload.owner_service and payload.task_type and payload.task_id
        else None
    )
    result = await _open_support_for_user(
        request=request,
        session=session,
        requester_user_id=current_user.user_id,
        subject=payload.subject,
        initial_message=payload.initial_message,
        priority=payload.priority,
        category=payload.category,
        origin_report_id=payload.origin_report_id,
        task=task,
        idempotency_key=idempotency_key,
    )
    return _support_case_response(result.case)


@router.post(
    "/support/conversations",
    response_model=SupportConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_support_conversation(
    payload: OpenSupportConversationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> SupportConversationResponse:
    task = (
        TaskReference(
            owner_service=payload.context.owner_service,
            task_type=payload.context.task_type,
            task_id=payload.context.task_id,
        )
        if payload.context
        else None
    )
    subject = payload.subject or payload.category.replace("_", " ").strip().capitalize()
    result = await _open_support_for_user(
        request=request,
        session=session,
        requester_user_id=current_user.user_id,
        subject=subject,
        initial_message=payload.message,
        priority=payload.priority,
        category=payload.category,
        origin_report_id=payload.origin_report_id,
        task=task,
        idempotency_key=idempotency_key,
    )
    case = result.case
    return SupportConversationResponse(
        conversation_id=result.conversation.id,
        support_case_id=case.id,
        conversation_state=result.conversation.state,
        case_status=case.status,
        owner_service=case.owner_service,
        task_type=case.task_type,
        task_id=case.task_id,
    )


@router.get("/support/cases", response_model=list[SupportCaseResponse])
async def list_support_cases(
    case_status: str | None = Query(default=None, alias="status"),
    owner_service: str | None = None,
    limit: int = 100,
    _service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> list[SupportCaseResponse]:
    cases = await SupportCaseRepository(session).list_cases(
        status=case_status,
        owner_service=owner_service,
        limit=min(max(limit, 1), 200),
    )
    return [_support_case_response(case) for case in cases]


@router.get("/support/cases/{case_id}", response_model=SupportCaseResponse)
async def get_support_case(
    case_id: UUID,
    _service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    case = await SupportCaseRepository(session).find_by_id(case_id)
    if case is None:
        raise ApiError(404, "SUPPORT_CASE_NOT_FOUND", "Support case was not found.")
    return _support_case_response(case)


@router.get("/support/cases/{case_id}/messages", response_model=list[MessageResponse])
async def list_support_case_messages(
    case_id: UUID,
    after_seq: int = 0,
    limit: int = 100,
    _service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    case = await SupportCaseRepository(session).find_by_id(case_id)
    if case is None:
        raise ApiError(404, "SUPPORT_CASE_NOT_FOUND", "Support case was not found.")
    messages = await diddisupport_read_client().list_user_visible_messages(case.external_case_id)
    return [
        _remote_support_message_response(message, conversation_id=case.conversation_id, sequence=index)
        for index, message in enumerate(messages, start=1)
        if index > max(after_seq, 0)
    ][: min(max(limit, 1), 200)]


@router.post("/support/cases/{case_id}/assign", response_model=SupportCaseResponse, deprecated=True)
async def assign_support_case(
    case_id: UUID,
    payload: AssignSupportCaseRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    raise ApiError(
        410,
        "DIDDISUPPORT_BACKOFFICE_REQUIRED",
        "Support assignment is owned by DiddiSupport Backoffice.",
    )


@router.patch("/support/cases/{case_id}/priority", response_model=SupportCaseResponse, deprecated=True)
async def update_support_case_priority(
    case_id: UUID,
    payload: UpdateSupportPriorityRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    raise ApiError(
        410,
        "DIDDISUPPORT_BACKOFFICE_REQUIRED",
        "Support priority is owned by DiddiSupport Backoffice.",
    )


@router.post("/support/cases/{case_id}/messages", response_model=MessageResponse, deprecated=True)
async def send_support_agent_message(
    case_id: UUID,
    payload: AgentSupportMessageRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_MESSAGES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    raise ApiError(
        410,
        "DIDDISUPPORT_BACKOFFICE_REQUIRED",
        "Agent replies are owned by DiddiSupport Backoffice.",
    )


@router.post("/support/cases/{case_id}/resolve", response_model=SupportCaseResponse, deprecated=True)
async def resolve_support_case(
    case_id: UUID,
    payload: ResolveSupportCaseRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    raise ApiError(
        410,
        "DIDDISUPPORT_BACKOFFICE_REQUIRED",
        "Support resolution is owned by DiddiSupport Backoffice.",
    )


def _message_response(
    message,
    *,
    created: bool | None = None,
    delivery_status: str = "accepted",
) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sequence=message.sequence,
        sender_user_id=message.sender_user_id,
        client_message_id=message.client_message_id,
        body=message.body,
        moderation_status=message.moderation_status,
        delivery_status=delivery_status,
        created=created,
    )


def _remote_support_message_response(
    message: RemoteSupportMessage,
    *,
    conversation_id: UUID,
    sequence: int,
) -> MessageResponse:
    return MessageResponse(
        id=message.message_id,
        conversation_id=conversation_id,
        sequence=sequence,
        sender_user_id=message.author_id,
        client_message_id=str(message.message_id),
        body=message.body,
        moderation_status="accepted",
        delivery_status="delivered",
        created=None,
    )


async def _open_support_for_user(
    *,
    request: Request,
    session: AsyncSession,
    requester_user_id: UUID,
    subject: str,
    initial_message: str | None,
    priority: str,
    category: str,
    origin_report_id: str | None,
    task: TaskReference | None,
    idempotency_key: str | None,
):
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    client_ip = request.client.host if request.client else "unknown"
    for dimension, subject_value in (
        ("user", str(requester_user_id)),
        ("task", str(task.task_id) if task else "general"),
        ("ip", client_ip),
    ):
        await enforce_rate_limit(
            request,
            bucket=f"support-case:{dimension}",
            subject=subject_value,
            limit=settings.support_case_rate_limit_per_hour,
            window_seconds=3600,
        )
    try:
        return await SupportCaseService(session).open_case(
            requester_user_id=requester_user_id,
            subject=subject,
            priority=priority,
            category=category,
            origin_report_id=origin_report_id,
            initial_message=initial_message,
            task=task,
            request_id=getattr(request.state, "request_id", None),
            idempotency_key=idempotency_key,
        )
    except PermissionError as exc:
        code = str(exc)
        if code == "ACTOR_NOT_TASK_PARTICIPANT":
            raise ApiError(404, "TASK_NOT_FOUND", "Task was not found.") from exc
        raise ApiError(403, code, "User is not allowed to open support for this task.") from exc
    except ValueError as exc:
        code = str(exc)
        if code == "IDEMPOTENCY_KEY_REQUIRED":
            raise ApiError(400, code, "Idempotency-Key is required.") from exc
        raise ApiError(422, code, "Support case payload is invalid.") from exc


async def _ensure_user_can_read_conversation(session: AsyncSession, *, conversation_id: UUID, user_id: UUID) -> None:
    conversations = ConversationRepository(session)
    conversation = await conversations.find_by_id(conversation_id)
    if conversation is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.")
    if conversation.conversation_type == "support":
        if not await conversations.has_active_participant(conversation_id=conversation_id, user_id=user_id):
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.")
        return

    task = TaskReference(
        owner_service=conversation.owner_service,
        task_type=conversation.task_type,
        task_id=conversation.task_id,
    )
    from app_base.modules.context.infra.factory import resolver_for_owner

    context = await resolver_for_owner(task.owner_service).get_task(task.task_type, task.task_id)
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.READ_HISTORY,
        actor_user_id=user_id,
        context=context,
        conversation=ConversationAccessSnapshot(
            task=task,
            state=ConversationState(conversation.state),
            closes_at=conversation.closes_at,
        ),
    )
    if not decision.allowed:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.")


def _support_case_response(case) -> SupportCaseResponse:
    return SupportCaseResponse(
        id=case.id,
        conversation_id=case.conversation_id,
        requester_user_id=case.requester_user_id,
        owner_service=case.owner_service,
        task_type=case.task_type,
        task_id=case.task_id,
        subject=case.subject,
        status=case.status,
        priority=case.priority,
        assigned_to_user_id=case.assigned_to_user_id,
        projection_status=getattr(case, "projection_status", "synced"),
        created_at=case.created_at.isoformat().replace("+00:00", "Z") if case.created_at else None,
        updated_at=case.updated_at.isoformat().replace("+00:00", "Z") if case.updated_at else None,
        resolved_at=case.resolved_at.isoformat().replace("+00:00", "Z") if case.resolved_at else None,
    )
