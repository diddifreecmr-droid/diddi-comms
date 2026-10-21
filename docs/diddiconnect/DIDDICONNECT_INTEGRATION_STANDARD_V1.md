# DiddiConnect Integration Standard v1

**Protocol:** `diddiconnect.module.v1`  
**Status:** draft for ecosystem adoption  
**Normative schema:** `diddiconnect.module.v1.schema.json`

## 1. Purpose

This standard defines how an owner module such as DiddiGo, DiddiSend, or
DiddiFood connects to DiddiComms and DiddiSupport. Each owner module publishes
one versioned manifest conforming to the JSON Schema in this directory.

The manifest is a control-plane declaration. It does not replace OpenAPI,
AsyncAPI, or implementation-level contract tests. A route is considered ready
for integration only when all four artifacts agree:

1. the module manifest;
2. the provider OpenAPI or AsyncAPI document;
3. provider contract tests;
4. consumer contract tests in DiddiComms or DiddiSupport.

## 2. Ownership

- The owner module owns task state, participant assignment, and communication
  policy for its ride, delivery, or order.
- DiddiComms owns conversations, messages, message receipts, call attempts,
  realtime delivery, and communication audits.
- DiddiSupport owns support cases, queues, support messages, SOS state,
  attachments, business-action requests, and the support timeline.
- DiddiFreeID owns user identity, service clients, audiences, scopes, and token
  issuance.
- No service reads another service's database.

## 3. Manifest Location And Lifecycle

Every owner repository must commit its manifest at:

```text
docs/integrations/diddiconnect.module.v1.json
```

DiddiComms additionally publishes its service-level manifest at
`manifests/diddicomms.v1.json`. Its `connections` array records each peer's
role, direction, contract document, identity, scopes, status, and blocker.
Business-owner manifests continue to declare their task and Support contexts;
identity, Backoffice, file, payment, and Support integrations use their own
connection roles rather than pretending to be task-context providers.

Backoffice routes acting for a human operator declare
`service_jwt_delegated_operator`: the service JWT is verified first, then the
matching client ID, delegated actor, operational reason, and request ID are
validated and audited together. A route whose stored state makes repeated
requests harmless may declare idempotency as `intrinsic`.

`status` has these meanings:

| Status | Meaning |
|---|---|
| `proposed` | Contract is being designed and must not be enabled in production. |
| `implemented` | Provider route, auth, tests, and documentation exist. |
| `deprecated` | Existing consumers may continue temporarily; no new consumer may connect. |

Promotion to `implemented` requires a successful schema check, provider
contract tests, consumer contract tests, and a staging smoke test. Runtime
service discovery must consume only manifests approved for the environment;
it must not blindly trust a manifest found over the network.

## 4. Common Identity Contract

All service-to-service requests use a short-lived DiddiFreeID service JWT:

```http
Authorization: Bearer <service-jwt>
X-Client-ID: <provisioned-client-id>
X-Request-ID: <uuid>
traceparent: <optional-w3c-trace-context>
```

The provider verifies `iss`, its own `aud`, `sub`, `client_id`,
`token_type=service`, `role=service`, `status=active`, expiry, and the declared
scope. `X-Client-ID` must equal the signed `client_id` claim. Browsers never
receive service tokens.

Required scope patterns are:

```text
<owner>:comms-task:read
<owner>:support-context:read
```

The task-context caller is `service:diddicomms`. The support-context caller is
`service:diddisupport`. A wrong token returns `401`; a valid token with the
wrong caller, audience, client ID, or scope returns `403`.

## 5. Task Context Provider

