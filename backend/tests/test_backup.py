import sqlite3

from minilog.cli import backup_database, restore_database, verify_database


def create_database(path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('test-revision')")
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
