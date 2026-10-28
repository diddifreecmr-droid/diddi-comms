# Sprint - Complete Frontend Conversations

**Date:** 28 October 2026
**Status:** implemented

## Delivered

- Message timestamps and explicit sender type and role.
- Authenticated Support conversation listing with opaque cursor pagination.
- Versioned Support category catalog and context validation.
- Browser-compatible WebSocket authentication through negotiated subprotocols.
- Native WebSocket authentication through `Authorization`.
- Reconnect, resynchronization, heartbeat, close-code, and polling documentation.
- Support category persistence and requester activity database index.

## Deployment Gate

Run Alembic migration `2026_10_28_0010` before starting the updated API and
worker. Rebuild the MkDocs container and verify the frontend contract. Staging
acceptance covers a general request, a DiddiGo request, pagination, an agent
reply over Redis, WebSocket reconnect, and an invisible internal note.
