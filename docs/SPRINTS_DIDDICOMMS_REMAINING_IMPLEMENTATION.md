# DiddiComms Remaining Implementation Sprints

**Status:** implementation in progress  
**Created:** 2026-10-20  
**Owner:** DiddiComms  
**Contract baseline:** `manifests/diddicomms.v1.json`  
**Open decisions:** `docs/diddiconnect/open-questions.md`

## Implementation Checkpoint

Implemented in DiddiComms on 2026-10-20:

- authoritative DiddiSupport case creation, initial/user message forwarding,
  visible-history reads, projection metadata, reconciliation dry-run, and
  deprecated local agent mutations;
- delegated DiddiAdmin service/operator authentication and task-chat routes;
- per-recipient delivery records, monotonic delivered/read acknowledgements,
  aggregate versions, and realtime delivery events;
- WebSocket heartbeat, idle timeout, connection limits, and trimmed-cursor
  resynchronization;
- Support consumer group runtime, SQL inbox deduplication, stale-version
  rejection, pending reclaim, bounded retry, privacy-safe DLQ, and replay
  dry-run;
- Redis rate limits for messages, calls, and Support-case creation;
- conversation mute and message-abuse reporting controls;
- JSON logging redaction, OTLP tracing hooks, auth/rate-limit counters, and
  Redis-shared worker metrics for outbox age/backlog, retries, DLQ, consumer
  pending entries, lag, and worker health;
- worker recovery with bounded exponential backoff and a live
  PostgreSQL/Redis consumer integration test covering commit-before-ACK;
- strict service-token type/subject validation, UUID-bound Backoffice request
  IDs, replay-time call authorization, and private-resource enumeration
  resistance tests;
- read-only operational readiness command and deployment, dependency-failure,
  backup/restore, replay, and rollback runbook.

Still dependent on ecosystem or staging work:

- DiddiSupport must publish its approved Redis event stream;
- DiddiAdmin must migrate its adapter and run shared deployment tests;
- DiddiSend and DiddiFood must expose and certify task-context providers;
- FreeID must provision production clients, audiences, and scopes;
- Platform/Security must provide OTLP infrastructure, dashboards, alerts,
  load/soak/chaos runs, backup/restore evidence, and final review;
- retention/deletion policy approval and pilot sign-off remain outstanding.

## Program Goal

Move DiddiComms from a locally working ride-messaging implementation to a
production-ready ecosystem service with one Support source of truth, secure
Backoffice access, accurate delivery state, reliable event consumption,
operational controls, and certified Go, Send, and Food integrations.

Each sprint is planned for 10 working days. Team capacity determines whether
independent tickets run in parallel, but sprint exit gates remain mandatory.

## Current Baseline

Already implemented:

- durable task conversations and text messages;
- owner-resolver participant authorization;
- DiddiGo task context;
- read cursors;
- external call attempts and device-dialer handoff;
- audits and transactional outbox;
- Redis Streams publisher, retry, and DLQ;
- authenticated per-conversation WebSocket;
- DiddiSupport client for case creation, context, and messages;
- PostgreSQL and Redis readiness probes;
- API and worker Compose services;
- versioned DiddiConnect manifests and integration contracts.

Not complete:

- Support source-of-truth migration;
- Admin delegated-operator access;
- delivery acknowledgement and receipts;
- durable Support event consumption;
- realtime production hardening;
- complete retry and idempotency rules;
- rate limits and abuse controls;
- platform dashboards, alerts, production runbooks, and staging certification;
- Send and Food owner resolvers.

## Sprint 1: Support Source Of Truth

**Goal:** make DiddiSupport authoritative while preserving the existing
`/comms/v1/support` client contract.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-201 | Add a stable external Support case reference and projection status to the local compatibility model | 3 | Comms |
| COMMS-202 | Forward the initial user message to DiddiSupport using a stable idempotency key | 5 | Comms |
| COMMS-203 | Replace local agent-message writes with the DiddiSupport internal message route | 5 | Comms + Support |
| COMMS-204 | Proxy assignment, priority, resolution, and context operations to DiddiSupport | 8 | Comms + Support |
| COMMS-205 | Read user-visible Support messages from DiddiSupport and exclude internal notes | 5 | Comms |
| COMMS-206 | Add a reconciliation command that reports local/remote divergence without silently merging | 5 | Comms |
| COMMS-207 | Add migration, rollback, idempotency, timeout, and malformed-response tests | 5 | Comms |
| COMMS-208 | Mark local Support mutation paths deprecated after parity | 2 | Comms |

