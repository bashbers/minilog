import { afterEach, expect, test, vi } from "vitest";

import { api } from "./client";
import type { CareRecord } from "./types";

afterEach(() => vi.unstubAllGlobals());

test("builds stable history cursor and filter parameters", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({ items: [], next_cursor: null }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.records("baby-id", {
    cursor: "opaque-cursor",
    recordTypes: ["breastfeeding", "bottle_feeding", "solid_food_feeding"],
    dateFrom: "2026-09-01",
    dateTo: "2026-09-10",
    limit: 50,
  });

  const requestUrl = new URL(String(fetchMock.mock.calls[0][0]), "http://minilog.test");
  expect(requestUrl.pathname).toBe("/api/v1/care-records");
  expect(requestUrl.searchParams.get("baby_id")).toBe("baby-id");
  expect(requestUrl.searchParams.get("cursor")).toBe("opaque-cursor");
  expect(requestUrl.searchParams.getAll("record_type")).toEqual([
    "breastfeeding",
    "bottle_feeding",
    "solid_food_feeding",
  ]);
  expect(requestUrl.searchParams.get("date_from")).toBe("2026-09-01");
  expect(requestUrl.searchParams.get("date_to")).toBe("2026-09-10");
  expect(requestUrl.searchParams.get("limit")).toBe("50");
});

test("fetches every page in a bounded active-record query", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: "first" }], next_cursor: "next" }), { headers: { "Content-Type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: "second" }], next_cursor: null }), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);

  const records = await api.allRecords("baby-id", {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-30",
    activeOnly: true,
  });

  expect(records.map((record) => record.id)).toEqual(["first", "second"]);
  const firstUrl = new URL(String(fetchMock.mock.calls[0][0]), "http://minilog.test");
  const secondUrl = new URL(String(fetchMock.mock.calls[1][0]), "http://minilog.test");
  expect(firstUrl.searchParams.get("active_only")).toBe("true");
  expect(firstUrl.searchParams.get("date_from")).toBe("2026-09-01");
  expect(secondUrl.searchParams.get("cursor")).toBe("next");
});

test("preserves the current care record from a stale-revision response", async () => {
  const current: CareRecord = {
    id: "record-id",
    baby_id: "baby-id",
    record_type: "note",
    occurred_at: "2026-09-10T10:00:00Z",
    ended_at: null,
    local_offset_minutes: 120,
    note: null,
    author_label: "Alex",
    last_modified_by_label: "Sam",
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:05:00Z",
    revision: 2,
    details: { body: "Current" },
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: { code: "stale_revision", current },
  }), { status: 409, headers: { "Content-Type": "application/json" } })));

  await expect(api.deleteRecord("record-id", 1)).rejects.toMatchObject({
    detail: "stale_revision",
    current,
  });
});

test("preserves the server recovery boundary from an expired sync cursor", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: { code: "sync_cursor_expired", oldest_valid_cursor: 42 },
  }), { status: 409, headers: { "Content-Type": "application/json" } })));

  await expect(api.sync(1)).rejects.toMatchObject({
    status: 409,
    detail: "sync_cursor_expired",
    oldestValidCursor: 42,
  });
});

test("removes a profile picture with a state-changing DELETE request", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);

  await api.deleteProfilePicture("baby-id");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/babies/baby-id/profile-picture",
    expect.objectContaining({ method: "DELETE" }),
  );
});
