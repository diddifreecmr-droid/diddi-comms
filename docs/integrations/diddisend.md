# DiddiSend Integration

**Status:** `proposed` for task communication; Support context is implemented.

## Ownership And Required Route

DiddiSend owns delivery state, assignment, participants, phone data, and the
communication policy. It must expose:

```http
GET /internal/v1/comms/tasks/delivery/{delivery_id}
```

The generic route form remains
`/internal/v1/comms/tasks/{task_type}/{task_id}` with
`task_type=delivery`. Authentication requires audience `diddisend`, subject
`service:diddicomms`, client ID matching the token, and scope
`diddisend:comms-task:read`.

## Required Projection

The response must conform to `diddiconnect.task-context.v1` and include only:

- stable delivery reference;
- current owner-defined delivery state and monotonic version;
- relevant participants by FreeID UUID and role;
- `messaging_allowed`, `calling_allowed`, and `closes_at`;
- phone numbers only when needed for an authorized call attempt.

Known Support roles are `sender`, `customer`, `recipient`, and `courier`.
DiddiSend must decide which roles participate in task communication and how
reassignment replaces or closes access for the previous courier.

## State Policy Decision Required

Before implementation, DiddiSend must enumerate every delivery state and
declare messaging, calling, closure, cancellation, completion, failed-delivery,
and reassignment behavior. The bootstrap manifest intentionally fails closed
with `owner_defined` until that table is approved.

## Existing Support Context

The existing route is:

```http
GET /internal/v1/support/delivery/{delivery_id}/context
```

It uses `diddi.context.v1`, subject `service:diddisupport`, audience
`diddisend`, and scope `diddisend:support-context:read`. It excludes phone
numbers, locations, provider details, and pickup/delivery PINs.

## Errors And Retry

The task resolver must return the standard `401`, `403`, `404`, `409`, `422`,
and `503` error envelope. GET is safe to retry. DiddiComms fails closed when
the resolver is unavailable and must not retain a removed courier as an active
participant after a newer task version.

## Conformance

Promotion requires provider and consumer tests for every state, sender versus
recipient identity, courier assignment and reassignment, cancellation,
completion grace, missing phone, privacy exclusions, auth failures, timeout,
and stale version handling.
