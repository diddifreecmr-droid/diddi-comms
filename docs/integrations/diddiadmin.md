# DiddiAdmin Integration

**Status:** `provider-implemented`, DiddiAdmin adapter migration pending  
**Direction:** DiddiAdmin's server-side BFF consumes DiddiComms and
DiddiSupport. The browser never calls either service with S2S credentials.

## Observed State

DiddiAdmin has the generic server-side S2S token and delegated-actor patterns,
but its current repository does not yet contain a DiddiComms adapter or BFF
routes. This document is therefore a migration contract, not a claim that the
consumer integration is already present.

DiddiComms human conversation routes intentionally reject service tokens with
`USER_TOKEN_REQUIRED`. DiddiAdmin must use the dedicated backoffice routes
below; it must never call the human routes with a service token or forward a
browser token as a service credential.

## Target Identity Contract

The BFF uses:

```http
Authorization: Bearer <diddiadmin-service-jwt>
X-Client-ID: <signed-client-id>
X-Request-ID: <uuid>
X-Backoffice-Actor: <agent-freeid-uuid>
X-Backoffice-Reason: <case-id-or-reason-code>
Idempotency-Key: <stable-key-for-mutations>
```

The token target is `aud=diddicomms`, `sub=service:diddiadmin`. Proposed scopes
are `diddicomms:backoffice:read` and `diddicomms:backoffice:write`.
`X-Backoffice-Actor` is trusted only after the service token, client ID, and
scope pass. DiddiComms records both service and human actor in its audit.

## DiddiComms Backoffice Routes

These routes are implemented by DiddiComms. DiddiAdmin must still migrate its
adapter and run the shared ASGI contract suite before the connection can be
marked fully implemented:

| Method | Path | Scope | Idempotency |
|---|---|---|---|
| POST | `/comms/v1/backoffice/tasks/{owner_service}/{task_type}/{task_id}/conversation` | `diddicomms:backoffice:read` | Required |
| GET | `/comms/v1/backoffice/conversations/{conversation_id}/messages` | `diddicomms:backoffice:read` | Safe retry |
| POST | `/comms/v1/backoffice/conversations/{conversation_id}/messages` | `diddicomms:backoffice:write` | Required |
| POST | `/comms/v1/backoffice/conversations/{conversation_id}/call-attempts` | `diddicomms:backoffice:write` | Required |

Case queues, assignment, priority, Support replies, SOS, attachments, actions,
and resolution are DiddiSupport Backoffice operations, not DiddiComms task-chat
operations. DiddiAdmin must call DiddiSupport for those resources.

## Authorization Rules

- The BFF authenticates the human agent before acquiring a service token.
- DiddiComms verifies the agent UUID and records the reason or linked case.
- Read access must be justified by an assigned case, explicit operational
  permission, or another versioned policy.
- A Backoffice message cannot masquerade as a customer message.
- Browser-supplied service headers are discarded and rebuilt by the BFF.
- Task chat access does not automatically grant Support internal-note access.

## Errors And Retry

Missing service auth returns `401`; wrong subject, scope, or operator context
returns `403`. Missing conversation returns `404`. Invalid or reused mutation
keys return `409`. Owner resolver or DiddiComms dependency failure returns
`503`. Reads are safe to retry; mutations retry only with the original key and
payload.

## Conformance

Tests must exercise a real DiddiComms ASGI contract rather than only mocking
the Admin adapter. Required cases are accepted read, accepted write, missing
actor, malformed actor, wrong service, missing scope, unauthorized case,
idempotent replay, conflicting replay, and audit attribution.
