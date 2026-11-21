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
from app_base.modules.conversations.infra.repositories import (
    ConversationRepository,
    MessageRepository,
    SupportCaseRepository,
)
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft
from app_base.modules.support.factory import diddisupport_read_client

logger = logging.getLogger(__name__)
FALLBACK_REPLY = "Your message has been sent to our support team. They will review it and get back to you."


async def process_support_ai_message(conversation_id: UUID, source_message_id: UUID) -> None:
    """Process a committed user message against remote DiddiSupport history."""
    logger.info(
        "support_ai_processing_started",
        extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
    )
    async with async_session_factory() as session:
        try:
            await _process(session, conversation_id, source_message_id)
            await session.commit()
            logger.info(
                "support_ai_processing_finished",
                extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "support_ai_processing_failed",
                extra={
                    "conversation_id": str(conversation_id),
                    "source_message_id": str(source_message_id),
                },
            )


async def process_latest_support_ai_message(conversation_id: UUID) -> None:
    """Process the initial message created while opening a support case."""
    logger.info("support_ai_initial_processing_started", extra={"conversation_id": str(conversation_id)})
    async with async_session_factory() as session:
        try:
            messages = await MessageRepository(session).list_after(
                conversation_id=conversation_id,
                after_sequence=0,
                limit=100,
            )
            if not messages:
                logger.warning(
                    "support_ai_skipped",
                    extra={
                        "conversation_id": str(conversation_id),
                        "reason": "local_source_message_not_found",
                    },
                )
            else:
                logger.info(
                    "support_ai_initial_message_loaded",
                    extra={
                        "conversation_id": str(conversation_id),
                        "source_message_id": str(messages[-1].id),
                    },
                )
                await _process(session, conversation_id, messages[-1].id)
            await session.commit()
            logger.info("support_ai_initial_processing_finished", extra={"conversation_id": str(conversation_id)})
        except Exception:
            await session.rollback()
            logger.exception("support_ai_processing_failed", extra={"conversation_id": str(conversation_id)})


