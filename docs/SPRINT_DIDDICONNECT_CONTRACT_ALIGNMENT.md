# DiddiConnect Contract Alignment Sprint

**Status:** in review  
**Duration:** 10 working days  
**Owner:** DiddiComms  
**Reference standard:** `docs/diddiconnect/DIDDICONNECT_INTEGRATION_STANDARD_V1.md`  
**Reference implementation:** `E:/DIDDI AI/diddi-support/docs/integrations` and
`E:/DIDDI AI/diddi-support/manifests/diddi-support.v1.json`

## Sprint Goal

Create one complete, versioned contract package that explains how every
relevant DiddiFree module connects to DiddiComms. The result must cover
DiddiFreeID, DiddiSupport, DiddiAdmin, DiddiGo, DiddiSend, DiddiFood,
DiddiFiles, and DiddiPay without pretending that every module plays the same
role.

This sprint produces contracts, manifests, conformance fixtures, and team
decisions. It does not implement messaging, calling, WebSockets, support
workflows, or business-module endpoints.

## Repository Delivery

Implemented in DiddiComms on 2026-10-20:

- expanded multi-role manifest schema;
- canonical `manifests/diddicomms.v1.json`;
- eight peer integration contracts;
- shared task, error, event, and delegated-operator fixtures;
- versioned changelog and blocking-question ledger;
- schema, route, WebSocket, event, evidence, and fixture conformance tests.

The package remains in review because downstream owner approval, missing
provider implementations, identity decisions, and staging evidence cannot be
completed inside the DiddiComms repository.

## Current Baseline

| Module | Current evidence | Contract status entering sprint |
|---|---|---|
| DiddiFreeID | Human JWTs, JWKS, service clients, audiences, and scopes exist | Needs a DiddiComms-specific identity contract |
| DiddiSupport | Service manifest and frozen DiddiComms contract exist | Reuse and reconcile; do not duplicate |
| DiddiAdmin | DiddiComms adapter exists; no explicit Support/Admin integration contract | Missing and blocking |
| DiddiGo | Task communication and Support context resolvers exist | Implemented connector; needs manifest adoption |
| DiddiSend | Support context exists; task communication resolver is absent | Partial |
| DiddiFood | Support documentation claims implementation; matching endpoint was not found | Contract/code status conflict |
| DiddiFiles | Temporary attachment access is documented by Support | Needs FreeID S2S and DiddiComms attachment boundary |
| DiddiPay | Support action contract is proposed | Read-only MVP boundary must be explicit |

## Required Contract Package

The sprint must deliver this structure in DiddiComms:

```text
manifests/
  diddicomms.v1.json

docs/integrations/
  diddifreeid.md
  diddisupport.md
  diddiadmin.md
  diddigo.md
  diddisend.md
  diddifood.md
  diddifiles.md
  diddipay.md

docs/diddiconnect/
  DIDDICONNECT_INTEGRATION_STANDARD_V1.md
  diddiconnect.module.v1.schema.json
  open-questions.md
  changelog.md
  fixtures/
```

The DiddiComms manifest is the service-level source of truth. The focused
integration documents explain each relationship. OpenAPI and AsyncAPI remain
the wire-level sources of truth and are referenced rather than copied into the
manifest.

## Work Items

| ID | Work item | Owner | Points | Depends on |
|---|---|---|---:|---|
| DCX-01 | Expand the manifest schema to model provider, consumer, identity, support, Backoffice, file, and payment roles | DiddiComms | 5 | None |
| DCX-02 | Create `diddicomms.v1.json` with ownership, identity, routes, events, reliability, and compatibility | DiddiComms | 5 | DCX-01 |
| DCX-03 | Reconcile the frozen DiddiSupport contract and define the gateway boundary | Comms + Support | 5 | DCX-01 |
| DCX-04 | Define FreeID clients, audiences, scopes, token rules, and delegated operator identity | Comms + FreeID | 5 | DCX-01 |
| DCX-05 | Define DiddiAdmin BFF, delegated operator, permissions, and audit contract | Comms + Admin + FreeID | 8 | DCX-04 |
| DCX-06 | Certify the DiddiGo task-context manifest and fixtures | Comms + Go | 3 | DCX-01 |
| DCX-07 | Define the missing DiddiSend task-context contract and reconcile Support context | Comms + Send | 3 | DCX-01 |
| DCX-08 | Define DiddiFood task and Support context contracts and resolve status contradiction | Comms + Food | 5 | DCX-01 |
| DCX-09 | Define future attachment boundaries and temporary access with DiddiFiles | Comms + Files | 3 | DCX-01 |
| DCX-10 | Define read-only payment context and exclude financial mutation from messaging MVP | Comms + Pay | 3 | DCX-01 |
| DCX-11 | Add schema, OpenAPI-path, fixture, scope, and state-policy conformance tests | DiddiComms | 5 | DCX-02 through DCX-10 |
| DCX-12 | Cross-team review, freeze v1.0.0, publish changelog, and record unresolved decisions | All | 3 | DCX-11 |

## Contract Rules To Freeze

1. DiddiComms owns conversations, task messages, receipts, call attempts,
   realtime delivery, and communication audits.
2. DiddiSupport owns support cases, support messages, queues, SOS, attachments,
   support actions, and the support timeline.
3. Business modules own resource state, participants, and communication
   policy.
4. DiddiAdmin is a BFF consumer, not a source of business or conversation
   truth.
5. DiddiFreeID is the only issuer of human and service identity.
6. PostgreSQL state is authoritative; Redis Streams and WebSockets are
   delivery mechanisms.
7. Internal calls use service JWTs, `X-Client-ID`, `X-Request-ID`, and W3C
   trace context.
