from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import signal
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from minilog.config import get_settings
from minilog.constants import API_CONTRACT_VERSION, SCHEMA_REVISION
from minilog.database import SessionLocal, database_file_lock
from minilog.models import AuthSession, Caregiver, CaregiverRole, now_ms
from minilog.security import hash_password

logger = logging.getLogger("minilog.startup")
DATABASE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def configured_database_path() -> Path:
    url = make_url(get_settings().database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Maintenance commands require a file-backed SQLite database.")
    return Path(url.database).resolve()


@contextmanager
def read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"file:{quote(path.as_posix(), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        yield connection
    finally:
        connection.close()


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


def database_revision(path: Path) -> str:
    verify_database(path)
    with read_only_connection(path) as connection:
        revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(revisions) != 1 or not revisions[0][0]:
        raise RuntimeError("Database must have exactly one schema revision.")
    return str(revisions[0][0])


def verify_database_writable(path: Path) -> None:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError("Minilog storage is not writable.")
    temporary_path: Path | None = None
    try:
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE alembic_version SET version_num = version_num")
            connection.rollback()
        descriptor, raw_path = tempfile.mkstemp(prefix=".minilog-write-probe-", dir=path.parent)
        os.close(descriptor)
        temporary_path = Path(raw_path)
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError("Minilog storage is not writable.") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
        with (
            database_file_lock(database_path, exclusive=False),
            read_only_connection(database_path) as source,
            sqlite3.connect(temporary) as target,
        ):
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        os.chmod(temporary, 0o600)
        verify_database(temporary)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in DATABASE_SIDECAR_SUFFIXES:
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)
    return output_path


def install_verified_snapshot(snapshot_path: Path, database_path: Path) -> None:
    snapshot_path = snapshot_path.resolve()
    database_path = database_path.resolve()
    verify_database(snapshot_path)
    temporary = database_path.with_name(f".{database_path.name}.restore")
    if temporary.exists():
        raise RuntimeError(f"Temporary restore path already exists: {temporary}")
    try:
        with read_only_connection(snapshot_path) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        os.chmod(temporary, 0o600)
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


def prepare_database_for_replacement(database_path: Path) -> None:
    """Make the live main file self-contained before its obsolete sidecars are removed."""
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        busy, _remaining, _checkpointed = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        if busy:
            raise RuntimeError("Live database is busy; stop the API before restoring.")
        journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if str(journal_mode).lower() != "delete":
            raise RuntimeError("Live database could not enter restore-safe journal mode.")


def restore_database(snapshot_path: Path, database_path: Path) -> Path:
    snapshot_path = snapshot_path.resolve()
    database_path = database_path.resolve()
    verify_database(snapshot_path)
    recovery = backup_database(database_path)
    install_verified_snapshot(snapshot_path, database_path)
    return recovery


class MigrationUpgradeError(RuntimeError):
    pass


def run_alembic_upgrade(config_path: Path) -> None:
    try:
        command.upgrade(Config(config_path.as_posix()), "head")
    finally:
        logger.disabled = False
        logger.setLevel(logging.INFO)


class MigrationInterruptedError(RuntimeError):
    pass


MIGRATION_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@contextmanager
def migration_signal_guard() -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous = {
        signal_number: signal.getsignal(signal_number)
        for signal_number in MIGRATION_SIGNALS
    }

    def interrupt(signum: int, _frame: object) -> None:
        for signal_number in MIGRATION_SIGNALS:
            signal.signal(signal_number, signal.SIG_IGN)
        raise MigrationInterruptedError(f"Migration interrupted by signal {signum}.")

    for signal_number in MIGRATION_SIGNALS:
        signal.signal(signal_number, interrupt)
    try:
        yield
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)


def hold_maintenance_until_shutdown() -> None:
    stopped = threading.Event()
    previous = {
        signal_number: signal.getsignal(signal_number)
        for signal_number in MIGRATION_SIGNALS
    }

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    for signal_number in MIGRATION_SIGNALS:
        signal.signal(signal_number, stop)
    try:
        stopped.wait()
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)


@contextmanager
def ignore_migration_signals() -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {
        signal_number: signal.getsignal(signal_number)
        for signal_number in MIGRATION_SIGNALS
    }
    for signal_number in MIGRATION_SIGNALS:
        signal.signal(signal_number, signal.SIG_IGN)
    try:
        yield
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)


