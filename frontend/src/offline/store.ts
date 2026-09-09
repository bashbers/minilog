import { openDB, type DBSchema } from "idb";

import { api } from "../api/client";
import type { CareRecordCreate, CareRecordPage } from "../api/types";

interface PendingCreation {
  mutationId: string;
  payload: CareRecordCreate;
  createdAt: number;
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
  await db.put("pending", { payload, mutationId, createdAt: Date.now() });
}

export async function pendingForBaby(babyId: string) {
  const db = await database;
  return (await db.getAll("pending")).filter((item) => item.payload.baby_id === babyId);
}

export async function flushPending(): Promise<number> {
  if (!navigator.onLine) return 0;
  const db = await database;
  const pending = await db.getAll("pending");
  let completed = 0;
  for (const item of pending) {
    try {
      await api.createRecord(item.payload, item.mutationId);
      await db.delete("pending", item.mutationId);
      completed += 1;
    } catch (error) {
      if (error instanceof TypeError) break;
      throw error;
    }
  }
  return completed;
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