Required behavior:

- DiddiSupport case creation commits before DiddiComms exposes success.
- A timeout recovers the original remote operation using the same key.
- DiddiComms never creates a shadow case when Support is unavailable.
- The local projection may cache IDs and user-visible transport state, but it
  cannot independently decide assignment, priority, or resolution.
- Initial and subsequent user messages are persisted by DiddiSupport.
- Internal Support notes never enter DiddiComms storage or events.

Exit criteria:

- One authoritative Support case ID exists across both services.
- Every compatibility mutation has a DiddiSupport-backed implementation.
- Duplicate requests produce one remote result.
- Failure and reconciliation tests pass.
- A rollback plan preserves access to existing local cases.

Dependencies:

- DiddiSupport confirms its frozen internal routes and error mappings.
- Migration policy decision `DCQ-03` is approved.

## Sprint 2: Secure DiddiAdmin Backoffice Boundary

**Goal:** provide service-authenticated Backoffice routes with explicit human
operator attribution.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-221 | Add a reusable delegated-operator authentication dependency | 5 | Comms + FreeID |
| COMMS-222 | Add Backoffice ensure-conversation route | 3 | Comms |
| COMMS-223 | Add Backoffice message-history route | 3 | Comms |
| COMMS-224 | Add Backoffice task-message route with non-customer author identity | 5 | Comms |
| COMMS-225 | Enforce `diddicomms:backoffice:read` and `diddicomms:backoffice:write` | 3 | Comms + FreeID |
| COMMS-226 | Record service subject, client ID, agent ID, reason, case ID, and request ID in audit | 5 | Comms |
| COMMS-227 | Add permission, task-access, and Support-case justification policy | 5 | Comms + Admin |
| COMMS-228 | Replace DiddiAdmin's human-route adapter calls with Backoffice routes | 5 | Admin |
| COMMS-229 | Add real ASGI consumer/provider contract tests | 5 | Comms + Admin |

Target request boundary:

```http
Authorization: Bearer <diddiadmin-service-jwt>
X-Client-ID: <signed-client-id>
X-Request-ID: <uuid>
X-Backoffice-Actor: <agent-freeid-uuid>
X-Backoffice-Reason: <case-id-or-reason-code>
Idempotency-Key: <required-for-mutations>
```

Exit criteria:

- Browser requests cannot inject trusted service or operator headers.
- DiddiComms verifies `service:diddiadmin`, audience, client ID, and scope.
- Every successful or denied operation identifies both service and operator.
- DiddiAdmin no longer calls user-only DiddiComms routes with a service token.
- Cross-service tests cover missing actor, invalid actor, wrong scope, wrong
  service, unauthorized task, replay, conflict, and dependency failure.

Dependencies:

- FreeID decisions `DCQ-01` and `DCQ-02`.
- DiddiAdmin permission mapping and case-justification policy.

## Sprint 3: Message Delivery And Realtime Hardening

**Goal:** make delivery state accurate and realtime reconnect behavior suitable
for mobile production use.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-241 | Implement message delivery state transitions instead of constant `pending` | 5 | Comms |
| COMMS-242 | Add idempotent delivery acknowledgement endpoint | 3 | Comms |
| COMMS-243 | Emit versioned delivered and read events | 3 | Comms |
| COMMS-244 | Define multi-device read-cursor and delivery semantics | 3 | Comms + Mobile |
| COMMS-245 | Add WebSocket heartbeat and idle timeout | 3 | Comms |
| COMMS-246 | Handle trimmed Redis cursors with an explicit REST resync response | 5 | Comms |
| COMMS-247 | Add per-user and per-conversation connection limits | 3 | Comms |
| COMMS-248 | Add reconnect, duplicate, out-of-order, multi-device, and slow-client tests | 8 | Comms |
| COMMS-249 | Run WebSocket concurrency and soak tests | 5 | Comms + Platform |

