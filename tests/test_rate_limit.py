from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app_base.core.errors import ApiError
from app_base.core.metrics import render_prometheus, reset_metrics
from app_base.core.rate_limit import check_rate_limit, enforce_rate_limit, record_rate_limit_success
from app_base.core.settings import settings


class FakeRedis:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    async def eval(self, *args):
        self.calls.append(("eval", *args))
        return self.result

    async def get(self, key):
        self.calls.append(("get", key))
        return self.result[0]

    async def ttl(self, key):
        self.calls.append(("ttl", key))
        return self.result[1]


def _request(redis) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(redis=redis))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "app": app})


@pytest.mark.asyncio
async def test_rate_limit_allows_request_inside_window() -> None:
    redis = FakeRedis([3, 45])

    await enforce_rate_limit(
        _request(redis),
        bucket="message:user",
        subject="user-1",
        limit=30,
        window_seconds=60,
    )

    assert redis.calls


@pytest.mark.asyncio
async def test_rate_limit_returns_stable_429_and_retry_after() -> None:
    reset_metrics()
    redis = FakeRedis([31, 42])

    with pytest.raises(ApiError) as exc:
        await enforce_rate_limit(
            _request(redis),
            bucket="message:user",
            subject="user-1",
            limit=30,
            window_seconds=60,
        )

    assert exc.value.status_code == 429
    assert exc.value.code == "RATE_LIMIT_EXCEEDED"
    assert exc.value.headers == {"Retry-After": "42"}
    assert 'diddicomms_rate_limit_denials_total{dimension="user",operation="message"} 1' in render_prometheus()


@pytest.mark.asyncio
async def test_rate_limit_debug_details_are_opt_in(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_debug_details", True)
    redis = FakeRedis([31, 42])

    with pytest.raises(ApiError) as exc:
        await enforce_rate_limit(
            _request(redis),
            bucket="support-case:ip",
            subject="127.0.0.1",
            limit=10,
            window_seconds=3600,
        )

    assert exc.value.details == {
        "operation": "support-case",
        "dimension": "ip",
        "limit": 10,
        "window_seconds": 3600,
        "current_count": 31,
        "retry_after_seconds": 42,
    }


@pytest.mark.asyncio
async def test_success_quota_check_does_not_consume_until_recorded() -> None:
    redis = FakeRedis([3, 42])
    request = _request(redis)

    await check_rate_limit(
        request,
        bucket="support-case-success:user",
        subject="user-1",
        limit=10,
        window_seconds=3600,
    )
    await record_rate_limit_success(
        request,
        bucket="support-case-success:user",
        subject="user-1",
        window_seconds=3600,
    )

    assert any(call[0] == "get" for call in redis.calls)
    assert any(call[0] == "eval" for call in redis.calls)
