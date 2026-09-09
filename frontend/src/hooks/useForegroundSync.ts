import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { synchronize } from "../offline/sync";

export function useForegroundSync() {
  const queryClient = useQueryClient();

  useEffect(() => {
    let active = true;
    const sync = async () => {
      if (!active || document.visibilityState !== "visible" || !navigator.onLine) return;
      try {
        const result = await synchronize();
        if (result.changed) await queryClient.invalidateQueries({ queryKey: ["records"] });
      } catch {
        // The next foreground poll retries. Care data never enters console output.
      }
    };
    const foreground = () => void sync();
    const timer = window.setInterval(sync, 5_000);
    document.addEventListener("visibilitychange", foreground);
    window.addEventListener("online", foreground);
    void sync();
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", foreground);
      window.removeEventListener("online", foreground);
    };
  }, [queryClient]);
}

