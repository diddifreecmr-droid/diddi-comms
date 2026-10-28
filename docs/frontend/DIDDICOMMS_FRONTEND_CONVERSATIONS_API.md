# DiddiComms Frontend Conversations API

**Audience:** DiddiFree application frontend
**API base:** `https://messaging.diddifree.com/comms/v1`
**Authentication:** DiddiFreeID user JWT

## Ownership

The frontend calls only DiddiComms. It never calls DiddiSupport or a business
module's `/internal/` route. DiddiComms validates business context and relays
Support operations through service-to-service contracts.

## List My Support Requests

```http
GET /support/conversations?status=open&limit=20&cursor=<opaque>
Authorization: Bearer <user-jwt>
```

The response contains only the authenticated user's requests, ordered by most
recent activity:

```json
{
  "items": [
    {
      "conversation_id": "bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb",
      "support_case_id": "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa",
      "category": "payment_issue",
      "subject": "Payment issue",
      "case_status": "open",
      "priority": "normal",
      "conversation_state": "active",
      "owner_service": "diddigo",
      "task_type": "ride",
      "task_id": "11111111-1111-1111-1111-111111111111",
      "created_at": "2026-10-28T10:00:00Z",
      "updated_at": "2026-10-28T10:05:00Z"
    }
  ],
  "next_cursor": null
}
```

The cursor is opaque. Return it unchanged; never parse or construct it.
`support_case_id` is display metadata only. Communication operations continue
to use `conversation_id`.

## Official Categories

```http
GET /support/categories
GET /support/categories?owner_service=diddigo&task_type=ride
Authorization: Bearer <user-jwt>
```

Global categories are `general`, `account_issue`, `payment_issue`,
`technical_issue`, `safety_issue`, and `other`.

| Context | Category |
|---|---|
| `diddigo/ride` | `ride_issue` |
| `diddisend/delivery` | `delivery_issue` |
| `diddifood/food_order` | `order_issue` |

Each item provides a stable `id`, a frontend translation `label_key`, and its
valid contexts. Both context query parameters must be provided together. Submit
category IDs, never translated labels.

## Message Contract

Message reads and writes return `created_at`, `sender_type`, and `sender_role`
in addition to the existing message fields. `sender_type` is one of `user`,
`support_agent`, or `system`. Use it to render message ownership. The contextual
role can be `requester`, `passenger`, `driver`, `support_agent`, or another
module-owned participant role. It can be `null` on the immediate acknowledgement
of a newly sent task message. Display time comes from UTC `created_at`.

## Realtime WebSocket

```text
wss://messaging.diddifree.com/comms/v1/ws?conversation_id=<uuid>&after_event_id=<event_id>
```

`after_event_id` is optional on the first connection. Store the latest received
`event_id` and reuse it after a disconnect.

Native clients capable of custom headers send `Authorization: Bearer <JWT>` and
may negotiate `Sec-WebSocket-Protocol: diddicomms.v1`.

Browser clients use:

```javascript
const socket = new WebSocket(
  `wss://messaging.diddifree.com/comms/v1/ws?conversation_id=${conversationId}`,
  ["diddicomms.v1", `diddicomms.auth.${accessToken}`],
);
```

The server selects only `diddicomms.v1`; it does not echo the JWT protocol.
Infrastructure must redact `Sec-WebSocket-Protocol` from access logs.

Events are notifications, not the source of truth. On message events, refresh
`GET /conversations/{conversation_id}/messages?after_seq=...`. Event payloads
intentionally contain no message body.

The server sends `{"type":"heartbeat"}` while idle. Send a small text frame,
such as `ping`, every 30 seconds to avoid the client-idle timeout.

| Close code | Meaning | Frontend action |
|---|---|---|
| `4401` | JWT absent or invalid | Refresh authentication before reconnecting |
| `4403` | Conversation absent or forbidden | Stop reconnecting |
| `4408` | Client idle timeout | Reconnect using the latest `event_id` |
| `4409` | Stream cursor expired | Use the HTTP resynchronization path supplied by the server |
| `4429` | Connection limit reached | Back off before reconnecting |

Use exponential reconnect delays with jitter. If WebSocket is unavailable,
poll message history every 3 to 5 seconds only while the screen is visible.

## Support Calls

Support calls are not part of this contract. Do not display a Support call
button until DiddiComms publishes an authorized destination contract.
