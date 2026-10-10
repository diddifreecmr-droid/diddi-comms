# DiddiComms Implementation Plan: Personas, Journeys, Specs

**Status:** Draft implementation plan  
**Service:** DiddiComms  
**Architecture reference:** `DIDDICOMMS_MVP_ARCHITECTURE.md`  
**Contract reference:** `docs/CONTEXT_RESOLVER_CONTRACT.md`

This plan starts from people and journeys, then turns those journeys into
implementation specs. The core design principle remains:

```text
DiddiComms owns communication.
Owner services own task truth.
Chats and calls are authorized by user_id + external task reference.
```

An external task reference is:

```text
owner_service + task_type + task_id
```

Examples:

- `diddigo + ride + <ride_id>`
- `diddisend + delivery + <delivery_id>`
- `diddifood + food_order + <order_id>`

DiddiComms must not hard-code what a ride, delivery, or order means.

## 1. Personas

### Passenger / Customer

They use DiddiGo, DiddiSend, or DiddiFood and need to contact the assigned
driver/courier when the task is active.

Needs:

- Ask where the driver/courier is.
- Send practical details such as gate, landmark, floor, substitution, or delay.
- Call when chat is too slow.
- Contact support if something feels wrong.
- See previous messages while the task is still relevant.

Risks:

- Phone number exposure in the MVP external-call flow.
- Harassment after a task ends.
- Confusion if messages fail or arrive late.
- Driver/courier contacts them outside the allowed window.

### Driver / Courier

They are assigned to a ride, delivery, or order and need low-friction contact
with the customer.

Needs:

- Ask for pickup/dropoff clarification.
- Send quick messages while moving.
- Call when urgent.
- Avoid typing while driving.
- Stop receiving messages after the task window closes.

Risks:

- Distraction while driving.
- Abuse from customers.
- Being contacted after work has ended.
- Operational blame for messages/calls that were not actually delivered.

### Support Agent

They work in DiddiAdmin and help users resolve task, payment, safety, and
delivery issues.

Needs:

- See support cases in queues.
- Open a user support chat.
- View task communication only when authorized and audited.
- Transfer, escalate, resolve, and add reason codes.
- Reconstruct what happened without exposing unnecessary private data.

Risks:

- Overbroad access to private chats.
- Silent support joining.
- Missing audit trail.
- SLA breaches due to lost queues/events.

### Operations / Pilotage

They monitor service health, abuse patterns, and support performance.

Needs:

- Aggregate reporting.
- Dashboards for API health, queue depth, event lag, and SLA.
- Safe audit search.
- DLQ visibility and replay tooling.

Risks:

- High-cardinality metrics.
- Message bodies or phone numbers leaking into logs.
- Unclear incident reconstruction.

### Owner Service

This is DiddiGo, DiddiSend, DiddiFood, or any future product module that owns a
business task.

Needs:

- Keep authority over task state and participants.
- Expose a narrow resolver contract.
- Avoid coupling its business tables directly to DiddiComms internals.
- Receive or emit task state changes when needed.

Risks:

- DiddiComms making assumptions about task states.
- Duplicate policy logic across services.
- Resolver latency blocking user actions.

## 2. Core Journeys

### Journey A: Customer Opens Task Chat

Scenario: A passenger opens chat with an assigned DiddiGo driver.

Flow:

1. Client asks DiddiComms to ensure a task conversation:
   `POST /comms/v1/tasks/{owner_service}/{task_type}/{task_id}/conversation`.
2. DiddiComms verifies the user token with FreeID JWKS.
3. DiddiComms calls the configured owner resolver:
   `GET /internal/v1/comms/tasks/{task_type}/{task_id}`.
4. Owner resolver returns task state, version, participants, permissions, and
   communication window.
5. DiddiComms checks that the caller `user_id` is a participant.
6. DiddiComms creates or returns one conversation keyed by:
   `(owner_service, task_type, task_id)`.
7. DiddiComms stores participants by `user_id` and role.
8. DiddiComms does not store phone numbers.

Acceptance:

- Non-participants get `403`.
- Repeated ensure requests return the same conversation.
- Resolver task reference must match the requested task reference.
- Logs contain request IDs, not message content or phone numbers.

