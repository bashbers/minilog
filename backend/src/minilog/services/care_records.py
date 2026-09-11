from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from minilog.models import (
    Baby,
    BottleFeedingRecord,
    BreastfeedingInterval,
    BreastfeedingRecord,
    Caregiver,
    CareRecord,
    DiaperChangeRecord,
    Household,
    ImportedCareRecord,
    MeasurementRecord,
    MedicationAdministrationRecord,
    NoteRecord,
    PumpingRecord,
    RecordType,
    SleepRecord,
    SolidFoodFeedingRecord,
    SyncChange,
    SyncOperation,
    now_ms,
)
from minilog.schemas import (
    BabyActiveStatus,
    BottleFeedingCreate,
    BreastfeedingCreate,
    CareRecordCreate,
    CareRecordOut,
    DiaperChangeCreate,
    MeasurementCreate,
    MedicationAdministrationCreate,
    NoteCreate,
    PumpingCreate,
    SleepCreate,
    SolidFoodFeedingCreate,
    StaleRevisionDetail,
    datetime_to_ms,
    ms_to_datetime,
)


class InvalidPageCursorError(ValueError):
    pass


class BabyNotFoundError(LookupError):
    pass


class InvalidOccurrenceRangeError(ValueError):
    pass


@dataclass(frozen=True)
class CareRecordPageResult:
    records: list[CareRecord]
    next_cursor: str | None


ACTIVE_RECORD_TYPES = {RecordType.SLEEP, RecordType.BREASTFEEDING, RecordType.PUMPING}


def encode_page_cursor(record: CareRecord) -> str:
    position = f"{record.occurred_at_utc}:{record.id}".encode()
    return b64encode(position, altchars=b"-_").decode().rstrip("=")


