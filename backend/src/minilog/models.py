from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from minilog.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


class CaregiverRole(StrEnum):
    OWNER = "owner"
    CAREGIVER = "caregiver"


class ClockFormat(StrEnum):
    TWELVE_HOUR = "12h"
    TWENTY_FOUR_HOUR = "24h"


class MeasurementSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class RecordType(StrEnum):
    BREASTFEEDING = "breastfeeding"
    BOTTLE_FEEDING = "bottle_feeding"
    SOLID_FOOD_FEEDING = "solid_food_feeding"
    SLEEP = "sleep"
    DIAPER_CHANGE = "diaper_change"
    PUMPING = "pumping"
    MEASUREMENT = "measurement"
    MEDICATION_ADMINISTRATION = "medication_administration"
    NOTE = "note"
    IMPORTED_CARE_RECORD = "imported_care_record"


class SyncOperation(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(120))
    time_zone: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(32), default="en")
    clock_format: Mapped[ClockFormat] = mapped_column(
        Enum(ClockFormat, native_enum=False, create_constraint=True),
        default=ClockFormat.TWENTY_FOUR_HOUR,
    )
    measurement_system: Mapped[MeasurementSystem] = mapped_column(
        Enum(MeasurementSystem, native_enum=False, create_constraint=True),
        default=MeasurementSystem.METRIC,
    )
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)


class Caregiver(Base):
    __tablename__ = "caregivers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username_normalized: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    username_display: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[CaregiverRole] = mapped_column(
        Enum(CaregiverRole, native_enum=False, create_constraint=True)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)
    identity_erased_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("caregivers.id"))
    role: Mapped[CaregiverRole] = mapped_column(
        Enum(CaregiverRole, native_enum=False, create_constraint=True),
        default=CaregiverRole.CAREGIVER,
    )
    expires_at: Mapped[int] = mapped_column(Integer)
    used_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    caregiver_id: Mapped[str] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"))
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    last_seen_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    expires_at: Mapped[int] = mapped_column(Integer)
    revoked_at: Mapped[int | None] = mapped_column(Integer, nullable=True)

    caregiver: Mapped[Caregiver] = relationship()


class CaregiverQuickAction(Base):
    __tablename__ = "caregiver_quick_actions"
    __table_args__ = (
        UniqueConstraint("caregiver_id", "position", name="visible_position"),
        CheckConstraint("position >= 0", name="position_non_negative"),
    )

    caregiver_id: Mapped[str] = mapped_column(
        ForeignKey("caregivers.id", ondelete="CASCADE"), primary_key=True
    )
    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, native_enum=False, create_constraint=True), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class Baby(Base):
    __tablename__ = "babies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(120), index=True)
    birth_date: Mapped[str] = mapped_column(String(10))
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)

    profile_picture: Mapped[BabyProfilePicture | None] = relationship(
        back_populates="baby", cascade="all, delete-orphan", passive_deletes=True
    )


