from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from minilog.models import CareRecord, ProcessedMutation, SyncChange, SyncState, now_ms

PRUNE_INTERVAL_MS = 60 * 60 * 1000


class SyncCursorExpiredError(ValueError):
    def __init__(self, oldest_valid_cursor: int) -> None:
        super().__init__("sync cursor expired")
        self.oldest_valid_cursor = oldest_valid_cursor


@dataclass(frozen=True)
class SyncPageResult:
    changes: list[SyncChange]
    next_cursor: int
    oldest_valid_cursor: int


def sync_state(db: Session) -> SyncState:
    state = db.get(SyncState, 1)
    if state is None:
        state = SyncState(id=1, oldest_valid_sequence=0)
        db.add(state)
        db.flush()
    return state


def prune_sync_history(db: Session, retention_days: int, *, force: bool = False) -> None:
    state = sync_state(db)
    current_time = now_ms()
    if (
        not force
        and state.last_pruned_at is not None
        and current_time - state.last_pruned_at < PRUNE_INTERVAL_MS
    ):
        return

    cutoff = current_time - retention_days * 24 * 60 * 60 * 1000
    expired_sequence = db.scalar(
        select(func.max(SyncChange.sequence)).where(SyncChange.changed_at < cutoff)
    )
    if expired_sequence is not None:
        db.execute(delete(SyncChange).where(SyncChange.sequence <= expired_sequence))
        state.oldest_valid_sequence = max(state.oldest_valid_sequence, expired_sequence)
    db.execute(delete(ProcessedMutation).where(ProcessedMutation.processed_at < cutoff))
    db.execute(
        delete(CareRecord).where(
            CareRecord.deleted_at.is_not(None),
            CareRecord.deleted_at < cutoff,
        )
    )
    state.last_pruned_at = current_time
    db.commit()


def pull_changes(
    db: Session,
    *,
    after: int,
    limit: int,
    retention_days: int,
) -> SyncPageResult:
    prune_sync_history(db, retention_days)
    state = sync_state(db)
    if after < state.oldest_valid_sequence:
        raise SyncCursorExpiredError(state.oldest_valid_sequence)
    changes = list(
        db.scalars(
            select(SyncChange)
            .where(SyncChange.sequence > after)
            .order_by(SyncChange.sequence)
            .limit(limit)
        ).all()
    )
    return SyncPageResult(
        changes=changes,
        next_cursor=changes[-1].sequence if changes else after,
        oldest_valid_cursor=state.oldest_valid_sequence,
    )
