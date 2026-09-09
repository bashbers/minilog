from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.engine import make_url

from minilog.config import get_settings
from minilog.database import SessionLocal
from minilog.models import AuthSession, Caregiver, CaregiverRole, now_ms
from minilog.security import hash_password


def configured_database_path() -> Path:
    url = make_url(get_settings().database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Maintenance commands require a file-backed SQLite database.")
    return Path(url.database).resolve()


def read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(path.as_posix(), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def verify_database(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Database snapshot does not exist: {path}")
    with read_only_connection(path) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise RuntimeError("SQLite integrity verification failed.")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "alembic_version" not in tables:
            raise RuntimeError("Snapshot is not a migrated Minilog database.")


def backup_database(database_path: Path, output_path: Path | None = None) -> Path:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise RuntimeError(f"Live database does not exist: {database_path}")
    if output_path is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        output_path = database_path.parent / "backups" / f"minilog-{timestamp}.sqlite3"
    output_path = output_path.resolve()
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_path.exists():
        raise RuntimeError(f"Refusing to overwrite existing backup: {output_path}")
    temporary = output_path.with_name(f".{output_path.name}.partial")
    if temporary.exists():
        raise RuntimeError(f"Temporary backup path already exists: {temporary}")
    try:
        with read_only_connection(database_path) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
        os.chmod(temporary, 0o600)
        verify_database(temporary)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def restore_database(snapshot_path: Path, database_path: Path) -> Path:
    snapshot_path = snapshot_path.resolve()
    database_path = database_path.resolve()
    verify_database(snapshot_path)
    recovery = backup_database(database_path)
    temporary = database_path.with_name(f".{database_path.name}.restore")
    if temporary.exists():
        raise RuntimeError(f"Temporary restore path already exists: {temporary}")
    try:
        with read_only_connection(snapshot_path) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        os.chmod(temporary, 0o600)
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


def backup_main() -> None:
    parser = argparse.ArgumentParser(description="Create and verify an online Minilog backup.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = backup_database(configured_database_path(), args.output)
    print(f"Verified backup created at {path}")


def restore_main() -> None:
    parser = argparse.ArgumentParser(description="Restore a verified Minilog SQLite snapshot.")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm the API service is stopped for the entire restore.",
    )
    args = parser.parse_args()
    if not args.confirm_offline:
        parser.error("stop the API, then pass --confirm-offline")
    recovery = restore_database(args.snapshot, configured_database_path())
    print(f"Restore complete. Pre-restore recovery copy: {recovery}")


def restore_export_main() -> None:
    parser = argparse.ArgumentParser(description="Restore a checked Minilog export package.")
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm the API service is stopped for the entire restore.",
    )
    args = parser.parse_args()
    if not args.confirm_offline:
        parser.error("stop the API, then pass --confirm-offline")
    from minilog.services.exports import restore_minilog_export

    recovery = restore_minilog_export(args.archive, configured_database_path())
    print(f"Export restored. Pre-restore recovery copy: {recovery}")


def reset_owner_main() -> None:
    parser = argparse.ArgumentParser(description="Reset the local Minilog Owner password.")
    parser.parse_args()
    first = getpass.getpass("New Owner password (minimum 12 characters): ")
    second = getpass.getpass("Repeat new Owner password: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    if len(first) < 12:
        raise SystemExit("Password must be at least 12 characters.")
    with SessionLocal() as db:
        owner = db.scalar(
            select(Caregiver).where(
                Caregiver.role == CaregiverRole.OWNER,
                Caregiver.is_active.is_(True),
            )
        )
        if owner is None:
            raise SystemExit("No active Owner exists.")
        owner.password_hash = hash_password(first)
        owner.updated_at = now_ms()
        for auth_session in db.scalars(
            select(AuthSession).where(
                AuthSession.caregiver_id == owner.id,
                AuthSession.revoked_at.is_(None),
            )
        ):
            auth_session.revoked_at = now_ms()
        db.commit()
    print("Owner password reset; all existing sessions were revoked.")
