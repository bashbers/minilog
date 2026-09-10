import type { QueryClient } from "@tanstack/react-query";

export async function invalidateCareRecordQueries(
  queryClient: QueryClient,
  babyId?: string,
): Promise<void> {
  const scope = babyId ? [babyId] : [];
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["records", ...scope] }),
    queryClient.invalidateQueries({ queryKey: ["history-records", ...scope] }),
  ]);
}