### Journey B: Participant Sends Message

Scenario: Courier sends “I am at the gate.”

Flow:

1. Client sends `POST /conversations/{id}/messages`.
2. DiddiComms verifies user token.
3. DiddiComms loads conversation and participants.
4. DiddiComms revalidates the owner task projection.
5. `ConversationAccessPolicy` checks:
   caller is participant, conversation state allows writes, owner allows
   messaging, and communication window is still open.
6. DiddiComms writes message, audit event, and outbox event in one transaction.
7. Redis outbox dispatcher publishes `comms.message.created`.
8. Realtime and push workers notify participants.

Acceptance:

- Message gets a monotonic sequence.
- Duplicate `client_message_id` returns the original accepted message.
- If Redis is down but Postgres commit succeeds, message remains durable and
  dispatch waits in outbox.
- If owner resolver denies messaging, no message row is created.

### Journey C: Participant Reads Messages

Scenario: Passenger reconnects after losing network.

Flow:

1. Client calls `GET /conversations/{id}/messages?after_seq=12`.
2. DiddiComms verifies the user token.
3. DiddiComms checks the user is/was a conversation participant.
4. DiddiComms returns messages after the sequence cursor.
5. Client advances read cursor with `POST /conversations/{id}/read`.

Acceptance:

- Reads may continue during retention after the communication window closes.
- Writes and calls remain blocked after close.
- Cursor sync repairs missed WebSocket or push notifications.

### Journey D: External Call Handoff

Scenario: Driver taps call because pickup location is unclear.

Flow:

1. Client sends `POST /conversations/{id}/call-attempts`.
2. DiddiComms verifies user token.
3. DiddiComms loads conversation and target participant.
4. DiddiComms revalidates owner task projection in real time.
5. Policy checks:
   actor and target are on the same task, calling is allowed, and windows are
   still open.
6. DiddiComms applies rate limits.
7. DiddiComms writes call attempt, audit event, and outbox event.
8. DiddiComms returns `tel:+...` action from the resolver response.
9. Client opens OS dialer.
10. Client may later report `dialer_opened`, `dialer_failed`, or no result.

Acceptance:

- Call attempt is recorded before `tel:` is returned.
- Phone number is not stored in DiddiComms tables.
- DiddiComms never claims connected/answered/missed/completed.
- Repeated idempotency key returns same attempt.

### Journey E: Task Ends

Scenario: Food order is delivered.

Flow:

1. Owner service updates task state.
2. Owner service either emits an event or resolver starts returning closing
   policy.
3. DiddiComms updates conversation state to `closing` with `closes_at`.
4. Participants can still communicate until `closes_at`.
5. After `closes_at`, writes and calls are blocked.
6. History remains readable during retention.

Acceptance:

- Closing windows are configurable by owner/task type.
- Immediate cancellation before assignment can close communication immediately.
- Read history remains separate from live communication permission.

### Journey F: User Opens Support Chat

Scenario: Customer reports a missing delivery item.

Flow:

1. User opens support case, optionally with task reference.
2. DiddiComms verifies user token.
3. If linked to a task, DiddiComms verifies the user is associated with that
   task through the owner resolver.
4. Support conversation is created independently from task chat.
5. Case enters queue.
6. Agent claims or is assigned the case.
7. User and agent chat.

Acceptance:

- Support case can exist with or without task reference.
- Task support does not silently expose task chat.
- Agent assignment and resolution are audited.

### Journey G: Support Escalates Into Task Context

Scenario: Support needs to inspect or join a customer-driver chat.

Flow:

1. Agent requests audited task-context access.
2. DiddiComms verifies support capability.
3. DiddiComms records reason code.
4. DiddiComms either shows safe context snapshot or joins the task bridge,
   depending on permission.
5. User-visible system event says support joined or inspected.

Acceptance:

- No silent support joins.
- Every privileged access has audit row.
- Support cannot access task chats without capability and reason code.

## 3. Product Specs

### MVP Channels

In scope:

- Durable text chat.
- Message sync by sequence.
- Read cursor.
- External call handoff with logged attempts.
- Customer-care support chat.
- Support queue and assignment.
- Audit and observability.

