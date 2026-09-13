import { openDB, type DBSchema } from "idb";

import { api, ApiError, isTemporaryApiFailure } from "../api/client";
import type { CareRecordCreate, CareRecordPage } from "../api/types";

export interface PendingCreation {
  mutationId: string;
  payload: CareRecordCreate;
  createdAt: number;
  status: "queued" | "failed";
  errorCode?: string;
}

interface MinilogDB extends DBSchema {
  pending: {
    key: string;
    value: PendingCreation;
  };
  cache: {
    key: string;
    value: CareRecordPage;
  };
  meta: {
    key: string;
    value: number;
  };
}

const database = openDB<MinilogDB>("minilog", 1, {
  upgrade(db) {
    db.createObjectStore("pending", { keyPath: "mutationId" });
    db.createObjectStore("cache");
    db.createObjectStore("meta");
  },
});

export async function queueCreation(payload: CareRecordCreate, mutationId: string) {
  const db = await database;
  await db.put("pending", { payload, mutationId, createdAt: Date.now(), status: "queued" });
}

export async function pendingForBaby(babyId: string) {
  const db = await database;
  return (await db.getAll("pending"))
    .filter((item) => item.payload.baby_id === babyId)
    .map((item) => ({ ...item, status: item.status ?? "queued" as const }));
}

export interface FlushPendingResult {
  completed: number;
  failed: number;
}

export async function flushPending(): Promise<FlushPendingResult> {
  if (!navigator.onLine) return { completed: 0, failed: 0 };
  const db = await database;
  const pending = await db.getAll("pending");
  let completed = 0;
  let failed = 0;
  for (const item of pending) {
    if (item.status === "failed") continue;
    try {
      await api.createRecord(item.payload, item.mutationId);
      await db.delete("pending", item.mutationId);
      completed += 1;
    } catch (error) {
      if (isTemporaryApiFailure(error)) break;
      await db.put("pending", {
        ...item,
        status: "failed",
        errorCode: error instanceof ApiError ? error.detail : "request_failed",
      });
      failed += 1;
    }
  }
  return { completed, failed };
}

export async function retryPendingCreation(mutationId: string) {
  const db = await database;
  const item = await db.get("pending", mutationId);
  if (!item) return;
  await db.put("pending", { ...item, status: "queued", errorCode: undefined });
}

export async function discardPendingCreation(mutationId: string) {
  const db = await database;
  await db.delete("pending", mutationId);
}

export async function cacheRecords(babyId: string, page: CareRecordPage) {
  const db = await database;
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const bounded = {
    ...page,
    items: page.items.filter((record) => new Date(record.occurred_at).getTime() >= cutoff),
  };
  await db.put("cache", bounded, `records:${babyId}`);
}

export async function cachedRecords(babyId: string) {
  const db = await database;
  return db.get("cache", `records:${babyId}`);
}

export async function clearRecordCache() {
  const db = await database;
  await db.clear("cache");
}

export async function getSyncCursor() {
  const db = await database;
  return (await db.get("meta", "syncCursor")) ?? 0;
}

export async function setSyncCursor(cursor: number) {
  const db = await database;
  await db.put("meta", cursor, "syncCursor");
}

export async function clearProfilePictureCache() {
  if ("caches" in globalThis) await caches.delete("minilog-profile-pictures");
}

export async function retainCurrentProfilePictureCache(pictureUrl: string | null) {
  if (!("caches" in globalThis)) return;
  try {
    const cache = await caches.open("minilog-profile-pictures");
    const retainedUrl = pictureUrl ? new URL(pictureUrl, globalThis.location.href).href : null;
    const requests = await cache.keys();
    await Promise.all(
      requests.filter((request) => request.url !== retainedUrl).map((request) => cache.delete(request)),
    );
  } catch {
    // Cache Storage can be disabled by browser privacy controls. Server state remains canonical.
  }
}

export async function reconcileBabyLocalData(
  currentBabyIds: string[],
  selectedBabyId: string | null,
) {
  try {
    const retained = new Set(currentBabyIds);
    const db = await database;
    const [pending, cacheKeys] = await Promise.all([
      db.getAll("pending"),
      db.getAllKeys("cache"),
    ]);
    await Promise.all([
      ...pending
        .filter((item) => !retained.has(item.payload.baby_id))
        .map((item) => db.delete("pending", item.mutationId)),
      ...cacheKeys
        .filter((key) => key.startsWith("records:") && key.slice(8) !== selectedBabyId)
        .map((key) => db.delete("cache", key)),
    ]);
  } catch {
    // Local cleanup is retried after the next successful Baby-list refresh.
  }
}

export async function clearLocalData() {
  const results = await Promise.allSettled([
    (async () => {
      const db = await database;
      await Promise.all([db.clear("pending"), db.clear("cache"), db.clear("meta")]);
    })(),
    clearProfilePictureCache(),
  ]);
  if (results.some((result) => result.status === "rejected")) {
    throw new Error("Browser storage cleanup is incomplete.");
  }
}

export async function clearBabyLocalData(babyId: string) {
  await Promise.allSettled([
    (async () => {
      const db = await database;
      const pending = await db.getAll("pending");
      await Promise.all([
        ...pending
          .filter((item) => item.payload.baby_id === babyId)
          .map((item) => db.delete("pending", item.mutationId)),
        db.delete("cache", `records:${babyId}`),
      ]);
    })(),
    clearProfilePictureCache(),
  ]);
}
