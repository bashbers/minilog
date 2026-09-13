import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, isTemporaryApiFailure } from "../api/client";
import { invalidateCareRecordQueries } from "../api/cache";
import type { CareRecord, CareRecordCreate, TimelineRecord } from "../api/types";
import { queuedTimelineRecord } from "../careRecordForms";
import { newUuid } from "../lib/uuid";
import {
  cachedRecords,
  cacheRecords,
  discardPendingCreation,
  flushPending,
  pendingForBaby,
  queueCreation,
  retryPendingCreation,
} from "../offline/store";

export function useRecords(babyId: string) {
  return useQuery({
    queryKey: ["records", babyId],
    queryFn: async ({ signal }): Promise<TimelineRecord[]> => {
      const pending = await pendingForBaby(babyId);
      try {
        signal.throwIfAborted();
        const page = await api.records(babyId, {}, signal);
        signal.throwIfAborted();
        await cacheRecords(babyId, page);
        return [...pending.map((item) => queuedTimelineRecord(item.payload, item.mutationId, item.status, item.errorCode)), ...page.items]
          .sort(
            (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
          );
      } catch (error) {
        signal.throwIfAborted();
        const cached = await cachedRecords(babyId);
        if (!cached) throw error;
        return [...pending.map((item) => queuedTimelineRecord(item.payload, item.mutationId, item.status, item.errorCode)), ...cached.items]
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
      const mutationId = newUuid();
      const identified = { ...payload, id: payload.id ?? newUuid() } as CareRecordCreate;
      await queueCreation(identified, mutationId);
      try {
        const record = await api.createRecord(identified, mutationId);
        await discardPendingCreation(mutationId);
        return record;
      } catch (error) {
        if (!isTemporaryApiFailure(error)) {
          await discardPendingCreation(mutationId);
          throw error;
        }
        return queuedTimelineRecord(identified, mutationId);
      }
    },
    onSuccess: () => invalidateCareRecordQueries(queryClient, babyId),
  });
}

export function useRetryQueuedCreation(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (mutationId: string) => {
      await retryPendingCreation(mutationId);
      await flushPending();
    },
    onSettled: () => invalidateCareRecordQueries(queryClient, babyId),
  });
}

export function useDiscardQueuedCreation(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: discardPendingCreation,
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
