# DiddiFreeID Integration

**Status:** `partial`  
**Direction:** DiddiComms consumes human JWT verification, JWKS, and service
credentials from DiddiFreeID.

## Ownership

DiddiFreeID owns identities, token issuance, service clients, audiences,
scopes, revocation, and account status. DiddiComms stores only stable FreeID
user IDs and the minimum actor metadata required for communication audits.

## Human Authentication

Public conversation, message, read-cursor, call-attempt, and WebSocket routes
accept a DiddiFreeID human JWT. DiddiComms verifies signature, issuer, expiry,
status, and a UUID `sub`, and rejects service tokens with
`403 USER_TOKEN_REQUIRED`.

Observed behavior: human-token verification currently uses
`require_audience=false`. Whether FreeID will issue `aud=diddicomms` human
tokens is unresolved and tracked in `docs/diddiconnect/open-questions.md`.

## Service Authentication

DiddiComms obtains short-lived service tokens through the FreeID
client-credentials flow before calling owner modules or DiddiSupport.

```http
Authorization: Bearer <service-jwt>
X-Client-ID: <signed-client-id>
X-Request-ID: <uuid>
traceparent: <w3c-trace-context>
```

The receiving service verifies `iss=diddifree-id`, its own audience,
`sub=service:diddicomms`, `role=service`, `token_type=service`, active status,
expiry, signed `client_id`, and the operation scope.

## Required Clients And Grants

| Consumer | Audience | Scopes | Status |
|---|---|---|---|
| DiddiComms to DiddiGo | `diddigo` | `diddigo:comms-task:read` | Implemented |
| DiddiComms to DiddiSend | `diddisend` | `diddisend:comms-task:read` | Proposed |
| DiddiComms to DiddiFood | `diddifood` | `diddifood:comms-task:read` | Proposed |
| DiddiComms to Support | `diddi-support` | `diddi-support:cases:create`, `diddi-support:cases:read`, `diddi-support:messages:write` | Partial |
| DiddiAdmin to DiddiComms | `diddicomms` | `diddicomms:backoffice:read`, `diddicomms:backoffice:write` | Proposed |

Credentials are environment-specific. Secrets are injected at deployment and
never committed to manifests, logs, traces, events, or browser state. Token
caches renew shortly before expiry; a rejected cached token may be refreshed
once before returning dependency failure.

## Errors And Retry

| HTTP | Code | Meaning |
|---:|---|---|
| 401 | `TOKEN_MISSING` | Bearer token is absent. |
| 401 | `TOKEN_INVALID` | Signature, issuer, expiry, subject, or claims are invalid. |
| 401 | `SERVICE_CLIENT_ID_INVALID` | `X-Client-ID` is absent or differs from the signed claim. |
| 403 | `USER_TOKEN_REQUIRED` | A service token was used on a human route. |
| 403 | `SERVICE_TOKEN_REQUIRED` | A human token was used on a service route. |
| 403 | `SERVICE_SUBJECT_FORBIDDEN` | The service identity is not allowlisted. |
| 403 | `SERVICE_SCOPE_FORBIDDEN` | The operation scope is absent. |

Authentication failures are not retried except for one service-token refresh
after expiry or a token-endpoint race. Token-endpoint timeout returns a safe
`503 DEPENDENCY_UNAVAILABLE` or a gateway-specific `502` mapping.

## Conformance

FreeID must provide accepted, expired, wrong-audience, wrong-client,
wrong-subject, missing-scope, human-token, and service-token fixtures. No real
private key or production credential may appear in the fixtures.
