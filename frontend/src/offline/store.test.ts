import { vi } from "vitest";

import { api, ApiError } from "../api/client";
import type { CareRecordCreate, CareRecordPage } from "../api/types";
import { cacheRecords, cachedRecords, clearBabyLocalData, clearLocalData, clearProfilePictureCache, flushPending, pendingForBaby, queueCreation, reconcileBabyLocalData, retainCurrentProfilePictureCache, retryPendingCreation } from "./store";

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

test("permanent Baby deletion clears only that Baby's local records and all picture residue", async () => {
  await clearLocalData();
  const deletedBabyId = crypto.randomUUID();
  const otherBabyId = crypto.randomUUID();
  const payload = (babyId: string): CareRecordCreate => ({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Private local note",
  });
  await queueCreation(payload(deletedBabyId), "deleted-baby-mutation");
  await queueCreation(payload(otherBabyId), "other-baby-mutation");
  await cacheRecords(deletedBabyId, { items: [], next_cursor: null });
  await cacheRecords(otherBabyId, { items: [], next_cursor: null });
  const deletePictureCache = vi.fn().mockResolvedValue(true);
  vi.stubGlobal("caches", { delete: deletePictureCache });

  await clearBabyLocalData(deletedBabyId);

  expect(await pendingForBaby(deletedBabyId)).toEqual([]);
  expect(await cachedRecords(deletedBabyId)).toBeUndefined();
  expect(await pendingForBaby(otherBabyId)).toHaveLength(1);
  expect(await cachedRecords(otherBabyId)).toEqual({ items: [], next_cursor: null });
  expect(deletePictureCache).toHaveBeenCalledWith("minilog-profile-pictures");
  vi.unstubAllGlobals();
});

test("Baby deletion cleanup continues when browser Cache Storage rejects deletion", async () => {
  await clearLocalData();
  const babyId = crypto.randomUUID();
  await queueCreation({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Must be removed from IndexedDB",
  }, "cache-rejection-mutation");
  await cacheRecords(babyId, { items: [], next_cursor: null });
  vi.stubGlobal("caches", {
    delete: vi.fn().mockRejectedValue(new Error("Cache Storage unavailable")),
  });

  await expect(clearBabyLocalData(babyId)).resolves.toBeUndefined();
  expect(await pendingForBaby(babyId)).toEqual([]);
  expect(await cachedRecords(babyId)).toBeUndefined();
  vi.unstubAllGlobals();
});

test("Baby-list reconciliation removes local data for remotely deleted Babies", async () => {
  await clearLocalData();
  const deletedBabyId = crypto.randomUUID();
  const retainedBabyId = crypto.randomUUID();
  const payload = (babyId: string): CareRecordCreate => ({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Local data",
  });
  await queueCreation(payload(deletedBabyId), "remote-deleted-mutation");
  await queueCreation(payload(retainedBabyId), "retained-mutation");
  await cacheRecords(deletedBabyId, { items: [], next_cursor: null });
  await cacheRecords(retainedBabyId, { items: [], next_cursor: null });

  await reconcileBabyLocalData([retainedBabyId], retainedBabyId);

  expect(await pendingForBaby(deletedBabyId)).toEqual([]);
  expect(await cachedRecords(deletedBabyId)).toBeUndefined();
  expect(await pendingForBaby(retainedBabyId)).toHaveLength(1);
  expect(await cachedRecords(retainedBabyId)).toEqual({ items: [], next_cursor: null });
});

test("Baby reconciliation caches records only for the selected Baby but retains pending writes", async () => {
  await clearLocalData();
  const selectedBabyId = crypto.randomUUID();
  const otherBabyId = crypto.randomUUID();
  const payload = (babyId: string): CareRecordCreate => ({
    id: crypto.randomUUID(),
    baby_id: babyId,
    record_type: "note",
    occurred_at: new Date().toISOString(),
    local_offset_minutes: 0,
    body: "Pending care",
  });
  await queueCreation(payload(selectedBabyId), "selected-pending");
  await queueCreation(payload(otherBabyId), "other-pending");
  await cacheRecords(selectedBabyId, { items: [], next_cursor: null });
  await cacheRecords(otherBabyId, { items: [], next_cursor: null });

  await reconcileBabyLocalData([selectedBabyId, otherBabyId], selectedBabyId);

  expect(await cachedRecords(selectedBabyId)).toBeDefined();
  expect(await cachedRecords(otherBabyId)).toBeUndefined();
  expect(await pendingForBaby(selectedBabyId)).toHaveLength(1);
  expect(await pendingForBaby(otherBabyId)).toHaveLength(1);
});

test("profile picture changes remove every version from the managed runtime cache", async () => {
  const deletePictureCache = vi.fn().mockResolvedValue(true);
  vi.stubGlobal("caches", { delete: deletePictureCache });

  await clearProfilePictureCache();

  expect(deletePictureCache).toHaveBeenCalledExactlyOnceWith("minilog-profile-pictures");
  vi.unstubAllGlobals();
});

test("profile picture reconciliation retains only the selected Baby's current version", async () => {
  const remove = vi.fn().mockResolvedValue(true);
  const request = (path: string) => new Request(new URL(path, globalThis.location.href));
  const current = request("/api/v1/babies/current/profile-picture?v=2");
  const oldVersion = request("/api/v1/babies/current/profile-picture?v=1");
  const otherBaby = request("/api/v1/babies/other/profile-picture?v=1");
  vi.stubGlobal("caches", {
    open: vi.fn().mockResolvedValue({
      delete: remove,
      keys: vi.fn().mockResolvedValue([oldVersion, current, otherBaby]),
    }),
  });

  await retainCurrentProfilePictureCache("/api/v1/babies/current/profile-picture?v=2");

  expect(remove).toHaveBeenCalledTimes(2);
  expect(remove).toHaveBeenCalledWith(oldVersion);
  expect(remove).toHaveBeenCalledWith(otherBaby);
  expect(remove).not.toHaveBeenCalledWith(current);

  remove.mockClear();
  await retainCurrentProfilePictureCache(null);
  expect(remove).toHaveBeenCalledTimes(3);
  vi.unstubAllGlobals();
});

test("profile picture reconciliation is best-effort when Cache Storage is blocked", async () => {
  const remove = vi.fn().mockResolvedValue(true);
  vi.stubGlobal("caches", {
    open: vi.fn()
      .mockRejectedValueOnce(new Error("Cache Storage blocked"))
      .mockResolvedValueOnce({
        delete: remove,
        keys: vi.fn().mockResolvedValue([
          new Request(new URL("/api/v1/babies/deleted/profile-picture?v=1", location.href)),
        ]),
      }),
  });

  await expect(retainCurrentProfilePictureCache(null)).resolves.toBeUndefined();
  await expect(retainCurrentProfilePictureCache(null)).resolves.toBeUndefined();
  expect(remove).toHaveBeenCalledTimes(1);
  vi.unstubAllGlobals();
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
