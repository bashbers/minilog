import asyncio
import csv
import io
import json
import sqlite3
import zipfile
from collections.abc import Awaitable, Callable

import httpx2 as httpx
from conftest import TEST_DATABASE

from minilog.database import engine
from minilog.main import app
from minilog.services.exports import restore_minilog_export


async def with_client(scenario: Callable[[httpx.AsyncClient], Awaitable[bytes]]) -> bytes:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await scenario(client)


def test_checked_export_csv_and_restore_round_trip(tmp_path) -> None:
    async def scenario(client: httpx.AsyncClient) -> bytes:
        setup = await client.post(
            "/api/v1/setup",
            json={
                "setup_token": "test-setup-token-that-is-long-enough",
                "household_name": "Home",
                "time_zone": "Europe/Amsterdam",
                "username": "owner",
                "display_name": "Owner",
                "password": "a long test passphrase",
            },
        )
        csrf = setup.json()["csrf_token"]
        baby = await client.post(
            "/api/v1/babies",
            headers={"X-CSRF-Token": csrf},
            json={"display_name": "Mila", "birth_date": "2026-01-01"},
        )
        baby_id = baby.json()["id"]
        note = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf},
            json={
                "baby_id": baby_id,
                "record_type": "note",
                "occurred_at": "2026-09-09T12:00:00+02:00",
                "local_offset_minutes": 120,
                "body": "Original export value",
            },
        )
        assert note.status_code == 201
        solid_food = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf},
            json={
                "baby_id": baby_id,
                "record_type": "solid_food_feeding",
                "occurred_at": "2026-09-09T13:00:00+02:00",
                "local_offset_minutes": 120,
                "foods": "Banana",
                "note": "=HYPERLINK(\"https://example.invalid\")",
            },
        )
        assert solid_food.status_code == 201

        csv_response = await client.get(f"/api/v1/exports/timeline.csv?baby_id={baby_id}")
        assert csv_response.status_code == 200
        assert "Original export value" in csv_response.text
        rows = list(csv.DictReader(io.StringIO(csv_response.text.lstrip("\ufeff"))))
        formula_note = next(
            row["note"] for row in rows if row["record_type"] == "solid_food_feeding"
        )
        assert formula_note.startswith("'=HYPERLINK")

        archive = await client.get("/api/v1/exports/minilog")
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"
        return archive.content

    archive_bytes = asyncio.run(with_client(scenario))
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == 1
        assert "data.json" in manifest["files"]

    archive_path = tmp_path / "export.zip"
    archive_path.write_bytes(archive_bytes)
    with sqlite3.connect(TEST_DATABASE) as connection:
        connection.execute("UPDATE note_records SET body = 'Changed after export'")
    engine.dispose()

    recovery = restore_minilog_export(archive_path, TEST_DATABASE)
    with sqlite3.connect(TEST_DATABASE) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Original export value"
        )
    with sqlite3.connect(recovery) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Changed after export"
        )
