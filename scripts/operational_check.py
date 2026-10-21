from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app_base.core.database import async_session_factory
from app_base.core.redis import create_redis
from app_base.core.settings import settings
from app_base.modules.events.domain import DIDDICOMMS_EVENTS_DLQ_STREAM
from app_base.modules.events.infra.models import OutboxEventModel


async def collect_status() -> dict[str, Any]:
    report: dict[str, Any] = {"service": settings.app_name, "checked_at": _iso(datetime.now(UTC))}
    report["database"] = await _database_status()
    report["redis"] = await _redis_status()
    report["status"] = _overall_status(report)
    return report


async def _database_status() -> dict[str, Any]:
    expected_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    try:
        async with async_session_factory() as session:
            current_revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            pending, oldest = (
                await session.execute(
                    select(func.count(), func.min(OutboxEventModel.created_at)).where(
                        OutboxEventModel.published_at.is_(None),
                        OutboxEventModel.terminal_failure_reason.is_(None),
                    )
                )
            ).one()
            terminal = await session.scalar(
                select(func.count()).select_from(OutboxEventModel).where(
                    OutboxEventModel.terminal_failure_reason.is_not(None)
                )
            )
        oldest_age = max((datetime.now(UTC) - oldest).total_seconds(), 0) if oldest is not None else 0
        return {
            "reachable": True,
            "migration_revision": current_revision,
            "expected_revision": expected_revision,
            "migration_current": current_revision == expected_revision,
            "outbox_pending": int(pending or 0),
            "outbox_oldest_age_seconds": round(oldest_age, 3),
            "outbox_terminal_failures": int(terminal or 0),
        }
    except Exception as exc:
        return {"reachable": False, "failure_type": type(exc).__name__}


async def _redis_status() -> dict[str, Any]:
    redis = create_redis()
    try:
        await redis.ping()
        groups = await redis.xinfo_groups(settings.support_events_stream)
        group = next(
            (item for item in groups if item.get("name") == settings.support_events_consumer_group),
            None,
        )
        return {
            "reachable": True,
            "support_stream_length": await redis.xlen(settings.support_events_stream),
            "consumer_group_present": group is not None,
            "consumer_pending": int(group.get("pending", 0)) if group else None,
            "consumer_lag": _optional_int(group.get("lag")) if group else None,
            "outbound_dlq_length": await redis.xlen(DIDDICOMMS_EVENTS_DLQ_STREAM),
            "inbound_dlq_length": await redis.xlen(settings.inbound_events_dlq_stream),
        }
    except Exception as exc:
        return {"reachable": False, "failure_type": type(exc).__name__}
    finally:
        await redis.aclose()


def _overall_status(report: dict[str, Any]) -> str:
    database = report["database"]
    redis = report["redis"]
    if not database.get("reachable") or not redis.get("reachable"):
        return "unhealthy"
    if not database.get("migration_current") or not redis.get("consumer_group_present"):
        return "unhealthy"
    if (
        database.get("outbox_terminal_failures", 0) > 0
        or redis.get("outbound_dlq_length", 0) > 0
        or redis.get("inbound_dlq_length", 0) > 0
    ):
        return "attention"
    return "healthy"


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only DiddiComms operational readiness check.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when DLQ entries require attention.")
    args = parser.parse_args()
    report = asyncio.run(collect_status())
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] == "unhealthy":
        raise SystemExit(1)
    if args.strict and report["status"] == "attention":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
