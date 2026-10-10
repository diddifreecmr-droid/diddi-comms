# DiddiComms MVP Sprint Plan

**Status:** Draft execution plan  
**Source plan:** `docs/IMPLEMENTATION_PLAN_PERSONAS_JOURNEYS_SPECS.md`  
**Architecture:** `DIDDICOMMS_MVP_ARCHITECTURE.md`

This sprint plan assumes one MVP vertical slice starts with DiddiGo, while the
DiddiComms core remains generic: conversations are tied to `user_id`s and an
external task reference, not to hard-coded product modules.

## Sprint 0: Foundation Lock

Goal: finish the service foundation so feature work has stable contracts,
storage, and safety primitives.

Deliverables:

- Finalize Phase 0 repository structure.
- Finalize `.env.example`, Docker Compose, README, and local boot commands.
- Confirm generic owner resolver config with `OWNER_SERVICE_RESOLVERS_JSON`.
- Confirm service-token scopes:
  - `<owner>:comms-task:read`
  - future `<owner>:comms-task:write`
- Confirm support capability draft: `diddicomms/support_agent`.
- Add/verify Alembic migrations for:
  - audit
  - outbox
  - processed events
  - conversations
  - conversation participants
- Keep access policy and task communication gate covered by unit tests.

Acceptance criteria:

- `pytest`, `ruff`, and `git diff --check` pass.
- DiddiComms has no code-level mapping such as `ride -> DiddiGo`.
- A policy test proves that only same-task participants can message/call.
- A policy test proves closed communication windows block writes/calls but not
  retained history reads.

Dependencies:

- FreeID service-token issuance contract remains available.
- Team confirms support-agent capability name.

## Sprint 1: DiddiGo Resolver Contract

Status: started. Initial DiddiGo internal resolver endpoint and unit tests have
been added in the `diddi-go` service.

Goal: implement the first owner service resolver in DiddiGo and prove the
cross-service contract.

Deliverables:

- Add DiddiGo internal endpoint:
  `GET /internal/v1/comms/tasks/{task_type}/{task_id}`.
- Protect endpoint with DiddiFreeID service token:
  - audience: `diddigo`
  - scope: `diddigo:comms-task:read`
  - subject: `service:diddicomms`
- Return task projection:
  - task reference
  - state
  - version
  - participants by FreeID `user_id`
  - participant roles
  - `messaging_allowed`
  - `calling_allowed`
  - `closes_at`
  - `phone_e164` for MVP direct-call flow
- Add DiddiGo tests for accepted ride, completed ride, cancelled ride,
  unauthorized service token, and unsupported task type.
- Add DiddiComms contract test using DiddiGo-shaped payload.

Implemented so far:

- `GET /internal/v1/comms/tasks/{task_type}/{task_id}` route.
- Service-token guard for `service:diddicomms` with
  `diddigo:comms-task:read`.
- Ride projection service for passenger/driver participants.
- 48-hour post-terminal ride communication window.
- Unit tests for active ride, expired completed ride, unsupported task type,
  route payload, and missing service auth.

Acceptance criteria:

- DiddiComms can resolve a DiddiGo ride task through the generic resolver.
- DiddiGo rejects missing/wrong service tokens.
- DiddiGo never exposes more than the communication projection.
- DiddiComms rejects a resolver response whose task reference does not match
  the requested task.

Dependencies:

- DiddiGo has canonical FreeID `user_id`s for passenger and driver.
- DiddiGo can expose participant phone numbers for MVP external calls.

## Sprint 2: Ensure Task Conversation

Status: started. The DiddiComms API endpoint and service path are implemented
with unit tests.

Goal: create or return one durable conversation for an eligible task.

Deliverables:

- API:
  `POST /comms/v1/tasks/{owner_service}/{task_type}/{task_id}/conversation`.
- User JWT verification through FreeID JWKS.
- Resolver call through configured owner service.
- Access gate check for caller participation.
- Conversation repository:
  - find by task reference
  - create task conversation
  - store participants by `user_id` and role
  - do not store phone numbers
- Audit event:
  `conversation.opened` or `conversation.reused`.
- Outbox event:
  `comms.conversation.opened` when newly created.
- API responses for:
  - created conversation
  - existing conversation
  - forbidden non-participant
  - resolver unavailable
  - communication not allowed

