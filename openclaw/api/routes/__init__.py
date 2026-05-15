from fastapi import APIRouter

from openclaw.api.routes.health import router as health_router
from openclaw.api.routes.qualification import router as qualification_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(qualification_router)

