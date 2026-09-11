import asyncio
import csv
import hashlib
import io
import json
import sqlite3
import stat
import warnings
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
import pytest
from conftest import TEST_DATABASE
from PIL import Image

from minilog.database import SessionLocal, engine
from minilog.main import app
from minilog.services import exports
from minilog.services.exports import (
    DATA_TABLES,
    build_minilog_export,
    checked_archive,
    restore_minilog_export,
)

PIYOLOG_EXPORT = b"""PiyoLog text export
September 8, 2026
07:00 Sleep
08:15 Wake up
08:30 Bottle: 120 ml formula
09:00 Diaper: wet
Diary: A relaxed morning
09:30 Custom event: details are kept
"""


async def with_client(scenario: Callable[[httpx.AsyncClient], Awaitable[bytes]]) -> bytes:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await scenario(client)


def archive_members(contents: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(contents)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def write_archive(path: Path, members: list[tuple[str | zipfile.ZipInfo, bytes]]) -> None:
    with (
        zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore", UserWarning)
        for name, contents in members:
            archive.writestr(name, contents)


def checked_fixture_members(data: bytes = b"{}") -> tuple[dict, list[tuple[str, bytes]]]:
    manifest = {
        "format": "minilog-export",
        "format_version": 1,
        "database_revision": "47ccc6557a5e",
        "files": {
            "data.json": {
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        },
    }
    return manifest, [("manifest.json", json.dumps(manifest).encode()), ("data.json", data)]


def test_checked_export_and_restore_round_trip_every_supported_domain_asset(tmp_path) -> None:
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

        image = io.BytesIO()
        Image.new("RGB", (80, 120), "#f0a07a").save(image, "PNG")
        uploaded = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("mila.png", image.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 204, uploaded.text

        common = {
            "baby_id": baby_id,
            "occurred_at": "2026-09-09T12:00:00+02:00",
            "local_offset_minutes": 120,
        }
        native_records = [
            {
                **common,
                "record_type": "breastfeeding",
                "ended_at": "2026-09-09T12:15:00+02:00",
                "estimated_amount_ml": 20,
                "intervals": [
                    {
                        "side": "left",
                        "started_at": "2026-09-09T12:00:00+02:00",
                        "ended_at": "2026-09-09T12:15:00+02:00",
                    }
                ],
            },
            {
                **common,
                "record_type": "bottle_feeding",
                "consumed_ml": 90,
                "offered_ml": 100,
                "contents": "formula",
            },
            {
                **common,
                "record_type": "solid_food_feeding",
                "foods": "Banana",
                "amount_value": "2",
                "amount_unit": "spoons",
                "reaction_note": "No reaction observed",
                "note": '=HYPERLINK("https://example.invalid")',
            },
            {**common, "record_type": "sleep", "ended_at": "2026-09-09T13:00:00+02:00"},
            {**common, "record_type": "diaper_change", "is_wet": True, "is_dirty": True},
            {
                **common,
                "record_type": "pumping",
                "ended_at": "2026-09-09T12:20:00+02:00",
                "expressed_ml": 80,
            },
            {
                **common,
                "record_type": "measurement",
                "kind": "weight",
                "entered_value": "7.2",
                "entered_unit": "kg",
            },
            {
                **common,
                "record_type": "medication_administration",
                "medicine_name": "Example medicine",
                "amount_value": "2.5",
                "unit_code": "ml",
            },
            {**common, "record_type": "note", "body": "Original export value"},
        ]
        for payload in native_records:
            response = await client.post(
                "/api/v1/care-records",
                headers={"X-CSRF-Token": csrf, "X-Mutation-ID": str(uuid4())},
                json=payload,
            )
            assert response.status_code == 201, response.text

        imported = await client.post(
            "/api/v1/imports/piyolog/confirm",
            headers={"X-CSRF-Token": csrf},
            data={
                "baby_id": baby_id,
                "source_time_zone": "Europe/Amsterdam",
                "retain_source": "true",
            },
            files={"file": ("piyolog.txt", PIYOLOG_EXPORT, "text/plain")},
        )
        assert imported.status_code == 201, imported.text

        csv_response = await client.get(f"/api/v1/exports/timeline.csv?baby_id={baby_id}")
        assert csv_response.status_code == 200
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
    members = archive_members(archive_bytes)
    manifest = json.loads(members["manifest.json"])
    payload = json.loads(members["data.json"])
    assert manifest["format_version"] == 1
    assert set(payload["tables"]) == set(DATA_TABLES)
    assert {row["record_type"] for row in payload["tables"]["care_records"]} == {
        "BREASTFEEDING",
        "BOTTLE_FEEDING",
        "SOLID_FOOD_FEEDING",
        "SLEEP",
        "DIAPER_CHANGE",
        "PUMPING",
        "MEASUREMENT",
        "MEDICATION_ADMINISTRATION",
        "NOTE",
        "IMPORTED_CARE_RECORD",
    }
    for detail_table in (
        "breastfeeding_records",
        "breastfeeding_intervals",
        "bottle_feeding_records",
        "solid_food_feeding_records",
        "sleep_records",
        "diaper_change_records",
        "pumping_records",
        "measurement_records",
        "medication_administration_records",
        "note_records",
        "imported_care_records",
        "imported_daily_notes",
    ):
        assert payload["tables"][detail_table], detail_table
    picture_name = next(name for name in members if name.startswith("profile-pictures/"))
    import_name = next(name for name in members if name.startswith("import-sources/"))
    original_picture = members[picture_name]
    assert members[import_name] == PIYOLOG_EXPORT

    archive_path = tmp_path / "export.zip"
    archive_path.write_bytes(archive_bytes)
    with sqlite3.connect(TEST_DATABASE) as connection:
        connection.execute("UPDATE note_records SET body = 'Changed after export'")
        connection.execute("UPDATE baby_profile_pictures SET webp_bytes = X'00'")
        connection.execute("UPDATE import_batches SET source_contents = X'01'")
    engine.dispose()

    invalid_payload = json.loads(members["data.json"])
    invalid_payload["tables"]["households"][0]["unsupported_column"] = True
    invalid_data = json.dumps(
        invalid_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    invalid_manifest = json.loads(members["manifest.json"])
    invalid_manifest["files"]["data.json"] = {
        "size": len(invalid_data),
        "sha256": hashlib.sha256(invalid_data).hexdigest(),
    }
    invalid_path = tmp_path / "invalid-semantic-export.zip"
    write_archive(
        invalid_path,
        [
            ("manifest.json", json.dumps(invalid_manifest).encode()),
            *[
                (name, invalid_data if name == "data.json" else contents)
                for name, contents in members.items()
                if name != "manifest.json"
            ],
        ],
    )
    with pytest.raises(RuntimeError, match="invalid columns"):
        restore_minilog_export(invalid_path, TEST_DATABASE)
    with sqlite3.connect(TEST_DATABASE) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Changed after export"
        )
        assert connection.execute("SELECT webp_bytes FROM baby_profile_pictures").fetchone()[0] == (
            b"\x00"
        )

    recovery = restore_minilog_export(archive_path, TEST_DATABASE)
    with sqlite3.connect(TEST_DATABASE) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Original export value"
        )
        assert connection.execute("SELECT webp_bytes FROM baby_profile_pictures").fetchone()[0] == (
            original_picture
        )
        assert connection.execute("SELECT source_contents FROM import_batches").fetchone()[0] == (
            PIYOLOG_EXPORT
        )
    with sqlite3.connect(recovery) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Changed after export"
        )

    with SessionLocal() as db:
        restored_members = archive_members(build_minilog_export(db))
    assert restored_members["data.json"] == members["data.json"]
    assert restored_members[picture_name] == original_picture
    assert restored_members[import_name] == PIYOLOG_EXPORT


def test_checked_archive_rejects_corruption(tmp_path) -> None:
    manifest, members = checked_fixture_members(b"trusted")
    path = tmp_path / "corrupt.zip"
    write_archive(path, [members[0], ("data.json", b"tampered")])

    with pytest.raises(RuntimeError, match="checksum failed"):
        checked_archive(path)
    assert manifest["files"]["data.json"]["size"] == len(b"trusted")


def test_checked_archive_rejects_traversal_symlinks_and_duplicate_paths(tmp_path) -> None:
    _manifest, members = checked_fixture_members()

    traversal = tmp_path / "traversal.zip"
    write_archive(traversal, [*members, ("../outside", b"private")])
    with pytest.raises(RuntimeError, match="unsafe path"):
        checked_archive(traversal)

    symlink_info = zipfile.ZipInfo("profile-pictures/link.webp")
    symlink_info.create_system = 3
    symlink_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    symlink = tmp_path / "symlink.zip"
    write_archive(symlink, [*members, (symlink_info, b"../../outside")])
    with pytest.raises(RuntimeError, match="symbolic link"):
        checked_archive(symlink)

    duplicate = tmp_path / "duplicate.zip"
    write_archive(duplicate, [*members, ("data.json", b"{}")])
    with pytest.raises(RuntimeError, match="duplicate path"):
        checked_archive(duplicate)


def test_checked_archive_rejects_unknown_versions_members_and_excessive_expansion(
    tmp_path, monkeypatch
) -> None:
    manifest, _members = checked_fixture_members()
    manifest["format_version"] = 2
    incompatible = tmp_path / "incompatible.zip"
    write_archive(
        incompatible,
        [("manifest.json", json.dumps(manifest).encode()), ("data.json", b"{}")],
    )
    with pytest.raises(RuntimeError, match="version is not supported"):
        checked_archive(incompatible)

    _manifest, valid_members = checked_fixture_members()
    extra = tmp_path / "extra.zip"
    write_archive(extra, [*valid_members, ("undeclared.txt", b"unexpected")])
    with pytest.raises(RuntimeError, match="do not match its manifest"):
        checked_archive(extra)

    oversized = tmp_path / "oversized.zip"
    write_archive(oversized, valid_members)
    monkeypatch.setattr(exports, "MAX_RESTORE_BYTES", 1)
    with pytest.raises(RuntimeError, match="safety limit"):
        checked_archive(oversized)
