import asyncio
import io
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2 as httpx
from conftest import TEST_DATABASE
from PIL import Image
from sqlalchemy import func, select, text

from minilog.api import health
from minilog.database import Base, SessionLocal, engine, get_db
from minilog.main import app
from minilog.models import (
    AuthSession,
    Caregiver,
    CaregiverQuickAction,
    CareRecord,
    ProcessedMutation,
    SyncChange,
    SyncState,
    now_ms,
)


async def with_client(scenario: Callable[[httpx.AsyncClient], Awaitable[None]]) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await scenario(client)


async def setup_owner(client: httpx.AsyncClient) -> str:
    response = await client.post(
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
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


async def create_baby(client: httpx.AsyncClient, csrf: str) -> str:
    response = await client.post(
        "/api/v1/babies",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": "Mila", "birth_date": "2026-01-01"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def record_payload(baby_id: str, record_type: str, **details: Any) -> dict[str, Any]:
    return {
        "baby_id": baby_id,
        "record_type": record_type,
        "occurred_at": "2026-09-09T12:00:00+02:00",
        "local_offset_minutes": 120,
        **details,
    }


def assert_live_database_erased(*private_markers: str) -> None:
    engine.dispose()
    for path in (TEST_DATABASE, Path(f"{TEST_DATABASE}-wal"), Path(f"{TEST_DATABASE}-shm")):
        if not path.exists():
            continue
        contents = path.read_bytes()
        for marker in private_markers:
            assert marker.encode() not in contents, (path, marker)


def test_setup_session_and_owner_only_baby_creation() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/setup")).json() == {"setup_required": True}
        assert (await client.get("/api/v1/babies")).status_code == 401

        csrf = await setup_owner(client)
        assert (await client.get("/api/v1/setup")).json() == {"setup_required": False}
        baby_id = await create_baby(client, csrf)

        babies = (await client.get("/api/v1/babies")).json()
        assert babies == [
            {
                "id": baby_id,
                "display_name": "Mila",
                "birth_date": "2026-01-01",
                "due_date": None,
                "has_profile_picture": False,
                "updated_at": babies[0]["updated_at"],
            }
        ]

    asyncio.run(with_client(scenario))


def test_compatibility_endpoint_refuses_an_unexpected_schema() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        compatible = await client.get("/api/v1/health/compatibility")
        assert compatible.status_code == 200
        assert compatible.json() == {
            "status": "ready",
            "api_contract_version": 1,
            "schema_revision": "47ccc6557a5e",
        }

        with SessionLocal() as db:
            db.execute(text("UPDATE alembic_version SET version_num = 'unexpected'"))
            db.commit()
        incompatible = await client.get("/api/v1/health/compatibility")
        assert incompatible.status_code == 503
        assert incompatible.json()["detail"] == "maintenance"

    asyncio.run(with_client(scenario))


def test_health_refuses_read_only_storage(monkeypatch) -> None:
    def fail_writable_probe(_path) -> None:
        raise RuntimeError("read-only")

    async def scenario(client: httpx.AsyncClient) -> None:
        ready = await client.get("/api/v1/health/ready")
        assert ready.status_code == 503
        assert ready.json()["detail"] == "storage_unavailable"
        compatibility = await client.get("/api/v1/health/compatibility")
        assert compatibility.status_code == 503
        assert compatibility.json()["detail"] == "maintenance"

    monkeypatch.setattr(health, "verify_database_writable", fail_writable_probe)
    asyncio.run(with_client(scenario))


def test_request_logs_use_route_templates_and_sanitize_request_ids(caplog) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        response = await client.get(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-Request-ID": "private value"},
        )
        assert response.status_code == 404

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert '"route":"/api/v1/babies/{baby_id}/profile-picture"' in messages
        assert baby_id not in messages
        assert "private value" not in messages

    caplog.set_level(logging.INFO, logger="minilog")
    asyncio.run(with_client(scenario))


def test_unhandled_failures_return_and_log_only_sanitized_details(caplog) -> None:
    private_detail = "private Baby name and medicine"

    async def failing_database():
        raise RuntimeError(private_detail)

    async def scenario(client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/health/compatibility")
        assert response.status_code == 500
        assert response.json() == {"detail": "internal_server_error"}
        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert '"exception":"RuntimeError"' in messages
        assert private_detail not in messages

    caplog.set_level(logging.ERROR, logger="minilog")
    app.dependency_overrides[get_db] = failing_database
    try:
        asyncio.run(with_client(scenario))
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_every_native_record_type_round_trips() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        cases = [
            record_payload(
                baby_id,
                "breastfeeding",
                ended_at="2026-09-09T12:15:00+02:00",
                estimated_amount_ml=20,
                intervals=[
                    {
                        "side": "left",
                        "started_at": "2026-09-09T12:00:00+02:00",
                        "ended_at": "2026-09-09T12:15:00+02:00",
                    }
                ],
            ),
            record_payload(
                baby_id,
                "bottle_feeding",
                consumed_ml=90,
                offered_ml=100,
                contents="formula",
            ),
            record_payload(
                baby_id,
                "solid_food_feeding",
                foods="Banana",
                amount_value="2",
                amount_unit="spoons",
                reaction_note="No reaction observed",
                note="Ate with family",
            ),
            record_payload(baby_id, "sleep", ended_at="2026-09-09T13:00:00+02:00"),
            record_payload(baby_id, "diaper_change", is_wet=True, is_dirty=True),
            record_payload(
                baby_id,
                "pumping",
                ended_at="2026-09-09T12:20:00+02:00",
                expressed_ml=80,
            ),
            record_payload(
                baby_id,
                "measurement",
                kind="weight",
                entered_value="7.2",
                entered_unit="kg",
            ),
            record_payload(
                baby_id,
                "medication_administration",
                medicine_name="Example medicine",
                amount_value="2.5",
                unit_code="ml",
            ),
            record_payload(baby_id, "note", body="A calm afternoon"),
        ]

        for payload in cases:
            response = await client.post(
                "/api/v1/care-records",
                headers={"X-CSRF-Token": csrf, "X-Mutation-ID": str(uuid4())},
                json=payload,
            )
            assert response.status_code == 201, response.text
            assert response.json()["record_type"] == payload["record_type"]

        timeline = (await client.get(f"/api/v1/care-records?baby_id={baby_id}")).json()
        assert {item["record_type"] for item in timeline["items"]} == {
            case["record_type"] for case in cases
        }
        solid_food = next(
            item for item in timeline["items"] if item["record_type"] == "solid_food_feeding"
        )
        assert solid_food["note"] == "Ate with family"
        assert solid_food["details"]["reaction_note"] == "No reaction observed"
        sync = (await client.get("/api/v1/sync")).json()
        assert len(sync["changes"]) == len(cases)

        overlapping = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf},
            json=record_payload(
                baby_id,
                "breastfeeding",
                occurred_at="2026-09-09T14:00:00+02:00",
                ended_at="2026-09-09T15:00:00+02:00",
                intervals=[
                    {
                        "side": "left",
                        "started_at": "2026-09-09T14:00:00+02:00",
                        "ended_at": "2026-09-09T14:40:00+02:00",
                    },
                    {
                        "side": "right",
                        "started_at": "2026-09-09T14:30:00+02:00",
                        "ended_at": "2026-09-09T15:00:00+02:00",
                    },
                ],
            ),
        )
        assert overlapping.status_code == 422

    asyncio.run(with_client(scenario))


def test_active_record_filter_and_medication_unit_codes_are_explicit() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        headers = {"X-CSRF-Token": csrf}
        active_sleep = await client.post(
            "/api/v1/care-records",
            headers={**headers, "X-Mutation-ID": str(uuid4())},
            json=record_payload(baby_id, "sleep"),
        )
        assert active_sleep.status_code == 201
        await client.post(
            "/api/v1/care-records",
            headers={**headers, "X-Mutation-ID": str(uuid4())},
            json=record_payload(baby_id, "note", body="Not an active timer"),
        )

        active = await client.get(
            "/api/v1/care-records",
            params={"baby_id": baby_id, "active_only": "true"},
        )
        assert [item["record_type"] for item in active.json()["items"]] == ["sleep"]

        invalid_unit = await client.post(
            "/api/v1/care-records",
            headers={**headers, "X-Mutation-ID": str(uuid4())},
            json=record_payload(
                baby_id,
                "medication_administration",
                medicine_name="Example medicine",
                amount_value="1",
                unit_code="spoonful",
            ),
        )
        assert invalid_unit.status_code == 422

    asyncio.run(with_client(scenario))


def test_mutation_retry_and_revision_conflict_are_safe() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        payload = record_payload(baby_id, "note", body="Original")
        mutation_id = str(uuid4())
        headers = {"X-CSRF-Token": csrf, "X-Mutation-ID": mutation_id}

        first = await client.post("/api/v1/care-records", headers=headers, json=payload)
        second = await client.post("/api/v1/care-records", headers=headers, json=payload)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

        record_id = first.json()["id"]
        changed = record_payload(baby_id, "note", body="Changed")
        update = await client.put(
            f"/api/v1/care-records/{record_id}",
            headers={"X-CSRF-Token": csrf},
            json={"expected_revision": 1, "record": changed},
        )
        assert update.status_code == 200, update.text
        assert update.json()["revision"] == 2

        stale = await client.put(
            f"/api/v1/care-records/{record_id}",
            headers={"X-CSRF-Token": csrf},
            json={"expected_revision": 1, "record": changed},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "stale_revision"
        assert stale.json()["detail"]["current"]["revision"] == 2
        assert stale.json()["detail"]["current"]["details"]["body"] == "Changed"

        deleted = await client.delete(
            f"/api/v1/care-records/{record_id}",
            headers={"X-CSRF-Token": csrf},
            params={"expected_revision": 2},
        )
        assert deleted.status_code == 204

        timeline = (await client.get(
            "/api/v1/care-records", params={"baby_id": baby_id}
        )).json()
        assert all(item["id"] != record_id for item in timeline["items"])
        sync = (await client.get("/api/v1/sync")).json()
        deletion = next(
            change for change in sync["changes"] if change["entity_id"] == record_id
            and change["operation"] == "delete"
        )
        assert deletion["revision"] == 3

    asyncio.run(with_client(scenario))


def test_expired_sync_cursor_prunes_history_but_preserves_pending_recovery_boundary() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        mutation_id = str(uuid4())
        created = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf, "X-Mutation-ID": mutation_id},
            json=record_payload(baby_id, "note", body="Ready to expire"),
        )
        assert created.status_code == 201, created.text
        record_id = created.json()["id"]
        deleted = await client.delete(
            f"/api/v1/care-records/{record_id}",
            headers={"X-CSRF-Token": csrf},
            params={"expected_revision": 1},
        )
        assert deleted.status_code == 204

        expired_at = now_ms() - 40 * 24 * 60 * 60 * 1000
        with SessionLocal() as db:
            for change in db.scalars(select(SyncChange)):
                change.changed_at = expired_at
            processed = db.get(ProcessedMutation, mutation_id)
            assert processed is not None
            processed.processed_at = expired_at
            record = db.get(CareRecord, record_id)
            assert record is not None
            record.deleted_at = expired_at
            state = db.get(SyncState, 1)
            if state is not None:
                state.last_pruned_at = None
            db.commit()

        expired = await client.get("/api/v1/sync", params={"after": 0})
        assert expired.status_code == 409, expired.text
        detail = expired.json()["detail"]
        assert detail["code"] == "sync_cursor_expired"
        assert detail["oldest_valid_cursor"] >= 2

        with SessionLocal() as db:
            assert db.get(CareRecord, record_id) is None
            assert db.get(ProcessedMutation, mutation_id) is None
            assert db.scalar(select(func.count()).select_from(SyncChange)) == 0

        resumed = await client.get(
            "/api/v1/sync",
            params={"after": detail["oldest_valid_cursor"]},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["changes"] == []

    asyncio.run(with_client(scenario))


def test_timeline_pagination_does_not_skip_equal_timestamps() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        record_ids = [str(uuid4()) for _ in range(3)]

        for record_id in record_ids:
            response = await client.post(
                "/api/v1/care-records",
                headers={"X-CSRF-Token": csrf},
                json=record_payload(baby_id, "note", id=record_id, body=record_id),
            )
            assert response.status_code == 201, response.text

        first = (
            await client.get(
                "/api/v1/care-records",
                params={"baby_id": baby_id, "limit": 2},
            )
        ).json()
        assert len(first["items"]) == 2
        assert first["next_cursor"] is not None

        second = (
            await client.get(
                "/api/v1/care-records",
                params={
                    "baby_id": baby_id,
                    "limit": 2,
                    "cursor": first["next_cursor"],
                },
            )
        ).json()
        combined_ids = [item["id"] for item in first["items"] + second["items"]]
        assert len(combined_ids) == 3
        assert set(combined_ids) == set(record_ids)

        invalid = await client.get(
            "/api/v1/care-records",
            params={"baby_id": baby_id, "cursor": "not-a-valid-cursor"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"] == "invalid_page_cursor"

    asyncio.run(with_client(scenario))


def test_active_status_exposes_only_cross_baby_indicator_metadata() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        created = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf},
            json=record_payload(baby_id, "sleep"),
        )
        assert created.status_code == 201

        response = await client.get("/api/v1/care-records/active-status")
        assert response.status_code == 200
        assert response.json() == [{"baby_id": baby_id, "active_types": ["sleep"]}]

    asyncio.run(with_client(scenario))


def test_timeline_filters_by_types_and_occurrence_range() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        records = [
            record_payload(
                baby_id,
                "note",
                occurred_at="2026-09-09T12:00:00+02:00",
                body="Earlier note",
            ),
            record_payload(
                baby_id,
                "sleep",
                occurred_at="2026-09-10T12:00:00+02:00",
                ended_at="2026-09-10T13:00:00+02:00",
            ),
            record_payload(
                baby_id,
                "bottle_feeding",
                occurred_at="2026-09-11T12:00:00+02:00",
                consumed_ml=80,
                contents="formula",
            ),
        ]
        for payload in records:
            response = await client.post(
                "/api/v1/care-records",
                headers={"X-CSRF-Token": csrf},
                json=payload,
            )
            assert response.status_code == 201, response.text

        response = await client.get(
            "/api/v1/care-records",
            params=[
                ("baby_id", baby_id),
                ("record_type", "sleep"),
                ("record_type", "bottle_feeding"),
                ("date_from", "2026-09-10"),
                ("date_to", "2026-09-10"),
            ],
        )
        assert response.status_code == 200, response.text
        assert [item["record_type"] for item in response.json()["items"]] == ["sleep"]

    asyncio.run(with_client(scenario))


def test_active_sleep_is_unique_per_baby() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        payload = record_payload(baby_id, "sleep")

        first = await client.post(
            "/api/v1/care-records", headers={"X-CSRF-Token": csrf}, json=payload
        )
        second = await client.post(
            "/api/v1/care-records", headers={"X-CSRF-Token": csrf}, json=payload
        )
        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["detail"] == "active_record_exists"

    asyncio.run(with_client(scenario))


def test_profile_picture_is_normalized_to_webp() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        original_version = (await client.get("/api/v1/babies")).json()[0]["updated_at"]
        source = io.BytesIO()
        Image.new("RGB", (640, 480), "#f0a07a").save(source, "JPEG")

        response = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("baby.jpg", source.getvalue(), "image/jpeg")},
        )
        assert response.status_code == 204, response.text

        picture = await client.get(f"/api/v1/babies/{baby_id}/profile-picture")
        assert picture.status_code == 200
        assert picture.headers["content-type"] == "image/webp"
        assert picture.headers["cache-control"] == "private, no-store"
        with Image.open(io.BytesIO(picture.content)) as normalized:
            assert normalized.size == (256, 256)
            assert normalized.format == "WEBP"

        uploaded_version = (await client.get("/api/v1/babies")).json()[0]["updated_at"]
        assert uploaded_version > original_version
        replacement = io.BytesIO()
        Image.new("RGB", (480, 640), "#216869").save(replacement, "PNG")
        replaced = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("replacement.png", replacement.getvalue(), "image/png")},
        )
        assert replaced.status_code == 204, replaced.text
        replacement_picture = await client.get(f"/api/v1/babies/{baby_id}/profile-picture")
        assert replacement_picture.content != picture.content
        replaced_version = (await client.get("/api/v1/babies")).json()[0]["updated_at"]
        assert replaced_version > uploaded_version

        metadata_update = await client.put(
            f"/api/v1/babies/{baby_id}",
            headers={"X-CSRF-Token": csrf},
            json={"display_name": "Mila updated", "birth_date": "2026-01-01"},
        )
        assert metadata_update.status_code == 200, metadata_update.text
        metadata_version = metadata_update.json()["updated_at"]
        assert metadata_version > replaced_version

        removed = await client.delete(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
        )
        assert removed.status_code == 204, removed.text
        baby = (await client.get("/api/v1/babies")).json()[0]
        assert baby["has_profile_picture"] is False
        assert baby["updated_at"] > metadata_version

    asyncio.run(with_client(scenario))


