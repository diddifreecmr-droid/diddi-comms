from uuid import UUID

from app_base.modules.conversations.infra.models import (
    ConversationModel,
    ConversationParticipantModel,
    MessageDeliveryModel,
)
from app_base.modules.conversations.infra.repositories import MessageDeliveryRepository, MessageRepository

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
SENDER_ID = UUID("22222222-2222-2222-2222-222222222222")
RECIPIENT_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)


def test_add_message_assigns_next_sequence_and_updates_conversation() -> None:
    conversation = ConversationModel(
        id=CONVERSATION_ID,
        conversation_type="task",
        owner_service="diddigo",
        task_type="ride",
        task_id=UUID("11111111-1111-1111-1111-111111111111"),
        state="active",
        task_version=1,
        last_sequence=4,
    )
    repo = MessageRepository(FakeSession())  # type: ignore[arg-type]

    message = repo.add_message(
        conversation=conversation,
        sender_user_id=SENDER_ID,
        client_message_id="client-1",
        body="I am here",
    )

    assert conversation.last_sequence == 5
    assert message.sequence == 5
    assert message.sender_user_id == SENDER_ID
    assert message.body == "I am here"


def test_delivery_repository_creates_recipient_receipt_and_advances_monotonically() -> None:
    session = FakeSession()
    repo = MessageDeliveryRepository(session)  # type: ignore[arg-type]
    message = MessageRepository(session).add_message(  # type: ignore[arg-type]
        conversation=ConversationModel(
            id=CONVERSATION_ID,
            conversation_type="task",
            owner_service="diddigo",
            task_type="ride",
            task_id=UUID("11111111-1111-1111-1111-111111111111"),
            state="active",
            task_version=1,
            last_sequence=0,
        ),
        sender_user_id=SENDER_ID,
        client_message_id="client-2",
        body="On my way",
    )
    participants = [
        ConversationParticipantModel(
            id=UUID("aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa"),
            conversation_id=CONVERSATION_ID,
            user_id=SENDER_ID,
            role="passenger",
        ),
        ConversationParticipantModel(
            id=UUID("bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb"),
            conversation_id=CONVERSATION_ID,
            user_id=RECIPIENT_ID,
            role="driver",
        ),
    ]

    deliveries = repo.add_recipients(message=message, participants=participants)

    assert len(deliveries) == 1
    assert deliveries[0].status == "accepted"
    assert repo.advance(deliveries[0], status="read") is True
    assert deliveries[0].delivered_at is not None
    assert deliveries[0].read_at is not None
    assert repo.advance(deliveries[0], status="delivered") is False
    assert MessageDeliveryRepository._aggregate_status(["read", "delivered"]) == "delivered"
    assert MessageDeliveryRepository._aggregate_status(["read", "read"]) == "read"


def test_delivery_model_has_read_timestamp() -> None:
    delivery = MessageDeliveryModel(
        id=UUID("cccccccc-3333-3333-3333-cccccccccccc"),
        message_id=UUID("dddddddd-4444-4444-4444-dddddddddddd"),
        participant_id=UUID("eeeeeeee-5555-5555-5555-eeeeeeeeeeee"),
        channel="realtime",
        status="accepted",
    )
    assert delivery.read_at is None
