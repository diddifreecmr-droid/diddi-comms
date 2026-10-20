from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app_base.core.auth_deps import AuthenticatedUser
from app_base.core.database import async_session_factory
from app_base.core.errors import ApiError
from app_base.core.redis import create_redis
from app_base.core.security import FreeIDTokenVerifier
from app_base.modules.conversations.infra.repositories import ConversationRepository
from app_base.modules.events.domain import DIDDICOMMS_EVENTS_STREAM

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        user = _authenticate(websocket)
        conversation_id = UUID(websocket.query_params["conversation_id"])
        await _ensure_participant(conversation_id=conversation_id, user=user)
    except (ApiError, KeyError, ValueError) as exc:
        await websocket.close(code=4401 if isinstance(exc, ApiError) and exc.status_code == 401 else 4403)
        return

    redis = create_redis()
    stream_id = websocket.query_params.get("after_event_id", "$")
    try:
        while True:
            entries = await redis.xread({DIDDICOMMS_EVENTS_STREAM: stream_id}, count=100, block=15000)
            for _, stream_entries in entries:
                for event_id, fields in stream_entries:
                    stream_id = event_id
                    event = _event_for_conversation(event_id, fields, conversation_id)
                    if event is not None:
                        await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    finally:
        await redis.aclose()


def _authenticate(websocket: WebSocket) -> AuthenticatedUser:
    authorization = websocket.headers.get("authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "TOKEN_MISSING", "Authentication is required.")
    claims = FreeIDTokenVerifier(require_audience=False).verify(authorization.removeprefix("Bearer ").strip())
    if claims.token_type == "service" or claims.subject.startswith("service:"):
        raise ApiError(403, "USER_TOKEN_REQUIRED", "A user token is required.")
    return AuthenticatedUser(user_id=UUID(claims.subject), role=claims.role, claims=claims.claims)


async def _ensure_participant(*, conversation_id: UUID, user: AuthenticatedUser) -> None:
    async with async_session_factory() as session:
        conversation = await ConversationRepository(session).find_by_id(conversation_id)
        if conversation is None:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "Conversation was not found.")
        if not await ConversationRepository(session).has_active_participant(
            conversation_id=conversation_id,
            user_id=user.user_id,
        ):
            raise ApiError(403, "ACTOR_NOT_CONVERSATION_PARTICIPANT", "User is not allowed to subscribe.")


def _event_for_conversation(event_id: str, fields: dict[str, str], conversation_id: UUID) -> dict | None:
    event_type = fields.get("event_type", "")
    if event_type not in {
        "comms.message.created.v1",
        "comms.support.message.created.v1",
        "comms.conversation.read_cursor_changed.v1",
    }:
        return None
    try:
        payload = json.loads(fields.get("payload", "{}"))
    except json.JSONDecodeError:
        return None
    if payload.get("conversation_id") != str(conversation_id):
        return None
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_version": int(fields.get("event_version", "1")),
        "payload": payload,
    }
