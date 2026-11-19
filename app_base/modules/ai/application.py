from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.database import async_session_factory
from app_base.core.settings import settings
from app_base.modules.ai.decision_gate import DecisionGateError, JevDecisionGate
from app_base.modules.ai.provider import AIProviderError, OpenRouterClient
from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.conversations.domain import ConversationState
from app_base.modules.conversations.infra.models import ConversationModel, MessageModel
from app_base.modules.conversations.infra.repositories import ConversationRepository, MessageRepository
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft

logger = logging.getLogger(__name__)


async def process_support_ai_message(conversation_id: UUID, source_message_id: UUID) -> None:
    """Generate one AI reply after a committed user message.

    The background task is deliberately idempotent: the generated message uses
    the source message ID as its client message ID. Human takeover and closed
    conversations are checked again before the AI message is persisted.
    """

    async with async_session_factory() as session:
        try:
            await _process(session, conversation_id, source_message_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("support_ai_processing_failed", extra={"conversation_id": str(conversation_id)})


async def process_latest_support_ai_message(conversation_id: UUID) -> None:
    async with async_session_factory() as session:
        try:
            messages = MessageRepository(session)
            history = await messages.list_after(conversation_id=conversation_id, after_sequence=0, limit=100)
            source = next(
                (message for message in reversed(history) if message.sender_user_id != settings.ai_actor_user_id),
                None,
            )
            if source is not None:
                await _process(session, conversation_id, source.id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("support_ai_processing_failed", extra={"conversation_id": str(conversation_id)})


async def _process(session: AsyncSession, conversation_id: UUID, source_message_id: UUID) -> None:
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    conversation = await conversations.find_by_id(conversation_id)
    source = await session.get(MessageModel, source_message_id)
    if conversation is None or source is None or conversation.conversation_type != "support":
        return
    if ConversationState(conversation.state) not in {ConversationState.ACTIVE, ConversationState.CLOSING}:
        return
    participants = await conversations.participants_for(conversation_id)
    if any(p.role in {"support_agent", "admin"} for p in participants):
        return
    if not any(p.user_id == settings.ai_actor_user_id for p in participants):
        conversations.add_participant(
            conversation_id=conversation_id,
            user_id=settings.ai_actor_user_id,
            role="ai",
            permissions="assistant",
        )

    history_models = await messages.list_after(conversation_id=conversation_id, after_sequence=0, limit=50)
    history = [m.body for m in history_models if m.sender_user_id != settings.ai_actor_user_id]
    try:
        decision = await JevDecisionGate().classify(message=source.body, history=history[:-1])
    except DecisionGateError:
        _record_gate_handoff(session, conversation, source)
        await _persist_ai_response(
            session,
            conversation,
            source,
            "Your message has been sent to our support team. They will review it and get back to you.",
            category="needs_human",
        )
        return
    if decision.route != "support_allowed":
        _record_gate_handoff(session, conversation, source, route=decision.route)
        response = (
            "I can help with Diddi support questions. Your message has been sent to our support team."
            if decision.route == "needs_human"
            else "I can only help with Diddi support questions. Please describe the issue you are experiencing."
        )
        await _persist_ai_response(session, conversation, source, response, category=decision.category)
        return

    try:
        completion = await OpenRouterClient().complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are DiddiComms support assistant. Answer only about the user's support request. "
                        "Do not act as a general chatbot. Ask concise clarifying questions when needed."
                    ),
                },
                *({"role": "user", "content": text} for text in history[-settings.decision_gate_history_messages :]),
            ],
            max_tokens=500,
        )
    except AIProviderError:
        _record_gate_handoff(session, conversation, source, route="needs_human")
        await _persist_ai_response(
            session,
            conversation,
            source,
            "Your message has been sent to our support team. They will review it and get back to you.",
            category=decision.category,
        )
        return

    await _persist_ai_response(session, conversation, source, completion.content, category=decision.category)


async def _persist_ai_response(
    session: AsyncSession,
    conversation: ConversationModel,
    source: MessageModel,
    body: str,
    *,
    category: str,
) -> None:
    messages = MessageRepository(session)
    existing = await messages.find_by_client_message(
        sender_user_id=settings.ai_actor_user_id,
        client_message_id=f"ai-reply-{source.id}",
    )
    if existing is not None:
        return
    ai_message = messages.add_message(
        conversation=conversation,
        sender_user_id=settings.ai_actor_user_id,
        client_message_id=f"ai-reply-{source.id}",
        body=body,
    )
    AuditRecorder(session).add(
        AuditEventDraft(
            actor_user_id=settings.ai_actor_user_id,
            action="support.ai_message.created",
            target_type="message",
            target_id=str(ai_message.id),
            outcome="succeeded",
            safe_metadata={"source_message_id": str(source.id), "category": category},
        )
    )
    OutboxWriter(session).add(
        OutboxEventDraft(
            aggregate_type="support_case",
            aggregate_id=str(conversation.task_id),
            event_type="comms.support.ai_context_updated.v1",
            payload={
                "conversation_id": str(conversation.id),
                "source_message_id": str(source.id),
                "ai_message_id": str(ai_message.id),
                "category": category,
            },
        )
    )


def _record_gate_handoff(
    session: AsyncSession,
    conversation: ConversationModel,
    source: MessageModel,
    *,
    route: str = "needs_human",
) -> None:
    AuditRecorder(session).add(
        AuditEventDraft(
            actor_user_id=settings.ai_actor_user_id,
            action="support.ai_handoff_requested",
            target_type="conversation",
            target_id=str(conversation.id),
            outcome="succeeded",
            safe_metadata={"source_message_id": str(source.id), "route": route},
        )
    )
