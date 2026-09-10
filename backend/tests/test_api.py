import asyncio
import io
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import httpx2 as httpx
from PIL import Image

from minilog.main import app


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
        sync = (await client.get("/api/v1/sync")).json()
        assert len(sync["changes"]) == len(cases)

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
        assert stale.json()["detail"] == "stale_revision"

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
        with Image.open(io.BytesIO(picture.content)) as normalized:
            assert normalized.size == (256, 256)
            assert normalized.format == "WEBP"

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
        assert none_visible.status_code == 422

    asyncio.run(with_client(scenario))


def test_destructive_deletion_requires_exact_confirmation() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf = await setup_owner(client)
        baby_id = await create_baby(client, csrf)
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
