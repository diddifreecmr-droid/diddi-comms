# DiddiGo Integration

**Status:** `implemented` in provider code; manifest adoption and staging
certification remain required.

## Ownership And Route

DiddiGo owns ride state, passenger/driver assignment, phone data, and the
decision to allow communication. DiddiComms owns the resulting conversation,
messages, call attempts, and communication audit.

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
Authorization: Bearer <diddicomms-service-jwt>
X-Client-ID: <diddicomms-client-id>
X-Request-ID: <uuid>
```

The only supported `task_type` is `ride`. Authentication requires audience
`diddigo`, subject `service:diddicomms`, and scope
`diddigo:comms-task:read`.

## Response

The endpoint returns the `diddiconnect.task-context.v1` shape represented by
`docs/diddiconnect/fixtures/task-context.ride.v1.json`. Participants are
identified by FreeID UUID and role `passenger` or `driver`. `version` changes
with ride updates.

## State Policy

| State | Messaging | Calling |
|---|---|---|
| `requested` | Denied | Denied |
| `driver_assigned` | Allowed | Allowed |
| `driver_en_route` | Allowed | Allowed |
| `arrived` | Allowed | Allowed |
| `in_progress` | Allowed | Allowed |
| `waiting` | Allowed | Allowed |
| `completed` | Until `closes_at` | Denied |
| `cancelled_by_passenger` | Denied | Denied |
| `cancelled_by_driver` | Denied | Denied |
| `no_driver_found` | Denied | Denied |

The completed-chat grace period comes from
`RIDE_COMMS_COMPLETED_CHAT_RETENTION_SECONDS`. Clients must use the returned
`closes_at` and never hardcode the duration.

## Phone Handling

`phone_e164` may be returned internally only for an authorized call attempt.
DiddiComms uses it transiently to build the device dial action. It must not be
stored in conversation, audit, outbox, log, metric, trace, or WebSocket data.

## Errors And Retry

`404 COMMS_TASK_NOT_FOUND` hides missing or inaccessible rides.
`422 COMMS_TASK_TYPE_UNSUPPORTED` rejects non-ride tasks. Authentication and
scope errors return `401` or `403`. GET is safe to retry. DiddiComms fails
closed for create, send, and call when the resolver cannot be reached.

## Conformance

DiddiGo provider tests and DiddiComms consumer tests must share fixtures for
every state, absent driver, missing phone, wrong task type, wrong task ID,
wrong subject, wrong audience, wrong client ID, missing scope, and timeout.