Out of scope for MVP:

- In-app VoIP.
- Masked phone relay.
- Attachments.
- Voice notes.
- Group chat beyond explicit support escalation.
- Message edit/delete.
- Translation.
- AI support agent.

### Conversation States

Task conversations:

```text
pending -> active -> closing -> closed
             |          |
             +------> suspended
```

Rules:

- `active`: message and call allowed if owner also allows.
- `closing`: message and call allowed until `closes_at`.
- `closed`: read retained history only.
- `suspended`: no writes/calls; limited reads according to safety policy.

Support conversations:

```text
open -> queued -> assigned -> waiting_user/waiting_agent -> resolved -> closed
                    |                                      |
                    +----------------> escalated <---------+
```

### Permissions

For messages:

- Actor must be authenticated.
- Actor must be participant of conversation.
- Actor must be participant of owner task.
- Conversation state must allow writes.
- Owner resolver must return `messaging_allowed=true`.
- `now < conversation.closes_at`, when set.
- `now < resolver.closes_at`, when set.

For calls:

- Same as messages.
- Target user must be a participant of the same conversation and owner task.
- Owner resolver must return `calling_allowed=true`.
- Rate limit must pass.
- Call attempt must be persisted before phone action is returned.

For history reads:

- Actor must be authenticated.
- Actor must be a participant or authorized support/admin actor.
- Live communication window may be closed.
- Retention policy must still allow access.

### Privacy

MVP direct calls expose real phone numbers through the telephone network.

Required safeguards:

- First-use warning before call button is enabled.
- No phone numbers in DiddiComms durable storage.
- No phone numbers in logs, metrics, traces, audit metadata, or outbox payload.
- Phone number fetched just in time from owner resolver.
- Masked external calls become first post-MVP telephony upgrade.

## 4. Technical Specs

### Data Model

Already started:

- `conversations`
- `conversation_participants`
- `audit_events`
- `outbox_events`
- `processed_events`

Next migrations:

- `messages`
- `message_deliveries`
- `call_attempts`
- `support_cases`
- `support_assignments` or assignment fields on support cases
- `conversation_reports`

Conversation key:

```text
UNIQUE(owner_service, task_type, task_id)
```

Participant key:

```text
UNIQUE(conversation_id, user_id)
```

Message keys:

```text
UNIQUE(conversation_id, sequence)
UNIQUE(sender_user_id, client_message_id)
```

Call attempt key:

```text
UNIQUE(actor_user_id, idempotency_key)
```

### API Specs

Task chat:

```http
POST /comms/v1/tasks/{owner_service}/{task_type}/{task_id}/conversation
GET  /comms/v1/conversations
GET  /comms/v1/conversations/{conversation_id}
GET  /comms/v1/conversations/{conversation_id}/messages?after_seq=
POST /comms/v1/conversations/{conversation_id}/messages
POST /comms/v1/conversations/{conversation_id}/read
POST /comms/v1/conversations/{conversation_id}/call-attempts
POST /comms/v1/conversations/{conversation_id}/call-attempts/{attempt_id}/client-result
POST /comms/v1/conversations/{conversation_id}/report
```

Support:

```http
POST /comms/v1/support/cases
GET  /comms/v1/support/cases
POST /comms/v1/support/cases/{case_id}/assign
POST /comms/v1/support/cases/{case_id}/transfer
POST /comms/v1/support/cases/{case_id}/resolve
POST /comms/v1/support/cases/{case_id}/escalate-task-context
```

Realtime:

```http
GET /comms/v1/ws
```

