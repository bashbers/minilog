from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from minilog.dependencies import CurrentCaregiver, Database
from minilog.models import SyncChange, SyncState
from minilog.schemas import SyncChangeOut, SyncPage

router = APIRouter(tags=["synchronization"])


@router.get("/sync", response_model=SyncPage)
async def pull_changes(
    _caregiver: CurrentCaregiver,
    db: Database,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SyncPage:
    state = db.get(SyncState, 1)
    oldest_valid = state.oldest_valid_sequence if state else 0
    if after < oldest_valid:
        raise HTTPException(status_code=409, detail="sync_cursor_expired")
    changes = list(
        db.scalars(
            select(SyncChange)
            .where(SyncChange.sequence > after)
            .order_by(SyncChange.sequence)
            .limit(limit)
        ).all()
    )
    next_cursor = changes[-1].sequence if changes else after
    return SyncPage(
        changes=[SyncChangeOut.model_validate(change) for change in changes],
        next_cursor=next_cursor,
        oldest_valid_cursor=oldest_valid,
    )
