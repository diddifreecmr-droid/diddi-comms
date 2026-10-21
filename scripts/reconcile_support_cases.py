from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app_base.core.database import async_session_factory
from app_base.modules.conversations.infra.models import SupportCaseModel
from app_base.modules.support.factory import diddisupport_read_client

COMPARABLE_FIELDS = ("status", "priority", "assigned_to_user_id")


async def reconcile(*, limit: int) -> list[dict]:
    client = diddisupport_read_client()
    async with async_session_factory() as session:
        result = await session.execute(select(SupportCaseModel).order_by(SupportCaseModel.created_at).limit(limit))
        cases = list(result.scalars().all())

    report = []
    for case in cases:
        remote = await client.get_case_context(case.external_case_id)
        differences = {}
        for field in COMPARABLE_FIELDS:
            local_value = getattr(case, field)
            remote_value = remote.case.get(field)
            local_text = str(local_value) if local_value is not None else None
            remote_text = str(remote_value) if remote_value is not None else None
            if local_text != remote_text:
                differences[field] = {"local": local_text, "remote": remote_text}
        report.append(
            {
                "case_id": str(case.id),
                "external_case_id": str(case.external_case_id),
                "projection_status": "diverged" if differences else "synced",
                "differences": differences,
            }
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Report DiddiComms/DiddiSupport projection divergence.")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    report = asyncio.run(reconcile(limit=min(max(args.limit, 1), 10_000)))
    print(json.dumps({"cases": report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
