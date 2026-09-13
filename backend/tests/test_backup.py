import io
import logging
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text

import minilog.cli as cli
from minilog.cli import (
    MaintenanceHandler,
    MigrationUpgradeError,
    backup_database,
    database_revision,
    install_verified_snapshot,
    restore_database,
    restore_source,
    run_alembic_upgrade,
    upgrade_database,
    verify_database,
    verify_database_writable,
)
from minilog.constants import SCHEMA_REVISION
from minilog.database import PrivateDatabaseBusyError, SessionLocal, engine
from minilog.models import Baby
from minilog.services.destructive import permanently_delete_baby


def create_database(path, value: str, revision: str = "test-revision") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))


def marker(path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM marker").fetchone()[0]


def test_backup_is_verified_and_restore_preserves_current_database(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    snapshot = tmp_path / "chosen-backup.sqlite3"
    create_database(live, "before")

    assert backup_database(live, snapshot) == snapshot
    verify_database(snapshot)
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert not any(
        Path(f"{snapshot}{suffix}").exists() for suffix in cli.DATABASE_SIDECAR_SUFFIXES
    )

    with sqlite3.connect(live) as connection:
        connection.execute("UPDATE marker SET value = 'after'")
    recovery = restore_database(snapshot, live)
    assert marker(live) == "before"
    assert marker(recovery) == "after"
    verify_database(recovery)


def test_restore_source_streams_private_input_inside_the_data_directory(
    tmp_path, monkeypatch
) -> None:
    private_bytes = b"private snapshot bytes"
    monkeypatch.setattr(sys, "stdin", Mock(buffer=io.BytesIO(private_bytes)))

    with restore_source("-", tmp_path / "minilog.db") as source:
        assert source.parent == tmp_path
        assert source.read_bytes() == private_bytes
        assert source.stat().st_mode & 0o777 == 0o600
        source_path = source

    assert not source_path.exists()


def test_snapshot_install_removes_an_orphaned_rollback_journal(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    snapshot = tmp_path / "snapshot.sqlite3"
    create_database(live, "private old value")
    create_database(snapshot, "restored value")
    rollback_journal = Path(f"{live}-journal")
    rollback_journal.write_bytes(b"PRIVATE_PRE_RESTORE_JOURNAL_MARKER")

    install_verified_snapshot(snapshot, live)

    assert marker(live) == "restored value"
    assert not rollback_journal.exists()


def test_failed_snapshot_replace_leaves_the_old_database_self_contained(
    tmp_path, monkeypatch
) -> None:
    live = tmp_path / "minilog.sqlite3"
    snapshot = tmp_path / "snapshot.sqlite3"
    create_database(live, "committed old value")
    create_database(snapshot, "replacement value")
    real_replace = os.replace

    def fail_live_replace(source, destination) -> None:
        if Path(destination) == live:
            raise OSError("simulated atomic replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(cli.os, "replace", fail_live_replace)

    with pytest.raises(OSError, match="simulated atomic replacement failure"):
        install_verified_snapshot(snapshot, live)

    assert marker(live) == "committed old value"
    assert not any(Path(f"{live}{suffix}").exists() for suffix in cli.DATABASE_SIDECAR_SUFFIXES)


def test_upgrade_takes_verified_snapshot_and_reaches_expected_revision(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    create_database(live, "before", revision="old-revision")

    def migrate(_config_path) -> None:
        with sqlite3.connect(live) as connection:
            connection.execute(
                "UPDATE alembic_version SET version_num = ?",
                (SCHEMA_REVISION,),
            )
            connection.execute("UPDATE marker SET value = 'migrated'")

    snapshot = upgrade_database(live, tmp_path / "alembic.ini", migrate)

    assert snapshot is not None
    assert marker(live) == "migrated"
    assert marker(snapshot) == "before"
    assert database_revision(live) == SCHEMA_REVISION
    verify_database(snapshot)


def test_failed_upgrade_restores_verified_pre_migration_snapshot(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    create_database(live, "before", revision="old-revision")

    def fail_after_write(_config_path) -> None:
        with sqlite3.connect(live) as connection:
            connection.execute("UPDATE marker SET value = 'partially migrated'")
        raise RuntimeError("simulated migration failure containing private details")

    with pytest.raises(MigrationUpgradeError, match="previous database was restored"):
        upgrade_database(live, tmp_path / "alembic.ini", fail_after_write)

    assert marker(live) == "before"
    assert database_revision(live) == "old-revision"


def test_current_schema_skips_migration_and_snapshot(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    create_database(live, "current", revision=SCHEMA_REVISION)
    calls = 0

    def migrate(_config_path) -> None:
        nonlocal calls
        calls += 1

    assert upgrade_database(live, tmp_path / "alembic.ini", migrate) is None
    assert calls == 0
    assert not (tmp_path / "upgrades").exists()


def test_database_revision_requires_exactly_one_head(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    create_database(live, "current", revision=SCHEMA_REVISION)
    with sqlite3.connect(live) as connection:
        connection.execute("INSERT INTO alembic_version VALUES ('future-branch')")

    with pytest.raises(RuntimeError, match="exactly one schema revision"):
        database_revision(live)


def test_writable_probe_rejects_a_read_only_database(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    create_database(live, "current", revision=SCHEMA_REVISION)
    live.chmod(0o400)
    try:
        with pytest.raises(RuntimeError, match="storage is not writable"):
            verify_database_writable(live)
    finally:
        live.chmod(0o600)


def test_alembic_cannot_disable_startup_diagnostics(tmp_path, monkeypatch) -> None:
    startup_logger = logging.getLogger("minilog.startup")
    startup_logger.disabled = False

    def disable_logger(_config, _revision) -> None:
        startup_logger.disabled = True

    monkeypatch.setattr(cli.command, "upgrade", disable_logger)
    run_alembic_upgrade(tmp_path / "alembic.ini")

    assert startup_logger.disabled is False
    assert startup_logger.level == logging.INFO


def test_maintenance_server_returns_retryable_503_for_writes() -> None:
    handler = object.__new__(MaintenanceHandler)
    handler.send_json = Mock()

    handler.do_POST()

    handler.send_json.assert_called_once_with(
        503,
        {
            "detail": "maintenance",
            "api_contract_version": 1,
        },
    )


def test_failed_start_stays_in_maintenance_without_restarting_migration(monkeypatch) -> None:
    server = Mock()
    thread = Mock()
    monkeypatch.setattr(sys, "argv", ["minilog-start"])
    monkeypatch.setattr(cli, "ThreadingHTTPServer", Mock(return_value=server))
    monkeypatch.setattr(cli.threading, "Thread", Mock(return_value=thread))
    monkeypatch.setattr(cli, "configured_database_path", Mock(return_value=Path("db.sqlite3")))
    monkeypatch.setattr(cli, "upgrade_database", Mock(side_effect=MigrationUpgradeError("failed")))
    hold = Mock()
    monkeypatch.setattr(cli, "hold_maintenance_until_shutdown", hold)
    exec_process = Mock()
    monkeypatch.setattr(cli.os, "execvp", exec_process)

    cli.start_main()

    hold.assert_called_once_with()
    thread.join.assert_called_once_with(timeout=5)
    exec_process.assert_not_called()


def test_invalid_startup_configuration_never_prints_the_setup_token() -> None:
    secret = "S3CR3T"
    environment = os.environ.copy()
    environment.update(
        {
            "MINILOG_SETUP_TOKEN": secret,
            "MINILOG_PUBLIC_ORIGIN": "http://localhost:8080",
            "MINILOG_SECURE_COOKIES": "false",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "from minilog.config import Settings; Settings(_env_file=None)"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_private_deletion_fails_before_commit_when_a_reader_prevents_exclusivity() -> None:
    with SessionLocal() as setup:
        baby = Baby(display_name="Private marker", birth_date="2026-01-01")
        setup.add(baby)
        setup.commit()
        baby_id = baby.id

    database_path = cli.configured_database_path()
    with closing(sqlite3.connect(database_path)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT display_name FROM babies").fetchall()
        with SessionLocal() as deleting:
            deleting.execute(text("PRAGMA busy_timeout=1"))
            with pytest.raises(PrivateDatabaseBusyError, match="exclusive access"):
                permanently_delete_baby(deleting, baby_id, "Private marker", True)

    with SessionLocal() as verification:
        assert verification.get(Baby, baby_id) is not None


def test_private_deletion_releases_exclusive_connection_for_queries_and_backup(tmp_path) -> None:
    with SessionLocal() as setup:
        baby = Baby(display_name="Delete me", birth_date="2026-01-01")
        setup.add(baby)
        setup.commit()
        baby_id = baby.id

    # Exercise the state that would leave multiple idle handles in a persistent SQLAlchemy pool.
    with engine.connect() as first, engine.connect() as second:
        first.execute(text("SELECT COUNT(*) FROM babies")).one()
        second.execute(text("SELECT COUNT(*) FROM babies")).one()

    with SessionLocal() as deleting:
        permanently_delete_baby(deleting, baby_id, "Delete me", True)

    database_path = cli.configured_database_path()
    with closing(sqlite3.connect(database_path, timeout=0.1)) as independent:
        assert independent.execute("SELECT COUNT(*) FROM babies").fetchone() == (0,)
    snapshot = backup_database(database_path, tmp_path / "after-private-change.sqlite3")
    verify_database(snapshot)


def test_sigterm_during_migration_restores_snapshot(tmp_path) -> None:
    live = tmp_path / "minilog.sqlite3"
    ready = tmp_path / "migration-started"
    create_database(live, "before", revision="old-revision")
    source_root = Path(__file__).parents[1] / "src"
    script = """
import sqlite3
import sys
import time
from pathlib import Path
from minilog.cli import upgrade_database

live = Path(sys.argv[1])
ready = Path(sys.argv[2])

def migrate(_config_path):
    with sqlite3.connect(live) as connection:
        connection.execute("UPDATE marker SET value = 'partially migrated'")
    ready.write_text("ready", encoding="utf-8")
    time.sleep(30)

upgrade_database(live, live.parent / "alembic.ini", migrate)
"""
    process_environment = os.environ.copy()
    process_environment["PYTHONPATH"] = source_root.as_posix()
    process = subprocess.Popen(
        [sys.executable, "-c", script, live.as_posix(), ready.as_posix()],
        env=process_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists(), process.communicate(timeout=2)

    process.terminate()
    process.communicate(timeout=5)

    assert process.returncode != 0
    assert marker(live) == "before"
    assert database_revision(live) == "old-revision"
