from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str | None = Field(default=None, max_length=120)


class CaregiverOut(APIModel):
    id: UUID
    username_display: str
    display_name: str
    role: str


class SessionOut(APIModel):
    caregiver: CaregiverOut
    csrf_token: str
    expires_at: int


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


class BabyOut(APIModel):
    id: UUID
    display_name: str
    birth_date: date
    due_date: date | None
    has_profile_picture: bool = False
    updated_at: int


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


class MedicationAdministrationCreate(RecordInputBase):
    record_type: Literal[RecordType.MEDICATION_ADMINISTRATION]
    medicine_name: str = Field(min_length=1, max_length=200)
    amount_value: Decimal = Field(gt=0)
    unit_code: str | None = Field(default=None, max_length=32)
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


class CareRecordOut(APIModel):
    id: UUID
    baby_id: UUID
    record_type: RecordType
    occurred_at: datetime
    ended_at: datetime | None
    local_offset_minutes: int
    note: str | None
    author_label: str
    last_modified_by_label: str
    created_at: datetime
    updated_at: datetime
    revision: int
    details: dict[str, object]


class CareRecordPage(APIModel):
    items: list[CareRecordOut]
    next_before: int | None = None


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


def datetime_to_ms(value: datetime) -> int:
    return int(value.astimezone(UTC).timestamp() * 1000)


def ms_to_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)

