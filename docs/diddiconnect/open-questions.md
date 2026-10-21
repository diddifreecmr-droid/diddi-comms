# DiddiConnect v1 Open Questions

Unknowns and proposed defaults remain here until the named owners approve a
decision. An unresolved item cannot be represented as `implemented`.

| ID | Blocking | Owners | Question | Proposed default |
|---|---|---|---|---|
| DCQ-01 | Yes | FreeID, Comms | Must human access tokens carry `aud=diddicomms`? | Require it in the target contract; retain current no-audience verification only during migration. |
| DCQ-02 | Yes | Admin, FreeID, Comms | How are delegated operator permissions cryptographically bound to the Admin service request? | Allowlisted Admin S2S token plus validated actor and reason headers, with downstream permission lookup. |
| DCQ-03 | Yes | Support, Comms | What is the migration and rollback procedure for local DiddiComms Support cases? | Freeze new local ownership, proxy writes, reconcile by stable external case ID, then retire tables after parity. |
| DCQ-04 | Yes | Send | Which delivery states and roles allow messaging and calling? | Fail closed until DiddiSend publishes the full state table. |
| DCQ-05 | Yes | Food | Which order states and actor pairs may communicate? | Fail closed until Food publishes the full state and participant matrix. |
| DCQ-06 | Yes | Food, Support | Is Food Support context actually implemented? | Treat it as proposed until route, tests, and staging evidence exist. |
| DCQ-07 | No | Comms | Should task conversation creation require `Idempotency-Key` rather than treating it as optional? | Require it in the next compatible API revision. |
| DCQ-08 | No | Comms | Should read-cursor and call-result writes require idempotency keys? | Require stable keys for mobile retries. |
| DCQ-09 | Yes | Files, Support, Comms | Is temporary access a new internal route or the existing `/v1/files/{id}/download-url`? | Reuse the signed-download route after adding purpose and caller authorization. |
| DCQ-10 | No | Files, Comms | Which media purposes, limits, scan states, and retention periods apply? | Keep media messages out of MVP until approved. |
| DCQ-11 | No | Comms, Platform | What Redis Stream retention and consumer-group recovery policy is required? | Define environment-specific max length and pending-entry recovery before production. |
| DCQ-12 | No | Comms | Should events add `aggregate_version` for stale-event rejection? | Add it in an event-envelope revision; current events make no ordering guarantee. |
| DCQ-13 | Yes | Admin, Support | Does Admin call Support directly through its BFF or through a DiddiComms compatibility proxy? | BFF calls Support for cases and DiddiComms for task conversations. |
| DCQ-14 | No | Pay, Support | Are refund requests part of the first Support rollout? | Keep read-only payment context in the initial rollout; approve financial mutations separately. |
