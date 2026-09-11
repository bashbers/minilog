from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from minilog.constants import API_CONTRACT_VERSION, SCHEMA_REVISION
from minilog.dependencies import Database
from minilog.schemas import CompatibilityStatus

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: Database) -> dict[str, str]:
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    if revision != SCHEMA_REVISION:
        raise HTTPException(status_code=503, detail="database_revision_mismatch")
    return {"status": "ready", "schema_revision": revision}


@router.get("/health/compatibility", response_model=CompatibilityStatus)
async def compatibility(db: Database) -> CompatibilityStatus:
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="maintenance") from exc
    if revision != SCHEMA_REVISION:
        raise HTTPException(status_code=503, detail="maintenance")
    return CompatibilityStatus(
        api_contract_version=API_CONTRACT_VERSION,
        schema_revision=revision,
    )
