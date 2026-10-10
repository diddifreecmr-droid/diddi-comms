from fastapi.testclient import TestClient

from app_base.main import app

client = TestClient(app)


def test_ping_uses_comms_prefix() -> None:
    response = client.get("/comms/v1/ping")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "DiddiComms", "api": "/comms/v1"}


def test_metrics_requires_bearer_token() -> None:
    response = client.get("/internal/metrics")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "METRICS_FORBIDDEN"


def test_metrics_accepts_configured_bearer_token() -> None:
    response = client.get("/internal/metrics", headers={"Authorization": "Bearer local-dev-metrics-token"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")

