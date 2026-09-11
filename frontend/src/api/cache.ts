import type { QueryClient } from "@tanstack/react-query";

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
