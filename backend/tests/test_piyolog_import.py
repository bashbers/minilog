# ruff: noqa: RUF001 -- Full-width punctuation is part of the Japanese fixture.

import asyncio
from collections.abc import Awaitable, Callable

import httpx2 as httpx

from minilog.main import app
from minilog.services.piyolog import parse_piyolog

ENGLISH_EXPORT = b"""PiyoLog text export
September 8, 2026
07:00 Sleep
08:15 Wake up
08:30 Bottle: 120 ml formula
09:00 Diaper: wet
Diary: A relaxed morning
09:30 Custom event: details are kept
"""

JAPANESE_EXPORT = """ぴよログ 育児記録
2026年9月9日(水)
07:00 寝る
08:00 起きる
08:10 ミルク：100ml
08:30 おしっこ
09:00 体温：36.8℃
日記：よく笑った
""".encode()


async def with_client(scenario: Callable[[httpx.AsyncClient], Awaitable[None]]) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await scenario(client)


async def setup(client: httpx.AsyncClient) -> tuple[str, str]:
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
    csrf = response.json()["csrf_token"]
    baby = await client.post(
        "/api/v1/babies",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": "Mila", "birth_date": "2026-01-01"},
    )
    return csrf, baby.json()["id"]


def test_english_and_japanese_adapters_preserve_unknowns() -> None:
    english = parse_piyolog(ENGLISH_EXPORT)
    assert english.locale == "en"
    assert english.counts == {
        "bottle_feeding": 1,
        "daily_note": 1,
        "diaper_change": 1,
        "imported_care_record": 1,
        "sleep": 1,
        "unplaced_line": 1,
    }
    assert english.unknown_lines[0]["placed"] is True
    assert english.unknown_lines[1]["placed"] is False

    japanese = parse_piyolog(JAPANESE_EXPORT)
    assert japanese.locale == "ja"
    assert japanese.counts["sleep"] == 1
    assert japanese.counts["bottle_feeding"] == 1
    assert japanese.counts["diaper_change"] == 1
    assert japanese.counts["measurement"] == 1
    assert japanese.counts["daily_note"] == 1


def test_import_preview_confirm_and_exact_file_idempotency() -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        csrf, baby_id = await setup(client)
        data = {"baby_id": baby_id, "source_time_zone": "Europe/Amsterdam"}
        files = {"file": ("piyolog.txt", ENGLISH_EXPORT, "text/plain")}
        preview = await client.post(
            "/api/v1/imports/piyolog/preview",
            headers={"X-CSRF-Token": csrf},
            data=data,
            files=files,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["counts"]["sleep"] == 1
        assert preview.json()["duplicate_import_id"] is None

        confirmed = await client.post(
            "/api/v1/imports/piyolog/confirm",
            headers={"X-CSRF-Token": csrf},
            data={**data, "retain_source": "true"},
            files=files,
        )
        assert confirmed.status_code == 201, confirmed.text
        assert confirmed.json()["source_retained"] is True

        timeline = (await client.get(f"/api/v1/care-records?baby_id={baby_id}&limit=20")).json()[
            "items"
        ]
        assert {item["record_type"] for item in timeline} == {
            "sleep",
            "bottle_feeding",
            "diaper_change",
            "imported_care_record",
        }
        assert all(item["author_label"] == "PiyoLog import" for item in timeline)
        daily_notes = await client.get(f"/api/v1/imports/piyolog/daily-notes?baby_id={baby_id}")
        assert daily_notes.status_code == 200
        assert daily_notes.json()[0]["body"] == "A relaxed morning"

        duplicate = await client.post(
            "/api/v1/imports/piyolog/confirm",
            headers={"X-CSRF-Token": csrf},
            data=data,
            files=files,
        )
        assert duplicate.status_code == 409
        preview_again = await client.post(
            "/api/v1/imports/piyolog/preview",
            headers={"X-CSRF-Token": csrf},
            data=data,
            files=files,
        )
        assert preview_again.json()["duplicate_import_id"] == confirmed.json()["id"]

        bottle = next(item for item in timeline if item["record_type"] == "bottle_feeding")
        corrected = await client.put(
            f"/api/v1/care-records/{bottle['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "expected_revision": 1,
                "record": {
                    "baby_id": baby_id,
                    "record_type": "bottle_feeding",
                    "occurred_at": bottle["occurred_at"],
                    "local_offset_minutes": 120,
                    "consumed_ml": 140,
                    "offered_ml": None,
                    "contents": "formula",
                },
            },
        )
        assert corrected.status_code == 200

        revised = ENGLISH_EXPORT.replace(b"120 ml", b"130 ml")
        revised_files = {"file": ("piyolog-revised.txt", revised, "text/plain")}
        revised_preview = await client.post(
            "/api/v1/imports/piyolog/preview",
            headers={"X-CSRF-Token": csrf},
            data=data,
            files=revised_files,
        )
        assert revised_preview.json()["conflicts"]["locally_modified"] == 1
        assert revised_preview.json()["conflicts"]["replaceable"] == 3
        revised_confirm = await client.post(
            "/api/v1/imports/piyolog/confirm",
            headers={"X-CSRF-Token": csrf},
            data={**data, "replace_modified": "false"},
            files=revised_files,
        )
        assert revised_confirm.status_code == 201, revised_confirm.text
        after_revision = (
            await client.get(f"/api/v1/care-records?baby_id={baby_id}&limit=20")
        ).json()["items"]
        bottles = [item for item in after_revision if item["record_type"] == "bottle_feeding"]
        assert len(bottles) == 1
        assert bottles[0]["details"]["consumed_ml"] == 140

        source_deleted = await client.delete(
            f"/api/v1/imports/piyolog/{confirmed.json()['id']}/source",
            headers={"X-CSRF-Token": csrf},
        )
        assert source_deleted.status_code == 204
        batches = (await client.get("/api/v1/imports/piyolog")).json()
        original_batch = next(item for item in batches if item["id"] == confirmed.json()["id"])
        assert original_batch["source_retained"] is False

    asyncio.run(with_client(scenario))