def test_profile_picture_rejects_oversized_dimensions_before_decode(monkeypatch) -> None:
    import minilog.api.babies as babies_api

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    settings = babies_api.get_settings().model_copy(
        update={"max_profile_picture_pixels": 256}
    )
    monkeypatch.setattr(babies_api, "get_settings", lambda: settings)

    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        compressed = io.BytesIO()
        Image.new("1", (17, 17), 1).save(compressed, "PNG", optimize=True)

        response = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("large-dimensions.png", compressed.getvalue(), "image/png")},
        )

        assert response.status_code == 413
        assert response.json()["detail"] == "profile_picture_dimensions_too_large"

    asyncio.run(with_client(scenario))


def test_profile_picture_maps_pillow_bomb_warning_to_stable_error(monkeypatch) -> None:
    import minilog.api.babies as babies_api

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    settings = babies_api.get_settings().model_copy(
        update={"max_profile_picture_pixels": 1_000}
    )
    monkeypatch.setattr(babies_api, "get_settings", lambda: settings)

    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        compressed = io.BytesIO()
        Image.new("1", (17, 17), 1).save(compressed, "PNG", optimize=True)

        response = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("bomb-warning.png", compressed.getvalue(), "image/png")},
        )

        assert response.status_code == 413
        assert response.json()["detail"] == "profile_picture_dimensions_too_large"

    asyncio.run(with_client(scenario))


