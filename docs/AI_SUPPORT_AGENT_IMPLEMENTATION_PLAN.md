# DiddiComms AI support agent plan

## Responsibility boundary

DiddiSupport is the source of truth for support cases and support messages.
DiddiComms owns the public conversation surface and calls DiddiSupport through
its internal service contract. The AI is attributed as an assistant message;
it must never be written using the user-message payload.

## Lots

1. **Identity and attribution** — expose `sender_role` and distinguish `user`,
   `ai`, `support_agent`, and `admin`. Implemented in the public mapper.
2. **AI response loop** — after a committed user message, run the decision gate
   and generate one asynchronous AI reply. Implemented in DiddiComms.
   The decision gate distinguishes `support_allowed`, `needs_clarification`,
   `needs_human`, and `out_of_scope`. Clarification prompts must request only
   user-provided facts that are missing; linked task identifiers already known
   by DiddiComms must not be requested from the user.
3. **Support write contract** — send the reply to DiddiSupport with
   `author_type=ai`; fail closed until DiddiSupport enables the contract.
4. **Context handoff** — publish an outbox event referencing the existing case,
   conversation, source message, AI message, and category. Implemented.
5. **Human takeover** — use the existing Support assignment/resolution event
   projection and stop AI when an assignee/admin is active. Implemented in the
   DiddiComms consumer; staging verification remains.
6. **Staging verification** — test user message, AI reply, replay/idempotency,
   context event, human takeover, and provider failure.

Every successful AI write is audited as `support.ai_message.created` with the
case, conversation, source message, category, and remote message ID. Message
bodies, prompts, provider responses, and credentials are not written to audit
metadata or logs.

The AI remains disabled by default with `AI_ENABLED=false`.

## Sprint tracking

### Sprint 1 — Identity and safe attribution — DONE

- Public message responses expose `user`, `ai`, `support_agent`, `admin`, and
  `system` sender types.
- Remote Support authors are mapped without exposing internal IDs as role
  logic.
- AI replies can never use the user-message payload.

### Sprint 2 — AI decision and response loop — DONE IN DIDDICOMMS

- User messages and initial support messages schedule asynchronous AI work.
- Jev remains the decision gate.
- OpenRouter uses the configured primary model and fallback model.
- `needs_clarification` generates one concise question through the existing AI
  message contract; it does not create another case.
- Known linked task references are included as internal prompt context and are
  never requested from the user.
- Human takeover and resolved/closed cases stop AI processing.

### Sprint 3 — DiddiSupport assistant-message contract — DONE

- DiddiComms implements the client method and idempotency key.
- The response must preserve `author_type` as `ai`, `assistant`, or
  `diddicomms`.
- DiddiSupport accepts and persists the attributed payload.
- The staging deployment must set `DIDDISUPPORT_AI_MESSAGES_ENABLED=true`.

### Sprint 4 — Audit and event handoff — DONE IN DIDDICOMMS

- Successful AI writes create a safe audit event.
- `comms.support.ai_context_updated.v1` contains only case, conversation,
  source-message, AI-message, and category identifiers.
- Outbox delivery remains responsible for retry and dead-letter behavior.

### Sprint 5 — Staging verification — IN PROGRESS

The opt-in staging test is now present in
`tests/staging/test_diddicomms_diddisupport_staging.py` and is enabled with
`RUN_STAGING_AI_TESTS=1`.

Run only after DiddiSupport confirms the assistant-message contract:

1. create a general support conversation with an initial message;
2. verify the user message and AI reply are both visible;
3. verify the reply is attributed as `ai`, never `user`;
4. replay the same request and verify no duplicate reply;
5. assign a human agent and verify no later AI reply is created;
6. resolve the case and verify the conversation is read-only;
7. verify audit, outbox, retry, and failure behavior.

## Explicit next action

The next implementation action inside DiddiComms is staging verification and
hardening based on the observed DiddiSupport response. No new DiddiComms route
or local message table is to be created for AI replies.