async def _process(session: AsyncSession, conversation_id: UUID, source_message_id: UUID) -> None:
    conversations = ConversationRepository(session)
    conversation = await conversations.find_by_id(conversation_id)
    source = await session.get(MessageModel, source_message_id)
    if conversation is None:
        logger.warning(
            "support_ai_skipped",
            extra={"conversation_id": str(conversation_id), "reason": "conversation_not_found"},
        )
        return
    if source is None:
        logger.warning(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "source_message_not_found",
            },
        )
        return
    if conversation.conversation_type != "support":
        logger.info(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "not_support_conversation",
            },
        )
        return
    if ConversationState(conversation.state) not in {ConversationState.ACTIVE, ConversationState.CLOSING}:
        logger.info(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "conversation_state_not_processable",
                "conversation_state": conversation.state,
            },
        )
        return
    case = await SupportCaseRepository(session).find_by_conversation(conversation_id)
    if case is None:
        logger.warning(
            "support_ai_skipped",
            extra={"conversation_id": str(conversation_id), "reason": "support_case_not_found"},
        )
        return
    if case.status in {"resolved", "closed"}:
        logger.info(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "case_not_open",
                "case_status": case.status,
            },
        )
        return
    participants = await conversations.participants_for(conversation_id)
    human_roles = sorted(
        {participant.role for participant in participants if participant.role in {"support_agent", "admin"}}
    )
    if case.assigned_to_user_id is not None:
        logger.info(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "case_assigned_to_human",
            },
        )
        return
    if human_roles:
        logger.info(
            "support_ai_skipped",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "reason": "human_participant_present",
                "human_participant_roles": human_roles,
            },
        )
        return

    client = diddisupport_read_client()
    logger.info(
        "support_ai_history_fetch_started",
        extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
    )
    remote_history = await client.list_user_visible_messages(case.external_case_id)
    history = [
        message.body
        for message in remote_history
        if message.author_type not in {"ai", "assistant", "diddicomms"}
    ]
    logger.info(
        "support_ai_history_fetched",
        extra={
            "conversation_id": str(conversation_id),
            "source_message_id": str(source_message_id),
            "remote_message_count": len(remote_history),
            "decision_history_count": len(history),
        },
    )
    try:
        logger.info(
            "support_ai_decision_started",
            extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
        )
        decision = await JevDecisionGate().classify(message=source.body, history=history[:-1])
        logger.info(
            "support_ai_decision_completed",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "route": decision.route,
                "category": decision.category,
                "confidence": decision.confidence,
                "human_required": decision.human_required,
            },
        )
    except DecisionGateError:
        logger.exception(
            "support_ai_decision_failed",
            extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
        )
        await _send_reply(session, case.external_case_id, conversation, source, FALLBACK_REPLY, "needs_human")
        return

    if decision.route != "support_allowed":
        body = (
            "I can help with Diddi support questions. Your message has been sent to our support team."
            if decision.route == "needs_human"
            else "I can only help with Diddi support questions. Please describe the issue you are experiencing."
        )
        await _send_reply(session, case.external_case_id, conversation, source, body, decision.category)
        return

    try:
        logger.info(
            "support_ai_completion_started",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "category": decision.category,
            },
        )
        completion = await OpenRouterClient().complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the DiddiComms support assistant. Answer only about the user's support request. "
                        "Do not act as a general chatbot. Ask concise clarifying questions when needed."
                    ),
                },
                *({"role": "user", "content": text} for text in history[-settings.decision_gate_history_messages :]),
            ],
            max_tokens=500,
        )
        body = completion.content
        category = decision.category
        logger.info(
            "support_ai_completion_completed",
            extra={
                "conversation_id": str(conversation_id),
                "source_message_id": str(source_message_id),
                "model": completion.model,
                "used_fallback": completion.used_fallback,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
            },
        )
    except AIProviderError:
        logger.exception(
            "support_ai_completion_failed",
            extra={"conversation_id": str(conversation_id), "source_message_id": str(source_message_id)},
        )
        body = FALLBACK_REPLY
        category = "needs_human"

    await _send_reply(session, case.external_case_id, conversation, source, body, category)


async def _send_reply(
    session: AsyncSession,
    case_id: UUID,
    conversation: ConversationModel,
    source: MessageModel,
    body: str,
    category: str,
) -> None:
    logger.info(
        "support_ai_message_write_started",
        extra={
            "conversation_id": str(conversation.id),
            "source_message_id": str(source.id),
            "case_id": str(case_id),
            "category": category,
        },
    )
    remote_message = await diddisupport_read_client().send_ai_message(
        case_id=case_id,
        body=body,
        idempotency_key=f"ai-reply-{source.id}",
    )
    logger.info(
        "support_ai_message_write_completed",
        extra={
            "conversation_id": str(conversation.id),
            "source_message_id": str(source.id),
            "case_id": str(case_id),
            "remote_message_id": str(remote_message.message_id),
            "author_type": remote_message.author_type,
        },
    )
    AuditRecorder(session).add(
        AuditEventDraft(
            actor_service="diddicomms",
            action="support.ai_message.created",
            target_type="support_message",
            target_id=str(remote_message.message_id),
            outcome="succeeded",
            idempotency_key=f"ai-reply-{source.id}",
            safe_metadata={
                "case_id": str(case_id),
                "conversation_id": str(conversation.id),
                "source_message_id": str(source.id),
                "category": category,
                "author_type": remote_message.author_type,
            },
        )
    )
    OutboxWriter(session).add(
        OutboxEventDraft(
            aggregate_type="support_case",
            aggregate_id=str(case_id),
            event_type="comms.support.ai_context_updated.v1",
            payload={
                "case_id": str(case_id),
                "conversation_id": str(conversation.id),
                "source_message_id": str(source.id),
                "ai_message_id": str(remote_message.message_id),
                "category": category,
            },
        )
    )
