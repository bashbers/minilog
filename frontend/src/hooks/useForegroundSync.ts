import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { synchronize } from "../offline/sync";
import { invalidateCareRecordQueries } from "../api/cache";

export function useForegroundSync() {
  const queryClient = useQueryClient();

  useEffect(() => {
    let active = true;
    const controllers = new Set<AbortController>();
    const sync = async () => {
      if (!active || document.visibilityState !== "visible" || !navigator.onLine) return;
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const result = await synchronize(controller.signal);
        if (active && result.changed) {
          await invalidateCareRecordQueries(queryClient);
        }
      } catch {
        // The next foreground poll retries. Care data never enters console output.
      } finally {
        controllers.delete(controller);
      }
    };
    const foreground = () => void sync();
    const timer = window.setInterval(sync, 5_000);
    document.addEventListener("visibilitychange", foreground);
    window.addEventListener("online", foreground);
    void sync();
    return () => {
      active = false;
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", foreground);
      window.removeEventListener("online", foreground);
    };
  }, [queryClient]);
}