def test_invitation_is_one_time_and_device_revocation_is_scoped() -> None:
    async def scenario(owner_client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(owner_client)
        invitation = await owner_client.post(
            "/api/v1/invitations",
            headers={"X-CSRF-Token": csrf},
            json={"expires_in_hours": 1},
        )
        assert invitation.status_code == 201, invitation.text
        token = invitation.json()["token"]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as invited:
            accepted = await invited.post(
                "/api/v1/invitations/accept",
                json={
                    "token": token,
                    "username": "caregiver",
                    "display_name": "Caregiver",
                    "password": "another long test passphrase",
                    "device_name": "Kitchen phone",
                },
            )
            assert accepted.status_code == 201, accepted.text
            caregiver_csrf = accepted.json()["csrf_token"]
            devices = (await invited.get("/api/v1/sessions/devices")).json()
            assert len(devices) == 1
            assert devices[0]["device_name"] == "Kitchen phone"
            assert devices[0]["current"] is True

            revoked = await invited.delete(
                f"/api/v1/sessions/devices/{devices[0]['id']}",
                headers={"X-CSRF-Token": caregiver_csrf},
            )
            assert revoked.status_code == 204
            assert (await invited.get("/api/v1/sessions/current")).status_code == 401

        second_accept = await owner_client.post(
            "/api/v1/invitations/accept",
            json={
                "token": token,
                "username": "other",
                "display_name": "Other",
                "password": "yet another test passphrase",
            },
        )
        assert second_accept.status_code == 410

    asyncio.run(with_client(scenario))


def test_inactive_caregiver_identity_can_be_erased_without_losing_history() -> None:
    async def scenario(owner_client: httpx.AsyncClient) -> None:
        private_username = "erasure-private-marker"
        private_display_name = "ERASURE_PRIVATE_MARKER"
        csrf = await setup_owner(owner_client)
        baby_id = await create_baby(owner_client, csrf)
        invitation = await owner_client.post(
            "/api/v1/invitations",
            headers={"X-CSRF-Token": csrf},
            json={},
        )
        token = invitation.json()["token"]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as invited:
            accepted = await invited.post(
                "/api/v1/invitations/accept",
                json={
                    "token": token,
                    "username": private_username,
                    "display_name": private_display_name,
                    "password": "another long test passphrase",
                },
            )
            caregiver_id = accepted.json()["caregiver"]["id"]
            caregiver_csrf = accepted.json()["csrf_token"]
            mutation_id = str(uuid4())
            record = await invited.post(
                "/api/v1/care-records",
                headers={
                    "X-CSRF-Token": caregiver_csrf,
                    "X-Mutation-ID": mutation_id,
                },
                json=record_payload(baby_id, "note", body="Keep this history"),
            )
            assert record.status_code == 201, record.text
            record_id = record.json()["id"]
            preferences = await invited.put(
                "/api/v1/caregivers/current/quick-actions",
                headers={"X-CSRF-Token": caregiver_csrf},
                json={"actions": [{"record_type": "note", "is_hidden": False}]},
            )
            assert preferences.status_code == 200, preferences.text

            active_erase = await owner_client.delete(
                f"/api/v1/caregivers/{caregiver_id}/identity",
                headers={"X-CSRF-Token": csrf},
            )
            assert active_erase.status_code == 409
            assert active_erase.json()["detail"] == "caregiver_must_be_inactive"

            deactivated = await owner_client.delete(
                f"/api/v1/caregivers/{caregiver_id}",
                headers={"X-CSRF-Token": csrf},
            )
            assert deactivated.status_code == 204
            assert (await invited.get("/api/v1/sessions/current")).status_code == 401

        erased = await owner_client.delete(
            f"/api/v1/caregivers/{caregiver_id}/identity",
            headers={"X-CSRF-Token": csrf},
        )
        assert erased.status_code == 204, erased.text

        with SessionLocal() as db:
            caregiver = db.get(Caregiver, caregiver_id)
            assert caregiver is not None
            assert caregiver.is_active is False
            assert caregiver.identity_erased_at is not None
            assert caregiver.username_normalized == f"deleted-{caregiver_id}"
            assert caregiver.username_display == "Deleted caregiver"
            assert caregiver.display_name == "Deleted caregiver"
            care_record = db.get(CareRecord, record_id)
            assert care_record is not None
            assert care_record.author_id is None
            assert care_record.author_label == "Deleted caregiver"
            assert care_record.last_modified_by_id is None
            assert care_record.last_modified_by_label == "Deleted caregiver"
            assert db.get(ProcessedMutation, mutation_id) is None
            assert db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.caregiver_id == caregiver_id)
            ) == 0
            assert db.scalar(
                select(func.count())
                .select_from(CaregiverQuickAction)
                .where(CaregiverQuickAction.caregiver_id == caregiver_id)
            ) == 0

        caregivers = (await owner_client.get("/api/v1/caregivers")).json()
        deleted = next(item for item in caregivers if item["id"] == caregiver_id)
        assert deleted["display_name"] == "Deleted caregiver"
        assert deleted["is_active"] is False
        assert deleted["identity_erased_at"] is not None
        history = await owner_client.get(f"/api/v1/care-records/{record_id}")
        assert history.json()["author_label"] == "Deleted caregiver"
        assert_live_database_erased(private_username, private_display_name)

    asyncio.run(with_client(scenario))


