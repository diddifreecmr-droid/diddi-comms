from fastapi import APIRouter

from app_base.core.settings import settings

router = APIRouter(tags=["platform"])


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "api": settings.api_prefix}

