import type { FormEvent } from "react";

import { ApiError } from "../api/client";
import type { TimelineRecord } from "../api/types";
import { careAction } from "../careActions";
import { careRecordForms, editedRecordPayload, localFormValue } from "../careRecordForms";
import { useUpdateRecord } from "../hooks/useRecords";
import { useOnlineStatus } from "../hooks/useOnlineStatus";

export function EditRecordSheet({ record, onClose }: { record: TimelineRecord; onClose: () => void }) {
  const update = useUpdateRecord(record.baby_id);
  const online = useOnlineStatus();
  if (record.record_type === "imported_care_record") return null;
  const form = careRecordForms[record.record_type];
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await update.mutateAsync({
        record,
        payload: editedRecordPayload(record, new FormData(event.currentTarget)),
      });
      onClose();
    } catch {
      // The mutation state renders a specific conflict or validation message below.
    }
  };
  const stale = update.error instanceof ApiError && update.error.status === 409 && update.error.detail === "stale_revision";

  return <div className="sheet-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="bottom-sheet" role="dialog" aria-modal="true" aria-label={`Edit ${careAction(record.record_type).label}`} onMouseDown={(event) => event.stopPropagation()}>
      <div className="sheet-handle" />
      <div className="sheet-header"><div><p className="eyebrow">Correct record</p><h2>Edit {careAction(record.record_type).label}</h2></div><button className="ghost icon-button" onClick={onClose} aria-label="Close">×</button></div>
      <form onSubmit={submit} className="form-stack care-form">
        <div className="field-row"><label>When<input type="datetime-local" name="occurredAt" required defaultValue={localFormValue(record.occurred_at)} /></label>{form.timed && <label>Ended <span className="muted">leave blank if active</span><input type="datetime-local" name="endedAt" defaultValue={localFormValue(record.ended_at)} /></label>}</div>
        {form.editFields(record)}
        {form.showCommonNote && <label>Note <span className="muted">optional</span><textarea name="note" rows={2} defaultValue={record.note ?? ""} /></label>}
        {!online ? <p className="offline-notice" role="status">Reconnect to edit this record.</p> : stale ? <p className="error" role="alert">This record changed on another device. Close this editor, review the latest version, and try again.</p> : update.isError && <p className="error" role="alert">Could not save these changes. Check the values and try again.</p>}
        <div className="sheet-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={!online || update.isPending}>Save changes</button></div>
      </form>
    </section>
  </div>;
}
