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
