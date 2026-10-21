from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app_base.core.errors import ApiError
from app_base.core.metrics import render_prometheus, reset_metrics
from app_base.core.rate_limit import enforce_rate_limit


class FakeRedis:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.result


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
