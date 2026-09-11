import { api, ApiError } from "../api/client";
import { flushPending, getSyncCursor, setSyncCursor } from "./store";

export interface SyncResult {
  changed: boolean;
  flushed: number;
  fullRefresh: boolean;
}

export async function synchronize(): Promise<SyncResult> {
  const flushResult = await flushPending();
  const flushed = flushResult.completed;
  const cursor = await getSyncCursor();
  try {
    const page = await api.sync(cursor);
    await setSyncCursor(page.next_cursor);
    return {
      changed: page.changes.length > 0 || flushed > 0 || flushResult.failed > 0,
      flushed,
      fullRefresh: false,
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.detail === "sync_cursor_expired") {
      await setSyncCursor(0);
      return { changed: true, flushed, fullRefresh: true };
    }
    throw error;
  }
}
