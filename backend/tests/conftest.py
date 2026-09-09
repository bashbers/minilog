import os
from pathlib import Path

import pytest

TEST_DATABASE = Path("/tmp/minilog-pytest.sqlite3")
os.environ["MINILOG_DATABASE_URL"] = f"sqlite:////{TEST_DATABASE.as_posix().lstrip('/')}"
os.environ["MINILOG_SETUP_TOKEN"] = "test-setup-token-that-is-long-enough"
os.environ["MINILOG_SECURE_COOKIES"] = "false"

from minilog import models as _models  # noqa: E402,F401
from minilog.database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
