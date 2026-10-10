# DiddiComms Phase 0 Spec Questions

**Status:** Draft specification with initial decisions  
**Service repository:** `diddicomms`  
**Canonical architecture:** `DIDDICOMMS_MVP_ARCHITECTURE.md`  
**Goal:** Freeze the service foundation before coding Phase 0.

Phase 0 is not the chat feature itself. It is the foundation that makes the
chat feature safe to build: repository shape, service identity, configuration,
contracts, migrations, observability, deployment assumptions, and local
development workflow.

## 1. Service Name and Repository

Draft default:

- Public product name: `DiddiComms`
- Technical service name: `diddicomms`
- Python package name: `diddicomms`
- API base path: `/comms/v1`
- Internal service audience: `diddicomms`

Decisions:

1. User-facing name: **DiddiComms**.
2. Repository name: `diddicomms`.
3. API routes: `/comms/v1`.
4. Service-token audience: `diddicomms`.

## 2. First Vertical Slice

Draft default:

- First product integration: DiddiGo
- Reason: rider-driver contact is already identified as an out-of-app gap.
- Food and Send adopt the same context resolver contract after the DiddiGo
  slice is proven.

Decisions:

1. First vertical slice: DiddiGo.
2. Next slices: DiddiSend, then DiddiFood.
3. Phase 0 includes configuration placeholders for all three owner services,
   while the first concrete contract work targets DiddiGo.

## 3. Runtime and Framework

Draft default based on nearby Diddi services:

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- `psycopg`
- `redis`
- `httpx`
- `PyJWT[crypto]`
- Prometheus client
- OpenTelemetry OTLP HTTP exporter
- Uvicorn
- Ruff and pytest for development

Decisions:

1. Runtime/framework: Python/FastAPI.
2. Baseline: DiddiGo-style modular service, cleaned up for stricter module
   boundaries and DRY shared core code.
3. Repository is initialized as a git repository.
4. Package layout follows the DiddiGo convention with `app_base/` as package
   root and feature modules under `app_base/modules`.

## 4. Datastores

Draft default:

- PostgreSQL as source of truth.
- Redis Streams for durable async events.
- Redis keys for presence, rate limits, and short-lived context cache.
- No SQLite fallback for the service MVP unless needed for tests.

Decisions:

1. Local PostgreSQL database name: `diddicomms_local`.
2. Redis namespace prefix: `diddicomms`.
3. Local development uses Docker Compose with Postgres and Redis.
4. Test storage strategy remains open; Phase 0 unit tests avoid requiring
   Postgres/Redis unless explicitly marked integration.

## 5. Authentication and Service Tokens

Draft default:

- User tokens are FreeID JWTs verified locally through JWKS.
- Service-to-service calls use DiddiFreeID client credentials.
- Human endpoints reject service tokens.
- Internal endpoints reject human tokens.
- `X-Client-ID` must match the JWT `client_id` claim for service tokens.

Decisions:

1. Accepted issuer: `diddifree-id`.
2. User-token audience: `diddicomms`.
3. JWKS URL variable: `IDENTITY_JWKS_URL`.
4. Outbound service-token URL variable: `IDENTITY_SERVICE_TOKEN_URL`.
5. Support-agent capability name remains open; current draft:
   `diddicomms/support_agent`.
6. Phase 0 includes auth helper scaffolding. FreeID provisioning scripts/specs
   remain a follow-up unless needed before Phase 1.

## 6. Context Resolver Contract

Draft default:

Each owner service exposes:

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
Authorization: Bearer <DiddiComms service JWT>
X-Client-ID: diddicomms-<environment>-<target>
X-Request-ID: <correlation id>
```

The response contains a task reference, state, version, participants, phone
numbers for call handoff, and messaging/calling policy.

Decisions:

1. Resolver endpoints include the owner task type in the path:
   `/internal/v1/comms/tasks/{task_type}/{task_id}`.
2. DiddiComms uses a generic owner resolver registry from
   `OWNER_SERVICE_RESOLVERS_JSON`; it does not hard-code `ride -> DiddiGo`,
   `delivery -> DiddiSend`, or `food_order -> DiddiFood`.
3. Resolver responses include canonical `user_id` and product-local participant
   roles such as `passenger`, `driver`, `customer`, and `courier`.
4. For the direct-call MVP, resolver responses may include `phone_e164`. The
   value must not be stored in DiddiComms tables or operational telemetry.
5. Context resolver caching remains open for Phase 1. Draft maximum TTL:
   30 seconds.

See `docs/CONTEXT_RESOLVER_CONTRACT.md` for the current contract.

## 7. Phase 0 API Surface

Draft default:

- `GET /health`
- `GET /ready`
- `GET /internal/metrics`
- `GET /comms/v1/ping`
- `GET /comms/v1/auth/debug` only in local/dev, if useful for token testing

Questions:

1. Phase 0 exposes platform endpoints and `/comms/v1/ping`.
2. `/internal/metrics` requires `METRICS_BEARER_TOKEN`.
3. Metrics token is required everywhere, including local/dev.

## 8. Observability

Draft default:

- JSON logs on stdout.
- `X-Request-ID` generated or propagated on every request.
- `X-Trace-ID` returned when tracing is active.
- No message bodies, phone numbers, auth headers, push tokens, or resolver full
  responses in logs.
- Prometheus metrics use route templates and low-cardinality labels.
- OpenTelemetry traces cover inbound HTTP, outbound HTTPX, Postgres, Redis, and
  background workers.

Questions:

1. What should the service name be in traces and metrics? Draft:
   `diddicomms`.
2. Do we already have a central OTLP collector endpoint per environment?
3. Do we already have a central log collector, or should Phase 0 only output
   JSON logs to stdout?
4. Should we copy the DiddiSend observability profile pattern with local
   Prometheus and Jaeger?

## 9. Redis Streams and Outbox

Draft default:

- Stream: `diddicomms.events`
- DLQ stream: `diddicomms.events.dlq`
- Consumer groups:
  - `diddicomms-realtime`
  - `diddicomms-push`
  - `diddicomms-support-sla`
  - `diddicomms-analytics`

Questions:

1. Stream prefix decision: `diddicomms`.
2. Phase 0 implements the outbox table and write helper now. Dispatcher worker
   remains a skeleton/follow-up before Phase 1 live delivery.
3. Should workers run in the same container initially, or as separate
   deployment processes from day one?
4. What stream retention policy should local/staging/prod use?

## 10. Database and Migrations

Draft default:

Phase 0 migrations create only foundation tables:

- `schema_migrations` via Alembic
- optional `outbox_events`
- optional `audit_events`
- optional `processed_events`

Feature tables for conversations, messages, calls, and support arrive in
later phases unless we decide to prepare all schemas now.

Questions:

1. Should Phase 0 create all core tables from the architecture doc, or only the
   foundation tables needed for outbox/audit readiness?
2. Should IDs be UUID primary keys everywhere?
3. Should timestamps use `TIMESTAMPTZ` and UTC only?
4. Should audit append-only guarantees be enforced in code only for MVP, or
   also with database permissions/triggers in Phase 0?

## 11. Deployment and Environments

Draft default:

- Environments: `local`, `staging`, `production`
- Config via environment variables.
- Dockerfile and Docker Compose included.
- No secrets in `.env.example`.

Questions:

1. Where will this service run first: local Compose, Portainer staging, or both?
2. Which public/staging hostname should be reserved? Draft:
   `comms-staging.diddifree.com`.
3. Should the service be deployed as one API container plus worker containers,
   or one combined MVP container first?
4. Should readiness fail when Redis is unavailable, even though writes can
   still commit to Postgres/outbox? Draft: fail readiness for Phase 0.

## 12. Security and Privacy Baseline

Draft default:

- No message content or phone numbers in operational telemetry.
- No phone numbers stored in conversation or audit tables.
- External call attempts are recorded before returning a `tel:` action.
- Direct phone number exposure is explicitly accepted only for MVP.

Decision:

1. Direct-number external calls are accepted for the MVP pilot, with a
   first-use privacy warning and durable call-attempt audit before returning
   `tel:`.
2. What countries are in the first pilot, and do they change retention/privacy
   requirements?
3. Who is allowed to read message content in support/admin tools?
4. Should Phase 0 include a written log-redaction test suite before feature
   development starts?

## 13. Local Developer Experience

Draft default:

- `README.md` with local setup.
- `.env.example` with non-secret placeholders only.
- `docker-compose.yml` for Postgres, Redis, API, and optional observability.
- `pytest`, `ruff`, and `alembic` commands documented.

Questions:

1. Do you want a one-command local boot with Docker Compose?
2. Should local Compose include Jaeger and Prometheus by default or behind an
   `observability` profile?
3. Should we include Bruno/Postman contract tests in Phase 0?
4. Should this repo include an `AGENTS.md` with implementation conventions?

## 14. Phase 0 Acceptance Criteria

Draft acceptance criteria:

1. The repo has a runnable FastAPI service with `/health`, `/ready`, and
   protected `/internal/metrics`.
2. Configuration is validated at startup and refuses production with insecure
   defaults.
3. FreeID JWKS verification helpers exist for user tokens and service tokens.
4. Outbound service-token client helpers exist for configured owner services.
5. PostgreSQL and Redis health checks are covered.
6. JSON logs, request IDs, metrics, and OTLP tracing are wired.
7. Alembic is configured and at least one foundation migration runs.
8. Outbox/Redis stream naming and worker process model are documented.
9. No secrets are committed, and `.env.example` contains placeholders only.
10. Phase 1 contracts are frozen enough to begin durable task chat.

Questions:

1. Are these acceptance criteria enough for Phase 0?
2. Which criteria should block coding Phase 1?
3. What deadline or milestone name should we attach to Phase 0?
