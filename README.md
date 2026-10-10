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
- `docs/PHASE_0_SPEC_QUESTIONS.md` contains the open questions to freeze before
  scaffolding the Phase 0 service foundation.

## Local Development

```bash
cp .env.example .env
docker compose up -d postgres redis
alembic upgrade head
uvicorn app_base.main:app --reload --port 8040
```

Useful endpoints:

- `GET /health`
- `GET /ready`
- `GET /comms/v1/ping`
- `GET /internal/metrics` with
  `Authorization: Bearer local-dev-metrics-token`
