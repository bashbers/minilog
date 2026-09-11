from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from minilog.models import ClockFormat, MeasurementSystem, RecordType


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SetupStatus(APIModel):
    setup_required: bool


class SetupRequest(APIModel):
    setup_token: str = Field(min_length=20, max_length=512)
    household_name: str = Field(min_length=1, max_length=120)
    time_zone: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("time_zone")
    @classmethod
    def valid_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time zone must be an IANA time zone") from exc
        return value


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str | None = Field(default=None, max_length=120)


class CaregiverOut(APIModel):
    id: UUID
    username_display: str
    display_name: str
    role: str
    is_active: bool
    identity_erased_at: int | None


class SessionOut(APIModel):
    caregiver: CaregiverOut
    csrf_token: str
    expires_at: int


class InvitationCreate(APIModel):
    expires_in_hours: int | None = Field(default=None, ge=1, le=168)


class InvitationOut(APIModel):
    id: UUID
    token: str
    expires_at: int


class InvitationAccept(APIModel):
    token: str = Field(min_length=20, max_length=512)
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1024)
    device_name: str | None = Field(default=None, max_length=120)


class DeviceSessionOut(APIModel):
    id: UUID
    device_name: str | None
    created_at: int
    last_seen_at: int
    expires_at: int
    current: bool


