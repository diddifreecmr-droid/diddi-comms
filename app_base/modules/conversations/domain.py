from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from app_base.modules.context.domain import CommunicationContext, CommunicationParticipant, TaskReference


class ConversationState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    SUSPENDED = "suspended"


class CommunicationAction(StrEnum):
    OPEN_CONVERSATION = "open_conversation"
    MESSAGE = "message"
    CALL = "call"
    READ_HISTORY = "read_history"


@dataclass(frozen=True)
class ConversationAccessSnapshot:
    task: TaskReference
    state: ConversationState
    closes_at: datetime | None


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason_code: str = "ALLOWED"

    @classmethod
    def allow(cls) -> AccessDecision:
        return cls(True)

    @classmethod
    def deny(cls, reason_code: str) -> AccessDecision:
        return cls(False, reason_code)


class ConversationAccessPolicy:
    writable_states = {ConversationState.ACTIVE, ConversationState.CLOSING}
    readable_states = {
        ConversationState.ACTIVE,
        ConversationState.CLOSING,
        ConversationState.CLOSED,
        ConversationState.SUSPENDED,
    }
    terminal_task_states = {
        "canceled",
        "cancelled",
        "closed",
        "completed",
        "done",
        "expired",
        "finished",
        "rejected",
        "terminated",
    }

    def decide(
        self,
        *,
        action: CommunicationAction,
        actor_user_id: UUID,
        context: CommunicationContext,
        conversation: ConversationAccessSnapshot | None = None,
        target_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AccessDecision:
        current_time = _ensure_aware(now or datetime.now(UTC))

        if conversation is not None:
            task_decision = self._task_matches(conversation, context)
            if not task_decision.allowed:
                return task_decision
            state_decision = self._state_allows_action(conversation.state, action)
            if not state_decision.allowed:
                return state_decision
            expiry_decision = self._time_allows_action(conversation.closes_at, action, current_time)
            if not expiry_decision.allowed:
                return expiry_decision

        actor = _participant_for(context, actor_user_id)
        if actor is None:
            return AccessDecision.deny("ACTOR_NOT_TASK_PARTICIPANT")

        if target_user_id is not None:
            target = _participant_for(context, target_user_id)
            if target is None:
                return AccessDecision.deny("TARGET_NOT_TASK_PARTICIPANT")
            if target.user_id == actor.user_id:
                return AccessDecision.deny("TARGET_SAME_AS_ACTOR")

        if action == CommunicationAction.OPEN_CONVERSATION and not (
            context.messaging_allowed or context.calling_allowed
        ):
            return AccessDecision.deny("COMMUNICATION_NOT_ALLOWED_BY_OWNER")
        if action == CommunicationAction.MESSAGE and not context.messaging_allowed:
            return AccessDecision.deny("MESSAGING_NOT_ALLOWED_BY_OWNER")
        if action == CommunicationAction.CALL and not context.calling_allowed:
            return AccessDecision.deny("CALLING_NOT_ALLOWED_BY_OWNER")

        terminal_decision = self._terminal_state_allows_action(context, action)
        if not terminal_decision.allowed:
            return terminal_decision

        if (
            action != CommunicationAction.READ_HISTORY
            and context.closes_at is not None
            and current_time >= _ensure_aware(context.closes_at)
        ):
            return AccessDecision.deny("TASK_COMMUNICATION_WINDOW_CLOSED")

        return AccessDecision.allow()

    def _task_matches(
        self,
        conversation: ConversationAccessSnapshot,
        context: CommunicationContext,
    ) -> AccessDecision:
        if conversation.task != context.task:
            return AccessDecision.deny("TASK_REFERENCE_MISMATCH")
        return AccessDecision.allow()

    def _state_allows_action(
        self,
        state: ConversationState,
        action: CommunicationAction,
    ) -> AccessDecision:
        allowed_states = self.readable_states if action == CommunicationAction.READ_HISTORY else self.writable_states
        if state not in allowed_states:
            return AccessDecision.deny("CONVERSATION_STATE_FORBIDS_ACTION")
        return AccessDecision.allow()

    def _time_allows_action(
        self,
        closes_at: datetime | None,
        action: CommunicationAction,
        now: datetime,
    ) -> AccessDecision:
        if action == CommunicationAction.READ_HISTORY:
            return AccessDecision.allow()
        if closes_at is not None and now >= _ensure_aware(closes_at):
            return AccessDecision.deny("CONVERSATION_WINDOW_CLOSED")
        return AccessDecision.allow()

    def _terminal_state_allows_action(
        self,
        context: CommunicationContext,
        action: CommunicationAction,
    ) -> AccessDecision:
        if action == CommunicationAction.READ_HISTORY:
            return AccessDecision.allow()
        normalized_state = context.state.strip().lower().replace("-", "_")
        if normalized_state not in self.terminal_task_states:
            return AccessDecision.allow()
        if context.closes_at is None:
            return AccessDecision.deny("TASK_TERMINAL_STATE_REQUIRES_COMMUNICATION_WINDOW")
        return AccessDecision.allow()


def _participant_for(context: CommunicationContext, user_id: UUID) -> CommunicationParticipant | None:
    return next((participant for participant in context.participants if participant.user_id == user_id), None)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
