import logging

from fastapi import FastAPI

from openclaw.api.routes import api_router
from openclaw.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI-assisted freelance mission monitoring and proposal workflow.",
)
app.include_router(api_router)


@app.on_event("startup")
async def _on_startup() -> None:
    from openclaw.db.session import check_db_connection, create_tables  # noqa: PLC0415
    if check_db_connection():
        create_tables()
        logger.info("Database connected and tables verified.")
    else:
        logger.warning("Database unreachable on startup — running without persistence.")


@app.get("/", tags=["meta"])
async def root() -> dict[str, object]:
    return {
        "application": settings.app_name,
        "environment": settings.environment,
        "platforms": settings.platform_targets,
        "workflow": [
            "monitor platforms",
            "apply hard filters",
            "score mission",
            "send Telegram alert",
            "draft proposal",
            "wait for approval",
            "submit",
        ],
    }

