import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import { invalidateCareRecordQueries } from "../api/cache";
import type { CareRecord, CareRecordCreate, TimelineRecord } from "../api/types";
import { queuedTimelineRecord } from "../careRecordForms";
import {
  cachedRecords,
  cacheRecords,
  pendingForBaby,
  queueCreation,
} from "../offline/store";

export function useRecords(babyId: string) {
  return useQuery({
    queryKey: ["records", babyId],
    queryFn: async (): Promise<TimelineRecord[]> => {
      const pending = await pendingForBaby(babyId);
      try {
        const page = await api.records(babyId);
        await cacheRecords(babyId, page);
        return [...pending.map((item) => queuedTimelineRecord(item.payload, item.mutationId)), ...page.items]
          .sort(
            (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
          );
      } catch (error) {
        const cached = await cachedRecords(babyId);
        if (!cached) throw error;
        return [...pending.map((item) => queuedTimelineRecord(item.payload, item.mutationId)), ...cached.items]
          .sort(
            (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
          );
      }
    },
  });
}

export function useCreateRecord(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CareRecordCreate) => {
      const mutationId = crypto.randomUUID();
      const identified = { ...payload, id: payload.id ?? crypto.randomUUID() } as CareRecordCreate;
      try {
        return await api.createRecord(identified, mutationId);
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        await queueCreation(identified, mutationId);
        return queuedTimelineRecord(identified, mutationId);
      }
    },
    onSuccess: () => invalidateCareRecordQueries(queryClient, babyId),
  });
}

export function useUpdateRecord(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ record, payload }: { record: CareRecord; payload: CareRecordCreate }) =>
      api.updateRecord(record.id, record.revision, payload),
    onSuccess: () => invalidateCareRecordQueries(queryClient, babyId),
    onError: async (error) => {
      if (!(error instanceof ApiError) || error.status !== 409 || error.detail !== "stale_revision") {
        return;
      }
      await invalidateCareRecordQueries(queryClient, babyId);
    },
  });
}

export function useDeleteRecord(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (record: CareRecord) => api.deleteRecord(record.id, record.revision),
    onSuccess: () => invalidateCareRecordQueries(queryClient, babyId),
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409 && error.detail === "stale_revision") {
        await invalidateCareRecordQueries(queryClient, babyId);
      }
    },
  });
}
