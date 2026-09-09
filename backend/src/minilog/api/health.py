from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from minilog.dependencies import Database

router = APIRouter(tags=["health"])
SCHEMA_REVISION = "47ccc6557a5e"


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
