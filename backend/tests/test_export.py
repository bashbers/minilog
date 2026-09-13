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
from contextlib import closing
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
Diary: =HYPERLINK("https://example.invalid/daily")
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
        "format_version": 2,
        "database_revision": "47ccc6557a5e",
        "files": {
            "data.json": {
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        },
    }
    return manifest, [("manifest.json", json.dumps(manifest).encode()), ("data.json", data)]


def write_self_consistent_export(
    path: Path,
    original_members: dict[str, bytes],
    *,
    replacements: dict[str, bytes] | None = None,
    omissions: set[str] | None = None,
) -> None:
    files = {
        name: contents
        for name, contents in original_members.items()
        if name != "manifest.json" and name not in (omissions or set())
    }
    files.update(replacements or {})
    manifest = json.loads(original_members["manifest.json"])
    manifest["files"] = {
        name: {"size": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
        for name, contents in sorted(files.items())
    }
    write_archive(
        path,
        [("manifest.json", json.dumps(manifest).encode()), *sorted(files.items())],
    )


def write_payload_variant(
    path: Path,
    original_members: dict[str, bytes],
    mutate: Callable[[dict], None],
) -> None:
    payload = json.loads(original_members["data.json"])
    mutate(payload)
    data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    write_self_consistent_export(
        path, original_members, replacements={"data.json": data}
    )


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
        daily_note = next(row for row in rows if row["record_type"] == "imported_daily_note")
        assert daily_note["occurred_at"] == "2026-09-08"
        assert daily_note["note"].startswith("'=HYPERLINK")

        archive = await client.get("/api/v1/exports/minilog")
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"
        return archive.content

    archive_bytes = asyncio.run(with_client(scenario))
    members = archive_members(archive_bytes)
    manifest = json.loads(members["manifest.json"])
    payload = json.loads(members["data.json"])
    assert manifest["format_version"] == 2
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
    with closing(sqlite3.connect(TEST_DATABASE)) as connection:
        connection.execute("UPDATE note_records SET body = 'RESTORE_PRIVATE_MARKER_C3F971'")
        connection.execute("UPDATE baby_profile_pictures SET webp_bytes = X'00'")
        connection.execute("UPDATE import_batches SET source_contents = X'01'")
        connection.commit()
    engine.dispose()

    invalid_payload = json.loads(members["data.json"])
    invalid_payload["tables"]["households"][0]["unsupported_column"] = True
    invalid_data = json.dumps(
        invalid_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    invalid_path = tmp_path / "invalid-semantic-export.zip"
    write_self_consistent_export(
        invalid_path, members, replacements={"data.json": invalid_data}
    )
    with pytest.raises(RuntimeError, match="invalid columns"):
        restore_minilog_export(invalid_path, TEST_DATABASE)
    with closing(sqlite3.connect(TEST_DATABASE)) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "RESTORE_PRIVATE_MARKER_C3F971"
        )
        assert connection.execute("SELECT webp_bytes FROM baby_profile_pictures").fetchone()[0] == (
            b"\x00"
        )

    missing_detail_payload = json.loads(members["data.json"])
    missing_detail_payload["tables"]["bottle_feeding_records"] = []
    missing_detail_data = json.dumps(
        missing_detail_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    missing_detail_path = tmp_path / "missing-detail.zip"
    write_self_consistent_export(
        missing_detail_path, members, replacements={"data.json": missing_detail_data}
    )
    with pytest.raises(RuntimeError, match="type-specific details"):
        restore_minilog_export(missing_detail_path, TEST_DATABASE)

    mismatched_detail_payload = json.loads(members["data.json"])
    bottle_id = mismatched_detail_payload["tables"]["bottle_feeding_records"][0][
        "care_record_id"
    ]
    mismatched_detail_payload["tables"]["sleep_records"].append(
        {"care_record_id": bottle_id}
    )
    mismatched_detail_data = json.dumps(
        mismatched_detail_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    mismatched_detail_path = tmp_path / "mismatched-detail.zip"
    write_self_consistent_export(
        mismatched_detail_path,
        members,
        replacements={"data.json": mismatched_detail_data},
    )
    with pytest.raises(RuntimeError, match="type-specific details"):
        restore_minilog_export(mismatched_detail_path, TEST_DATABASE)

    invalid_picture_payload = json.loads(members["data.json"])
    invalid_picture_payload["tables"]["baby_profile_pictures"][0]["content_hash"] = (
        hashlib.sha256(b"not a webp").hexdigest()
    )
    invalid_picture_data = json.dumps(
        invalid_picture_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    invalid_picture_path = tmp_path / "invalid-picture.zip"
    write_self_consistent_export(
        invalid_picture_path,
        members,
        replacements={"data.json": invalid_picture_data, picture_name: b"not a webp"},
    )
    with pytest.raises(RuntimeError, match="valid WebP"):
        restore_minilog_export(invalid_picture_path, TEST_DATABASE)

    mismatched_picture_path = tmp_path / "mismatched-picture.zip"
    write_self_consistent_export(
        mismatched_picture_path, members, replacements={picture_name: b"not the stored picture"}
    )
    with pytest.raises(RuntimeError, match="stored identity"):
        restore_minilog_export(mismatched_picture_path, TEST_DATABASE)

    metadata_picture = io.BytesIO()
    private_exif = Image.Exif()
    private_exif[0x010E] = "private original description"
    Image.new("RGB", (256, 256), "#f0a07a").save(
        metadata_picture, "WEBP", exif=private_exif
    )
    metadata_picture_bytes = metadata_picture.getvalue()
    metadata_picture_payload = json.loads(members["data.json"])
    metadata_picture_payload["tables"]["baby_profile_pictures"][0]["content_hash"] = (
        hashlib.sha256(metadata_picture_bytes).hexdigest()
    )
    metadata_picture_data = json.dumps(
        metadata_picture_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    metadata_picture_path = tmp_path / "metadata-picture.zip"
    write_self_consistent_export(
        metadata_picture_path,
        members,
        replacements={
            "data.json": metadata_picture_data,
            picture_name: metadata_picture_bytes,
        },
    )
    with pytest.raises(RuntimeError, match="forbidden metadata"):
        restore_minilog_export(metadata_picture_path, TEST_DATABASE)

    animated_picture = io.BytesIO()
    Image.new("RGB", (256, 256), "#f0a07a").save(
        animated_picture,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (256, 256), "#7256a8")],
        duration=100,
        loop=0,
    )
    animated_picture_bytes = animated_picture.getvalue()
    animated_picture_payload = json.loads(members["data.json"])
    animated_picture_payload["tables"]["baby_profile_pictures"][0]["content_hash"] = (
        hashlib.sha256(animated_picture_bytes).hexdigest()
    )
    animated_picture_data = json.dumps(
        animated_picture_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    animated_picture_path = tmp_path / "animated-picture.zip"
    write_self_consistent_export(
        animated_picture_path,
        members,
        replacements={
            "data.json": animated_picture_data,
            picture_name: animated_picture_bytes,
        },
    )
    with pytest.raises(RuntimeError, match="exactly one frame"):
        restore_minilog_export(animated_picture_path, TEST_DATABASE)

    private_chunk_payload = b"private profile-picture residue"
    private_chunk = (
        b"PRIV"
        + len(private_chunk_payload).to_bytes(4, "little")
        + private_chunk_payload
        + (b"\x00" if len(private_chunk_payload) % 2 else b"")
    )
    original_picture = members[picture_name]
    chunked_picture_bytes = (
        b"RIFF"
        + (len(original_picture) - 8 + len(private_chunk)).to_bytes(4, "little")
        + original_picture[8:]
        + private_chunk
    )
    chunked_picture_payload = json.loads(members["data.json"])
    chunked_picture_payload["tables"]["baby_profile_pictures"][0]["content_hash"] = (
        hashlib.sha256(chunked_picture_bytes).hexdigest()
    )
    chunked_picture_data = json.dumps(
        chunked_picture_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    chunked_picture_path = tmp_path / "private-chunk-picture.zip"
    write_self_consistent_export(
        chunked_picture_path,
        members,
        replacements={
            "data.json": chunked_picture_data,
            picture_name: chunked_picture_bytes,
        },
    )
    with pytest.raises(RuntimeError, match="unsupported WebP chunks"):
        restore_minilog_export(chunked_picture_path, TEST_DATABASE)

    omitted_source_path = tmp_path / "omitted-source.zip"
    write_self_consistent_export(omitted_source_path, members, omissions={import_name})
    with pytest.raises(RuntimeError, match="source file is missing"):
        restore_minilog_export(omitted_source_path, TEST_DATABASE)

    substituted_source_path = tmp_path / "substituted-source.zip"
    write_self_consistent_export(
        substituted_source_path, members, replacements={import_name: b"different source"}
    )
    with pytest.raises(RuntimeError, match="does not match its import"):
        restore_minilog_export(substituted_source_path, TEST_DATABASE)

    invalid_source_payload = json.loads(members["data.json"])
    invalid_source_payload["tables"]["import_batches"][0]["source_hash"] = hashlib.sha256(
        b"\x80"
    ).hexdigest()
    invalid_source_data = json.dumps(
        invalid_source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    invalid_source_path = tmp_path / "invalid-source-text.zip"
    write_self_consistent_export(
        invalid_source_path,
        members,
        replacements={"data.json": invalid_source_data, import_name: b"\x80"},
    )
    with pytest.raises(RuntimeError, match="not valid import text"):
        restore_minilog_export(invalid_source_path, TEST_DATABASE)

    def remove_active_owner(payload: dict) -> None:
        owner = next(
            row for row in payload["tables"]["caregivers"] if row["role"] == "OWNER"
        )
        owner["is_active"] = False

    no_owner_path = tmp_path / "no-active-owner.zip"
    write_payload_variant(no_owner_path, members, remove_active_owner)
    with pytest.raises(RuntimeError, match="exactly one active Owner"):
        restore_minilog_export(no_owner_path, TEST_DATABASE)

    def invalidate_owner_password(payload: dict) -> None:
        owner = next(
            row for row in payload["tables"]["caregivers"] if row["role"] == "OWNER"
        )
        owner["password_hash"] = "not-an-argon2-hash"

    invalid_owner_password_path = tmp_path / "invalid-owner-password.zip"
    write_payload_variant(
        invalid_owner_password_path, members, invalidate_owner_password
    )
    with pytest.raises(RuntimeError, match="invalid Caregiver identity"):
        restore_minilog_export(invalid_owner_password_path, TEST_DATABASE)

    def add_invalid_unreferenced_baby(payload: dict) -> None:
        baby = dict(payload["tables"]["babies"][0])
        baby.update({"id": "not-a-uuid", "display_name": "Invalid identity"})
        payload["tables"]["babies"].append(baby)

    invalid_uuid_path = tmp_path / "invalid-uuid.zip"
    write_payload_variant(invalid_uuid_path, members, add_invalid_unreferenced_baby)
    with pytest.raises(RuntimeError, match=r"invalid UUID in babies\.id"):
        restore_minilog_export(invalid_uuid_path, TEST_DATABASE)

    def invalidate_baby_timestamp(payload: dict) -> None:
        payload["tables"]["babies"][0]["updated_at"] = "not-an-integer"

    invalid_scalar_path = tmp_path / "invalid-scalar.zip"
    write_payload_variant(invalid_scalar_path, members, invalidate_baby_timestamp)
    with pytest.raises(RuntimeError, match=r"invalid value type in babies\.updated_at"):
        restore_minilog_export(invalid_scalar_path, TEST_DATABASE)

    def invalidate_boolean(payload: dict) -> None:
        payload["tables"]["caregivers"][0]["is_active"] = 1

    invalid_boolean_path = tmp_path / "invalid-boolean.zip"
    write_payload_variant(invalid_boolean_path, members, invalidate_boolean)
    with pytest.raises(RuntimeError, match=r"invalid value type in caregivers\.is_active"):
        restore_minilog_export(invalid_boolean_path, TEST_DATABASE)

    def invalidate_enum(payload: dict) -> None:
        payload["tables"]["households"][0]["clock_format"] = "THIRTEEN_HOUR"

    invalid_enum_path = tmp_path / "invalid-enum.zip"
    write_payload_variant(invalid_enum_path, members, invalidate_enum)
    with pytest.raises(RuntimeError, match=r"invalid value type in households\.clock_format"):
        restore_minilog_export(invalid_enum_path, TEST_DATABASE)

    def empty_note(payload: dict) -> None:
        payload["tables"]["note_records"][0]["body"] = ""

    empty_note_path = tmp_path / "empty-note.zip"
    write_payload_variant(empty_note_path, members, empty_note)
    with pytest.raises(RuntimeError, match="invalid care-record value"):
        restore_minilog_export(empty_note_path, TEST_DATABASE)

    def non_positive_medication(payload: dict) -> None:
        payload["tables"]["medication_administration_records"][0]["amount_value"] = "0"

    invalid_medication_path = tmp_path / "invalid-medication.zip"
    write_payload_variant(invalid_medication_path, members, non_positive_medication)
    with pytest.raises(RuntimeError, match="invalid care-record value"):
        restore_minilog_export(invalid_medication_path, TEST_DATABASE)

    def wrong_measurement_canonical_value(payload: dict) -> None:
        payload["tables"]["measurement_records"][0]["canonical_value"] = "999"

    invalid_measurement_path = tmp_path / "invalid-measurement.zip"
    write_payload_variant(
        invalid_measurement_path, members, wrong_measurement_canonical_value
    )
    with pytest.raises(RuntimeError, match="invalid care-record value"):
        restore_minilog_export(invalid_measurement_path, TEST_DATABASE)

    def out_of_bounds_breastfeeding_interval(payload: dict) -> None:
        interval = payload["tables"]["breastfeeding_intervals"][0]
        interval["started_at_utc"] -= 60_000

    out_of_bounds_path = tmp_path / "out-of-bounds-breastfeeding.zip"
    write_payload_variant(
        out_of_bounds_path, members, out_of_bounds_breastfeeding_interval
    )
    with pytest.raises(RuntimeError, match="invalid care-record value"):
        restore_minilog_export(out_of_bounds_path, TEST_DATABASE)

    def overlapping_breastfeeding_intervals(payload: dict) -> None:
        interval = payload["tables"]["breastfeeding_intervals"][0]
        payload["tables"]["breastfeeding_intervals"].append(
            {
                "id": str(uuid4()),
                "care_record_id": interval["care_record_id"],
                "position": 1,
                "side": "right",
                "started_at_utc": interval["started_at_utc"] + 1,
                "ended_at_utc": interval["ended_at_utc"],
            }
        )

    overlapping_path = tmp_path / "overlapping-breastfeeding.zip"
    write_payload_variant(overlapping_path, members, overlapping_breastfeeding_intervals)
    with pytest.raises(RuntimeError, match="invalid care-record value"):
        restore_minilog_export(overlapping_path, TEST_DATABASE)

    with closing(sqlite3.connect(TEST_DATABASE)) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "RESTORE_PRIVATE_MARKER_C3F971"
        )
        assert connection.execute("SELECT webp_bytes FROM baby_profile_pictures").fetchone()[0] == (
            b"\x00"
        )
    recovery = restore_minilog_export(archive_path, TEST_DATABASE)
    with closing(sqlite3.connect(TEST_DATABASE)) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "Original export value"
        )
        assert connection.execute("SELECT webp_bytes FROM baby_profile_pictures").fetchone()[0] == (
            original_picture
        )
        assert connection.execute("SELECT source_contents FROM import_batches").fetchone()[0] == (
            PIYOLOG_EXPORT
        )
    with closing(sqlite3.connect(recovery)) as connection:
        assert connection.execute("SELECT body FROM note_records").fetchone()[0] == (
            "RESTORE_PRIVATE_MARKER_C3F971"
        )

    engine.dispose()
    for live_path in (
        TEST_DATABASE,
        Path(f"{TEST_DATABASE}-wal"),
        Path(f"{TEST_DATABASE}-shm"),
        Path(f"{TEST_DATABASE}-journal"),
    ):
        if live_path.exists():
            assert b"RESTORE_PRIVATE_MARKER_C3F971" not in live_path.read_bytes()

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
    manifest["format_version"] = 3
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


def test_checked_archive_preflights_file_size_and_member_count(tmp_path, monkeypatch) -> None:
    _manifest, members = checked_fixture_members()
    path = tmp_path / "preflight.zip"
    write_archive(path, members)

    original_archive_limit = exports.MAX_RESTORE_ARCHIVE_BYTES
    monkeypatch.setattr(exports, "MAX_RESTORE_ARCHIVE_BYTES", 1)
    with pytest.raises(RuntimeError, match="archive-size limit"):
        checked_archive(path)

    monkeypatch.setattr(exports, "MAX_RESTORE_ARCHIVE_BYTES", original_archive_limit)
    monkeypatch.setattr(exports, "MAX_RESTORE_MEMBERS", 1)
    with pytest.raises(RuntimeError, match="too many members"):
        checked_archive(path)