def test_quick_action_preferences_are_ordered_hidden_and_extensible() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)

        defaults = (await client.get("/api/v1/caregivers/current/quick-actions")).json()
        assert len(defaults) == 9
        assert defaults[0] == {
            "record_type": "breastfeeding",
            "position": 0,
            "is_hidden": False,
        }
        assert all(item["record_type"] != "imported_care_record" for item in defaults)

        updated = await client.put(
            "/api/v1/caregivers/current/quick-actions",
            headers={"X-CSRF-Token": csrf},
            json={
                "actions": [
                    {"record_type": "sleep", "is_hidden": False},
                    {"record_type": "diaper_change", "is_hidden": True},
                ]
            },
        )
        assert updated.status_code == 200, updated.text
        preferences = updated.json()
        assert [item["position"] for item in preferences] == list(range(9))
        assert preferences[:2] == [
            {"record_type": "sleep", "position": 0, "is_hidden": False},
            {"record_type": "diaper_change", "position": 1, "is_hidden": True},
        ]
        assert len({item["record_type"] for item in preferences}) == 9

        fetched = await client.get("/api/v1/caregivers/current/quick-actions")
        assert fetched.json() == preferences

        invalid = await client.put(
            "/api/v1/caregivers/current/quick-actions",
            headers={"X-CSRF-Token": csrf},
            json={
                "actions": [
                    {"record_type": "sleep", "is_hidden": False},
                    {"record_type": "sleep", "is_hidden": True},
                ]
            },
        )
        assert invalid.status_code == 422

        none_visible = await client.put(
            "/api/v1/caregivers/current/quick-actions",
            headers={"X-CSRF-Token": csrf},
            json={
                "actions": [
                    {"record_type": item["record_type"], "is_hidden": True}
                    for item in defaults
                ]
            },
        )
        assert none_visible.status_code == 200
        assert all(item["is_hidden"] for item in none_visible.json())

    asyncio.run(with_client(scenario))


