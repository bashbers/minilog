import os
import subprocess
import sys
from pathlib import Path


def test_absolute_sqlite_url_creates_its_absolute_parent(tmp_path: Path) -> None:
    database_path = tmp_path / "volume" / "minilog.db"
    readonly_workdir = tmp_path / "readonly"
    readonly_workdir.mkdir()
    readonly_workdir.chmod(0o555)

    environment = os.environ.copy()
    environment["MINILOG_DATABASE_URL"] = f"sqlite:////{database_path.as_posix().lstrip('/')}"
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    try:
        result = subprocess.run(
            [sys.executable, "-c", "import minilog.database"],
            cwd=readonly_workdir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        readonly_workdir.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert database_path.parent.is_dir()
