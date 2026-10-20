from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.auth_deps import AuthenticatedService, AuthenticatedUser, require_current_user, require_service_token
from app_base.core.database import get_session
from app_base.core.errors import ApiError
from app_base.modules.calls.application import CreateCallAttemptService, RecordCallClientResultService
from app_base.modules.context.domain import TaskReference
from app_base.modules.conversations.application import (
    EnsureTaskConversationService,
    MarkConversationReadService,
    SendMessageService,
    SupportCaseService,
)
from app_base.modules.conversations.domain import (
    CommunicationAction,
    ConversationAccessPolicy,
    ConversationAccessSnapshot,
    ConversationState,
)
from app_base.modules.conversations.infra.repositories import (
    ConversationRepository,
    MessageRepository,
    SupportCaseRepository,
)

router = APIRouter(tags=["conversations"])

SUPPORT_CASES_READ_SCOPE = "diddicomms:support-cases:read"
SUPPORT_CASES_WRITE_SCOPE = "diddicomms:support-cases:write"
SUPPORT_MESSAGES_WRITE_SCOPE = "diddicomms:messages:write"


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


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    sequence: int
    sender_user_id: UUID
    client_message_id: str
    body: str
    moderation_status: str
    delivery_status: str = "pending"
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
        code = str(exc)
        raise ApiError(
            409 if code == "MESSAGE_IDEMPOTENCY_CONFLICT" else 422,
            code,
            "Message payload is invalid.",
        ) from exc

    return _message_response(result.message, created=result.created)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    after_seq: int = 0,
    limit: int = 100,
    current_user: AuthenticatedUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    await _ensure_user_can_read_conversation(session, conversation_id=conversation_id, user_id=current_user.user_id)
    messages = await MessageRepository(session).list_after(
        conversation_id=conversation_id,
        after_sequence=max(after_seq, 0),
        limit=min(max(limit, 1), 200),
    )
    return [_message_response(message) for message in messages]


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
        raise ApiError(403, str(exc), "User is not allowed to call this participant.") from exc
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
    try:
        result = await SupportCaseService(session).open_case(
            requester_user_id=current_user.user_id,
            subject=payload.subject,
            priority=payload.priority,
            category=payload.category,
            origin_report_id=payload.origin_report_id,
            initial_message=payload.initial_message,
            task=task,
            request_id=getattr(request.state, "request_id", None),
            idempotency_key=idempotency_key,
        )
    except PermissionError as exc:
        raise ApiError(403, str(exc), "User is not allowed to open support for this task.") from exc
    except ValueError as exc:
        code = str(exc)
        if code == "IDEMPOTENCY_KEY_REQUIRED":
            raise ApiError(400, code, "Idempotency-Key is required.") from exc
        raise ApiError(422, code, "Support case payload is invalid.") from exc
    return _support_case_response(result.case)


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
    messages = await MessageRepository(session).list_after(
        conversation_id=case.conversation_id,
        after_sequence=max(after_seq, 0),
        limit=min(max(limit, 1), 200),
    )
    return [_message_response(message) for message in messages]


@router.post("/support/cases/{case_id}/assign", response_model=SupportCaseResponse)
async def assign_support_case(
    case_id: UUID,
    payload: AssignSupportCaseRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    try:
        case = await SupportCaseService(session).assign_case(
            case_id=case_id,
            assignee_user_id=payload.assignee_user_id,
            actor_service=service.subject,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Support case was not found.") from exc
    except ValueError as exc:
        raise ApiError(409, str(exc), "Support case cannot be assigned.") from exc
    return _support_case_response(case)


@router.patch("/support/cases/{case_id}/priority", response_model=SupportCaseResponse)
async def update_support_case_priority(
    case_id: UUID,
    payload: UpdateSupportPriorityRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    try:
        case = await SupportCaseService(session).update_priority(
            case_id=case_id,
            priority=payload.priority,
            actor_service=service.subject,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Support case was not found.") from exc
    except ValueError as exc:
        raise ApiError(422, str(exc), "Support priority is invalid.") from exc
    return _support_case_response(case)


@router.post("/support/cases/{case_id}/messages", response_model=MessageResponse)
async def send_support_agent_message(
    case_id: UUID,
    payload: AgentSupportMessageRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_MESSAGES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    try:
        result = await SupportCaseService(session).send_agent_message(
            case_id=case_id,
            agent_user_id=payload.agent_user_id,
            client_message_id=payload.client_message_id,
            body=payload.body,
            actor_service=service.subject,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Support case was not found.") from exc
    except PermissionError as exc:
        raise ApiError(403, str(exc), "Agent is not allowed to reply to this support case.") from exc
    except ValueError as exc:
        raise ApiError(409, str(exc), "Support case does not accept new messages.") from exc
    return _message_response(result.message, created=result.created)


@router.post("/support/cases/{case_id}/resolve", response_model=SupportCaseResponse)
async def resolve_support_case(
    case_id: UUID,
    payload: ResolveSupportCaseRequest,
    request: Request,
    service: AuthenticatedService = Depends(require_service_token(required_scope=SUPPORT_CASES_WRITE_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> SupportCaseResponse:
    try:
        case = await SupportCaseService(session).resolve_case(
            case_id=case_id,
            actor_service=service.subject,
            resolution_note=payload.resolution_note,
            request_id=getattr(request.state, "request_id", None),
        )
    except LookupError as exc:
        raise ApiError(404, str(exc), "Support case was not found.") from exc
    return _support_case_response(case)


def _message_response(message, *, created: bool | None = None) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sequence=message.sequence,
        sender_user_id=message.sender_user_id,
        client_message_id=message.client_message_id,
        body=message.body,
        moderation_status=message.moderation_status,
        delivery_status="pending",
        created=created,
    )


async def _ensure_user_can_read_conversation(session: AsyncSession, *, conversation_id: UUID, user_id: UUID) -> None:
    conversations = ConversationRepository(session)
    conversation = await conversations.find_by_id(conversation_id)
    if conversation is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.")
    if conversation.conversation_type == "support":
        if not await conversations.has_active_participant(conversation_id=conversation_id, user_id=user_id):
            raise ApiError(403, "ACTOR_NOT_SUPPORT_PARTICIPANT", "User is not allowed to read this conversation.")
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
        raise ApiError(403, decision.reason_code, "User is not allowed to read this conversation.")


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
        created_at=case.created_at.isoformat().replace("+00:00", "Z") if case.created_at else None,
        updated_at=case.updated_at.isoformat().replace("+00:00", "Z") if case.updated_at else None,
        resolved_at=case.resolved_at.isoformat().replace("+00:00", "Z") if case.resolved_at else None,
    )
