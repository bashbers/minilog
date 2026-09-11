from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from minilog.cli import backup_database, read_only_connection, verify_database
from minilog.database import Base
from minilog.models import BabyProfilePicture, CareRecord, ImportBatch
from minilog.services.care_records import to_output

EXPORT_FORMAT_VERSION = 1
MAX_RESTORE_BYTES = 100_000_000
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
SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


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
    return output.getvalue()


def spreadsheet_safe(value: str) -> str:
    if value.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def checked_archive(path: Path) -> tuple[dict, dict[str, bytes]]:
    if not path.is_file():
        raise RuntimeError(f"Export archive does not exist: {path}")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if sum(info.file_size for info in infos) > MAX_RESTORE_BYTES:
            raise RuntimeError("Export archive expands beyond the restore safety limit.")
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise RuntimeError("Export archive contains an unsafe path.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("Export manifest is missing or invalid.") from exc
        if (
            manifest.get("format") != "minilog-export"
            or manifest.get("format_version") != EXPORT_FORMAT_VERSION
        ):
            raise RuntimeError("Export format version is not supported.")
        files = {}
        for name, expected in manifest.get("files", {}).items():
            try:
                contents = archive.read(name)
            except KeyError as exc:
                raise RuntimeError(f"Export member is missing: {name}") from exc
            if len(contents) != expected.get("size") or hashlib.sha256(
                contents
            ).hexdigest() != expected.get("sha256"):
                raise RuntimeError(f"Export checksum failed: {name}")
            files[name] = contents
    if "data.json" not in files:
        raise RuntimeError("Export data is missing.")
    return manifest, files


def insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    allowed = {column.name for column in Base.metadata.tables[table].columns}
    for row in rows:
        if not row or not set(row).issubset(allowed):
            raise RuntimeError(f"Export has invalid columns for {table}.")
        columns = list(row)
        quoted = ",".join(f'"{column}"' for column in columns)
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
            [row[column] for column in columns],
        )


def restore_minilog_export(archive_path: Path, database_path: Path) -> Path:
    manifest, files = checked_archive(archive_path.resolve())
    try:
        payload = json.loads(files["data.json"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Export data JSON is invalid.") from exc
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
                for table in DATA_TABLES:
                    rows = tables[table]
                    if not isinstance(rows, list):
                        raise RuntimeError(f"Export rows for {table} are invalid.")
                    for row in rows:
                        if not isinstance(row, dict):
                            raise RuntimeError(f"Export row for {table} is invalid.")
                        if table == "baby_profile_pictures":
                            row["webp_bytes"] = files.get(f"profile-pictures/{row['baby_id']}.webp")
                            if row["webp_bytes"] is None:
                                raise RuntimeError("A profile picture file is missing.")
                        if table == "import_batches":
                            row["source_contents"] = files.get(f"import-sources/{row['id']}.txt")
                    insert_rows(connection, table, rows)
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError("Restored export violates database relationships.")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        verify_database(temporary)
        for suffix in ("-wal", "-shm"):
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, database_path)
    finally:
        temporary.unlink(missing_ok=True)
        Path(f"{temporary}-wal").unlink(missing_ok=True)
        Path(f"{temporary}-shm").unlink(missing_ok=True)
    verify_database(database_path)
    return recovery
