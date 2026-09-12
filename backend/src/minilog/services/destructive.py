from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from minilog.database import commit_private_changes
from minilog.models import (
    AuthSession,
    Baby,
    Caregiver,
    CaregiverQuickAction,
    CareRecord,
    Household,
    ImportBatch,
    ImportedDailyNote,
    Invitation,
    ProcessedMutation,
    SyncChange,
    SyncOperation,
    SyncState,
    now_ms,
)
from minilog.security import hash_password, new_token


class DestructiveCommandError(RuntimeError):
    pass


class BabyNotFoundError(DestructiveCommandError):
    pass


class HouseholdNotFoundError(DestructiveCommandError):
    pass


class ConfirmationMismatchError(DestructiveCommandError):
    pass


class ExportAcknowledgementRequiredError(DestructiveCommandError):
    pass


class CaregiverNotFoundError(DestructiveCommandError):
    pass


class CurrentOwnerMutationError(DestructiveCommandError):
    pass


class CaregiverMustBeInactiveError(DestructiveCommandError):
    pass


class CaregiverIdentityAlreadyErasedError(DestructiveCommandError):
    pass


def permanently_delete_baby(
    db: Session,
    baby_id: str,
    confirmation: str,
    export_acknowledged: bool,
) -> None:
    baby = db.get(Baby, baby_id)
    if baby is None:
        raise BabyNotFoundError
    if not export_acknowledged:
        raise ExportAcknowledgementRequiredError
    if confirmation != baby.display_name:
        raise ConfirmationMismatchError

    record_ids = select(CareRecord.id).where(CareRecord.baby_id == baby_id)
    db.execute(
        delete(ProcessedMutation).where(
            ProcessedMutation.entity_kind == "care_record",
            ProcessedMutation.entity_id.in_(record_ids),
        )
    )
    db.execute(
        delete(SyncChange).where(
            SyncChange.entity_kind == "care_record",
            SyncChange.entity_id.in_(record_ids),
        )
    )
    db.delete(baby)
    commit_private_changes(db)


def permanently_delete_household(db: Session, confirmation: str) -> None:
    household = db.scalar(select(Household))
    if household is None:
        raise HouseholdNotFoundError
    if confirmation != f"DELETE {household.display_name}":
        raise ConfirmationMismatchError

    for model in (
        ProcessedMutation,
        SyncChange,
        SyncState,
        ImportedDailyNote,
        CareRecord,
        ImportBatch,
        Baby,
        Invitation,
        AuthSession,
        CaregiverQuickAction,
        Caregiver,
        Household,
    ):
        db.execute(delete(model))
    commit_private_changes(db)


def deactivate_caregiver(db: Session, caregiver_id: str, current_owner_id: str) -> None:
    caregiver = db.get(Caregiver, caregiver_id)
    if caregiver is None or not caregiver.is_active:
        raise CaregiverNotFoundError
    if caregiver.id == current_owner_id:
        raise CurrentOwnerMutationError
    changed_at = now_ms()
    caregiver.is_active = False
    caregiver.updated_at = changed_at
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.caregiver_id == caregiver.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=changed_at)
    )
    db.commit()


def erase_caregiver_identity(db: Session, caregiver_id: str, current_owner_id: str) -> None:
    caregiver = db.get(Caregiver, caregiver_id)
    if caregiver is None:
        raise CaregiverNotFoundError
    if caregiver.id == current_owner_id:
        raise CurrentOwnerMutationError
    if caregiver.identity_erased_at is not None:
        raise CaregiverIdentityAlreadyErasedError
    if caregiver.is_active:
        raise CaregiverMustBeInactiveError

    deleted_label = "Deleted caregiver"
    changed_at = now_ms()
    affected_records = db.scalars(
        select(CareRecord).where(
            or_(
                CareRecord.author_id == caregiver.id,
                CareRecord.last_modified_by_id == caregiver.id,
            )
        )
    ).all()
    for record in affected_records:
        if record.author_id == caregiver.id:
            record.author_id = None
            record.author_label = deleted_label
        if record.last_modified_by_id == caregiver.id:
            record.last_modified_by_id = None
            record.last_modified_by_label = deleted_label
        record.updated_at = changed_at
        record.revision += 1
        db.add(
            SyncChange(
                entity_kind="care_record",
                entity_id=record.id,
                operation=(
                    SyncOperation.DELETE if record.deleted_at is not None else SyncOperation.UPSERT
                ),
                revision=record.revision,
                changed_at=changed_at,
            )
        )
    db.execute(delete(AuthSession).where(AuthSession.caregiver_id == caregiver.id))
    db.execute(delete(ProcessedMutation).where(ProcessedMutation.caregiver_id == caregiver.id))
    db.execute(
        delete(CaregiverQuickAction).where(CaregiverQuickAction.caregiver_id == caregiver.id)
    )
    caregiver.username_normalized = f"deleted-{caregiver.id}"
    caregiver.username_display = deleted_label
    caregiver.display_name = deleted_label
    caregiver.password_hash = hash_password(new_token())
    caregiver.identity_erased_at = changed_at
    caregiver.updated_at = changed_at
    commit_private_changes(db)
