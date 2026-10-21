from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app_base.core.auth_deps import AuthenticatedUser
from app_base.core.database import async_session_factory
from app_base.core.errors import ApiError
from app_base.core.metrics import increment, set_gauge
from app_base.core.redis import create_redis
from app_base.core.security import FreeIDTokenVerifier
from app_base.core.settings import settings
from app_base.modules.conversations.infra.repositories import ConversationRepository
from app_base.modules.events.domain import DIDDICOMMS_EVENTS_STREAM

router = APIRouter(tags=["realtime"])


class ConnectionRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_user: dict[UUID, int] = defaultdict(int)
        self._by_conversation: dict[UUID, int] = defaultdict(int)

    async def acquire(self, *, user_id: UUID, conversation_id: UUID) -> bool:
        async with self._lock:
            if self._by_user[user_id] >= settings.websocket_max_connections_per_user:
                return False
            if self._by_conversation[conversation_id] >= settings.websocket_max_connections_per_conversation:
                return False
            self._by_user[user_id] += 1
            self._by_conversation[conversation_id] += 1
            set_gauge("diddicomms_websocket_active_connections", sum(self._by_user.values()))
            return True

    async def release(self, *, user_id: UUID, conversation_id: UUID) -> None:
        async with self._lock:
            self._by_user[user_id] = max(self._by_user[user_id] - 1, 0)
            self._by_conversation[conversation_id] = max(self._by_conversation[conversation_id] - 1, 0)
            if self._by_user[user_id] == 0:
                del self._by_user[user_id]
            if self._by_conversation[conversation_id] == 0:
                del self._by_conversation[conversation_id]
            set_gauge("diddicomms_websocket_active_connections", sum(self._by_user.values()))


connection_registry = ConnectionRegistry()


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

    if not await connection_registry.acquire(user_id=user.user_id, conversation_id=conversation_id):
        increment("diddicomms_websocket_connections_total", {"outcome": "limited"})
        await websocket.close(code=4429, reason="connection limit reached")
        return
    increment("diddicomms_websocket_connections_total", {"outcome": "accepted"})

    redis = create_redis()
    stream_id = websocket.query_params.get("after_event_id", "$")
    last_client_activity = time.monotonic()
    try:
        try:
            cursor_trimmed = stream_id != "$" and await _cursor_is_trimmed(redis, stream_id)
        except ApiError:
            await websocket.send_json({"type": "resync_required", "reason": "stream_cursor_invalid"})
            await websocket.close(code=4400, reason="invalid stream cursor")
            return
        if cursor_trimmed:
            increment("diddicomms_websocket_connections_total", {"outcome": "resync_required"})
            await websocket.send_json(
                {
                    "type": "resync_required",
                    "reason": "stream_cursor_trimmed",
                    "resync_path": f"/comms/v1/conversations/{conversation_id}/messages?after_seq=0",
                }
            )
            await websocket.close(code=4409, reason="stream cursor trimmed")
            return
        while True:
            read_task = asyncio.create_task(
                redis.xread(
                    {DIDDICOMMS_EVENTS_STREAM: stream_id},
                    count=100,
                    block=settings.websocket_heartbeat_seconds * 1000,
                )
            )
            receive_task = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                {read_task, receive_task},
                timeout=settings.websocket_heartbeat_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task

            if receive_task in done:
                receive_task.result()
                last_client_activity = time.monotonic()
                continue

            entries = read_task.result() if read_task in done else []
            if not entries:
                if time.monotonic() - last_client_activity >= settings.websocket_idle_timeout_seconds:
                    await websocket.close(code=4408, reason="idle timeout")
                    return
                await websocket.send_json({"type": "heartbeat"})
                continue
            for _, stream_entries in entries:
                for event_id, fields in stream_entries:
                    stream_id = event_id
                    event = _event_for_conversation(event_id, fields, conversation_id)
                    if event is not None:
                        await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    finally:
        await connection_registry.release(user_id=user.user_id, conversation_id=conversation_id)
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
        "comms.message.delivered.v1",
        "comms.message.read.v1",
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


async def _cursor_is_trimmed(redis, stream_id: str) -> bool:
    try:
        oldest_entries = await redis.xrange(DIDDICOMMS_EVENTS_STREAM, min="-", max="+", count=1)
    except Exception:
        return False
    if not oldest_entries:
        return False
    oldest_id = str(oldest_entries[0][0])
    return _stream_id_tuple(stream_id) < _stream_id_tuple(oldest_id)


def _stream_id_tuple(stream_id: str) -> tuple[int, int]:
    try:
        milliseconds, sequence = stream_id.split("-", maxsplit=1)
        return int(milliseconds), int(sequence)
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "STREAM_CURSOR_INVALID", "Realtime stream cursor is invalid.") from exc
