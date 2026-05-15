from fastapi import FastAPI

from openclaw.api.routes import api_router
from openclaw.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI-assisted freelance mission monitoring and proposal workflow.",
)
app.include_router(api_router)


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

