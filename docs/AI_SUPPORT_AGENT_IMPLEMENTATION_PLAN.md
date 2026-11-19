# DiddiComms AI support agent plan

## Responsibility boundary

DiddiComms owns the support conversation and all messages. DiddiSupport owns
the support case lifecycle. The AI is a DiddiComms participant; it does not
create a second case and does not call DiddiSupport as a separate user.

## Lots

1. **Identity and attribution** — expose `sender_role` and distinguish `user`,
   `ai`, `support_agent`, and `admin`. Completed.
2. **AI response loop** — after a committed user message, run the decision gate
   and generate one asynchronous AI reply in the existing conversation.
3. **Context handoff** — publish an outbox event referencing the existing case,
   conversation, source message, AI message, and category. No duplicate case.
4. **Human takeover** — consume the support handoff/assignment signal and stop
   AI replies as soon as an agent or admin is an active participant.
5. **Staging verification** — test user message, AI reply, replay/idempotency,
   context event, human takeover, and provider failure.

The AI remains disabled by default with `AI_ENABLED=false`.
