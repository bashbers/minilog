import { vi } from "vitest";

import { api, ApiError } from "../api/client";
import type { CareRecordCreate, CareRecordPage } from "../api/types";
import { cacheRecords, cachedRecords, clearLocalData, flushPending, pendingForBaby, queueCreation, retryPendingCreation } from "./store";

test("persists offline creations by baby until synchronization", async () => {
  await clearLocalData();
  const babyId = crypto.randomUUID();
  const mutationId = crypto.randomUUID();
  await queueCreation(
    {
      id: crypto.randomUUID(),
      baby_id: babyId,
      record_type: "note",
      occurred_at: new Date().toISOString(),
      local_offset_minutes: 0,
      body: "Offline note",
    },
    mutationId,
  );

  const pending = await pendingForBaby(babyId);
  expect(pending).toHaveLength(1);
  expect(pending[0].mutationId).toBe(mutationId);

  await clearLocalData();
  expect(await pendingForBaby(babyId)).toEqual([]);
});

test("keeps only seven recent days in the offline timeline cache", async () => {
  await clearLocalData();
  const babyId = crypto.randomUUID();
  const record = (occurredAt: string, body: string) => ({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note" as const,
    occurred_at: occurredAt,
    ended_at: null,
    local_offset_minutes: 0,
    note: null,
    author_label: "Owner",
    last_modified_by_label: "Owner",
    created_at: occurredAt,
    updated_at: occurredAt,
    revision: 1,
    details: { body },
  });
  const page: CareRecordPage = {
    items: [
      record(new Date().toISOString(), "recent"),
      record(new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(), "old"),
    ],
    next_cursor: null,
  };
  await cacheRecords(babyId, page);
  const cached = await cachedRecords(babyId);
  expect(cached?.items).toHaveLength(1);
  const cachedRecord = cached?.items[0];
  expect(cachedRecord?.record_type).toBe("note");
  if (cachedRecord?.record_type !== "note") throw new Error("Expected a cached note");
  expect(cachedRecord.details.body).toBe("recent");
});

test("marks a rejected creation failed, continues the queue, and supports explicit retry", async () => {
  await clearLocalData();
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const babyId = crypto.randomUUID();
  const payload = (body: string): CareRecordCreate => ({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body,
  });
  await queueCreation(payload("Rejected"), "failed-mutation");
  await queueCreation(payload("Accepted"), "successful-mutation");
  vi.spyOn(api, "createRecord")
    .mockRejectedValueOnce(new ApiError(422, "invalid_record"))
    .mockResolvedValueOnce({} as never);

  expect(await flushPending()).toEqual({ completed: 1, failed: 1 });
  let pending = await pendingForBaby(babyId);
  expect(pending).toHaveLength(1);
  expect(pending[0]).toMatchObject({
    mutationId: "failed-mutation",
    status: "failed",
    errorCode: "invalid_record",
  });

  await retryPendingCreation("failed-mutation");
  pending = await pendingForBaby(babyId);
  expect(pending[0].status).toBe("queued");
});

test("keeps maintenance failures queued for a later replay", async () => {
  await clearLocalData();
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const babyId = crypto.randomUUID();
  await queueCreation({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Keep through maintenance",
  }, "maintenance-mutation");
  vi.spyOn(api, "createRecord").mockRejectedValue(new ApiError(503, "maintenance"));

  expect(await flushPending()).toEqual({ completed: 0, failed: 0 });
  expect(await pendingForBaby(babyId)).toEqual([
    expect.objectContaining({ mutationId: "maintenance-mutation", status: "queued" }),
  ]);
});