def decode_page_cursor(cursor: str) -> tuple[int, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = b64decode(cursor + padding, altchars=b"-_", validate=True).decode()
        occurred_at, record_id = decoded.split(":", maxsplit=1)
        occurred_at_ms = int(occurred_at)
        if occurred_at_ms < 0:
            raise ValueError
        return occurred_at_ms, str(UUID(record_id))
    except (Base64Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidPageCursorError from exc


def list_records(
    db: Session,
    baby_id: str,
    *,
    cursor: str | None,
    record_types: list[RecordType] | None,
    date_from: date | None,
    date_to: date | None,
    active_only: bool,
    limit: int,
) -> CareRecordPageResult:
    if db.get(Baby, baby_id) is None:
        raise BabyNotFoundError
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidOccurrenceRangeError
    household = db.scalar(select(Household))
    if household is None:
        raise RuntimeError("configured Household is missing")
    household_time_zone = ZoneInfo(household.time_zone)
    statement = (
        select(CareRecord)
        .where(CareRecord.baby_id == baby_id, CareRecord.deleted_at.is_(None))
        .order_by(CareRecord.occurred_at_utc.desc(), CareRecord.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        before, before_id = decode_page_cursor(cursor)
        statement = statement.where(
            or_(
                CareRecord.occurred_at_utc < before,
                and_(
                    CareRecord.occurred_at_utc == before,
                    CareRecord.id < before_id,
                ),
            )
        )
    if record_types:
        statement = statement.where(CareRecord.record_type.in_(record_types))
    if active_only:
        statement = statement.where(
            CareRecord.record_type.in_(ACTIVE_RECORD_TYPES),
            CareRecord.ended_at_utc.is_(None),
        )
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=household_time_zone)
        statement = statement.where(
            CareRecord.occurred_at_utc >= int(start.timestamp() * 1000)
        )
    if date_to is not None:
        end = datetime.combine(
            date_to + timedelta(days=1), time.min, tzinfo=household_time_zone
        )
        statement = statement.where(CareRecord.occurred_at_utc < int(end.timestamp() * 1000))
    records = list(db.scalars(statement).all())
    has_more = len(records) > limit
    records = records[:limit]
    return CareRecordPageResult(
        records=records,
        next_cursor=encode_page_cursor(records[-1]) if has_more and records else None,
    )


def active_statuses(db: Session) -> list[BabyActiveStatus]:
    records = db.execute(
        select(CareRecord.baby_id, CareRecord.record_type)
        .where(
            CareRecord.record_type.in_(ACTIVE_RECORD_TYPES),
            CareRecord.ended_at_utc.is_(None),
            CareRecord.deleted_at.is_(None),
        )
        .order_by(CareRecord.baby_id, CareRecord.record_type)
    ).all()
    grouped: dict[str, list[RecordType]] = {}
    for baby_id, record_type in records:
        grouped.setdefault(baby_id, []).append(record_type)
    return [
        BabyActiveStatus(baby_id=baby_id, active_types=record_types)
        for baby_id, record_types in grouped.items()
    ]


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def canonical_measurement(kind: str, value: Decimal, unit: str) -> tuple[str, str]:
    normalized_unit = unit.strip().casefold()
    if kind == "weight":
        factors = {
            "kg": Decimal("1"),
            "g": Decimal("0.001"),
            "lb": Decimal("0.45359237"),
            "oz": Decimal("0.028349523125"),
        }
        canonical_unit = "kg"
    elif kind == "height":
        factors = {"cm": Decimal("1"), "mm": Decimal("0.1"), "in": Decimal("2.54")}
        canonical_unit = "cm"
    else:
        if normalized_unit in {"c", "°c", "celsius"}:
            return decimal_text(value), "celsius"
        if normalized_unit in {"f", "°f", "fahrenheit"}:
            return decimal_text((value - Decimal(32)) * Decimal(5) / Decimal(9)), "celsius"
        raise HTTPException(status_code=422, detail="unsupported_temperature_unit")
    factor = factors.get(normalized_unit)
    if factor is None:
        raise HTTPException(status_code=422, detail=f"unsupported_{kind}_unit")
    return decimal_text(value * factor), canonical_unit


def ensure_active_slot(
    db: Session,
    payload: CareRecordCreate,
    caregiver: Caregiver,
    excluding_id: str | None = None,
) -> None:
    if payload.ended_at is not None:
        return
    if payload.record_type not in {
        RecordType.SLEEP,
        RecordType.BREASTFEEDING,
        RecordType.PUMPING,
    }:
        return
    conditions = [
        CareRecord.baby_id == str(payload.baby_id),
        CareRecord.record_type == payload.record_type,
        CareRecord.ended_at_utc.is_(None),
        CareRecord.deleted_at.is_(None),
    ]
    if payload.record_type is RecordType.PUMPING:
        conditions.append(CareRecord.author_id == caregiver.id)
    if excluding_id:
        conditions.append(CareRecord.id != excluding_id)
    if db.scalar(select(CareRecord.id).where(*conditions).limit(1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="active_record_exists")


def add_detail(db: Session, record_id: str, payload: CareRecordCreate) -> None:
    match payload:
        case BreastfeedingCreate():
            db.add(
                BreastfeedingRecord(
                    care_record_id=record_id,
                    estimated_amount_ml=payload.estimated_amount_ml,
                )
            )
            for position, interval in enumerate(payload.intervals):
                db.add(
                    BreastfeedingInterval(
                        care_record_id=record_id,
                        position=position,
                        side=interval.side,
                        started_at_utc=datetime_to_ms(interval.started_at),
                        ended_at_utc=(
                            datetime_to_ms(interval.ended_at) if interval.ended_at else None
                        ),
                    )
                )
        case BottleFeedingCreate():
            db.add(
                BottleFeedingRecord(
                    care_record_id=record_id,
                    consumed_ml=payload.consumed_ml,
                    offered_ml=payload.offered_ml,
                    contents=payload.contents,
                )
            )
        case SolidFoodFeedingCreate():
            db.add(
                SolidFoodFeedingRecord(
                    care_record_id=record_id,
                    foods=payload.foods,
                    amount_value=(
                        decimal_text(payload.amount_value)
                        if payload.amount_value is not None
                        else None
                    ),
                    amount_unit=payload.amount_unit,
                    reaction_note=payload.reaction_note,
                )
            )
        case SleepCreate():
            db.add(SleepRecord(care_record_id=record_id))
        case DiaperChangeCreate():
            db.add(
                DiaperChangeRecord(
                    care_record_id=record_id,
                    is_wet=payload.is_wet,
                    is_dirty=payload.is_dirty,
                    stool_colour=payload.stool_colour,
                    stool_consistency=payload.stool_consistency,
                )
            )
        case PumpingCreate():
            db.add(PumpingRecord(care_record_id=record_id, expressed_ml=payload.expressed_ml))
        case MeasurementCreate():
            canonical_value, canonical_unit = canonical_measurement(
                payload.kind, payload.entered_value, payload.entered_unit
            )
            db.add(
                MeasurementRecord(
                    care_record_id=record_id,
                    kind=payload.kind,
                    canonical_value=canonical_value,
                    canonical_unit=canonical_unit,
                    entered_value=decimal_text(payload.entered_value),
                    entered_unit=payload.entered_unit,
                )
            )
        case MedicationAdministrationCreate():
            db.add(
                MedicationAdministrationRecord(
                    care_record_id=record_id,
                    medicine_name=payload.medicine_name,
                    amount_value=decimal_text(payload.amount_value),
                    unit_code=payload.unit_code,
                    custom_unit=payload.custom_unit,
                    route=payload.route,
                )
            )
        case NoteCreate():
            db.add(NoteRecord(care_record_id=record_id, body=payload.body))
        case _:
            raise HTTPException(status_code=422, detail="unsupported_record_type")


def delete_detail(db: Session, record: CareRecord) -> None:
    detail_type = {
        RecordType.BREASTFEEDING: BreastfeedingRecord,
        RecordType.BOTTLE_FEEDING: BottleFeedingRecord,
        RecordType.SOLID_FOOD_FEEDING: SolidFoodFeedingRecord,
        RecordType.SLEEP: SleepRecord,
        RecordType.DIAPER_CHANGE: DiaperChangeRecord,
        RecordType.PUMPING: PumpingRecord,
        RecordType.MEASUREMENT: MeasurementRecord,
        RecordType.MEDICATION_ADMINISTRATION: MedicationAdministrationRecord,
        RecordType.NOTE: NoteRecord,
        RecordType.IMPORTED_CARE_RECORD: ImportedCareRecord,
    }[record.record_type]
    if record.record_type is RecordType.BREASTFEEDING:
        db.execute(
            delete(BreastfeedingInterval).where(BreastfeedingInterval.care_record_id == record.id)
        )
    db.execute(delete(detail_type).where(detail_type.care_record_id == record.id))


def details_for(db: Session, record: CareRecord) -> dict[str, object]:
    match record.record_type:
        case RecordType.BREASTFEEDING:
            detail = db.get(BreastfeedingRecord, record.id)
            intervals = db.scalars(
                select(BreastfeedingInterval)
                .where(BreastfeedingInterval.care_record_id == record.id)
                .order_by(BreastfeedingInterval.position)
            ).all()
            return {
                "estimated_amount_ml": detail.estimated_amount_ml if detail else None,
                "intervals": [
                    {
                        "side": item.side,
                        "started_at": ms_to_datetime(item.started_at_utc).isoformat(),
                        "ended_at": (
                            ms_to_datetime(item.ended_at_utc).isoformat()
                            if item.ended_at_utc
                            else None
                        ),
                    }
                    for item in intervals
                ],
            }
        case RecordType.BOTTLE_FEEDING:
            detail = db.get(BottleFeedingRecord, record.id)
            return {
                "consumed_ml": detail.consumed_ml,
                "offered_ml": detail.offered_ml,
                "contents": detail.contents,
            }
        case RecordType.SOLID_FOOD_FEEDING:
            detail = db.get(SolidFoodFeedingRecord, record.id)
            return {
                "foods": detail.foods,
                "amount_value": detail.amount_value,
                "amount_unit": detail.amount_unit,
                "reaction_note": detail.reaction_note,
            }
        case RecordType.SLEEP:
            return {}
        case RecordType.DIAPER_CHANGE:
            detail = db.get(DiaperChangeRecord, record.id)
            return {
                "is_wet": detail.is_wet,
                "is_dirty": detail.is_dirty,
                "stool_colour": detail.stool_colour,
                "stool_consistency": detail.stool_consistency,
            }
        case RecordType.PUMPING:
            detail = db.get(PumpingRecord, record.id)
            return {"expressed_ml": detail.expressed_ml}
        case RecordType.MEASUREMENT:
            detail = db.get(MeasurementRecord, record.id)
            return {
                "kind": detail.kind,
                "canonical_value": detail.canonical_value,
                "canonical_unit": detail.canonical_unit,
                "entered_value": detail.entered_value,
                "entered_unit": detail.entered_unit,
            }
        case RecordType.MEDICATION_ADMINISTRATION:
            detail = db.get(MedicationAdministrationRecord, record.id)
            return {
                "medicine_name": detail.medicine_name,
                "amount_value": detail.amount_value,
                "unit_code": detail.unit_code,
                "custom_unit": detail.custom_unit,
                "route": detail.route,
            }
        case RecordType.NOTE:
            detail = db.get(NoteRecord, record.id)
            return {"body": detail.body}
        case RecordType.IMPORTED_CARE_RECORD:
            detail = db.get(ImportedCareRecord, record.id)
            return {
                "raw_label": detail.raw_label,
                "raw_details": detail.raw_details,
                "raw_line": detail.raw_line,
            }


def to_output(db: Session, record: CareRecord) -> CareRecordOut:
    occurred_at = ms_to_datetime(record.occurred_at_utc)
    created_at = ms_to_datetime(record.created_at)
    updated_at = ms_to_datetime(record.updated_at)
    assert occurred_at is not None and created_at is not None and updated_at is not None
    return CareRecordOut.model_validate(
        {
            "id": record.id,
            "baby_id": record.baby_id,
            "record_type": record.record_type,
            "occurred_at": occurred_at,
            "ended_at": ms_to_datetime(record.ended_at_utc),
            "local_offset_minutes": record.local_offset_minutes,
            "note": record.note,
            "author_label": record.author_label,
            "last_modified_by_label": record.last_modified_by_label,
            "created_at": created_at,
            "updated_at": updated_at,
            "revision": record.revision,
            "details": details_for(db, record),
        }
    )


def append_change(db: Session, record: CareRecord, operation: SyncOperation) -> None:
    db.add(
        SyncChange(
            entity_kind="care_record",
            entity_id=record.id,
            operation=operation,
            revision=record.revision,
        )
    )


def create_record(db: Session, payload: CareRecordCreate, caregiver: Caregiver) -> CareRecord:
    ensure_active_slot(db, payload, caregiver)
    record_id = str(payload.id) if payload.id else None
    if record_id and db.get(CareRecord, record_id):
        raise HTTPException(status_code=409, detail="record_id_exists")
    record = CareRecord(
        id=record_id or None,
        baby_id=str(payload.baby_id),
        record_type=payload.record_type,
        occurred_at_utc=datetime_to_ms(payload.occurred_at),
        ended_at_utc=datetime_to_ms(payload.ended_at) if payload.ended_at else None,
        local_offset_minutes=payload.local_offset_minutes,
        note=payload.note,
        author_id=caregiver.id,
        author_label=caregiver.display_name,
        last_modified_by_id=caregiver.id,
        last_modified_by_label=caregiver.display_name,
    )
    db.add(record)
    db.flush()
    add_detail(db, record.id, payload)
    db.flush()
    append_change(db, record, SyncOperation.UPSERT)
    return record


def update_record(
    db: Session,
    record: CareRecord,
    payload: CareRecordCreate,
    expected_revision: int,
    caregiver: Caregiver,
) -> CareRecord:
    if record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="care_record_not_found")
    if record.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail=StaleRevisionDetail(current=to_output(db, record)).model_dump(mode="json"),
        )
    if record.record_type is RecordType.IMPORTED_CARE_RECORD:
        raise HTTPException(status_code=409, detail="imported_record_read_only")
    if record.record_type != payload.record_type:
        raise HTTPException(status_code=422, detail="record_type_cannot_change")
    if str(payload.baby_id) != record.baby_id:
        raise HTTPException(status_code=422, detail="baby_cannot_change")
    ensure_active_slot(db, payload, caregiver, excluding_id=record.id)
    delete_detail(db, record)
    record.occurred_at_utc = datetime_to_ms(payload.occurred_at)
    record.ended_at_utc = datetime_to_ms(payload.ended_at) if payload.ended_at else None
    record.local_offset_minutes = payload.local_offset_minutes
    record.note = payload.note
    record.last_modified_by_id = caregiver.id
    record.last_modified_by_label = caregiver.display_name
    record.updated_at = now_ms()
    record.revision += 1
    if record.import_batch_id:
        record.modified_since_import = True
    add_detail(db, record.id, payload)
    db.flush()
    append_change(db, record, SyncOperation.UPSERT)
    return record


def tombstone_record(
    db: Session, record: CareRecord, expected_revision: int, caregiver: Caregiver
) -> CareRecord:
    if record.deleted_at is not None:
        return record
    if record.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail=StaleRevisionDetail(current=to_output(db, record)).model_dump(mode="json"),
        )
    if record.record_type is RecordType.IMPORTED_CARE_RECORD:
        raise HTTPException(status_code=409, detail="imported_record_read_only")
    record.deleted_at = now_ms()
    record.updated_at = record.deleted_at
    record.last_modified_by_id = caregiver.id
    record.last_modified_by_label = caregiver.display_name
    record.revision += 1
    append_change(db, record, SyncOperation.DELETE)
    return record