class PasswordChange(APIModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class QuickActionPreferenceInput(APIModel):
    record_type: RecordType
    is_hidden: bool = False

    @field_validator("record_type")
    @classmethod
    def native_record_type(cls, value: RecordType) -> RecordType:
        if value is RecordType.IMPORTED_CARE_RECORD:
            raise ValueError("imported records cannot be quick actions")
        return value


class QuickActionPreferencesUpdate(APIModel):
    actions: list[QuickActionPreferenceInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def record_types_are_unique(self) -> QuickActionPreferencesUpdate:
        record_types = [action.record_type for action in self.actions]
        if len(record_types) != len(set(record_types)):
            raise ValueError("quick action record types must be unique")
        return self


class QuickActionPreferenceOut(QuickActionPreferenceInput):
    position: int = Field(ge=0)


class HouseholdOut(APIModel):
    id: UUID
    display_name: str
    time_zone: str
    locale: str
    clock_format: ClockFormat
    measurement_system: MeasurementSystem


class BabyCreate(APIModel):
    display_name: str = Field(min_length=1, max_length=120)
    birth_date: date
    due_date: date | None = None


class BabyUpdate(BabyCreate):
    pass


class BabyDeleteRequest(APIModel):
    confirmation: str = Field(min_length=1, max_length=120)
    export_acknowledged: bool


class HouseholdDeleteRequest(APIModel):
    confirmation: str = Field(min_length=1, max_length=200)


class BabyOut(APIModel):
    id: UUID
    display_name: str
    birth_date: date
    due_date: date | None
    has_profile_picture: bool = False
    updated_at: int


class BabyActiveStatus(APIModel):
    baby_id: UUID
    active_types: list[RecordType]


class RecordInputBase(APIModel):
    id: UUID | None = None
    baby_id: UUID
    occurred_at: datetime
    ended_at: datetime | None = None
    local_offset_minutes: int = Field(ge=-840, le=840)
    note: str | None = Field(default=None, max_length=10_000)

    @field_validator("occurred_at", "ended_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include an offset")
        return value

    @model_validator(mode="after")
    def end_follows_start(self) -> RecordInputBase:
        if self.ended_at is not None and self.ended_at < self.occurred_at:
            raise ValueError("end must not precede start")
        return self


class BreastfeedingIntervalInput(APIModel):
    side: Literal["left", "right"]
    started_at: datetime
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> BreastfeedingIntervalInput:
        if self.started_at.tzinfo is None or (
            self.ended_at is not None and self.ended_at.tzinfo is None
        ):
            raise ValueError("interval timestamps must include an offset")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("interval end must not precede start")
        return self


class BreastfeedingCreate(RecordInputBase):
    record_type: Literal[RecordType.BREASTFEEDING]
    estimated_amount_ml: int | None = Field(default=None, ge=0, le=10_000)
    intervals: list[BreastfeedingIntervalInput] = Field(default_factory=list, max_length=100)


class BottleFeedingCreate(RecordInputBase):
    record_type: Literal[RecordType.BOTTLE_FEEDING]
    consumed_ml: int = Field(ge=0, le=10_000)
    offered_ml: int | None = Field(default=None, ge=0, le=10_000)
    contents: Literal["breast_milk", "formula", "mixed", "other"]

    @model_validator(mode="after")
    def offered_covers_consumed(self) -> BottleFeedingCreate:
        if self.offered_ml is not None and self.offered_ml < self.consumed_ml:
            raise ValueError("offered volume cannot be below consumed volume")
        return self


class SolidFoodFeedingCreate(RecordInputBase):
    record_type: Literal[RecordType.SOLID_FOOD_FEEDING]
    foods: str = Field(min_length=1, max_length=2_000)
    amount_value: Decimal | None = Field(default=None, ge=0)
    amount_unit: str | None = Field(default=None, max_length=40)
    reaction_note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def amount_is_complete(self) -> SolidFoodFeedingCreate:
        if (self.amount_value is None) != (self.amount_unit is None):
            raise ValueError("amount value and unit must be supplied together")
        return self


class SleepCreate(RecordInputBase):
    record_type: Literal[RecordType.SLEEP]


class DiaperChangeCreate(RecordInputBase):
    record_type: Literal[RecordType.DIAPER_CHANGE]
    is_wet: bool
    is_dirty: bool
    stool_colour: str | None = Field(default=None, max_length=32)
    stool_consistency: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def diaper_has_observation(self) -> DiaperChangeCreate:
        if not self.is_wet and not self.is_dirty:
            raise ValueError("diaper must be wet, dirty, or both")
        if not self.is_dirty and (self.stool_colour or self.stool_consistency):
            raise ValueError("stool descriptors require a dirty diaper")
        return self


class PumpingCreate(RecordInputBase):
    record_type: Literal[RecordType.PUMPING]
    expressed_ml: int | None = Field(default=None, ge=0, le=10_000)


class MeasurementCreate(RecordInputBase):
    record_type: Literal[RecordType.MEASUREMENT]
    kind: Literal["weight", "height", "temperature"]
    entered_value: Decimal
    entered_unit: str = Field(min_length=1, max_length=24)


MedicationUnitCode = Literal["ml", "mg", "g", "mcg", "tablet", "drop"]


class MedicationAdministrationCreate(RecordInputBase):
    record_type: Literal[RecordType.MEDICATION_ADMINISTRATION]
    medicine_name: str = Field(min_length=1, max_length=200)
    amount_value: Decimal = Field(gt=0)
    unit_code: MedicationUnitCode | None = None
    custom_unit: str | None = Field(default=None, max_length=40)
    route: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def exactly_one_unit(self) -> MedicationAdministrationCreate:
        if (self.unit_code is None) == (self.custom_unit is None):
            raise ValueError("provide exactly one common or custom unit")
        return self


class NoteCreate(RecordInputBase):
    record_type: Literal[RecordType.NOTE]
    body: str = Field(min_length=1, max_length=10_000)


CareRecordCreate = Annotated[
    BreastfeedingCreate
    | BottleFeedingCreate
    | SolidFoodFeedingCreate
    | SleepCreate
    | DiaperChangeCreate
    | PumpingCreate
    | MeasurementCreate
    | MedicationAdministrationCreate
    | NoteCreate,
    Field(discriminator="record_type"),
]


class CareRecordOutBase(APIModel):
    id: UUID
    baby_id: UUID
    occurred_at: datetime
    ended_at: datetime | None
    local_offset_minutes: int
    note: str | None
    author_label: str
    last_modified_by_label: str
    created_at: datetime
    updated_at: datetime
    revision: int


class BreastfeedingDetails(APIModel):
    estimated_amount_ml: int | None
    intervals: list[BreastfeedingIntervalInput]


class BottleFeedingDetails(APIModel):
    consumed_ml: int
    offered_ml: int | None
    contents: Literal["breast_milk", "formula", "mixed", "other"]


class SolidFoodFeedingDetails(APIModel):
    foods: str
    amount_value: Decimal | None
    amount_unit: str | None
    reaction_note: str | None


class SleepDetails(APIModel):
    pass


class DiaperChangeDetails(APIModel):
    is_wet: bool
    is_dirty: bool
    stool_colour: str | None
    stool_consistency: str | None


class PumpingDetails(APIModel):
    expressed_ml: int | None


class MeasurementDetails(APIModel):
    kind: Literal["weight", "height", "temperature"]
    canonical_value: Decimal
    canonical_unit: str
    entered_value: Decimal
    entered_unit: str


class MedicationAdministrationDetails(APIModel):
    medicine_name: str
    amount_value: Decimal
    unit_code: MedicationUnitCode | None
    custom_unit: str | None
    route: str | None


class NoteDetails(APIModel):
    body: str


class ImportedCareRecordDetails(APIModel):
    raw_label: str
    raw_details: str | None
    raw_line: str


class BreastfeedingOut(CareRecordOutBase):
    record_type: Literal[RecordType.BREASTFEEDING]
    details: BreastfeedingDetails


class BottleFeedingOut(CareRecordOutBase):
    record_type: Literal[RecordType.BOTTLE_FEEDING]
    details: BottleFeedingDetails


class SolidFoodFeedingOut(CareRecordOutBase):
    record_type: Literal[RecordType.SOLID_FOOD_FEEDING]
    details: SolidFoodFeedingDetails


class SleepOut(CareRecordOutBase):
    record_type: Literal[RecordType.SLEEP]
    details: SleepDetails


class DiaperChangeOut(CareRecordOutBase):
    record_type: Literal[RecordType.DIAPER_CHANGE]
    details: DiaperChangeDetails


class PumpingOut(CareRecordOutBase):
    record_type: Literal[RecordType.PUMPING]
    details: PumpingDetails


class MeasurementOut(CareRecordOutBase):
    record_type: Literal[RecordType.MEASUREMENT]
    details: MeasurementDetails


class MedicationAdministrationOut(CareRecordOutBase):
    record_type: Literal[RecordType.MEDICATION_ADMINISTRATION]
    details: MedicationAdministrationDetails


class NoteOut(CareRecordOutBase):
    record_type: Literal[RecordType.NOTE]
    details: NoteDetails


class ImportedCareRecordOut(CareRecordOutBase):
    record_type: Literal[RecordType.IMPORTED_CARE_RECORD]
    details: ImportedCareRecordDetails


CareRecordVariant = Annotated[
    BreastfeedingOut
    | BottleFeedingOut
    | SolidFoodFeedingOut
    | SleepOut
    | DiaperChangeOut
    | PumpingOut
    | MeasurementOut
    | MedicationAdministrationOut
    | NoteOut
    | ImportedCareRecordOut,
    Field(discriminator="record_type"),
]


class CareRecordOut(RootModel[CareRecordVariant]):
    pass


class CareRecordPage(APIModel):
    items: list[CareRecordOut]
    next_cursor: str | None = None


class StaleRevisionDetail(APIModel):
    code: Literal["stale_revision"] = "stale_revision"
    current: CareRecordOut


class CareRecordConflictResponse(APIModel):
    detail: StaleRevisionDetail | str


class CareRecordUpdate(APIModel):
    expected_revision: int = Field(ge=1)
    record: CareRecordCreate


class SyncChangeOut(APIModel):
    sequence: int
    entity_kind: str
    entity_id: UUID
    operation: str
    revision: int


class SyncPage(APIModel):
    changes: list[SyncChangeOut]
    next_cursor: int
    oldest_valid_cursor: int


class SyncCursorExpiredDetail(APIModel):
    code: Literal["sync_cursor_expired"] = "sync_cursor_expired"
    oldest_valid_cursor: int


class SyncCursorExpiredResponse(APIModel):
    detail: SyncCursorExpiredDetail


class CompatibilityStatus(APIModel):
    status: Literal["ready"] = "ready"
    api_contract_version: int
    schema_revision: str


class PiyoLogPreview(APIModel):
    source_hash: str
    duplicate_import_id: UUID | None = None
    detected_locale: Literal["en", "ja"]
    date_from: date | None = None
    date_to: date | None = None
    counts: dict[str, int]
    conflicts: dict[str, int] = Field(default_factory=dict)
    unknown_lines: list[dict[str, object]]
    warnings: list[str]


class ImportBatchOut(APIModel):
    id: UUID
    baby_id: UUID
    source_hash: str
    detected_locale: str
    date_from: date | None
    date_to: date | None
    status: str
    counts: dict[str, int]
    source_retained: bool
    created_at: datetime


class ImportedDailyNoteOut(APIModel):
    id: UUID
    baby_id: UUID
    local_date: date
    body: str
    source_author_text: str | None
    source_line: int | None


def datetime_to_ms(value: datetime) -> int:
    return int(value.astimezone(UTC).timestamp() * 1000)


def ms_to_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
