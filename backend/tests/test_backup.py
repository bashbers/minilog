import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

import minilog.cli as cli
from minilog.cli import (
    MaintenanceHandler,
    MigrationUpgradeError,
    backup_database,
    database_revision,
    restore_database,
    run_alembic_upgrade,
    upgrade_database,
    verify_database,
    verify_database_writable,
)
from minilog.constants import SCHEMA_REVISION


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

    with sqlite3.connect(live) as connection:
        connection.execute("UPDATE marker SET value = 'after'")

    recovery = restore_database(snapshot, live)
    assert marker(live) == "before"
    assert marker(recovery) == "after"
    verify_database(recovery)


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
