from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import stat
import struct
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, UnidentifiedImageError
from pydantic import TypeAdapter
from sqlalchemy import Boolean, Enum, Integer, LargeBinary, String, create_engine, select, text
from sqlalchemy.orm import Session

from minilog.cli import (
    DATABASE_SIDECAR_SUFFIXES,
    backup_database,
    prepare_database_for_replacement,
    read_only_connection,
    verify_database,
)
from minilog.database import Base
from minilog.models import (
    BabyProfilePicture,
    CareRecord,
    ImportBatch,
    ImportedDailyNote,
    RecordType,
)
from minilog.schemas import CareRecordCreate
from minilog.security import is_password_hash
from minilog.services.care_records import canonical_measurement, to_output
from minilog.services.piyolog import parse_piyolog

EXPORT_FORMAT_VERSION = 2
MAX_RESTORE_BYTES = 100_000_000
MAX_RESTORE_ARCHIVE_BYTES = 100_000_000
MAX_RESTORE_MEMBERS = 10_000
MAX_CENTRAL_DIRECTORY_BYTES = 5_000_000
DATA_TABLES = [
    "households",
    "caregivers",
    "caregiver_quick_actions",
    "babies",
    "baby_profile_pictures",
    "import_batches",
    "care_records",
    "breastfeeding_records",
    "breastfeeding_intervals",
    "bottle_feeding_records",
    "solid_food_feeding_records",
    "sleep_records",
    "diaper_change_records",
    "pumping_records",
    "measurement_records",
    "medication_administration_records",
    "note_records",
    "imported_care_records",
    "imported_daily_notes",
]
RUNTIME_TABLES = ["invitations", "sessions", "processed_mutations", "sync_changes", "sync_state"]
BINARY_COLUMNS = {
    "baby_profile_pictures": {"webp_bytes"},
    "import_batches": {"source_contents"},
}
UUID_COLUMNS = {
    "households": {"id"},
    "caregivers": {"id"},
    "caregiver_quick_actions": {"caregiver_id"},
    "babies": {"id"},
    "baby_profile_pictures": {"baby_id"},
    "import_batches": {"id", "baby_id", "created_by_id"},
    "care_records": {
        "id",
        "baby_id",
        "author_id",
        "last_modified_by_id",
        "import_batch_id",
    },
    "breastfeeding_records": {"care_record_id"},
    "breastfeeding_intervals": {"id", "care_record_id"},
    "bottle_feeding_records": {"care_record_id"},
    "solid_food_feeding_records": {"care_record_id"},
    "sleep_records": {"care_record_id"},
    "diaper_change_records": {"care_record_id"},
    "pumping_records": {"care_record_id"},
    "measurement_records": {"care_record_id"},
    "medication_administration_records": {"care_record_id"},
    "note_records": {"care_record_id"},
    "imported_care_records": {"care_record_id"},
    "imported_daily_notes": {"id", "baby_id", "import_batch_id"},
}
SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
DETAIL_TABLE_BY_RECORD_TYPE = {
    RecordType.BREASTFEEDING.name: "breastfeeding_records",
    RecordType.BOTTLE_FEEDING.name: "bottle_feeding_records",
    RecordType.SOLID_FOOD_FEEDING.name: "solid_food_feeding_records",
    RecordType.SLEEP.name: "sleep_records",
    RecordType.DIAPER_CHANGE.name: "diaper_change_records",
    RecordType.PUMPING.name: "pumping_records",
    RecordType.MEASUREMENT.name: "measurement_records",
    RecordType.MEDICATION_ADMINISTRATION.name: "medication_administration_records",
    RecordType.NOTE.name: "note_records",
    RecordType.IMPORTED_CARE_RECORD.name: "imported_care_records",
}
CARE_RECORD_CREATE_ADAPTER = TypeAdapter(CareRecordCreate)


def json_value(value):
    if hasattr(value, "name") and hasattr(value, "value"):
        return value.name
    return value


def table_rows(db: Session, table_name: str) -> list[dict[str, object]]:
    table = Base.metadata.tables[table_name]
    binary = BINARY_COLUMNS.get(table_name, set())
    rows = []
    for mapping in db.execute(select(table)).mappings():
        rows.append({key: json_value(value) for key, value in mapping.items() if key not in binary})
    return rows


def add_archive_file(files: dict[str, bytes], name: str, contents: bytes) -> None:
    files[name] = contents


