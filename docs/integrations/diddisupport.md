# DiddiSupport Integration

**Status:** `partial`, authoritative user-message flow and stream consumer implemented  
**Existing authority:** `E:/DIDDI AI/diddi-support/manifests/diddi-support.v1.json`  
**Existing frozen contract:**
`E:/DIDDI AI/diddi-support/docs/integrations/diddicomms.md`

## Ownership

DiddiSupport is the only target source of truth for support cases, support
messages, assignments, priorities, SOS state, attachments, actions, and the
support timeline. DiddiComms owns transport of user-visible messages and
notifications but must not maintain an independent long-term case state.

DiddiComms retains local Support tables only as a compatibility projection.
Case creation, initial and subsequent user messages, and user-visible history
are confirmed by DiddiSupport. Legacy assignment, priority, agent-reply, and
resolution routes return `410 DIDDISUPPORT_BACKOFFICE_REQUIRED`; DiddiAdmin
must use DiddiSupport Backoffice for those operations.

## Identity

Outbound calls use audience `diddi-support`, subject
`service:diddicomms`, a matching `X-Client-ID`, and `X-Request-ID`.

| Operation | Scope |
|---|---|
| Create or recover a case | `diddi-support:cases:create` |
| Read case or business context | `diddi-support:cases:read` |
| Add a user-visible user message | `diddi-support:messages:write` |

## Internal Routes Consumed By DiddiComms

| Method | Path | Idempotency | Status |
|---|---|---|---|
| POST | `/support/v1/internal/cases` | Required | Implemented client and Support route |
| GET | `/support/v1/internal/context/{origin_service}/{resource_type}/{resource_id}` | Safe retry | Implemented client and Support route |
| GET | `/support/v1/internal/cases/{case_id}/context` | Safe retry | Implemented client and Support route |
| POST | `/support/v1/internal/cases/{case_id}/messages` | Required | Implemented client and Support route |
| GET | `/support/v1/internal/cases/{case_id}/messages` | Safe retry | Implemented client and Support route |

Case creation identifies both the technical creator `service:diddicomms` and
the human `reporter_user_id`. `origin_service` identifies the business owner,
not the caller. Reusing an idempotency key with identical content returns the
original result; different content returns `409 IDEMPOTENCY_CONFLICT`.

Only `user_visible` messages may be returned to DiddiComms. Support internal
notes are never exposed through this connection.

## Events

Target event consumption is:

```text
support.case.message.created.v1
support.case.updated.v1
support.case.resolved.v1
```

The durable Support event envelope is at least once and deduplicated by
`event_id`. DiddiSupport publishes it as one Redis field named `event` whose
value is the complete JSON envelope. Flat Redis fields remain accepted only as
a migration compatibility format.

DiddiComms reads `diddisupport.events` through `SUPPORT_EVENTS_REDIS_URL` and
the `diddicomms` consumer group. For the pilot, the stacks do not share a
Docker network: DiddiSupport publishes Redis on host port `16382`, and the
containerized DiddiComms worker connects to
`redis://host.docker.internal:16382/0`. A worker launched directly on the host
uses `redis://localhost:16382/0` instead. Its own `REDIS_URL` remains authoritative for
the DiddiComms outbox, shared worker metrics, internal streams, and
`diddicomms.inbound.dlq`. If `SUPPORT_EVENTS_REDIS_URL` is empty in local
development, it falls back to `REDIS_URL`; staging and production must inject
the published Support Redis endpoint or a relay endpoint through Portainer.

Each replica must set a unique `SUPPORT_EVENTS_CONSUMER_NAME`. When it is empty,
the worker derives `diddicomms-worker-<hostname>`. The Support Redis ACL needs
`XGROUP`, `XREADGROUP`, `XACK`, `XPENDING`, `XAUTOCLAIM`, and `XINFO` access to
the source stream. SQL state and the inbox record commit before acknowledgement.

## Compatibility Migration

1. Freeze creation of new independent Support capabilities in DiddiComms.
2. Make `/comms/v1/support/*` call DiddiSupport using stable idempotency keys.
3. Persist the DiddiSupport case ID as the external case reference.
4. Reconcile existing local cases and messages with an explicit migration
   report; never silently merge conflicting histories.
5. Route DiddiAdmin case operations to DiddiSupport.
6. Retire local case ownership only after parity, migration, and rollback
   verification.

## Public DiddiComms Entry Point

The DiddiFree frontend opens both contextual and general Support conversations
through `POST /comms/v1/support/conversations`. It never calls DiddiSupport or
an `/internal/` business route directly. Contextual requests are checked with
the owning module's DiddiComms task resolver before case creation. General
requests omit the context and therefore do not invoke a business module.

`POST /comms/v1/support/cases` remains a compatibility route during migration.

## Errors And Dependency Failure

Support `401` and `403` responses map to `502 DIDDISUPPORT_AUTH_REJECTED`
because they indicate service configuration failure. A missing case remains
`404`. Idempotency conflict remains `409`. Timeout, malformed response, or
unavailability returns a safe gateway error and must not create a local shadow
case as fallback.

## Conformance

Provider and consumer tests must share fixtures for case creation, context,
visible messages, idempotent retry, idempotency conflict, internal-note
redaction, malformed response, timeout, and service-token rejection.
