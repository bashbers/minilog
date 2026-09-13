import os
from pathlib import Path

import pytest

TEST_DATABASE = Path("/tmp/minilog-pytest.sqlite3")
os.environ["MINILOG_DATABASE_URL"] = f"sqlite:////{TEST_DATABASE.as_posix().lstrip('/')}"
os.environ["MINILOG_SETUP_TOKEN"] = "test-setup-token-that-is-long-enough"
os.environ["MINILOG_SECURE_COOKIES"] = "false"
os.environ["MINILOG_PUBLIC_ORIGIN"] = "http://test"

from sqlalchemy import text  # noqa: E402

from minilog import models as _models  # noqa: E402,F401
from minilog.database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        connection.execute(text("INSERT INTO alembic_version VALUES ('47ccc6557a5e')"))
    yield
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
