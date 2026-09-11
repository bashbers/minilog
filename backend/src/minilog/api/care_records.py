import json
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database
from minilog.models import Baby, CareRecord, ProcessedMutation, RecordType
from minilog.schemas import (
    BabyActiveStatus,
    CareRecordConflictResponse,
    CareRecordCreate,
    CareRecordOut,
    CareRecordPage,
    CareRecordUpdate,
)
from minilog.services.care_records import (
    BabyNotFoundError,
    InvalidOccurrenceRangeError,
    InvalidPageCursorError,
    active_statuses,
    create_record,
    list_records,
    to_output,
    tombstone_record,
    update_record,
)

router = APIRouter(tags=["care records"])


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
    try:
        page = list_records(
            db,
            str(baby_id),
            cursor=cursor,
            record_types=record_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    except BabyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="baby_not_found") from exc
    except InvalidPageCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid_page_cursor") from exc
    except InvalidOccurrenceRangeError as exc:
        raise HTTPException(status_code=422, detail="invalid_occurrence_range") from exc
    return CareRecordPage(
        items=[to_output(db, record) for record in page.records],
        next_cursor=page.next_cursor,
    )


@router.get("/care-records/active-status", response_model=list[BabyActiveStatus])
async def list_active_statuses(
    _caregiver: CurrentCaregiver, db: Database
) -> list[BabyActiveStatus]:
    return active_statuses(db)


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


@router.put(
    "/care-records/{record_id}",
    response_model=CareRecordOut,
    responses={409: {"model": CareRecordConflictResponse}},
)
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


@router.delete(
    "/care-records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": CareRecordConflictResponse}},
)
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
