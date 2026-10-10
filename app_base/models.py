"""Import SQLAlchemy models so metadata is complete for Alembic and tests."""

from app_base.modules.audit.infra.models import AuditEventModel
from app_base.modules.conversations.infra.models import (
    ConversationModel,
    ConversationParticipantModel,
    MessageDeliveryModel,
    MessageModel,
)
from app_base.modules.events.infra.models import OutboxEventModel, ProcessedEventModel

__all__ = [
    "AuditEventModel",
    "ConversationModel",
    "ConversationParticipantModel",
    "MessageDeliveryModel",
    "MessageModel",
    "OutboxEventModel",
    "ProcessedEventModel",
]