An owner that supports task communication exposes:

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
```

The response schema is identified as `diddiconnect.task-context.v1`:

```json
{
  "task": {
    "owner_service": "diddigo",
    "task_type": "ride",
    "task_id": "11111111-1111-1111-1111-111111111111"
  },
  "state": "driver_assigned",
  "version": 12,
  "participants": [
    {"user_id": "22222222-2222-2222-2222-222222222222", "role": "passenger"},
    {"user_id": "33333333-3333-3333-3333-333333333333", "role": "driver"}
  ],
  "messaging_allowed": true,
  "calling_allowed": true,
  "closes_at": null
}
```

`version` must increase whenever participants, state, permissions, or
`closes_at` changes. DiddiComms treats owner state as opaque and enforces the
returned booleans. A caller may message or request a call only if present in
`participants` and the relevant flag is true.

Telephone numbers are permitted only when the manifest declares
`phone_numbers=call_attempt_only`. They may be used transiently to complete an
authorized call attempt and must not enter conversation rows, audits, outbox
payloads, application logs, metrics, or traces.

### Errors And Dependency Failure

| HTTP | Stable code | Meaning |
|---:|---|---|
| 401 | `SERVICE_TOKEN_REQUIRED` | Service token is missing or invalid. |
| 403 | `SERVICE_ACCESS_FORBIDDEN` | Caller, client, audience, or scope is invalid. |
| 404 | `COMMS_TASK_NOT_FOUND` | Task does not exist or is intentionally hidden. |
| 409 | `COMMS_TASK_COMMUNICATION_BLOCKED` | Task exists but communication is unavailable. |
| 422 | `COMMS_TASK_TYPE_UNSUPPORTED` | Task type or ID is unsupported. |
| 503 | `DEPENDENCY_UNAVAILABLE` | Required owner dependency is unavailable. |

GET is safe to retry. DiddiComms fails closed for conversation creation,
participant changes, message sends, and call attempts if the owner cannot be
revalidated. Historical reads may continue according to DiddiComms retention.

## 6. Support Context Provider

An owner connected to DiddiSupport exposes:

```http
GET /internal/v1/support/{resource_type}/{resource_id}/context
X-Support-Context-Scope: <owner>:support-context:read
```

The response uses `protocol=diddi.context.v1`, identifies the owner and
resource, contains a privacy-minimized `data` projection, lists
`redacted_fields`, and includes `as_of` and `fetched_at`. The JWT scope remains
the authorization source; the scope header is a contract guard, not a grant.

The endpoint returns `404 RESOURCE_NOT_FOUND`, `403 SERVICE_ACCESS_FORBIDDEN`,
or `503 DEPENDENCY_UNAVAILABLE` using the common error envelope.

## 7. Common Error Envelope

```json
{
  "error": {
    "code": "COMMS_TASK_NOT_FOUND",
    "message": "The requested communication task was not found.",
    "request_id": "44444444-4444-4444-4444-444444444444",
    "details": {}
  }
}
```

`code` is stable and machine-readable. `message` is safe for logs and clients.
`details` must not disclose tokens, phone numbers, private message content, or
whether an unrelated user's resource exists.

## 8. Events

Owner lifecycle events are optional for the REST MVP but must use the common
envelope when declared:

```json
{
  "event_id": "55555555-5555-5555-5555-555555555555",
  "event_type": "diddigo.ride.communication_changed.v1",
  "occurred_at": "2026-10-20T12:00:00Z",
  "producer": "diddigo",
  "aggregate_type": "ride",
  "aggregate_id": "11111111-1111-1111-1111-111111111111",
  "correlation_id": "44444444-4444-4444-4444-444444444444",
  "causation_id": null,
  "aggregate_version": 12,
  "payload": {}
}
```

Redis Stream delivery is at least once. Consumers deduplicate by `event_id`,
commit local state before acknowledging, make no global ordering assumption,
and use `aggregate_version` to reject stale updates. REST task context remains
the resynchronization source of truth.

## 9. Conventions

- IDs are lowercase UUID strings unless an existing owner ID format is
  explicitly declared in its manifest.
- Dates are RFC 3339 UTC timestamps ending in `Z`.
- Missing optional fields are preferred to ambiguous `null`; fields explicitly
  nullable in OpenAPI may use `null`.
- New enum values and response fields are backward-compatible minor changes.
- Removing or changing semantics of a field, route, scope, or event creates a
  new major protocol version.
- All mutating operations outside these read-only resolver routes require an
  `Idempotency-Key` and define conflict behavior in OpenAPI.
- Service timeouts, retries, base URLs, and completed-task grace periods are
  runtime configuration and must not grant privileges.

## 10. Conformance Gate

A module is DiddiConnect v1 conformant only when:

1. its manifest validates against the schema;
2. every `implemented` route exists in generated OpenAPI;
3. auth tests cover missing, invalid, expired, wrong-audience, wrong-client,
   wrong-subject, and missing-scope tokens;
4. policy tests cover every declared owner state;
5. privacy tests prove excluded fields are absent and secrets are not logged;
6. DiddiComms or DiddiSupport consumer tests use the same fixtures;
7. staging verifies success, denial, timeout, retry, and dependency recovery.

The manifest is reviewed by the owner team, DiddiComms or DiddiSupport, and
DiddiFreeID before production activation.
