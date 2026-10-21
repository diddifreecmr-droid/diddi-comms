from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app_base.core.redis import create_redis
from app_base.core.settings import settings


async def replay(*, event_ids: set[UUID], execute: bool) -> int:
    redis = create_redis()
    matched = 0
    try:
        entries = await redis.xrange(settings.support_events_stream, min="-", max="+")
        for stream_id, fields in entries:
            try:
                event_id = UUID(fields.get("event_id", ""))
            except ValueError:
                continue
            if event_id not in event_ids:
                continue
            matched += 1
            print(f"event_id={event_id} stream_id={stream_id} type={fields.get('event_type', '')}")
            if execute:
                await redis.xadd(settings.support_events_stream, fields)
    finally:
        await redis.aclose()
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or replay selected Support events through normal deduplication."
    )
    parser.add_argument("--event-id", action="append", required=True, type=UUID)
    parser.add_argument("--execute", action="store_true", help="Append matching events; default is dry-run.")
    args = parser.parse_args()
    matched = asyncio.run(replay(event_ids=set(args.event_id), execute=args.execute))
    print(f"matched={matched} mode={'execute' if args.execute else 'dry-run'}")


if __name__ == "__main__":
    main()
