# DiddiSupport Gateway Contract

This is the boundary required before replacing the current local compatibility
case store. DiddiComms owns the conversation and message history; DiddiSupport
owns the case lifecycle.

## Read contract implemented in DiddiComms

The routes below belong to DiddiSupport. DiddiComms calls them as a read-only
consumer; it does not expose or proxy them publicly.

### Business context

`GET /support/v1/internal/context/{origin_service}/{resource_type}/{resource_id}`

Returns the `diddi.context.v1` projection authorized by the owning service.

### Case context

`GET /support/v1/internal/cases/{case_id}/context`

Returns the Support case and its current business context.

Both calls use `Authorization: Bearer <service-token>`, `X-Client-ID`, and
`X-Request-ID`. The token must target audience `diddi-support`, subject
`service:diddicomms`, and scope `diddi-support:cases:read`.

## Conversation-first case creation implemented in DiddiComms

The public frontend entry point is:

`POST /comms/v1/support/conversations`

It accepts a category, initial message, optional subject and priority, and an
optional atomic business context (`owner_service`, `task_type`, `task_id`). A
contextual request is authorized against the owning module's task resolver
before DiddiSupport is called. A request without context is a general Support
request and does not call a business resolver.

The legacy route `POST /comms/v1/support/cases` remains available for backward
compatibility. Both routes create the authoritative Support case through:

`POST /support/v1/internal/cases`

It sends the reporter, category, subject, priority, request ID, service token,
and idempotency key. The business resource reference is included only for a
contextual request. The returned Support `case_id` is used to link the
DiddiComms conversation projection.

The Support contract requires:

- authorization for `service:diddicomms`;
- idempotency by `Idempotency-Key`;
- a returned `case_id`.

General Support case creation additionally requires DiddiSupport to accept a
case without `origin_service`, `resource_type`, and `resource_id`.

DiddiComms stores the returned case reference to link its conversation. The
Support service remains the source of truth for the case lifecycle.

## Authentication errors

The client maps Support's `401`, `403`, `404`, and `503` responses to explicit
DiddiComms API errors and preserves the request correlation ID.

Case assignment, resolution, and agent replies remain DiddiSupport-owned
operations until their write contract is agreed.

## Conversation handoff

DiddiSupport emits or requests a handoff when an agent takes ownership. The
DiddiComms conversation then changes from `waiting_for_support` to
`agent_active`; the AI must stop sending messages. Case resolution changes the
conversation to read-only.
