from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from minilog.config import get_settings
from minilog.dependencies import CurrentCaregiver, Database
from minilog.schemas import (
    SyncChangeOut,
    SyncCursorExpiredDetail,
    SyncCursorExpiredResponse,
    SyncPage,
)
from minilog.services.synchronization import SyncCursorExpiredError
from minilog.services.synchronization import pull_changes as query_changes

router = APIRouter(tags=["synchronization"])


@router.get(
    "/sync",
    response_model=SyncPage,
    responses={409: {"model": SyncCursorExpiredResponse}},
)
async def pull_changes(
    _caregiver: CurrentCaregiver,
    db: Database,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SyncPage:
    try:
        page = query_changes(
            db,
            after=after,
            limit=limit,
            retention_days=get_settings().sync_tombstone_days,
        )
    except SyncCursorExpiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=SyncCursorExpiredDetail(
                oldest_valid_cursor=exc.oldest_valid_cursor
            ).model_dump(),
        ) from exc
    return SyncPage(
        changes=[SyncChangeOut.model_validate(change) for change in page.changes],
        next_cursor=page.next_cursor,
        oldest_valid_cursor=page.oldest_valid_cursor,
    )