Owner resolver:

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
```

### Event Specs

Stream:

```text
diddicomms.events
```

Initial events:

- `comms.conversation.opened`
- `comms.conversation.state_changed`
- `comms.message.created`
- `comms.message.read`
- `comms.call_attempt.recorded`
- `comms.call_attempt.client_result_recorded`
- `comms.support.case_opened`
- `comms.support.case_assigned`
- `comms.support.case_resolved`
- `comms.support.task_context_accessed`

Consumer groups:

- `diddicomms-realtime`
- `diddicomms-push`
- `diddicomms-support-sla`
- `diddicomms-analytics`

### Observability Specs

Metrics:

- HTTP latency/errors by route template.
- WebSocket connection count and disconnect reasons.
- Messages created by outcome.
- Message delivery latency by channel/outcome.
- Call attempts by owner service, task type, and outcome.
- Resolver latency/errors by owner service.
- Outbox unpublished count and oldest age.
- Redis pending count, oldest pending age, retry count, DLQ count.
- Support queue depth, first response time, resolution time, SLA breaches.

Logs:

- JSON.
- Include `request_id`, `trace_id`, route template, outcome, error code.
- Do not include message bodies, phone numbers, tokens, push credentials, full
  resolver responses, or raw headers.

Traces:

- Inbound HTTP.
- Outbound resolver calls.
- PostgreSQL.
- Redis.
- Worker spans.

## 5. Implementation Phases

### Phase 0: Foundation and Contracts

Status: in progress.

Build:

- FastAPI service foundation.
- Config and Docker Compose.
- Postgres and Redis readiness.
- Metrics endpoint.
- FreeID token verification helpers.
- Service-token client.
- Generic owner resolver client.
- Access policy and task communication gate.
- Foundation migrations.
- Conversation task-reference schema.

Exit criteria:

- Unit tests pass.
- Resolver contract documented.
- No code-level product coupling.
- DiddiComms can validate a task communication decision from resolver data.

### Phase 1: Durable Task Chat

Build:

- Ensure/get task conversation endpoint.
- Message schema and repository.
- Send message endpoint.
- Incremental message sync endpoint.
- Read cursor endpoint.
- Transactional audit + outbox for message creation.
- DiddiGo resolver endpoint as first owner implementation.
- Contract tests between DiddiComms and DiddiGo.

Exit criteria:

- Two participants on the same owner task can exchange messages.
- Non-participants cannot discover or message.
- Messages survive restart.
- Sequence-based sync repairs missed realtime events.

### Phase 2: Realtime and Push

Build:

- WebSocket authentication.
- Conversation subscription model.
- Redis outbox dispatcher.
- Redis realtime consumer.
- Push notification consumer.
- Delivery records.
- Reconnect/resync behavior.

Exit criteria:

- Online participant receives near-realtime event.
- Offline participant gets push job.
- Redis outage delays delivery but does not lose messages.
- Consumers are idempotent.

### Phase 3: External Call MVP

Build:

- Call attempt schema and repository.
- Call attempt endpoint.
- Channel-specific policy revalidation.
- Rate limits.
- First-use privacy disclosure flag or client contract.
- Client-result endpoint.
- Audit and outbox events.

Exit criteria:

- Call attempt is persisted before `tel:` action is returned.
- Phone number is never stored.
- Calls fail closed after task/window expiry.
- DiddiComms never claims call connection outcome.

### Phase 4: Customer Care

Build:

- Support case schema.
- User support chat.
- Support queue.
- Agent assignment and transfer.
- Resolution codes.
- SLA timers.
- DiddiAdmin support inbox integration.
- Audited task-context access.

Exit criteria:

- User can open support case.
- Agent can respond and resolve.
- Agent privileged access is capability-gated and audited.
- Support joins/inspection are visible and traceable.

### Phase 5: Hardening and Pilot

Build:

- Load tests.
- Resolver failure tests.
- Redis pending reclaim and DLQ replay.
- Log redaction tests.
- Security tests for broken object-level authorization.
- Dashboards and alerts.
- Retention/anonymization jobs.

Exit criteria:

- Pilot-ready runbook.
- Dashboards operational.
- Abuse and privacy failure cases tested.
- One city/product slice can be enabled by feature flag.

## 6. Open Decisions

1. Exact support-agent FreeID capability name. Draft:
   `diddicomms/support_agent`.
2. First support inbox location: DiddiAdmin or minimal DiddiComms UI.
3. Exact retention periods after legal review.
4. Push provider setup per client platform.
5. Pilot country/city and whether privacy copy must vary by country.
6. Whether owner services emit task state events in Phase 1 or DiddiComms
   relies on resolver revalidation until Phase 2.

