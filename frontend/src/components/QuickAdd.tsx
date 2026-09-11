import { useQuery } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useState } from "react";

import { api } from "../api/client";
import { careAction, orderedCareActions, type CareActionKind } from "../careActions";
import { careRecordRegistry, createRecordPayload } from "../careRecordForms";
import { useCreateRecord } from "../hooks/useRecords";
import { localDateTimeValue } from "../lib/time";
import { BottomSheet } from "./BottomSheet";

export function QuickAdd({ babyId, onClose }: { babyId: string; onClose: () => void }) {
  const [kind, setKind] = useState<CareActionKind | null>(null);
  const mutation = useCreateRecord(babyId);
  const preferences = useQuery({
    queryKey: ["quick-actions"],
    queryFn: api.quickActions,
    staleTime: 60_000,
  });
  const actions = preferences.data ? orderedCareActions(preferences.data) : [];
  const [occurredAt] = useState(() => localDateTimeValue());

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!kind) return;
    const values = new FormData(event.currentTarget);
    await mutation.mutateAsync(createRecordPayload(kind, babyId, values));
    onClose();
  };

  return (
    <BottomSheet label="Add care record" onClose={onClose}>
        <div className="sheet-handle" />
        <div className="sheet-header">
          <div><p className="eyebrow">Quick add</p><h2>{kind ? careAction(kind).label : "What happened?"}</h2></div>
          <button className="ghost icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
        {!kind ? (
          preferences.isPending ? <p role="status">Loading your quick actions…</p>
          : preferences.isError && !preferences.data ? <div className="empty-state"><p>Quick actions could not be loaded.</p><span>Retry before recording so hidden actions stay private.</span><button className="secondary" onClick={() => preferences.refetch()}>Retry</button></div>
          : actions.length ? <div className="action-grid">
              {actions.map(({ kind: actionKind, label, icon: Icon }) => (
                <button key={actionKind} onClick={() => setKind(actionKind)} className="care-action">
                  <Icon aria-hidden="true" /> <span>{label}</span>
                </button>
              ))}
            </div> : <div className="empty-state quick-actions-empty"><p>No quick actions are visible.</p><span>Choose which actions to show in Settings.</span><a className="secondary" href="/settings">Open Settings</a></div>
        ) : (
          <form onSubmit={submit} className="form-stack care-form">
            <label>When<input type="datetime-local" name="occurredAt" defaultValue={occurredAt} required /></label>
            {careRecordRegistry[kind].createFields()}
            {careRecordRegistry[kind].showCommonNote && <label>Note <span className="muted">optional</span><textarea name="note" rows={2} /></label>}
            {mutation.isError && <p className="error" role="alert">Could not save. Check the values and try again.</p>}
            <div className="sheet-actions"><button type="button" className="secondary" onClick={() => setKind(null)}>Back</button><button className="primary" disabled={mutation.isPending}>{careRecordRegistry[kind].timed ? "Start" : "Save"}</button></div>
          </form>
        )}
    </BottomSheet>
  );
}