Implemented so far:

- Public ensure conversation route.
- FreeID user-token dependency skeleton.
- Resolver-backed ensure service.
- Participant policy gate for `open_conversation`.
- Conversation create/reuse repository path.
- Audit events for opened, reused, and denied opens.
- Outbox event `comms.conversation.opened`.
- Unit tests for service create/reuse/deny and route success/auth-required.

Acceptance criteria:

- Repeated ensure requests return the same conversation.
- Non-participant user cannot create/discover conversation.
- Conversation is uniquely keyed by `(owner_service, task_type, task_id)`.
- Participant rows contain user IDs and roles only.
- Phone numbers are not persisted.

Dependencies:

- Sprint 1 DiddiGo resolver endpoint.

## Sprint 3: Durable Messages

Status: started. Message persistence, send endpoint, incremental read endpoint,
audit, and outbox path have been added in DiddiComms.

Goal: allow same-task participants to send and read durable text messages.

Deliverables:

- Migration for:
  - `messages`
  - `message_deliveries`
- Message repository:
  - create message with monotonic sequence
  - enforce `client_message_id` idempotency
  - list after sequence
- APIs:
  - `POST /comms/v1/conversations/{conversation_id}/messages`
  - `GET /comms/v1/conversations/{conversation_id}/messages?after_seq=`
  - `POST /comms/v1/conversations/{conversation_id}/read`
- Access policy revalidation before message writes.
- Audit event:
  `message.created` and denied attempts.
- Outbox event:
  `comms.message.created`.
- Basic content limits:
  - max length
  - non-empty text
  - text only for MVP

Implemented so far:

- `messages` and `message_deliveries` migration and SQLAlchemy models.
- Message repository with monotonic sequence assignment.
- Idempotency lookup by `(sender_user_id, client_message_id)`.
- `POST /comms/v1/conversations/{conversation_id}/messages`.
- `GET /comms/v1/conversations/{conversation_id}/messages?after_seq=`.
- Message send service with owner resolver revalidation and policy gate.
- Audit event `message.created` and denied write audit path.
- Outbox event `comms.message.created` without message body.
- Unit tests for repository, service, side-channel body exclusion, and route.

Acceptance criteria:

- Participant can send message while task window is open.
- Outsider cannot send or read.
- Same `client_message_id` returns the original message.
- Sequence is monotonically increasing within a conversation.
- Messages survive process restart.
- Closed windows block writes but still allow retained reads.

Dependencies:

- Sprint 2 conversation creation.

## Sprint 4: Outbox Dispatcher and Redis Streams

Goal: publish durable domain events from Postgres outbox to Redis Streams.

Deliverables:

- Outbox dispatcher worker.
- Redis `XADD` publisher to `diddicomms.events`.
- Published entry ID stored on outbox row.
- Retry scheduling with bounded backoff.
- Poison event handling to `diddicomms.events.dlq`.
- Worker metrics:
  - unpublished count
  - oldest unpublished age
  - publish attempts
  - terminal failures
- Idempotency guard for duplicate publication.
- Operational command or function to replay DLQ entries.

Acceptance criteria:

- Outbox event is eventually published to Redis.
- Duplicate worker run does not create duplicate side effects in consumers.
- Redis outage leaves events unpublished, not lost.
- DLQ receives poison events after bounded retries.

Dependencies:

- Sprint 3 outbox-producing message flow.

## Sprint 5: Realtime Delivery and Sync

Goal: deliver message events live when possible and repair missed delivery with
HTTP sync.

Deliverables:

- WebSocket endpoint:
  `GET /comms/v1/ws`.
- WebSocket authentication with user JWT.
- User connection registry.
- Subscribe user to their conversations.
- Realtime consumer group:
  `diddicomms-realtime`.
- Server events:
  - `message.created`
  - `conversation.read_cursor_changed`
  - `conversation.state_changed`
- Reconnect guidance:
  client resumes using `after_seq`.
- Delivery attempt records for realtime channel.

Acceptance criteria:

- Online participant receives `message.created`.
- If WebSocket is missed, HTTP sync returns the message.
- User cannot subscribe to another user's conversation.
- Multiple devices for same user can receive events.

Dependencies:

- Sprint 4 Redis Streams.

## Sprint 6: Push Notification Jobs

