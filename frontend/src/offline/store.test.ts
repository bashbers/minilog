import type { CareRecordPage } from "../api/types";
import { cacheRecords, cachedRecords, clearLocalData, pendingForBaby, queueCreation } from "./store";

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
    next_before: null,
  };
  await cacheRecords(babyId, page);
  const cached = await cachedRecords(babyId);
  expect(cached?.items).toHaveLength(1);
  expect(cached?.items[0].details.body).toBe("recent");
});
