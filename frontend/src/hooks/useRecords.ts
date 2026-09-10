import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { CareRecord, CareRecordCreate, TimelineRecord } from "../api/types";
import {
  cachedRecords,
  cacheRecords,
  pendingForBaby,
  queueCreation,
} from "../offline/store";

function detailsFromPayload(payload: CareRecordCreate): Record<string, unknown> {
  const {
    id: _id,
    baby_id: _baby,
    record_type: _type,
    occurred_at: _occurred,
    ended_at: _ended,
    local_offset_minutes: _offset,
    note: _note,
    ...details
  } = payload;
  return details;
}

function pendingRecord(payload: CareRecordCreate, mutationId: string): TimelineRecord {
  const now = new Date().toISOString();
  return {
    id: payload.id ?? mutationId,
    baby_id: payload.baby_id,
    record_type: payload.record_type,
    occurred_at: payload.occurred_at,
    ended_at: payload.ended_at ?? null,
    local_offset_minutes: payload.local_offset_minutes,
    note: payload.note ?? null,
    author_label: "You",
    last_modified_by_label: "You",
    created_at: now,
    updated_at: now,
    revision: 1,
    details: detailsFromPayload(payload),
    queued: true,
  };
}

export function useRecords(babyId: string) {
  return useQuery({
    queryKey: ["records", babyId],
    queryFn: async (): Promise<TimelineRecord[]> => {
      const pending = await pendingForBaby(babyId);
      try {
        const page = await api.records(babyId);
        await cacheRecords(babyId, page);
        return [...pending.map((item) => pendingRecord(item.payload, item.mutationId)), ...page.items]
          .sort(
            (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
          );
      } catch (error) {
        const cached = await cachedRecords(babyId);
        if (!cached) throw error;
        return [...pending.map((item) => pendingRecord(item.payload, item.mutationId)), ...cached.items]
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
        return pendingRecord(identified, mutationId);
      }
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", babyId] }),
        queryClient.invalidateQueries({ queryKey: ["history-records", babyId] }),
      ]);
    },
  });
}

export function useUpdateRecord(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ record, payload }: { record: CareRecord; payload: CareRecordCreate }) =>
      api.updateRecord(record.id, record.revision, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", babyId] }),
        queryClient.invalidateQueries({ queryKey: ["history-records", babyId] }),
      ]);
    },
    onError: async (error) => {
      if (!(error instanceof ApiError) || error.status !== 409 || error.detail !== "stale_revision") {
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", babyId] }),
        queryClient.invalidateQueries({ queryKey: ["history-records", babyId] }),
      ]);
    },
  });
}

export function useDeleteRecord(babyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (record: CareRecord) => api.deleteRecord(record.id, record.revision),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", babyId] }),
        queryClient.invalidateQueries({ queryKey: ["history-records", babyId] }),
      ]);
    },
  });
}
