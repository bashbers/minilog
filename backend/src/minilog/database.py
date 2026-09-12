import fcntl
import os
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from minilog.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


settings = get_settings()

database_url = make_url(settings.database_url)
database_path: Path | None = None
if (
    database_url.get_backend_name() == "sqlite"
    and database_url.database
    and database_url.database != ":memory:"
):
    database_path = Path(database_url.database)
    database_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 5},
    pool_pre_ping=True,
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(Engine, "connect")
def configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA secure_delete=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


class PrivateDatabaseBusyError(RuntimeError):
    pass


@contextmanager
def database_file_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Coordinate online snapshots and privacy-sensitive database mutations."""
    lock_path = path.resolve().with_name(f".{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def private_database_changes(session: Session) -> Iterator[None]:
    """Commit and scrub a sensitive mutation without post-commit failure reporting."""
    if database_path is None:
        raise RuntimeError("Private database changes require file-backed SQLite storage.")

    # Authentication reads may have opened a logical SQLAlchemy transaction. Private commands
    # enter with no pending work, so close that read boundary before acquiring database locks.
    session.rollback()
    with database_file_lock(database_path, exclusive=True):
        original_bind = session.bind
        exclusive_connection = engine.connect()
        session.bind = exclusive_connection
        try:
            try:
                session.execute(text("PRAGMA locking_mode=EXCLUSIVE"))
                busy, _remaining, _checkpointed = session.execute(
                    text("PRAGMA wal_checkpoint(TRUNCATE)")
                ).one()
                if busy:
                    raise PrivateDatabaseBusyError(
                        "Private database maintenance could not checkpoint active readers."
                    )
                journal_mode = session.execute(text("PRAGMA journal_mode=DELETE")).scalar_one()
                if str(journal_mode).lower() != "delete":
                    raise PrivateDatabaseBusyError(
                        "Private database maintenance could not enter rollback-journal mode."
                    )
                session.execute(text("BEGIN EXCLUSIVE"))
            except OperationalError as exc:
                session.rollback()
                raise PrivateDatabaseBusyError(
                    "Private database maintenance could not obtain exclusive access."
                ) from exc

            try:
                yield
                session.commit()
            except Exception:
                session.rollback()
                raise
        finally:
            # Close the Session on success and on failed exclusivity so it cannot retain a
            # reference to the one-use connection.
            session.close()
            session.bind = original_bind
            # Destroy the one-use exclusive handle before releasing the application file lock.
            exclusive_connection.invalidate()
            exclusive_connection.close()


async def get_db() -> AsyncGenerator[Session, None]:
    with SessionLocal() as session:
        yield session
