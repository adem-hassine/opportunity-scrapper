from fastapi import APIRouter

from openclaw.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, object]:
    settings = get_settings()
    return {"status": "ok", **settings.public_summary()}