def build_minilog_export(db: Session) -> bytes:
    tables = {name: table_rows(db, name) for name in DATA_TABLES}
    retained_source_ids = set(
        db.scalars(select(ImportBatch.id).where(ImportBatch.source_contents.is_not(None)))
    )
    for row in tables["import_batches"]:
        row["source_retained"] = row["id"] in retained_source_ids
    files: dict[str, bytes] = {}
    for picture in db.scalars(select(BabyProfilePicture)):
        add_archive_file(files, f"profile-pictures/{picture.baby_id}.webp", picture.webp_bytes)
    for batch in db.scalars(select(ImportBatch).where(ImportBatch.source_contents.is_not(None))):
        assert batch.source_contents is not None
        add_archive_file(files, f"import-sources/{batch.id}.txt", batch.source_contents)

    data = {
        "format_version": EXPORT_FORMAT_VERSION,
        "tables": tables,
    }
    add_archive_file(
        files,
        "data.json",
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
    )
    database_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    manifest = {
        "format": "minilog-export",
        "format_version": EXPORT_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database_revision": database_revision,
        "files": {
            name: {"sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents)}
            for name, contents in sorted(files.items())
        },
        "notice": "Contains private household data and password hashes; protect this archive.",
    }

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for name, contents in sorted(files.items()):
            archive.writestr(name, contents)
    return output.getvalue()


def build_timeline_csv(db: Session, baby_id: str) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "occurred_at",
            "ended_at",
            "record_type",
            "details_json",
            "note",
            "author",
            "revision",
        ]
    )
    records = db.scalars(
        select(CareRecord)
        .where(CareRecord.baby_id == baby_id, CareRecord.deleted_at.is_(None))
        .order_by(CareRecord.occurred_at_utc, CareRecord.id)
    )
    for record in records:
        item = to_output(db, record).root
        writer.writerow(
            [
                str(item.id),
                item.occurred_at.isoformat(),
                item.ended_at.isoformat() if item.ended_at else "",
                item.record_type.value,
                json.dumps(
                    item.details.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                spreadsheet_safe(item.note or ""),
                spreadsheet_safe(item.author_label),
                item.revision,
            ]
        )
    daily_notes = db.scalars(
        select(ImportedDailyNote)
        .where(ImportedDailyNote.baby_id == baby_id)
        .order_by(ImportedDailyNote.local_date, ImportedDailyNote.id)
    )
    for note in daily_notes:
        writer.writerow(
            [
                note.id,
                note.local_date,
                "",
                "imported_daily_note",
                json.dumps(
                    {"source_author_text": note.source_author_text},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                spreadsheet_safe(note.body),
                spreadsheet_safe(note.source_author_text or "PiyoLog import"),
                "",
            ]
        )
    return output.getvalue()


def spreadsheet_safe(value: str) -> str:
    if value.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def preflight_zip_archive(path: Path) -> None:
    archive_size = path.stat().st_size
    if archive_size > MAX_RESTORE_ARCHIVE_BYTES:
        raise RuntimeError("Export ZIP exceeds the restore archive-size limit.")
    with path.open("rb") as source:
        source.seek(max(0, archive_size - (65_535 + 22)))
        tail = source.read()
    signature = b"PK\x05\x06"
    position = tail.rfind(signature)
    if position < 0 or len(tail) - position < 22:
        raise RuntimeError("Export archive is not a supported ZIP file.")
    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        entry_count,
        directory_size,
        directory_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", tail, position)
    if position + 22 + comment_size != len(tail):
        raise RuntimeError("Export archive has an invalid ZIP directory.")
    if (
        disk_number != 0
        or directory_disk != 0
        or entries_on_disk != entry_count
        or entry_count == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise RuntimeError("Export archive uses an unsupported ZIP layout.")
    if entry_count > MAX_RESTORE_MEMBERS:
        raise RuntimeError("Export archive contains too many members.")
    if directory_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise RuntimeError("Export archive ZIP directory is too large.")
    if directory_offset + directory_size > archive_size:
        raise RuntimeError("Export archive has an invalid ZIP directory.")


def checked_archive(path: Path) -> tuple[dict, dict[str, bytes]]:
    if not path.is_file():
        raise RuntimeError(f"Export archive does not exist: {path}")
    preflight_zip_archive(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_RESTORE_MEMBERS:
                raise RuntimeError("Export archive contains too many members.")
            if sum(info.file_size for info in infos) > MAX_RESTORE_BYTES:
                raise RuntimeError("Export archive expands beyond the restore safety limit.")

            archive_names: set[str] = set()
            for info in infos:
                name = PurePosixPath(info.filename)
                if (
                    not info.filename
                    or "\\" in info.filename
                    or info.filename.endswith("/")
                    or name.is_absolute()
                    or ".." in name.parts
                    or name.as_posix() != info.filename
                ):
                    raise RuntimeError("Export archive contains an unsafe path.")
                if info.filename in archive_names:
                    raise RuntimeError(f"Export archive contains a duplicate path: {info.filename}")
                archive_names.add(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise RuntimeError("Export archive contains a symbolic link.")
                if info.flag_bits & 0x1:
                    raise RuntimeError("Export archive contains an encrypted member.")

            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("Export manifest is missing or invalid.") from exc
            if not isinstance(manifest, dict):
                raise RuntimeError("Export manifest is missing or invalid.")
            if (
                manifest.get("format") != "minilog-export"
                or manifest.get("format_version") != EXPORT_FORMAT_VERSION
            ):
                raise RuntimeError("Export format version is not supported.")
            declared_files = manifest.get("files")
            if not isinstance(declared_files, dict):
                raise RuntimeError("Export manifest file list is invalid.")
            if archive_names != {"manifest.json", *declared_files}:
                raise RuntimeError("Export archive members do not match its manifest.")

            files = {}
            for name, expected in declared_files.items():
                if not isinstance(name, str) or not isinstance(expected, dict):
                    raise RuntimeError("Export manifest file list is invalid.")
                expected_size = expected.get("size")
                expected_hash = expected.get("sha256")
                if (
                    not isinstance(expected_size, int)
                    or isinstance(expected_size, bool)
                    or expected_size < 0
                    or not isinstance(expected_hash, str)
                    or len(expected_hash) != 64
                    or any(character not in "0123456789abcdef" for character in expected_hash)
                ):
                    raise RuntimeError(f"Export manifest metadata is invalid: {name}")
                contents = archive.read(name)
                if len(contents) != expected_size or hashlib.sha256(contents).hexdigest() != (
                    expected_hash
                ):
                    raise RuntimeError(f"Export checksum failed: {name}")
                files[name] = contents
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise RuntimeError("Export archive is not a supported ZIP file.") from exc
    if "data.json" not in files:
        raise RuntimeError("Export data is missing.")
    return manifest, files


def insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    table_definition = Base.metadata.tables[table]
    allowed = {column.name for column in table_definition.columns}
    for row in rows:
        if set(row) != allowed:
            raise RuntimeError(f"Export has invalid columns for {table}.")
        for column in table_definition.columns:
            value = row[column.name]
            if value is None:
                if not column.nullable:
                    raise RuntimeError(
                        f"Export has a null value in {table}.{column.name}."
                    )
                continue
            if column.name in UUID_COLUMNS.get(table, set()):
                try:
                    if not isinstance(value, str) or str(UUID(value)) != value:
                        raise ValueError
                except ValueError as exc:
                    raise RuntimeError(
                        f"Export has an invalid UUID in {table}.{column.name}."
                    ) from exc
            if isinstance(column.type, Boolean):
                valid_type = type(value) is bool
            elif isinstance(column.type, Integer):
                valid_type = type(value) is int and -(2**63) <= value < 2**63
            elif isinstance(column.type, LargeBinary):
                valid_type = isinstance(value, bytes)
            elif isinstance(column.type, Enum):
                valid_type = isinstance(value, str) and value in column.type.enums
            elif isinstance(column.type, String):
                valid_type = isinstance(value, str) and (
                    column.type.length is None or len(value) <= column.type.length
                )
            else:
                raise RuntimeError(
                    f"Restore validation does not support {table}.{column.name}."
                )
            if not valid_type:
                raise RuntimeError(
                    f"Export has an invalid value type in {table}.{column.name}."
                )
        columns = list(row)
        quoted = ",".join(f'"{column}"' for column in columns)
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
            [row[column] for column in columns],
        )


def validate_profile_picture(row: dict, contents: bytes) -> None:
    expected_hash = row.get("content_hash")
    if not isinstance(expected_hash, str) or hashlib.sha256(contents).hexdigest() != expected_hash:
        raise RuntimeError("A profile picture does not match its stored identity.")
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.format != "WEBP" or image.size != (256, 256):
                raise RuntimeError("A profile picture is not a supported Minilog derivative.")
            if image.is_animated or image.n_frames != 1:
                raise RuntimeError("A profile picture must contain exactly one frame.")
            if any(image.info.get(key) for key in ("exif", "xmp", "icc_profile")):
                raise RuntimeError("A profile picture contains forbidden metadata.")
            image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError("A profile picture is not a valid WebP image.") from exc
    if (
        len(contents) < 20
        or contents[:4] != b"RIFF"
        or int.from_bytes(contents[4:8], "little") != len(contents) - 8
        or contents[8:12] != b"WEBP"
        or contents[12:16] != b"VP8 "
    ):
        raise RuntimeError("A profile picture contains unsupported WebP chunks.")
    chunk_size = int.from_bytes(contents[16:20], "little")
    if 20 + chunk_size + (chunk_size % 2) != len(contents):
        raise RuntimeError("A profile picture contains unsupported WebP chunks.")
    if row.get("width") != 256 or row.get("height") != 256:
        raise RuntimeError("A profile picture has invalid stored dimensions.")


def validate_restored_domain(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        household_count = connection.execute("SELECT COUNT(*) FROM households").fetchone()[0]
        if household_count != 1:
            raise RuntimeError("Export must contain exactly one Household.")
        active_owner_count = connection.execute(
            "SELECT COUNT(*) FROM caregivers WHERE role = 'OWNER' AND is_active = 1"
        ).fetchone()[0]
        if active_owner_count != 1:
            raise RuntimeError("Export must contain exactly one active Owner.")
        household = connection.execute(
            "SELECT display_name, time_zone FROM households"
        ).fetchone()
        try:
            if not household[0].strip():
                raise ValueError
            ZoneInfo(household[1])
        except (AttributeError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise RuntimeError("Export contains invalid Household identity data.") from exc
        for username, username_display, display_name, password_hash in connection.execute(
            """
            SELECT username_normalized, username_display, display_name, password_hash
            FROM caregivers
            """
        ):
            if (
                not username.strip()
                or not username_display.strip()
                or not display_name.strip()
                or not is_password_hash(password_hash)
            ):
                raise RuntimeError("Export contains invalid Caregiver identity data.")
        for display_name, birth_date, due_date in connection.execute(
            "SELECT display_name, birth_date, due_date FROM babies"
        ):
            try:
                if not display_name.strip():
                    raise ValueError
                date.fromisoformat(birth_date)
                if due_date is not None:
                    date.fromisoformat(due_date)
            except (AttributeError, TypeError, ValueError) as exc:
                raise RuntimeError("Export contains invalid Baby identity data.") from exc
        for source_time_zone, report_json in connection.execute(
            "SELECT source_time_zone, report_json FROM import_batches"
        ):
            try:
                ZoneInfo(source_time_zone)
                if not isinstance(json.loads(report_json), dict):
                    raise ValueError
            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
                ZoneInfoNotFoundError,
            ) as exc:
                raise RuntimeError("Export contains invalid import metadata.") from exc
        for local_date, body in connection.execute(
            "SELECT local_date, body FROM imported_daily_notes"
        ):
            try:
                date.fromisoformat(local_date)
                if not body:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Export contains an invalid imported daily note.") from exc

        detail_tables_by_record: dict[str, list[str]] = {}
        for table in DETAIL_TABLE_BY_RECORD_TYPE.values():
            for (record_id,) in connection.execute(f'SELECT care_record_id FROM "{table}"'):
                detail_tables_by_record.setdefault(record_id, []).append(table)
        for record_id, record_type in connection.execute(
            "SELECT id, record_type FROM care_records"
        ):
            expected_table = DETAIL_TABLE_BY_RECORD_TYPE.get(record_type)
            if detail_tables_by_record.get(record_id) != [expected_table]:
                raise RuntimeError("A care record has invalid type-specific details.")
        invalid_interval = connection.execute(
            """
            SELECT 1
            FROM breastfeeding_intervals AS intervals
            JOIN care_records AS records ON records.id = intervals.care_record_id
            WHERE records.record_type != 'BREASTFEEDING'
            LIMIT 1
            """
        ).fetchone()
        if invalid_interval:
            raise RuntimeError("A breastfeeding interval belongs to the wrong record type.")

    validation_engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        with Session(validation_engine) as db:
            for record in db.scalars(select(CareRecord)):
                item = to_output(db, record).root
                if not item.author_label.strip() or not item.last_modified_by_label.strip():
                    raise RuntimeError("A care record has invalid attribution.")
                if item.record_type is RecordType.IMPORTED_CARE_RECORD:
                    details = item.details
                    if (
                        not details.raw_label
                        or len(details.raw_label) > 200
                        or not details.raw_line
                    ):
                        raise RuntimeError("An imported care record is invalid.")
                    continue
                details = item.details.model_dump()
                CARE_RECORD_CREATE_ADAPTER.validate_python(
                    {
                        "id": item.id,
                        "baby_id": item.baby_id,
                        "record_type": item.record_type.value,
                        "occurred_at": item.occurred_at,
                        "ended_at": item.ended_at,
                        "local_offset_minutes": item.local_offset_minutes,
                        "note": item.note,
                        **details,
                    }
                )
                if item.record_type is RecordType.MEASUREMENT:
                    expected_value, expected_unit = canonical_measurement(
                        details["kind"], details["entered_value"], details["entered_unit"]
                    )
                    if (
                        details["canonical_value"] != Decimal(expected_value)
                        or details["canonical_unit"] != expected_unit
                    ):
                        raise RuntimeError("A measurement has invalid canonical values.")
    except Exception as exc:
        raise RuntimeError("Export contains an invalid care-record value.") from exc
    finally:
        validation_engine.dispose()


def restore_minilog_export(archive_path: Path, database_path: Path) -> Path:
    manifest, files = checked_archive(archive_path.resolve())
    try:
        payload = json.loads(files["data.json"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Export data JSON is invalid.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Export data JSON is invalid.")
    if payload.get("format_version") != EXPORT_FORMAT_VERSION:
        raise RuntimeError("Export data version is not supported.")
    tables = payload.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(DATA_TABLES):
        raise RuntimeError("Export table set is incomplete or unsupported.")

    database_path = database_path.resolve()
    recovery = backup_database(database_path)
    temporary = database_path.with_name(f".{database_path.name}.export-restore")
    if temporary.exists():
        raise RuntimeError(f"Temporary restore path already exists: {temporary}")
    try:
        with read_only_connection(database_path) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        os.chmod(temporary, 0o600)
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA secure_delete = ON")
            current_revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
            if current_revision != manifest.get("database_revision"):
                raise RuntimeError("Export database revision does not match this Minilog version.")
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            try:
                for table in [*reversed(DATA_TABLES), *RUNTIME_TABLES]:
                    connection.execute(f'DELETE FROM "{table}"')
                expected_asset_files = {"data.json"}
                for table in DATA_TABLES:
                    rows = tables[table]
                    if not isinstance(rows, list):
                        raise RuntimeError(f"Export rows for {table} are invalid.")
                    prepared_rows = []
                    for exported_row in rows:
                        if not isinstance(exported_row, dict):
                            raise RuntimeError(f"Export row for {table} is invalid.")
                        row = dict(exported_row)
                        if table == "baby_profile_pictures":
                            baby_id = row.get("baby_id")
                            if not isinstance(baby_id, str):
                                raise RuntimeError("A profile picture row is invalid.")
                            picture_name = f"profile-pictures/{baby_id}.webp"
                            expected_asset_files.add(picture_name)
                            row["webp_bytes"] = files.get(picture_name)
                            if not isinstance(row["webp_bytes"], bytes):
                                raise RuntimeError("A profile picture file is missing.")
                            validate_profile_picture(row, row["webp_bytes"])
                        if table == "import_batches":
                            batch_id = row.get("id")
                            retained = row.pop("source_retained", None)
                            if not isinstance(batch_id, str) or not isinstance(retained, bool):
                                raise RuntimeError("An import batch retention marker is invalid.")
                            source_name = f"import-sources/{batch_id}.txt"
                            if retained:
                                expected_asset_files.add(source_name)
                                source_contents = files.get(source_name)
                                if not isinstance(source_contents, bytes):
                                    raise RuntimeError("A retained PiyoLog source file is missing.")
                                try:
                                    parsed_source = parse_piyolog(source_contents)
                                except Exception as exc:
                                    raise RuntimeError(
                                        "A retained PiyoLog source is not valid import text."
                                    ) from exc
                                if parsed_source.source_hash != row.get("source_hash"):
                                    raise RuntimeError(
                                        "A retained PiyoLog source does not match its import."
                                    )
                                row["source_contents"] = source_contents
                            else:
                                row["source_contents"] = None
                        prepared_rows.append(row)
                    insert_rows(connection, table, prepared_rows)
                if set(files) != expected_asset_files:
                    raise RuntimeError("Export contains an unreferenced binary asset.")
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError("Restored export violates database relationships.")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        validate_restored_domain(temporary)
        verify_database(temporary)
        prepare_database_for_replacement(database_path)
        for suffix in DATABASE_SIDECAR_SUFFIXES:
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, database_path)
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in DATABASE_SIDECAR_SUFFIXES:
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)
    verify_database(database_path)
    return recovery
