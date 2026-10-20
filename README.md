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

Run the transactional outbox worker separately for Redis delivery:

```bash
python -m app_base.modules.events.worker
```

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
