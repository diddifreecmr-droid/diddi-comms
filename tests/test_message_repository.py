from uuid import UUID

from app_base.modules.conversations.infra.models import ConversationModel
from app_base.modules.conversations.infra.repositories import MessageRepository

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
SENDER_ID = UUID("22222222-2222-2222-2222-222222222222")


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
