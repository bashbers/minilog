import json
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from datetime import date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from sqlalchemy import and_, or_, select

from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database
from minilog.models import Baby, CareRecord, Household, ProcessedMutation, RecordType
from minilog.schemas import (
    CareRecordCreate,
    CareRecordOut,
    CareRecordPage,
    CareRecordUpdate,
)
from minilog.services.care_records import (
    create_record,
    to_output,
    tombstone_record,
    update_record,
)

router = APIRouter(tags=["care records"])


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
        raise HTTPException(status_code=422, detail="invalid_page_cursor") from exc


def get_record_or_404(db: Database, record_id: str) -> CareRecord:
    record = db.get(CareRecord, record_id)
    if record is None or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="care_record_not_found")
    return record


@router.get("/care-records", response_model=CareRecordPage)
async def list_care_records(
    baby_id: UUID,
    _caregiver: CurrentCaregiver,
    db: Database,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    record_type: Annotated[list[RecordType] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CareRecordPage:
    if db.get(Baby, str(baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="invalid_occurrence_range")
    household = db.scalar(select(Household))
    if household is None:
        raise RuntimeError("configured Household is missing")
    household_time_zone = ZoneInfo(household.time_zone)
    statement = (
        select(CareRecord)
        .where(CareRecord.baby_id == str(baby_id), CareRecord.deleted_at.is_(None))
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
    if record_type:
        statement = statement.where(CareRecord.record_type.in_(record_type))
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
    return CareRecordPage(
        items=[to_output(db, record) for record in records],
        next_cursor=encode_page_cursor(records[-1]) if has_more and records else None,
    )


@router.get("/care-records/{record_id}", response_model=CareRecordOut)
async def get_care_record(
    record_id: str, _caregiver: CurrentCaregiver, db: Database
) -> CareRecordOut:
    return to_output(db, get_record_or_404(db, record_id))


@router.post("/care-records", response_model=CareRecordOut, status_code=status.HTTP_201_CREATED)
async def post_care_record(
    payload: CareRecordCreate,
    caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
    mutation_id: Annotated[UUID | None, Header(alias="X-Mutation-ID")] = None,
) -> CareRecordOut:
    if db.get(Baby, str(payload.baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    if mutation_id is not None:
        processed = db.get(ProcessedMutation, str(mutation_id))
        if processed is not None:
            if processed.caregiver_id != caregiver.id:
                raise HTTPException(status_code=409, detail="mutation_id_conflict")
            return CareRecordOut.model_validate_json(processed.replay_result)

    record = create_record(db, payload, caregiver)
    output = to_output(db, record)
    if mutation_id is not None:
        db.add(
            ProcessedMutation(
                mutation_id=str(mutation_id),
                caregiver_id=caregiver.id,
                entity_kind="care_record",
                entity_id=record.id,
                result_revision=record.revision,
                replay_result=json.dumps(output.model_dump(mode="json")),
            )
        )
    db.commit()
    return output


@router.put("/care-records/{record_id}", response_model=CareRecordOut)
async def put_care_record(
    record_id: str,
    payload: CareRecordUpdate,
    caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
) -> CareRecordOut:
    record = get_record_or_404(db, record_id)
    record = update_record(db, record, payload.record, payload.expected_revision, caregiver)
    output = to_output(db, record)
    db.commit()
    return output


@router.delete("/care-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_care_record(
    record_id: str,
    expected_revision: Annotated[int, Query(ge=1)],
    caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    record = get_record_or_404(db, record_id)
    tombstone_record(db, record, expected_revision, caregiver)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
