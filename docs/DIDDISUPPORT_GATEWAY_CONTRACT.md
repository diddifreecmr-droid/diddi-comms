# DiddiSupport Gateway Contract

This is the boundary required before replacing the current local compatibility
case store. DiddiComms owns the conversation and message history; DiddiSupport
owns the case lifecycle.

## Case creation

`POST /internal/v1/support/cases`

Required fields:

- `conversation_id`
- `requester_user_id`
- `subject`
- `priority`
- optional `owner_service`, `task_type`, and `task_id`

DiddiSupport returns `case_id`, `status`, and `created_at`. DiddiComms stores
only the case reference and continues to own the conversation messages.

## Case updates

- `GET /internal/v1/support/cases/{case_id}`
- `POST /internal/v1/support/cases/{case_id}/assign`
- `PATCH /internal/v1/support/cases/{case_id}/priority`
- `POST /internal/v1/support/cases/{case_id}/resolve`

All requests use a FreeID service token, `X-Client-ID`, `X-Request-ID`, and an
idempotency key for mutations. DiddiAdmin supplies delegated operator claims.

## Conversation handoff

DiddiSupport emits or requests a handoff when an agent takes ownership. The
DiddiComms conversation then changes from `waiting_for_support` to
`agent_active`; the AI must stop sending messages. Case resolution changes the
conversation to read-only.