Goal: create offline notification jobs without making push delivery the source
of truth.

Deliverables:

- Push consumer group:
  `diddicomms-push`.
- Device-token abstraction or integration point with existing notification
  module.
- Privacy-safe notification payload:
  - no phone numbers
  - no excessive message body exposure
  - conversation/task labels only when safe
- `message_deliveries` records for push attempts.
- Retry on provider failure.
- Metrics for push outcomes and latency.

Acceptance criteria:

- Offline participant receives push job.
- Push provider failure does not lose the message.
- No secrets or tokens in logs.
- Push payloads respect privacy rules.

Dependencies:

- Client/device-token source decision.
- Sprint 4 Redis Streams.

## Sprint 7: External Call MVP

Goal: implement logged external call handoff with strict revalidation.

Deliverables:

- Migration for `call_attempts`.
- API:
  `POST /comms/v1/conversations/{conversation_id}/call-attempts`.
- API:
  `POST /comms/v1/conversations/{conversation_id}/call-attempts/{attempt_id}/client-result`.
- Revalidate owner task before returning `tel:`.
- Access policy check:
  - actor participant
  - target participant
  - same task
  - calling allowed
  - window open
- Rate limits:
  - per conversation
  - per user
- Idempotency by `(actor_user_id, idempotency_key)`.
- Audit events:
  - call requested
  - call link issued
  - client result reported
  - call denied
- Outbox events:
  - `comms.call_attempt.recorded`
  - `comms.call_attempt.client_result_recorded`
- First-use privacy disclosure client contract.

Acceptance criteria:

- Call attempt is persisted before `tel:` action is returned.
- DiddiComms does not persist phone numbers.
- Expired/cancelled/reassigned tasks fail closed.
- DiddiComms does not claim connected/answered/missed/completed outcomes.
- Duplicate idempotency key returns same attempt.

Dependencies:

- Owner resolver returns `phone_e164` only for authorized participants.
- Product/client accepts direct-number privacy warning.

## Sprint 8: DiddiGo Client Integration

Goal: expose the MVP chat and call experience in the first product slice.

Deliverables:

- DiddiGo passenger chat entry point.
- DiddiGo driver chat entry point.
- Conversation creation on accepted ride.
- Chat message screen:
  - message list
  - send text
  - reconnect/sync
  - read state
- Call button:
  - first-use privacy warning
  - call attempt API
  - OS dialer handoff
  - client-result callback where possible
- Basic empty/error/offline states.

Acceptance criteria:

- Passenger and assigned driver can chat on active ride.
- Unassigned user cannot open chat.
- Completed ride follows configured grace period.
- Call button works only while calling is allowed.
- UX does not claim external call success.

Dependencies:

- Sprints 2, 3, 5, and 7.

## Sprint 9: Support Chat Foundation

Goal: support users can open customer-care chats independent of task chat.

Deliverables:

- Migration for `support_cases`.
- API:
  `POST /comms/v1/support/cases`.
- API:
  `GET /comms/v1/support/cases/{case_id}`.
- Link optional task reference.
- Verify linked task belongs to requester when provided.
- Case states:
  - open
  - queued
  - assigned
  - waiting_user
  - waiting_agent
  - resolved
  - closed
- Support conversation messages reuse durable message mechanics.
- Audit case open and linked task verification.

Acceptance criteria:

- User can open support chat with or without task reference.
- User cannot link a task they do not belong to.
- Support case appears in queue.
- Support chat is separate from task chat.

Dependencies:

- Sprint 3 durable messages.
- Resolver integration.

## Sprint 10: Agent Inbox and Assignment

Goal: support agents can work support cases safely.

Deliverables:

- FreeID capability check for support agents.
- DiddiAdmin support inbox integration or minimal admin UI.
- APIs:
  - list queue
  - assign
  - transfer
  - resolve
  - add resolution code
- Audit all agent actions.
- SLA timestamps:
  - first response due
  - first response at
  - resolution due
  - resolved at
- Support metrics.

Acceptance criteria:

- Agent without capability is rejected.
- Agent can claim and respond to a case.
- Assignment, transfer, and resolution are audited.
- Queue depth and SLA metrics are available.

Dependencies:

- Support-agent capability decision.
- DiddiAdmin integration path.

