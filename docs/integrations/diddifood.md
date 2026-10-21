# DiddiFood Integration

**Status:** `proposed` for task communication and Support context.

## Status Correction

DiddiSupport documentation currently labels the Food `diddi.context.v1`
contract implemented, but no matching Food provider endpoint was found during
the repository audit. Until provider code, tests, and staging evidence exist,
both connectors remain proposed.

## Ownership And Required Routes

DiddiFood owns order state, restaurant membership, customer identity, courier
assignment, phone data, and communication policy.

```http
GET /internal/v1/comms/tasks/food_order/{order_id}
GET /internal/v1/support/order/{order_id}/context
```

Task communication uses `task_type=food_order`; Support uses
`resource_type=order`. This distinction is explicit and must not be converted
implicitly from arbitrary browser input.

The DiddiComms caller requires audience `diddifood`, subject
`service:diddicomms`, and scope `diddifood:comms-task:read`. The Support caller
uses `service:diddisupport` and `diddifood:support-context:read`.

## Participant And State Decisions Required

The task projection may include `customer`, `restaurant`, and `courier` roles,
but DiddiFood must define whether restaurant communication is direct, mediated,
or excluded. It must enumerate all order states and define:

- when customer-to-restaurant messaging is available;
- when customer-to-courier messaging and calling begin;
- behavior before courier assignment and after reassignment;
- cancellation by each actor;
- rejected and failed orders;
- pickup, delivery, completion, and retention windows.

The bootstrap manifest fails closed until this table is approved.

## Privacy

Task context contains IDs, roles, state, version, policy flags, and optionally
phone numbers for an authorized call attempt. Support context excludes phone
numbers, exact coordinates, restaurant private notes, provider details, and
unrelated financial or kitchen data. Removed fields are listed in
`redacted_fields`.

## Errors And Retry

Both GET routes use the common error envelope. Missing or inaccessible orders
return `404`; unsupported type returns `422`; blocked communication may return
`409`; dependency failure returns `503`. Reads are safe to retry. DiddiComms
fails closed for messages and calls if current order policy cannot be resolved.

## Conformance

Promotion requires provider OpenAPI, auth tests, every-state policy tests,
restaurant-membership tests, courier reassignment tests, privacy tests,
DiddiComms consumer fixtures, DiddiSupport consumer fixtures, and a staging
smoke test. Documentation must not say `implemented` before those gates pass.