8. Backoffice calls identify both the calling service and delegated human
   operator.
9. Message bodies, phone numbers, tokens, and attachment contents never enter
   ordinary logs, metrics, traces, or generic event envelopes.
10. A connector is not `implemented` until provider tests, consumer tests, and
    a staging smoke test pass.

## Team Handoff Messages

### DiddiFreeID

Please review the DiddiConnect identity requirements and propose the exact
service clients, audiences, scopes, token lifetimes, rotation behavior, and
denial codes for DiddiComms, DiddiSupport, and DiddiAdmin. Define a delegated
operator contract that lets an Admin BFF call downstream services while every
action remains attributable to the human agent. Confirm what already exists,
what must change, and provide token fixtures for provider and consumer
contract tests. Do not implement until the v1 contract is jointly approved.

### DiddiSupport

Please reconcile `manifests/diddi-support.v1.json` and
`docs/integrations/diddicomms.md` with the DiddiConnect v1 standard. Confirm
that DiddiSupport remains the only source of truth for support cases and that
DiddiComms acts as the user messaging gateway. List implemented and missing
internal routes, events, scopes, idempotency behavior, and deployment gaps.
Propose the smallest compatibility plan for existing `/comms/v1/support`
clients without creating a second case database.

### DiddiAdmin

Please define how the Admin BFF connects to DiddiSupport for cases and to
DiddiComms for task conversations. Audit the existing adapter and
`X-Backoffice-Actor` behavior, then propose the service-token and delegated
operator contract, required permissions, pagination, errors, audit fields,
and contract tests. The browser must never receive service credentials or
impersonate a customer. Identify stale UI assumptions and routes that must be
migrated.

### DiddiGo

Please adopt the DiddiConnect module manifest for `ride` and verify it against
the existing task communication and Support context endpoints. Confirm every
ride state, participant role, messaging/calling decision, completed-ride grace
period, privacy exclusion, error, scope, and test path. Provide approved
request/response fixtures for DiddiComms consumer tests and record the staging
smoke-test evidence.

### DiddiSend

Please inspect the implemented delivery Support context and design the missing
`GET /internal/v1/comms/tasks/delivery/{delivery_id}` resolver. Declare all
delivery states, participant and reassignment rules, messaging/calling
decisions, privacy fields, scope, errors, and closure behavior. Reconcile the
new task contract with the existing `diddi.context.v1` response and provide
fixtures and implementation sequencing.

### DiddiFood

Please verify repository reality against the current DiddiSupport documentation
that marks Food context as implemented. Define the order task resolver and
Support context endpoint, including customer, restaurant, and courier roles;
assignment changes; cancellation and completion behavior; privacy exclusions;
scopes; errors; and tests. Correct the status to `proposed` if the provider
endpoint is not implemented, and identify the work required before promotion.

### DiddiFiles

Please define the future DiddiComms and DiddiSupport attachment boundary using
`file_id` references and temporary access only. Propose FreeID S2S scopes,
upload purpose values, ownership checks, MIME and size limits, quarantine and
scan states, expiration, retention, deletion, errors, and audit events. Public
or permanent file URLs and static shared tokens are not acceptable in the v1
target contract.

### DiddiPay

Please define a privacy-minimized, read-only support context contract for
payment references linked to a conversation or support case. Separate this
from refund, reversal, or other financial mutations. For any future mutation,
specify delegated operator attribution, strong idempotency, approval rules,
immutable audit evidence, timeout recovery, and result confirmation. Financial
mutation remains outside the messaging MVP unless separately approved.

## Ten-Day Sequence

| Day | Outcome |
|---:|---|
| 1 | Inventory current routes, manifests, scopes, events, and contradictions |
| 2 | Agree manifest roles and update the schema proposal |
| 3 | Draft the canonical DiddiComms service manifest |
| 4 | Freeze FreeID and DiddiSupport relationships |
| 5 | Freeze DiddiAdmin delegated Backoffice relationship |
| 6 | Certify DiddiGo and draft DiddiSend contracts |
| 7 | Draft DiddiFood and resolve its implementation-status conflict |
| 8 | Draft Files and Pay boundaries; assemble shared fixtures |
| 9 | Run provider/consumer conformance review and close blocking questions |
| 10 | Approve v1.0.0, publish changelog, and prepare implementation backlog |

## Acceptance Criteria

- `manifests/diddicomms.v1.json` validates against the approved schema.
- All eight integration documents exist and identify producer, consumer,
  audience, caller, scopes, routes, events, errors, retries, ownership, and
  current implementation status.
- DiddiSupport's existing manifest is referenced and reconciled, not copied
  into a contradictory DiddiComms-owned contract.
- DiddiAdmin has an explicit BFF and delegated-operator contract.
- Go, Send, and Food each have state-by-state messaging and calling policy.
- Every `implemented` declaration has provider tests, consumer fixtures, and
  staging evidence.
- The Food documentation/code contradiction is resolved.
- Cross-service error envelopes and event envelopes are frozen and versioned.
- Unknown decisions are recorded in `open-questions.md`; no unknown is silently
  represented as implemented.
- Schema validation, contract tests, Ruff, and `git diff --check` pass.

## Definition Of Done

The sprint is complete when every team has reviewed its connection document,
the DiddiComms and DiddiSupport owners agree on data ownership, FreeID approves
all identity contracts, Admin approves the delegated operator flow, and the
versioned package is sufficient to create implementation tickets without
inventing routes, scopes, payloads, or authorization behavior.

## Out Of Scope

- Implementing missing owner-module endpoints.
- Migrating existing support records.
- Building Admin screens.
- Implementing Redis workers, WebSockets, push notifications, or VoIP.
- Adding media messages or production attachment uploads.
- Executing refunds or other financial mutations.