State target:

```text
accepted -> delivered -> read
accepted -> delivery_failed
```

The database remains authoritative. WebSocket events are hints; clients use
the incremental REST message route to resynchronize after reconnect or cursor
expiry.

Exit criteria:

- API responses return stored delivery state.
- Duplicate acknowledgements are harmless.
- Read state never moves backward.
- A trimmed or unknown stream cursor produces a documented resync path.
- Heartbeat, idle timeout, and connection limits are configurable.
- Load tests meet the agreed pilot concurrency and latency targets.

Dependencies:

- Mobile teams confirm acknowledgement and multi-device behavior.
- Platform approves Redis retention policy from `DCQ-11`.

## Sprint 4: Durable Event Consumption And Recovery

**Goal:** consume Support and future owner events with at-least-once safety and
operational recovery.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-261 | Implement Redis consumer-group runtime and inbox deduplication | 8 | Comms |
| COMMS-262 | Consume `support.case.message.created.v1` | 5 | Comms + Support |
| COMMS-263 | Consume Support case update and resolution events | 5 | Comms + Support |
| COMMS-264 | Add pending-entry reclaim after worker failure | 5 | Comms |
| COMMS-265 | Add bounded retry, poison classification, and consumer DLQ | 5 | Comms |
| COMMS-266 | Add replay command with dry-run and event-ID filters | 5 | Comms + Platform |
| COMMS-267 | Add stream retention and trimming configuration | 3 | Platform |
| COMMS-268 | Add duplicate, stale, out-of-order, crash, reclaim, and replay tests | 8 | Comms |
| COMMS-269 | Add `aggregate_version` in the next event-envelope revision | 3 | Comms |

Required semantics:

- Consumers acknowledge only after local commit.
- `event_id` deduplicates repeated delivery.
- `aggregate_version` rejects stale updates once the revised envelope is
  adopted.
- Poison events preserve safe failure metadata without message bodies or
  private data.
- Replay never bypasses normal idempotency checks.

Exit criteria:

- Restarting a consumer loses no committed event.
- Duplicate events produce no duplicate user-visible action.
- Abandoned pending entries are reclaimed.
- DLQ events can be inspected and safely replayed.
- Support polling remains a fallback only during controlled migration.

Dependencies:

- DiddiSupport publishes the approved versioned events.
- Platform provisions streams, groups, retention, alerts, and replay access.

## Sprint 5: Security, Abuse Controls, And Observability

**Goal:** close production security and operational visibility gaps.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-281 | Add per-user, per-conversation, per-task, and per-IP rate limits | 5 | Comms |
| COMMS-282 | Add call-attempt throttling and suspicious-contact audit signals | 3 | Comms |
| COMMS-283 | Add message abuse report and conversation mute controls | 5 | Comms + Trust |
| COMMS-284 | Add automated log, metric, trace, audit, and event redaction tests | 5 | Comms + Security |
| COMMS-285 | Instrument resolver, Support, Redis, DB, and WebSocket traces | 5 | Comms + Platform |
| COMMS-286 | Add outbox age, retry, DLQ, consumer lag, reconnect, and denial metrics | 5 | Comms |
| COMMS-287 | Add dashboards and actionable alerts | 5 | Platform |
| COMMS-288 | Add token-confusion, IDOR, replay, privilege-escalation, and enumeration tests | 8 | Security |
| COMMS-289 | Complete retention, deletion, and audit-access policies | 3 | Comms + Legal/Security |

Exit criteria:

- Limits return stable `429` errors with safe retry guidance.
- No message body, phone number, token, signed URL, or attachment content is
  present in ordinary logs, metrics, traces, audits, or generic event metadata.
- Alerts exist for dependency failure, outbox age, retry exhaustion, DLQ
  growth, consumer lag, WebSocket saturation, and auth-denial spikes.
- A security review has no unresolved release-blocking finding.

Dependencies:

- Trust and Safety define abuse categories and response ownership.
- Platform provides trace, metric, log, and alert backends.

## Sprint 6: Ecosystem Integration And Pilot Certification