class BabyProfilePicture(Base):
    __tablename__ = "baby_profile_pictures"
    __table_args__ = (CheckConstraint("width = height", name="picture_square"),)

    baby_id: Mapped[str] = mapped_column(
        ForeignKey("babies.id", ondelete="CASCADE"), primary_key=True
    )
    webp_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)

    baby: Mapped[Baby] = relationship(back_populates="profile_picture")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    baby_id: Mapped[str] = mapped_column(ForeignKey("babies.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("caregivers.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    source_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_time_zone: Mapped[str] = mapped_column(String(64))
    detected_locale: Mapped[str] = mapped_column(String(32))
    detected_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    format: Mapped[str] = mapped_column(String(32))
    date_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    report_json: Mapped[str] = mapped_column(Text)
    source_contents: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    source_deleted_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CareRecord(Base):
    __tablename__ = "care_records"
    __table_args__ = (
        CheckConstraint("local_offset_minutes BETWEEN -840 AND 840", name="offset_range"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "ended_at_utc IS NULL OR ended_at_utc >= occurred_at_utc", name="end_after_start"
        ),
        Index("ix_care_records_timeline", "baby_id", "deleted_at", "occurred_at_utc", "id"),
        Index(
            "uq_active_sleep_per_baby",
            "baby_id",
            unique=True,
            sqlite_where=text(
                "record_type = 'SLEEP' AND ended_at_utc IS NULL AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_active_breastfeeding_per_baby",
            "baby_id",
            unique=True,
            sqlite_where=text(
                "record_type = 'BREASTFEEDING' AND ended_at_utc IS NULL AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_active_pumping_per_caregiver_baby",
            "baby_id",
            "author_id",
            unique=True,
            sqlite_where=text(
                "record_type = 'PUMPING' AND ended_at_utc IS NULL AND deleted_at IS NULL"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    baby_id: Mapped[str] = mapped_column(ForeignKey("babies.id", ondelete="CASCADE"), index=True)
    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, native_enum=False, create_constraint=True), index=True
    )
    occurred_at_utc: Mapped[int] = mapped_column(Integer, index=True)
    local_offset_minutes: Mapped[int] = mapped_column(Integer)
    ended_at_utc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("caregivers.id"), nullable=True)
    author_label: Mapped[str] = mapped_column(String(120))
    last_modified_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("caregivers.id"), nullable=True
    )
    last_modified_by_label: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    import_source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modified_since_import: Mapped[bool] = mapped_column(Boolean, default=False)

    baby: Mapped[Baby] = relationship()


class BreastfeedingRecord(Base):
    __tablename__ = "breastfeeding_records"
    __table_args__ = (
        CheckConstraint(
            "estimated_amount_ml IS NULL OR estimated_amount_ml >= 0", name="amount_non_negative"
        ),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    estimated_amount_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BreastfeedingInterval(Base):
    __tablename__ = "breastfeeding_intervals"
    __table_args__ = (
        UniqueConstraint("care_record_id", "position"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint(
            "ended_at_utc IS NULL OR ended_at_utc >= started_at_utc", name="end_after_start"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(8))
    started_at_utc: Mapped[int] = mapped_column(Integer)
    ended_at_utc: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BottleFeedingRecord(Base):
    __tablename__ = "bottle_feeding_records"
    __table_args__ = (
        CheckConstraint("consumed_ml >= 0", name="consumed_non_negative"),
        CheckConstraint("offered_ml IS NULL OR offered_ml >= consumed_ml", name="offered_enough"),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    consumed_ml: Mapped[int] = mapped_column(Integer)
    offered_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contents: Mapped[str] = mapped_column(String(24))


class SolidFoodFeedingRecord(Base):
    __tablename__ = "solid_food_feeding_records"
    __table_args__ = (
        CheckConstraint(
            "(amount_value IS NULL AND amount_unit IS NULL) OR "
            "(amount_value IS NOT NULL AND amount_unit IS NOT NULL)",
            name="amount_complete",
        ),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    foods: Mapped[str] = mapped_column(Text)
    amount_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reaction_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SleepRecord(Base):
    __tablename__ = "sleep_records"
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )


class DiaperChangeRecord(Base):
    __tablename__ = "diaper_change_records"
    __table_args__ = (
        CheckConstraint("is_wet = 1 OR is_dirty = 1", name="wet_or_dirty"),
        CheckConstraint(
            "is_dirty = 1 OR (stool_colour IS NULL AND stool_consistency IS NULL)",
            name="stool_requires_dirty",
        ),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    is_wet: Mapped[bool] = mapped_column(Boolean)
    is_dirty: Mapped[bool] = mapped_column(Boolean)
    stool_colour: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stool_consistency: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PumpingRecord(Base):
    __tablename__ = "pumping_records"
    __table_args__ = (
        CheckConstraint("expressed_ml IS NULL OR expressed_ml >= 0", name="amount_non_negative"),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    expressed_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MeasurementRecord(Base):
    __tablename__ = "measurement_records"
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    canonical_value: Mapped[str] = mapped_column(String(40))
    canonical_unit: Mapped[str] = mapped_column(String(24))
    entered_value: Mapped[str] = mapped_column(String(40))
    entered_unit: Mapped[str] = mapped_column(String(24))


class MedicationAdministrationRecord(Base):
    __tablename__ = "medication_administration_records"
    __table_args__ = (
        CheckConstraint(
            "(unit_code IS NULL AND custom_unit IS NOT NULL) OR "
            "(unit_code IS NOT NULL AND custom_unit IS NULL)",
            name="exactly_one_unit",
        ),
    )
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    medicine_name: Mapped[str] = mapped_column(String(200))
    amount_value: Mapped[str] = mapped_column(String(40))
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    custom_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    route: Mapped[str | None] = mapped_column(String(40), nullable=True)


class NoteRecord(Base):
    __tablename__ = "note_records"
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    body: Mapped[str] = mapped_column(Text)


class ImportedCareRecord(Base):
    __tablename__ = "imported_care_records"
    care_record_id: Mapped[str] = mapped_column(
        ForeignKey("care_records.id", ondelete="CASCADE"), primary_key=True
    )
    raw_label: Mapped[str] = mapped_column(String(200))
    raw_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_line: Mapped[str] = mapped_column(Text)


class ImportedDailyNote(Base):
    __tablename__ = "imported_daily_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    baby_id: Mapped[str] = mapped_column(ForeignKey("babies.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[str] = mapped_column(String(10), index=True)
    body: Mapped[str] = mapped_column(Text)
    source_author_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    import_batch_id: Mapped[str] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class SyncChange(Base):
    __tablename__ = "sync_changes"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_kind: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    operation: Mapped[SyncOperation] = mapped_column(
        Enum(SyncOperation, native_enum=False, create_constraint=True)
    )
    revision: Mapped[int] = mapped_column(Integer)
    changed_at: Mapped[int] = mapped_column(Integer, default=now_ms, index=True)


class ProcessedMutation(Base):
    __tablename__ = "processed_mutations"
    mutation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    caregiver_id: Mapped[str] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"))
    entity_kind: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    result_revision: Mapped[int] = mapped_column(Integer)
    processed_at: Mapped[int] = mapped_column(Integer, default=now_ms, index=True)
    replay_result: Mapped[str] = mapped_column(Text)


class SyncState(Base):
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    oldest_valid_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_pruned_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
