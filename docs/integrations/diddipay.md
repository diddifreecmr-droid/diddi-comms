# DiddiPay Integration

**Status:** `proposed` for DiddiComms; DiddiPay's Support contract exists.  
**MVP rule:** DiddiComms does not execute refunds or other financial mutations.

## Ownership And Routing

DiddiPay owns payment intent, refund, provider, ledger, and settlement state.
DiddiSupport owns support cases, operator decisions, requested actions, and
their timeline. DiddiComms transports user-visible conversation content only.

For the messaging MVP, payment context is reached through DiddiSupport rather
than by adding a direct DiddiComms-to-DiddiPay connector.

## Existing Read Contract

```http
GET /payfund/v1/internal/support/payment/{payment_intent_id}/context
```

The caller uses audience `diddipay`, an allowlisted client ID, and scope
`diddipay:support-context:read`. The projection excludes payer/payee IDs,
phone numbers, provider references and payloads, callback URLs, credentials,
metadata, and ledger details. Unknown payment returns
`PAYMENT_CONTEXT_NOT_FOUND`.

## Financial Mutations

DiddiPay also documents delegated refund requests, but they are outside the
DiddiComms MVP. Any future Support-initiated refund requires a distinct scope,
operator and delegation identifiers, a stable command ID, idempotency key,
reason, immutable DiddiPay audit, and durable result reconciliation.

DiddiComms must never infer that a refund succeeded from a message or timeout.
Only DiddiPay's authoritative state or signed result event can establish the
outcome.

## Retry And Events

Payment-context GET is safe to retry. A financial command, if separately
approved later, retries only with the original key and payload. Timeout remains
`unknown` until read-back or a durable result event confirms terminal state.

Documented result events include:

```text
diddipay.refund.succeeded.v1
diddipay.refund.failed.v1
diddipay.refund.unknown.v1
```

Consumers acknowledge only after durable processing and deduplicate by event
ID.

## Conformance

The contract suite must prove privacy minimization, owner-scoped lookup,
missing-scope denial, wrong-client denial, timeout handling, event
deduplication, and the absence of financial mutation routes from the
DiddiComms public and Backoffice APIs.
