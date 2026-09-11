import { api, ApiError } from "../api/client";
import { clearRecordCache, flushPending, getSyncCursor, setSyncCursor } from "./store";

export interface SyncResult {
  changed: boolean;
  flushed: number;
  fullRefresh: boolean;
}

export async function synchronize(): Promise<SyncResult> {
  const cursor = await getSyncCursor();
  try {
    const page = await api.sync(cursor);
    await setSyncCursor(page.next_cursor);
    const flushResult = await flushPending();
    const flushed = flushResult.completed;
    return {
      changed: page.changes.length > 0 || flushed > 0 || flushResult.failed > 0,
      flushed,
      fullRefresh: false,
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.detail === "sync_cursor_expired") {
      if (error.oldestValidCursor === undefined) throw error;
      await clearRecordCache();
      await setSyncCursor(error.oldestValidCursor);
      return { changed: true, flushed: 0, fullRefresh: true };
    }
    throw error;
  }
}
