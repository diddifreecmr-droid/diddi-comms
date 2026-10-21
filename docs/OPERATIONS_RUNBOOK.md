# DiddiComms Operations Runbook

## Scope

This runbook covers API and worker deployment, schema migration, dependency
failure, outbox and consumer recovery, backup/restore validation, and rollback.
It does not authorize deletion of messages, audits, or Support records.

## Pre-Deployment Gate

1. Stop the worker before any schema downgrade. Keep it running during normal
   forward-compatible upgrades only when the migration has been reviewed for
   mixed-version safety.
2. Back up PostgreSQL and the Redis AOF/volume using the platform's approved
   encrypted backup mechanism.
3. Run `alembic current` and `alembic heads`; there must be one head.
4. Run `python scripts/operational_check.py --strict` against the target
   environment. Exit code `1` means unavailable or structurally unsafe. Exit
   code `2` means DLQ or terminal outbox records require review.
5. Validate `/health`, `/ready`, and authenticated `/internal/metrics`.

## Deployment Order

1. Apply secrets and configuration without printing their values.
2. Deploy the API image and execute `alembic upgrade head` exactly once.
3. Wait for `/ready` to report PostgreSQL and Redis as `ok`.
4. Deploy the worker from the same immutable image.
5. Confirm `diddicomms_worker_last_success_unixtime` advances and
   `diddicomms_worker_consecutive_failures` returns to zero.
6. Run the operational check and a synthetic create/message/read flow.

## Failure Triage

### PostgreSQL unavailable

- Expect `/ready` to return `503`; do not route new traffic to the instance.
- The worker retries with bounded exponential backoff and must not be manually
  restarted in a tight loop.
- After recovery, verify migration revision, outbox age, and terminal failures.

### Redis unavailable

- Expect `/ready` to return `503`; HTTP writes already committed to PostgreSQL
  remain in the transactional outbox.
- After recovery, confirm the outbox backlog drains and consumer lag returns to
  zero. Do not delete stream entries to accelerate recovery.

### Outbox terminal failure or DLQ growth

- Inspect only event IDs, event types, timestamps, aggregate IDs, and safe
  failure types. Do not paste message bodies, tokens, phone numbers, or signed
  URLs into tickets.
- Correct the dependency or contract failure before replay.
- Use `python scripts/replay_support_events.py --event-id <uuid>` as a dry-run.
  Add `--execute` only after review; inbox deduplication remains active.

### Support projection divergence

- Run `python scripts/reconcile_support_cases.py --limit 100`.
- Treat DiddiSupport as authoritative. Never overwrite remote state from the
  local projection during incident response.

## Backup And Restore Drill

1. Record image digest, Alembic revision, backup identifier, and Redis snapshot
   identifier in the drill ticket.
2. Restore into an isolated environment with outbound integrations disabled.
3. Start PostgreSQL and Redis, then run `alembic current` and the operational
   check before starting API or worker traffic.
4. Verify conversation, participant, delivery, audit, outbox, and processed
   event counts against the backup manifest.
5. Start one worker, confirm pending entries are reclaimed, and verify no
   duplicate user-visible action is produced.
6. Destroy the isolated restore environment according to the approved data
   handling policy.

## Rollback

Application rollback is preferred when the previous image understands the
current schema. For a schema rollback:

1. Remove API traffic and stop every worker.
2. Take a fresh backup.
3. Run the reviewed `alembic downgrade <revision>` command.
4. Deploy the matching previous API and worker image.
5. Run the operational check, readiness checks, and synthetic journey before
   restoring traffic.

Never run a newer worker against a downgraded schema.

## Required Evidence

Keep timestamps and safe identifiers for the image digest, migration revision,
backup/restore result, operational-check output, synthetic journey, outbox age,
consumer lag, DLQ counts, and rollback decision. Secrets and communication
content are forbidden in operational evidence.
