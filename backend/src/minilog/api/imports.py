import json
from datetime import datetime, time, timedelta
from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, select

from minilog.config import Settings, get_settings
from minilog.database import private_database_changes
from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database, Owner
from minilog.models import (
    Baby,
    CareRecord,
    ImportBatch,
    ImportedCareRecord,
    ImportedDailyNote,
    RecordType,
    SyncOperation,
    now_ms,
)
from minilog.schemas import (
    ImportBatchOut,
    ImportedDailyNoteOut,
    PiyoLogPreview,
    datetime_to_ms,
    ms_to_datetime,
)
from minilog.services.care_records import append_change, create_record
from minilog.services.piyolog import (
    entry_to_payload,
    localize,
    parse_piyolog,
    reconciliation_totals,
)

router = APIRouter(prefix="/imports/piyolog", tags=["PiyoLog import"])


async def read_source(upload: UploadFile, settings: Settings) -> bytes:
    source = await upload.read(settings.max_import_bytes + 1)
    if len(source) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail="import_too_large")
    if not source:
        raise HTTPException(status_code=422, detail="import_is_empty")
    return source


def import_conflicts(
    db: Database, baby_id: str, parsed, time_zone: str
) -> tuple[list[CareRecord], dict[str, int]]:
    if not parsed.dates:
        return [], {"replaceable": 0, "locally_modified": 0}
    started = datetime_to_ms(localize(datetime.combine(min(parsed.dates), time.min), time_zone))
    ended = datetime_to_ms(
        localize(datetime.combine(max(parsed.dates) + timedelta(days=1), time.min), time_zone)
    )
    records = list(
        db.scalars(
            select(CareRecord).where(
                CareRecord.baby_id == baby_id,
                CareRecord.import_batch_id.is_not(None),
                CareRecord.deleted_at.is_(None),
                CareRecord.occurred_at_utc >= started,
                CareRecord.occurred_at_utc < ended,
            )
        )
    )
    return records, {
        "replaceable": sum(not item.modified_since_import for item in records),
        "locally_modified": sum(item.modified_since_import for item in records),
    }


def preview_response(
    parsed, duplicate_id: str | None = None, conflicts: dict[str, int] | None = None
) -> PiyoLogPreview:
    dates = parsed.dates
    return PiyoLogPreview(
        source_hash=parsed.source_hash,
        duplicate_import_id=duplicate_id,
        detected_locale=parsed.locale,
        date_from=min(dates) if dates else None,
        date_to=max(dates) if dates else None,
        counts=parsed.counts,
        reconciliation_totals=reconciliation_totals(parsed),
        conflicts=conflicts or {},
        unknown_lines=parsed.unknown_lines,
        warnings=parsed.warnings,
    )


def batch_output(batch: ImportBatch) -> ImportBatchOut:
    report = json.loads(batch.report_json)
    created_at = ms_to_datetime(batch.created_at)
    assert created_at is not None
    return ImportBatchOut(
        id=batch.id,
        baby_id=batch.baby_id,
        source_hash=batch.source_hash,
        detected_locale=batch.detected_locale,
        date_from=batch.date_from,
        date_to=batch.date_to,
        status=batch.status,
        counts=report["counts"],
        source_retained=batch.source_contents is not None,
        created_at=created_at,
    )


