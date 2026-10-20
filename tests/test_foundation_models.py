import app_base.models  # noqa: F401
from app_base.core.database import Base


def test_foundation_models_are_registered() -> None:
    assert "audit_events" in Base.metadata.tables
    assert "conversations" in Base.metadata.tables
    assert "conversation_participants" in Base.metadata.tables
    assert "messages" in Base.metadata.tables
    assert "message_deliveries" in Base.metadata.tables
    assert "support_cases" in Base.metadata.tables
    assert "call_attempts" in Base.metadata.tables
    assert "outbox_events" in Base.metadata.tables
    assert "processed_events" in Base.metadata.tables


def test_conversations_are_keyed_by_external_task_reference() -> None:
    table = Base.metadata.tables["conversations"]
    unique_names = {constraint.name for constraint in table.constraints}

    assert "uq_conversation_task_reference" in unique_names
    assert {"owner_service", "task_type", "task_id"}.issubset(table.columns.keys())


def test_messages_have_sequence_and_client_idempotency_constraints() -> None:
    table = Base.metadata.tables["messages"]
    unique_names = {constraint.name for constraint in table.constraints}

    assert "uq_messages_conversation_sequence" in unique_names
    assert "uq_messages_sender_client_message" in unique_names


def test_support_cases_link_to_support_conversation_and_optional_task() -> None:
    table = Base.metadata.tables["support_cases"]

    assert {"conversation_id", "requester_user_id", "owner_service", "task_type", "task_id"}.issubset(
        table.columns.keys()
    )
    assert table.columns["conversation_id"].unique
