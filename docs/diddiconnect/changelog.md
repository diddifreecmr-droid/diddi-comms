# DiddiConnect Contract Changelog

## Frontend conversation completion - 2026-10-28

- Added user-owned Support conversation listing with opaque cursor pagination.
- Added the official context-aware Support category catalog.
- Added message timestamps and explicit sender type and role.
- Enabled browser WebSocket authentication through negotiated subprotocols.
- Replaced the cross-repository DiddiSupport import test with a local versioned event fixture.

## 1.0.0-draft - 2026-10-20

- Added service-level connection roles for identity, business context,
  Support, Backoffice, files, and payments.
- Added the canonical `manifests/diddicomms.v1.json` service manifest.
- Added focused integration contracts for FreeID, Support, Admin, Go, Send,
  Food, Files, and Pay.
- Preserved Go as implemented at connector level.
- Classified Send task communication and Food integrations as proposed.
- Classified Admin as blocked pending S2S delegated-operator routes.
- Classified DiddiSupport as partial until duplicate local case ownership is
  migrated.
- Recorded the DiddiFiles route mismatch and Food implementation-status
  contradiction.
- Added shared task-context, error, event, and delegated-operator fixtures.
- Added a blocking-question ledger and conformance requirements.

This draft is not a production activation signal. Promotion requires owner
approval, provider and consumer contract tests, and staging evidence.