@router.post("/preview", response_model=PiyoLogPreview)
async def preview_import(
    baby_id: Annotated[UUID, Form()],
    source_time_zone: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> PiyoLogPreview:
    if db.get(Baby, str(baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    localize(datetime.now(), source_time_zone)
    parsed = parse_piyolog(await read_source(file, get_settings()))
    existing = db.scalar(
        select(ImportBatch.id).where(ImportBatch.source_hash == parsed.source_hash)
    )
    _, conflicts = import_conflicts(db, str(baby_id), parsed, source_time_zone)
    return preview_response(parsed, existing, conflicts)


@router.post("/confirm", response_model=ImportBatchOut, status_code=status.HTTP_201_CREATED)
async def confirm_import(
    baby_id: Annotated[UUID, Form()],
    source_time_zone: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
    retain_source: Annotated[bool, Form()] = True,
    replace_modified: Annotated[bool, Form()] = False,
) -> ImportBatchOut:
    if db.get(Baby, str(baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    source = await read_source(file, get_settings())
    parsed = parse_piyolog(source)
    if db.scalar(select(ImportBatch.id).where(ImportBatch.source_hash == parsed.source_hash)):
        raise HTTPException(status_code=409, detail="import_already_confirmed")
    existing_records, conflicts = import_conflicts(db, str(baby_id), parsed, source_time_zone)
    locally_modified_keys = {
        (item.occurred_at_utc, item.record_type)
        for item in existing_records
        if item.modified_since_import
    }
    affected_batches = {item.import_batch_id for item in existing_records if item.import_batch_id}
    changed_at = now_ms()
    for old in existing_records:
        if old.modified_since_import and not replace_modified:
            continue
        old.deleted_at = changed_at
        old.updated_at = changed_at
        old.revision += 1
        append_change(db, old, SyncOperation.DELETE)
    if parsed.dates:
        db.execute(
            delete(ImportedDailyNote).where(
                ImportedDailyNote.baby_id == str(baby_id),
                ImportedDailyNote.local_date >= min(parsed.dates).isoformat(),
                ImportedDailyNote.local_date <= max(parsed.dates).isoformat(),
            )
        )
    for previous_id in affected_batches:
        previous = db.get(ImportBatch, previous_id)
        if previous:
            previous.status = (
                "partially_superseded"
                if conflicts["locally_modified"] and not replace_modified
                else "superseded"
            )

    dates = parsed.dates
    report = {
        "counts": parsed.counts,
        "reconciliation_totals": reconciliation_totals(parsed),
        "warnings": parsed.warnings,
        "unknown_lines": parsed.unknown_lines,
        "conflicts": conflicts,
        "kept_locally_modified": conflicts["locally_modified"] if not replace_modified else 0,
    }
    filename = PurePath((file.filename or "piyolog.txt").replace("\x00", "")).name[:255]
    batch = ImportBatch(
        baby_id=str(baby_id),
        created_by_id=owner.id,
        original_filename=filename or "piyolog.txt",
        source_hash=parsed.source_hash,
        source_time_zone=source_time_zone,
        detected_locale=parsed.locale,
        detected_platform=None,
        format="text",
        date_from=min(dates).isoformat() if dates else None,
        date_to=max(dates).isoformat() if dates else None,
        status="confirmed",
        report_json=json.dumps(report, ensure_ascii=False),
        source_contents=source if retain_source else None,
    )
    db.add(batch)
    db.flush()

    for entry in parsed.entries:
        payload = entry_to_payload(entry, str(baby_id), source_time_zone)
        incoming_type = (
            payload.record_type if payload is not None else RecordType.IMPORTED_CARE_RECORD
        )
        incoming_at = datetime_to_ms(localize(entry.local_at, source_time_zone))
        if not replace_modified and (incoming_at, incoming_type) in locally_modified_keys:
            continue
        if payload is not None:
            record = create_record(db, payload, owner)
            record.author_id = None
            record.author_label = "PiyoLog import"
            record.last_modified_by_id = None
            record.last_modified_by_label = "PiyoLog import"
        else:
            occurred = localize(entry.local_at, source_time_zone)
            offset = int((occurred.utcoffset() or timedelta()).total_seconds() / 60)
            record = CareRecord(
                baby_id=str(baby_id),
                record_type=RecordType.IMPORTED_CARE_RECORD,
                occurred_at_utc=datetime_to_ms(occurred),
                local_offset_minutes=offset,
                author_id=None,
                author_label="PiyoLog import",
                last_modified_by_id=None,
                last_modified_by_label="PiyoLog import",
            )
            db.add(record)
            db.flush()
            db.add(
                ImportedCareRecord(
                    care_record_id=record.id,
                    raw_label=entry.raw_label,
                    raw_details=entry.raw_details,
                    raw_line=entry.raw_line,
                )
            )
            append_change(db, record, SyncOperation.UPSERT)
        record.import_batch_id = batch.id
        record.import_source_line = entry.source_line

    for note in parsed.daily_notes:
        db.add(
            ImportedDailyNote(
                baby_id=str(baby_id),
                local_date=note.local_date.isoformat(),
                body=note.body,
                source_author_text=None,
                import_batch_id=batch.id,
                source_line=note.source_line,
            )
        )
    db.commit()
    return batch_output(batch)


@router.get("", response_model=list[ImportBatchOut])
async def list_imports(_owner: Owner, db: Database) -> list[ImportBatchOut]:
    batches = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())).all()
    return [batch_output(batch) for batch in batches]


@router.get("/daily-notes", response_model=list[ImportedDailyNoteOut])
async def list_imported_daily_notes(
    baby_id: UUID, _caregiver: CurrentCaregiver, db: Database
) -> list[ImportedDailyNoteOut]:
    if db.get(Baby, str(baby_id)) is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    notes = db.scalars(
        select(ImportedDailyNote)
        .where(ImportedDailyNote.baby_id == str(baby_id))
        .order_by(ImportedDailyNote.local_date.desc(), ImportedDailyNote.source_line)
    ).all()
    return [ImportedDailyNoteOut.model_validate(note) for note in notes]


@router.delete("/{batch_id}/source", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import_source(
    batch_id: UUID,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    with private_database_changes(db):
        batch = db.get(ImportBatch, str(batch_id))
        if batch is None:
            raise HTTPException(status_code=404, detail="import_not_found")
        batch.source_contents = None
        batch.source_deleted_at = now_ms()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
