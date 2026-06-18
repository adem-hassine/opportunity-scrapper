from fastapi import APIRouter

from openclaw.core.config import get_settings
from openclaw.db.session import check_db_connection

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, object]:
    settings = get_settings()
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "connected" if db_ok else "unreachable",
        **settings.public_summary(),
    }

