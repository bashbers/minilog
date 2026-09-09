from fastapi import APIRouter

from minilog.api import auth, babies, care_records, health, household, sync

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(household.router)
api_router.include_router(babies.router)
api_router.include_router(care_records.router)
api_router.include_router(sync.router)