def test_destructive_deletion_requires_exact_confirmation() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        baby_private_marker = "BABY_PRIVATE_MARKER_7ED019"
        household_private_marker = "HOUSEHOLD_PRIVATE_MARKER_963BC1"
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
        mutation_id = str(uuid4())
        record = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf, "X-Mutation-ID": mutation_id},
            json=record_payload(baby_id, "note", body=baby_private_marker),
        )
        assert record.status_code == 201, record.text

        image = io.BytesIO()
        Image.new("RGB", (32, 48), "#f0a07a").save(image, "PNG")
        picture = await client.put(
            f"/api/v1/babies/{baby_id}/profile-picture",
            headers={"X-CSRF-Token": csrf},
            files={"image": ("baby.png", image.getvalue(), "image/png")},
        )
        assert picture.status_code == 204, picture.text

        piyolog_source = b"""PiyoLog text export
September 8, 2026
07:00 Sleep
08:15 Wake up
Diary: BABY_PRIVATE_MARKER_7ED019 imported note
"""
        imported = await client.post(
            "/api/v1/imports/piyolog/confirm",
            headers={"X-CSRF-Token": csrf},
            data={
                "baby_id": baby_id,
                "source_time_zone": "Europe/Amsterdam",
                "retain_source": "true",
            },
            files={"file": ("piyolog.txt", piyolog_source, "text/plain")},
        )
        assert imported.status_code == 201, imported.text

        denied = await client.request(
            "DELETE",
            f"/api/v1/babies/{baby_id}",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": "Wrong", "export_acknowledged": True},
        )
        assert denied.status_code == 409
        deleted = await client.request(
            "DELETE",
            f"/api/v1/babies/{baby_id}",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": "Mila", "export_acknowledged": True},
        )
        assert deleted.status_code == 204
        assert (await client.get("/api/v1/babies")).json() == []
        baby_owned_tables = (
            "babies",
            "baby_profile_pictures",
            "import_batches",
            "care_records",
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
            "processed_mutations",
            "sync_changes",
        )
        with SessionLocal() as db:
            for table_name in baby_owned_tables:
                table = Base.metadata.tables[table_name]
                count = db.scalar(select(func.count()).select_from(table))
                assert count == 0, table_name
        assert_live_database_erased(baby_private_marker)

        remaining_baby_id = await create_baby(client, csrf)
        remaining_record = await client.post(
            "/api/v1/care-records",
            headers={"X-CSRF-Token": csrf},
            json=record_payload(remaining_baby_id, "note", body=household_private_marker),
        )
        assert remaining_record.status_code == 201, remaining_record.text

        household_denied = await client.request(
            "DELETE",
            "/api/v1/household",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": "Home"},
        )
        assert household_denied.status_code == 409
        household_deleted = await client.request(
            "DELETE",
            "/api/v1/household",
            headers={"X-CSRF-Token": csrf},
            json={"confirmation": "DELETE Home"},
        )
        assert household_deleted.status_code == 204
        assert (await client.get("/api/v1/setup")).json() == {"setup_required": True}
        with SessionLocal() as db:
            for table in Base.metadata.sorted_tables:
                count = db.scalar(select(func.count()).select_from(table))
                assert count == 0, table.name
        assert_live_database_erased(household_private_marker)

    asyncio.run(with_client(scenario))


def test_login_failures_are_rate_limited_without_revealing_username() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await setup_owner(client)
        payload = {"username": "nonexistent-rate-limit-user", "password": "incorrect"}
        for _ in range(8):
            response = await client.post("/api/v1/sessions", json=payload)
            assert response.status_code == 401
            assert response.json()["detail"] == "invalid_credentials"
        limited = await client.post("/api/v1/sessions", json=payload)
        assert limited.status_code == 429
        assert limited.json()["detail"] == "try_again_later"

    asyncio.run(with_client(scenario))