**Goal:** certify the complete MVP across FreeID, Go, Send, Food, Support,
Admin, Redis, PostgreSQL, and deployed clients.

| ID | Work item | Points | Owner |
|---|---|---:|---|
| COMMS-301 | Provision and verify final FreeID clients, audiences, and scopes | 3 | FreeID + Platform |
| COMMS-302 | Certify DiddiGo provider and DiddiComms consumer fixtures | 3 | Go + Comms |
| COMMS-303 | Integrate and certify DiddiSend task resolver | 5 | Send + Comms |
| COMMS-304 | Integrate and certify DiddiFood task and Support resolvers | 5 | Food + Comms + Support |
| COMMS-305 | Certify DiddiSupport case and event integration | 5 | Support + Comms |
| COMMS-306 | Certify DiddiAdmin conversation and case workflows | 5 | Admin + Comms + Support |
| COMMS-307 | Run migrations, backup, restore, rollback, and dependency-failure drills | 8 | Platform |
| COMMS-308 | Execute end-to-end client, driver, courier, restaurant, and agent journeys | 8 | QA |
| COMMS-309 | Run load, soak, reconnect, retry, and chaos tests | 8 | QA + Platform |
| COMMS-310 | Complete release checklist and pilot go/no-go review | 3 | All owners |

Required staging scenarios:

- create, reuse, message, deliver, read, close, and retain a ride conversation;
- audited external call attempt with no phone leakage;
- delivery and food-order conversations with reassignment;
- Support case creation, user reply, agent reply, assignment, and resolution;
- Admin task-chat inspection with delegated operator audit;
- token expiry and refresh;
- duplicate HTTP requests and duplicate Redis events;
- API, worker, Redis, PostgreSQL, owner-module, and Support restart;
- stream cursor expiry and REST resynchronization;
- backup restore and deployment rollback.

Exit criteria:

- All provider and consumer contract suites pass from immutable deployment
  artifacts.
- All required staging journeys pass with trace and audit evidence.
- No manifest says `implemented` without provider tests, consumer tests, and
  staging evidence.
- Dashboards and alerts are active before pilot traffic.
- Rollback and recovery drills are documented and successful.
- Product, Support, Security, Platform, and module owners sign the go/no-go.

Dependencies:

- DiddiSend and DiddiFood deliver their missing provider endpoints.
- All open blocking contract decisions are closed.

## Parallel External-Team Track

These dependencies should begin during Sprint 1 instead of waiting for Sprint
6.

| Team | Required delivery | Needed by |
|---|---|---|
| FreeID | Human audience decision, Admin client, scopes, delegated-operator design, token fixtures | Sprint 2 |
| DiddiSupport | Gateway parity, user-visible message routes, versioned events, migration approval | Sprints 1 and 4 |
| DiddiAdmin | Backoffice adapter migration and real contract tests | Sprint 2 |
| DiddiSend | Delivery state/participant policy and task resolver | Sprint 6 |
| DiddiFood | Food state/participant policy, task resolver, and Support context | Sprint 6 |
| Platform | Stream retention, consumer groups, observability, secrets, staging and rollback | Sprints 3 through 6 |
| Security | Abuse policy, threat model, and penetration review | Sprint 5 |

## Definition Of Ready

A ticket may enter implementation only when:

- its route, event, scope, state transition, error behavior, and idempotency
  behavior are documented;
- producer and consumer owners are named;
- required external endpoint or fixture is available;
- privacy and audit expectations are explicit;
- unresolved contract decisions are linked and do not block implementation.

## Definition Of Done

Every ticket requires:

- implementation and migration where applicable;
- focused unit tests and cross-service contract tests;
- failure, retry, duplicate, and authorization tests;
- structured logs, metrics, traces, and redaction checks;
- generated OpenAPI or AsyncAPI alignment;
- updated manifest status and changelog;
- deployment configuration and rollback instructions;
- staging evidence for cross-service behavior;
- `pytest`, Ruff, schema validation, and `git diff --check` passing.

## Program Completion

DiddiComms is production-ready only after Sprint 6 exits. Completion of an
individual sprint must not be used to claim ecosystem readiness while a
blocking dependency or security gate remains open.
