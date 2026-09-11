import sqlite3

import pytest

from minilog.cli import (
    MigrationUpgradeError,
    backup_database,
    database_revision,
    restore_database,
    upgrade_database,
    verify_database,
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
