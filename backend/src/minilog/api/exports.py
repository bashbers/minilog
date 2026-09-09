from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from minilog.dependencies import Database, Owner
from minilog.models import Baby
from minilog.services.exports import build_minilog_export, build_timeline_csv

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/minilog")
async def export_minilog(_owner: Owner, db: Database) -> Response:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=build_minilog_export(db),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="minilog-export-{stamp}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/timeline.csv")
async def export_timeline_csv(baby_id: UUID, _owner: Owner, db: Database) -> Response:
    if db.get(Baby, str(baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content="\ufeff" + build_timeline_csv(db, str(baby_id)),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="minilog-timeline-{stamp}.csv"',
            "Cache-Control": "no-store",
        },
    )
