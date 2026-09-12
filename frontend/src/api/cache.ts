import type { QueryClient } from "@tanstack/react-query";

const BABY_SCOPED_QUERY_KEYS = new Set([
  "active-records",
  "history-records",
  "imported-daily-notes",
  "records",
  "today-records",
  "trend-records",
]);
const MIXED_BABY_QUERY_KEYS = new Set(["baby-active-statuses", "imports"]);

export function removeMissingBabyQueries(queryClient: QueryClient, currentBabyIds: string[]) {
  const retained = new Set(currentBabyIds);
  queryClient.removeQueries({
    predicate: ({ queryKey, state }) => {
      const [family, babyId] = queryKey;
      if (typeof family !== "string") return false;
      if (
        MIXED_BABY_QUERY_KEYS.has(family)
        && queryKey.length === 1
        && Array.isArray(state.data)
      ) {
        return state.data.some(
          (item) => typeof item === "object"
            && item !== null
            && "baby_id" in item
            && typeof item.baby_id === "string"
            && !retained.has(item.baby_id),
        );
      }
      return BABY_SCOPED_QUERY_KEYS.has(family)
        && typeof babyId === "string"
        && !retained.has(babyId);
    },
  });
}

export async function invalidateCareRecordQueries(
  queryClient: QueryClient,
  babyId?: string,
): Promise<void> {
  const scope = babyId ? [babyId] : [];
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["history-records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["today-records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["active-records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["trend-records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["baby-active-statuses"] }),
  ]);
}
