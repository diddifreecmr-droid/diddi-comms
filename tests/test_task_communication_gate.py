from uuid import UUID

import pytest

from app_base.modules.context.domain import CommunicationContext, TaskReference
from app_base.modules.conversations.application import CommunicationGateRequest, TaskCommunicationGate
from app_base.modules.conversations.domain import CommunicationAction

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DRIVER_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTSIDER_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeResolver:
    def __init__(self, context: CommunicationContext) -> None:
        self.context = context
        self.calls: list[tuple[str, UUID]] = []

    async def get_task(self, task_type: str, task_id: UUID) -> CommunicationContext:
        self.calls.append((task_type, task_id))
        return self.context


@pytest.mark.asyncio
async def test_gate_resolves_owner_task_before_authorizing_action() -> None:
    resolver = FakeResolver(_context())
    gate = TaskCommunicationGate(resolver_factory=lambda owner: resolver)
    task = TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID)

    decision = await gate.decide(
        CommunicationGateRequest(
            task=task,
            action=CommunicationAction.CALL,
            actor_user_id=PASSENGER_ID,
            target_user_id=DRIVER_ID,
        )
    )

    assert decision.allowed is True
    assert resolver.calls == [("ride", TASK_ID)]


@pytest.mark.asyncio
async def test_gate_denies_when_resolved_task_participants_do_not_include_actor() -> None:
    resolver = FakeResolver(_context())
    gate = TaskCommunicationGate(resolver_factory=lambda owner: resolver)

    decision = await gate.decide(
        CommunicationGateRequest(
            task=TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID),
            action=CommunicationAction.MESSAGE,
            actor_user_id=OUTSIDER_ID,
            target_user_id=DRIVER_ID,
        )
    )

    assert decision.allowed is False
    assert decision.reason_code == "ACTOR_NOT_TASK_PARTICIPANT"


def _context() -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
            "state": "driver_assigned",
            "version": 12,
            "participants": [
                {"user_id": str(PASSENGER_ID), "role": "passenger", "phone_e164": "+237600000001"},
                {"user_id": str(DRIVER_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": True,
            "calling_allowed": True,
            "closes_at": None,
        }
    )