def upgrade_database(
    database_path: Path,
    config_path: Path,
    migration_runner: Callable[[Path], None] | None = None,
) -> Path | None:
    database_path = database_path.resolve()
    config_path = config_path.resolve()
    existing = database_path.is_file() and database_path.stat().st_size > 0
    if existing and database_revision(database_path) == SCHEMA_REVISION:
        verify_database_writable(database_path)
        return None

    snapshot: Path | None = None
    if existing:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        snapshot = backup_database(
            database_path,
            database_path.parent / "upgrades" / f"minilog-pre-upgrade-{timestamp}.sqlite3",
        )
    else:
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    runner = migration_runner or run_alembic_upgrade
    with migration_signal_guard():
        try:
            runner(config_path)
            revision = database_revision(database_path)
            if revision != SCHEMA_REVISION:
                raise RuntimeError("Migration did not reach the expected schema revision.")
            verify_database_writable(database_path)
        except Exception as exc:
            with ignore_migration_signals():
                if snapshot is not None:
                    install_verified_snapshot(snapshot, database_path)
                else:
                    for suffix in ("", "-wal", "-shm"):
                        Path(f"{database_path}{suffix}").unlink(missing_ok=True)
            raise MigrationUpgradeError(
                "Database migration failed; the previous database was restored."
                if snapshot is not None
                else "Initial database migration failed; the incomplete database was removed."
            ) from exc
    return snapshot


class MaintenanceHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/v1/health/live":
            self.send_json(200, {"status": "maintenance"})
            return
        self.send_maintenance()

    def send_maintenance(self) -> None:
        self.send_json(
            503,
            {"detail": "maintenance", "api_contract_version": API_CONTRACT_VERSION},
        )

    def do_POST(self) -> None:
        self.send_maintenance()

    def do_PUT(self) -> None:
        self.send_maintenance()

    def do_PATCH(self) -> None:
        self.send_maintenance()

    def do_DELETE(self) -> None:
        self.send_maintenance()

    def do_OPTIONS(self) -> None:
        self.send_maintenance()

    def log_message(self, _format: str, *args: object) -> None:
        return


def start_main() -> None:
    parser = argparse.ArgumentParser(description="Safely migrate and start the Minilog API.")
    parser.add_argument("--alembic-config", type=Path, default=Path("alembic.ini"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    server = ThreadingHTTPServer(("0.0.0.0", 8000), MaintenanceHandler)
    thread = threading.Thread(target=server.serve_forever, name="maintenance-http", daemon=True)
    thread.start()
    try:
        logger.info("database lifecycle status=checking")
        snapshot = upgrade_database(configured_database_path(), args.alembic_config)
        if snapshot is not None:
            logger.info("database lifecycle status=upgraded snapshot=%s", snapshot)
        else:
            logger.info("database lifecycle status=ready")
    except Exception as exc:
        logger.error("database lifecycle status=failed exception=%s", type(exc).__name__)
        logger.error("database lifecycle status=maintenance operator_action=required")
        hold_maintenance_until_shutdown()
        return
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "minilog.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-access-log",
            "--no-proxy-headers",
        ],
    )


@contextmanager
def restore_source(argument: str, database_path: Path) -> Iterator[Path]:
    if argument != "-":
        yield Path(argument)
        return
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".minilog-restore-input-", dir=database_path.parent
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as output:
            while chunk := sys.stdin.buffer.read(1024 * 1024):
                output.write(chunk)
        os.chmod(temporary, 0o600)
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def backup_main() -> None:
    parser = argparse.ArgumentParser(description="Create and verify an online Minilog backup.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = backup_database(configured_database_path(), args.output)
    print(f"Verified backup created at {path}")


def restore_main() -> None:
    parser = argparse.ArgumentParser(description="Restore a verified Minilog SQLite snapshot.")
    parser.add_argument("snapshot", help="Snapshot path, or - to read it from standard input.")
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm the API service is stopped for the entire restore.",
    )
    args = parser.parse_args()
    if not args.confirm_offline:
        parser.error("stop the API, then pass --confirm-offline")
    database_path = configured_database_path()
    with restore_source(args.snapshot, database_path) as snapshot:
        recovery = restore_database(snapshot, database_path)
    print(f"Restore complete. Pre-restore recovery copy: {recovery}")


def restore_export_main() -> None:
    parser = argparse.ArgumentParser(description="Restore a checked Minilog export package.")
    parser.add_argument("archive", help="Export path, or - to read it from standard input.")
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm the API service is stopped for the entire restore.",
    )
    args = parser.parse_args()
    if not args.confirm_offline:
        parser.error("stop the API, then pass --confirm-offline")
    from minilog.services.exports import restore_minilog_export

    database_path = configured_database_path()
    with restore_source(args.archive, database_path) as archive:
        recovery = restore_minilog_export(archive, database_path)
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