## Sprint 11: Audited Task Context Escalation

Goal: support can inspect or join task context only with explicit audited
permission.

Deliverables:

- API:
  `POST /comms/v1/support/cases/{case_id}/escalate-task-context`.
- Reason code required.
- Capability required.
- User-visible system event when support joins task chat.
- Audit events:
  - task context inspected
  - support joined task context
  - access denied
- Optional safe context snapshot view.

Acceptance criteria:

- No silent support join.
- Every privileged access is audited.
- Agent cannot access unrelated task conversation.
- User sees support joined when bridge mode is active.

Dependencies:

- Sprint 10 agent capability and support case workflow.

## Sprint 12: Observability and Runbooks

Goal: make the service operable before pilot.

Deliverables:

- Dashboards:
  - API health
  - message latency
  - resolver latency/errors
  - Redis/outbox lag
  - DLQ growth
  - support SLA
  - call attempts
- Alerts:
  - high 5xx
  - resolver failure spike
  - outbox oldest age
  - Redis pending age
  - DLQ non-empty
  - support SLA breach
- Runbooks:
  - Redis outage
  - owner resolver outage
  - DLQ replay
  - stuck outbox
  - privacy incident
  - service-token failure
- Log redaction tests.

Acceptance criteria:

- Incident operator can trace a message by request ID without seeing body.
- Metrics have no user IDs, phone numbers, message bodies, or task IDs as labels.
- Runbooks identify owner, symptoms, diagnosis, and rollback path.

Dependencies:

- Sprints 3-7 produce meaningful events and metrics.

## Sprint 13: Security, Abuse, and Retention

Goal: close privacy and authorization risks before pilot.

Deliverables:

- Broken object-level authorization tests.
- Token confusion tests:
  - service token rejected on user routes
  - user token rejected on internal service routes
- Replay/idempotency tests.
- Rate-limit bypass tests.
- Phone-number leakage tests.
- Message body log leakage tests.
- Retention jobs:
  - task messages
  - support cases
  - call attempts
  - operational logs policy documentation
- Abuse report endpoint hardening.

Acceptance criteria:

- Unauthorized user cannot discover, read, message, or call another task.
- Phone numbers are never persisted in DiddiComms.
- Logs/metrics/traces/audits contain no message bodies or phone numbers.
- Expired retention data can be deleted or anonymized according to policy.

Dependencies:

- Legal/operations confirm retention periods.

## Sprint 14: Pilot Readiness

Goal: prepare one controlled pilot slice.

Deliverables:

- Feature flags by owner service/task type/city.
- Pilot checklist.
- Seed data and smoke tests.
- End-to-end test:
  accepted ride -> chat -> realtime -> sync -> call attempt -> support case.
- Load test for expected pilot traffic.
- Backup restore test.
- Rollback plan.
- Support training notes.
- Privacy copy confirmed in app.

Acceptance criteria:

- Pilot slice can be enabled and disabled without redeploying.
- End-to-end smoke test passes in staging.
- On-call runbook is ready.
- Support team can handle first incidents.

Dependencies:

- Product chooses pilot city/context.
- Client apps include chat/call UI.

## Recommended Sprint Order

1. Sprint 0: Foundation Lock
2. Sprint 1: DiddiGo Resolver Contract
3. Sprint 2: Ensure Task Conversation
4. Sprint 3: Durable Messages
5. Sprint 4: Outbox Dispatcher and Redis Streams
6. Sprint 5: Realtime Delivery and Sync
7. Sprint 7: External Call MVP
8. Sprint 8: DiddiGo Client Integration
9. Sprint 6: Push Notification Jobs
10. Sprint 9: Support Chat Foundation
11. Sprint 10: Agent Inbox and Assignment
12. Sprint 11: Audited Task Context Escalation
13. Sprint 12: Observability and Runbooks
14. Sprint 13: Security, Abuse, and Retention
15. Sprint 14: Pilot Readiness

Push can move earlier if mobile readiness requires it. Support can also start
in parallel after durable messages are stable.

## Sprint Tracking Labels

Suggested labels:

- `comms-foundation`
- `comms-contract`
- `comms-task-chat`
- `comms-messages`
- `comms-realtime`
- `comms-call-mvp`
- `comms-support`
- `comms-observability`
- `comms-security`
- `comms-pilot`
