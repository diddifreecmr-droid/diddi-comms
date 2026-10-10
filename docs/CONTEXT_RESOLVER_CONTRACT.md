# DiddiComms Context Resolver Contract

**Status:** Phase 0 draft  
**First owner service:** DiddiGo  
**Next owner services:** DiddiSend, then DiddiFood

DiddiComms does not decide whether a user belongs to a ride, delivery, food
order, or any future task. The owning product service decides that. DiddiComms
stores conversations against user IDs plus an external task reference:
`owner_service`, `task_type`, and `task_id`.

The resolver is a generic port. DiddiComms must not contain code such as
`ride -> DiddiGo` or `delivery -> DiddiSend`. That mapping belongs in
configuration and in the caller that asks to ensure a conversation for a task.

## Authentication

The resolver is protected with a DiddiFreeID service token.

```http
Authorization: Bearer <service-jwt>
X-Client-ID: diddicomms-<environment>-<owner-service>
X-Request-ID: <correlation-id>
```

The owner service verifies:

- `iss=diddifree-id`
- `aud=<owner-service>`, for example `diddigo`
- `sub=service:diddicomms`
- `role=service`
- `token_type=service`
- `status=active`
- `client_id` equals `X-Client-ID`
- required scope is present

Initial scopes:

| Owner | Audience | Scope |
| --- | --- | --- |
| DiddiGo | `diddigo` | `diddigo:comms-task:read` |
| DiddiSend | `diddisend` | `diddisend:comms-task:read` |
| DiddiFood | `diddifood` | `diddifood:comms-task:read` |

## Endpoint

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
```

`task_type` is owned by the product service. Examples are `ride`, `delivery`,
and `food_order`, but DiddiComms treats this as an opaque external name.

## Response

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
    {
      "user_id": "22222222-2222-2222-2222-222222222222",
      "role": "passenger",
      "phone_e164": "+237600000001"
    },
    {
      "user_id": "33333333-3333-3333-3333-333333333333",
      "role": "driver",
      "phone_e164": "+237600000002"
    }
  ],
  "messaging_allowed": true,
  "calling_allowed": true,
  "closes_at": null
}
```

`phone_e164` is allowed in this internal response for the MVP because direct
external calls are accepted for the pilot. DiddiComms must not store phone
numbers in conversation, audit, outbox, logs, metrics, or traces.

## Error Semantics

| Status | Meaning |
| ---: | --- |
| 401/403 | DiddiComms service token is missing, invalid, or not scoped. |
| 404 | The context does not exist or is not visible to DiddiComms. |
| 409 | The context exists but is in a state that cannot currently communicate. |
| 422 | The task reference is malformed or not supported by the owner. |
| 5xx | Owner service is unavailable or failed while resolving the context. |

DiddiComms fails closed for creation, participant changes, and call-number
release when the owner resolver is unavailable. Later chat continuation may use
a short versioned cache, but that is not part of Phase 0.

## DiddiComms Enforcement

DiddiComms revalidates the owner task projection before sensitive actions.

A user may send a message or request a call only when:

- the caller is authenticated;
- the conversation task reference matches the owner resolver task reference;
- the caller `user_id` appears in the resolver participants;
- the target `user_id`, when present, appears in the same resolver participants;
- the conversation state allows the action;
- `now` is before the conversation `closes_at`, when set;
- `now` is before the resolver `closes_at`, when set;
- the resolver says the requested channel is allowed:
  `messaging_allowed` for messages and `calling_allowed` for calls.

History reads may continue after the communication window closes while the
conversation is retained, but writes and call-number release fail closed.
