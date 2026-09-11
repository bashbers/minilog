import { afterEach, expect, test, vi } from "vitest";

import { api, ApiError } from "../api/client";
import type { CareRecordPage } from "../api/types";
import {
  cacheRecords,
  cachedRecords,
  clearLocalData,
  getSyncCursor,
  pendingForBaby,
  queueCreation,
  setSyncCursor,
} from "./store";
import { synchronize } from "./sync";

afterEach(async () => {
  vi.restoreAllMocks();
  await clearLocalData();
});

test("refreshes an expired cursor before replaying preserved pending writes", async () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const babyId = crypto.randomUUID();
  await queueCreation({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Preserve me",
  }, "pending-mutation");
  await cacheRecords(babyId, { items: [], next_cursor: null } satisfies CareRecordPage);
  await setSyncCursor(4);

  vi.spyOn(api, "sync")
    .mockRejectedValueOnce(new ApiError(409, "sync_cursor_expired", undefined, 10))
    .mockResolvedValueOnce({ changes: [], next_cursor: 10, oldest_valid_cursor: 10 });
  const create = vi.spyOn(api, "createRecord").mockResolvedValue({} as never);

  await expect(synchronize()).resolves.toEqual({
    changed: true,
    flushed: 0,
    fullRefresh: true,
  });
  expect(create).not.toHaveBeenCalled();
  expect(await getSyncCursor()).toBe(10);
  expect(await cachedRecords(babyId)).toBeUndefined();
  expect(await pendingForBaby(babyId)).toHaveLength(1);

  await synchronize();
  expect(create).toHaveBeenCalledOnce();
  expect(await pendingForBaby(babyId)).toEqual([]);
});
