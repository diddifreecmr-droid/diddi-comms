# MkDocs Docker Deployment

## Purpose

The `docs` container publishes the repository documentation as a standalone
MkDocs Material site. It has no database, Redis, service credentials, or
dependency on the DiddiComms API. It can therefore be deployed and restarted
independently inside the DiddiComms stack.

Two deployment forms are provided:

- `docker-compose.portainer.yml` includes `docs` in the main DiddiComms stack;
- `docker-compose.docs.yml` deploys it as an independent `diddicomms-docs`
  stack.

## Port Exposure

The container listens on port `8000`. Docker publishes it on the host with:

```text
${DIDDICOMMS_DOCS_PORT:-8041}:8000
```

With the default value, teams on the authorized network open:

```text
http://<SERVER_IP>:8041
```

Set this Portainer environment variable to select another host port:

```dotenv
DIDDICOMMS_DOCS_PORT=8041
```

This is a host-port integration. Other Diddi services do not need to join the
DiddiComms Docker network to read the documentation.

## Local Use

Build and start only the documentation service:

```bash
docker compose up -d --build docs
```

Or start the independent documentation stack:

```bash
docker compose -f docker-compose.docs.yml up -d --build
```

Open `http://localhost:8041`. The local Compose file mounts the repository into
the container, so Markdown and `mkdocs.yml` changes are reloaded automatically.

Validate the complete Compose file and build the documentation strictly:

```bash
docker compose config
docker compose run --rm docs mkdocs build --strict
```

## Portainer

The `docker-compose.portainer.yml` file builds `Dockerfile.docs` from the same
Git revision as the API and publishes `DIDDICOMMS_DOCS_PORT`. After changing
documentation, redeploy the stack so the immutable documentation image is
rebuilt from the latest commit.

Recommended Portainer value:

```dotenv
DIDDICOMMS_DOCS_PORT=8041
```

For a fully independent Portainer stack, use:

```text
Name: diddicomms-docs
Repository: https://github.com/diddifreecmr-droid/diddi-comms.git
Reference: refs/heads/main
Compose path: docker-compose.docs.yml
```

Do not expose the port directly to the public Internet unless a firewall,
reverse proxy, or equivalent access policy protects it. The site contains no
runtime secrets, but it documents internal service contracts and operations.

## Health Check

The image performs an HTTP health check against `http://127.0.0.1:8000/`.
Operators can verify the published port with:

```bash
curl http://<SERVER_IP>:8041/
```
