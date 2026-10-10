# Portainer Environment And DiddiGo Wiring

## Portainer Stack

Stack:

- Name: `diddi-comms`
- Environment: `diddifree-prod`
- Repository: `https://github.com/diddifreecmr-droid/diddi-comms.git`
- Reference: `refs/heads/main`
- Compose path: `docker-compose.portainer.yml`
- Public API: `https://messaging.diddifree.com` or `http://169.58.70.37:8040`

Configured environment keys:

- `ENVIRONMENT=staging`
- `LOG_LEVEL=INFO`
- `DIDDICOMMS_POSTGRES_DB`
- `DIDDICOMMS_POSTGRES_USER`
- `DIDDICOMMS_POSTGRES_PASSWORD`
- `DIDDICOMMS_API_PORT=8040`
- `IDENTITY_ISSUER=diddifree-id`
- `IDENTITY_JWKS_URL=https://auth-staging.diddifree.com/identity/v1/.well-known/jwks.json`
- `IDENTITY_SERVICE_TOKEN_URL=https://auth-staging.diddifree.com/identity/v1/auth/service/token`
- `METRICS_BEARER_TOKEN`
- `OWNER_SERVICE_RESOLVERS_JSON`
- `OTEL_EXPORTER_OTLP_ENDPOINT`

Do not commit secret values. Keep the database password, metrics token, and
owner resolver client secrets only in Portainer or a later secret manager.

## DiddiGo Resolver Entry

`OWNER_SERVICE_RESOLVERS_JSON` contains a `diddigo` entry with this shape:

```json
{
  "diddigo": {
    "base_url": "https://go-staging.diddifree.com",
    "client_id": "diddicomms-staging-diddigo",
    "client_secret": "<stored only in Portainer>",
    "audience": "diddigo",
    "scope": "diddigo:comms-task:read"
  }
}
```

The matching DiddiFreeID service client must be active:

- Client ID: `diddicomms-staging-diddigo`
- Service: `diddicomms`
- Environment: `staging`
- Allowed audience: `diddigo`
- Allowed scope: `diddigo:comms-task:read`

## DiddiGo Service Changes

DiddiGo must expose this internal resolver endpoint:

```http
GET /internal/v1/comms/tasks/{task_type}/{task_id}
Authorization: Bearer <service-token>
X-Client-ID: diddicomms-staging-diddigo
```

For the first slice:

- `task_type=ride`
- `task_id=<ride uuid>`
- Required audience: `diddigo`
- Required scope: `diddigo:comms-task:read`
- Expected subject: `service:diddicomms`

The endpoint returns the communication context for the ride: task reference,
state, version, participants by `user_id`, channel permissions, and optional
`closes_at`. DiddiComms stores the conversation against
`owner_service + task_type + task_id`, not against a DiddiGo-specific table.

Current integration signal:

- DiddiComms can obtain a service token for DiddiGo.
- `https://go-staging.diddifree.com/internal/v1/comms/tasks/ride/<uuid>`
  currently returns `404`, which means the DiddiGo resolver route still needs
  to be deployed on the DiddiGo staging backend.

## Smoke Checks

After Portainer redeploy:

```bash
curl http://169.58.70.37:8040/health
curl http://169.58.70.37:8040/ready
curl http://169.58.70.37:8040/comms/v1/ping
curl -H "Authorization: Bearer $METRICS_BEARER_TOKEN" \
  http://169.58.70.37:8040/internal/metrics
```

After DiddiGo route deployment:

```bash
curl -H "Authorization: Bearer $DIDDICOMMS_TO_DIDDIGO_TOKEN" \
  -H "X-Client-ID: diddicomms-staging-diddigo" \
  https://go-staging.diddifree.com/internal/v1/comms/tasks/ride/<ride-id>
```

