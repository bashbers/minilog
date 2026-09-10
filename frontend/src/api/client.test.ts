import { afterEach, expect, test, vi } from "vitest";

import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

test("builds stable history cursor and filter parameters", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({ items: [], next_before: null, next_before_id: null }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.records("baby-id", {
    before: 1234,
    beforeId: "record-id",
    recordTypes: ["breastfeeding", "bottle_feeding", "solid_food_feeding"],
    dateFrom: "2026-09-01",
    dateTo: "2026-09-10",
    limit: 50,
  });

  const requestUrl = new URL(String(fetchMock.mock.calls[0][0]), "http://minilog.test");
  expect(requestUrl.pathname).toBe("/api/v1/care-records");
  expect(requestUrl.searchParams.get("baby_id")).toBe("baby-id");
  expect(requestUrl.searchParams.get("before")).toBe("1234");
  expect(requestUrl.searchParams.get("before_id")).toBe("record-id");
  expect(requestUrl.searchParams.getAll("record_type")).toEqual([
    "breastfeeding",
    "bottle_feeding",
    "solid_food_feeding",
  ]);
  expect(requestUrl.searchParams.get("date_from")).toBe("2026-09-01");
  expect(requestUrl.searchParams.get("date_to")).toBe("2026-09-10");
  expect(requestUrl.searchParams.get("limit")).toBe("50");
});
