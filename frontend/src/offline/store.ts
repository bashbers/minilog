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

export async function clearLocalData() {
  const db = await database;
  await Promise.all([db.clear("pending"), db.clear("cache"), db.clear("meta")]);
  if ("caches" in globalThis) await caches.delete("minilog-profile-pictures");
}
