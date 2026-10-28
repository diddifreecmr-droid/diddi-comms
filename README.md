# DiddiComms / DiddiConnect

This repository is the planned communication service for the Diddi ecosystem.

Current scope:

- Durable in-app task chat between customers/passengers and drivers/couriers.
- Customer-care chat and support operations.
- MVP external call handoff with durable call-attempt logging.
- Audit, observability, Redis Streams events, and privacy-safe telemetry.

Start here:

- `DIDDICOMMS_MVP_ARCHITECTURE.md` contains the full MVP architecture.
- `docs/IMPLEMENTATION_PLAN_PERSONAS_JOURNEYS_SPECS.md` turns the architecture
  into personas, user journeys, product specs, and implementation phases.
- `docs/SPRINT_PLAN_DIDDICOMMS_MVP.md` breaks the MVP into execution sprints.
- `docs/PORTAINER_ENV_AND_DIDDIGO.md` documents the Portainer environment and
  DiddiGo resolver wiring.
- `docs/PHASE_0_SPEC_QUESTIONS.md` contains the open questions to freeze before
  scaffolding the Phase 0 service foundation.

## Local Development

```bash
cp .env.example .env
docker compose up -d postgres redis
alembic upgrade head
uvicorn app_base.main:app --reload --port 8040
```

Run the documentation site in its dedicated container:

```bash
docker compose up -d --build docs
```

It can also run as its own stack:

```bash
docker compose -f docker-compose.docs.yml up -d --build
```

The site is available at `http://localhost:8041` by default. Set
`DIDDICOMMS_DOCS_PORT` to publish it on another host port. See
`docs/MKDOCS_DOCKER.md` for IP-based and Portainer deployment.

Run the transactional outbox worker separately for Redis delivery:

```bash
python -m app_base.modules.events.worker
```

The same worker also consumes DiddiSupport events through a Redis consumer
group, SQL inbox deduplication, pending-entry reclaim, and a privacy-safe DLQ.
It retries transient Redis/PostgreSQL failures with bounded exponential backoff
and exports outbox age, backlog, consumer lag, retry, and DLQ metrics.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP collector base URL to enable
FastAPI, HTTPX, Redis, and SQLAlchemy traces. Leave it empty for local runs
without a collector.

Operational dry-runs:

```bash
python scripts/operational_check.py --strict
python scripts/reconcile_support_cases.py --limit 100
python scripts/replay_support_events.py --event-id <uuid>
```

Add `--execute` to the replay command only after reviewing its dry-run output.
See `docs/OPERATIONS_RUNBOOK.md` for deployment, recovery, backup/restore, and
rollback procedures.

Staging checks against the deployed DiddiComms and DiddiSupport APIs are
documented in `docs/STAGING_DIDDICOMMS_DIDDISUPPORT_TESTS.md`. They are opt-in
and never import code from another repository.

For schema rollback, stop the API and worker first, run the Alembic downgrade,
deploy matching application code, then restart both processes. Running a newer
worker against a downgraded schema is intentionally unsupported.

Useful endpoints:

- `GET /health`
- `GET /ready`
- `GET /comms/v1/ping`
- `GET /internal/metrics` with
  `Authorization: Bearer local-dev-metrics-token`

## Portainer

Use `docker-compose.portainer.yml` when creating the stack from Git.

Recommended stack settings:

- Name: `diddicomms`
- Repository: `https://github.com/diddifreecmr-droid/diddi-comms.git`
- Reference: `refs/heads/main`
- Compose path: `docker-compose.portainer.yml`
- Environment: `diddifree-prod`

The stack also publishes the dedicated documentation service on
`http://<SERVER_IP>:${DIDDICOMMS_DOCS_PORT:-8041}`.
