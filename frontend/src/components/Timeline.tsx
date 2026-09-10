import { CloudOff, Ellipsis, Square } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import type { CareRecordCreate, TimelineRecord } from "../api/types";
import { careRecordDetail } from "../careRecordForms";
import { useOnlineStatus } from "../hooks/useOnlineStatus";
import { useDeleteRecord, useUpdateRecord } from "../hooks/useRecords";
import { formatDay, formatTime } from "../lib/time";
import { EditRecordSheet } from "./EditRecordSheet";

const labels: Record<TimelineRecord["record_type"], string> = {
  breastfeeding: "Breastfeeding",
  bottle_feeding: "Bottle feeding",
  solid_food_feeding: "Solid food",
  sleep: "Sleep",
  diaper_change: "Diaper change",
  pumping: "Pumping",
  measurement: "Measurement",
  medication_administration: "Medicine",
  note: "Note",
  imported_care_record: "Imported record",
};

function stoppedPayload(record: TimelineRecord): CareRecordCreate {
  const endedAt = new Date().toISOString();
  const common = {
    id: record.id,
    baby_id: record.baby_id,
    occurred_at: record.occurred_at,
    ended_at: endedAt,
    local_offset_minutes: record.local_offset_minutes,
    note: record.note,
  };
  if (record.record_type === "sleep") return { ...common, record_type: "sleep" };
  if (record.record_type === "pumping") {
    return {
      ...common,
      record_type: "pumping",
      expressed_ml: Number(record.details.expressed_ml) || null,
    };
  }
  const intervals: { side: "left" | "right"; started_at: string; ended_at: string | null }[] = Array.isArray(record.details.intervals)
    ? record.details.intervals.map((item) => {
        const interval = item as { side: "left" | "right"; started_at: string; ended_at: string | null };
        return { ...interval, ended_at: interval.ended_at ?? endedAt };
      })
    : [];
  return {
    ...common,
    record_type: "breastfeeding",
    estimated_amount_ml: Number(record.details.estimated_amount_ml) || null,
    intervals,
  };
}

function switchSidePayload(record: TimelineRecord): CareRecordCreate {
  const switchedAt = new Date().toISOString();
  const intervals: { side: "left" | "right"; started_at: string; ended_at: string | null }[] = Array.isArray(record.details.intervals)
    ? record.details.intervals.map((item) => {
        const interval = item as { side: "left" | "right"; started_at: string; ended_at: string | null };
        return { ...interval, ended_at: interval.ended_at ?? switchedAt };
      })
    : [];
  const previous = intervals.at(-1)?.side ?? "left";
  intervals.push({ side: previous === "left" ? "right" : "left", started_at: switchedAt, ended_at: null });
  return {
    id: record.id,
    baby_id: record.baby_id,
    record_type: "breastfeeding",
    occurred_at: record.occurred_at,
    local_offset_minutes: record.local_offset_minutes,
    note: record.note,
    estimated_amount_ml: Number(record.details.estimated_amount_ml) || null,
    intervals,
  };
}

export function Timeline({ records, babyId, showDay = false }: { records: TimelineRecord[]; babyId: string; showDay?: boolean }) {
  const update = useUpdateRecord(babyId);
  const remove = useDeleteRecord(babyId);
  const online = useOnlineStatus();
  const [menu, setMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<TimelineRecord | null>(null);
  const [updatingRecordId, setUpdatingRecordId] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [finishingPump, setFinishingPump] = useState<string | null>(null);
  const [pumpAmount, setPumpAmount] = useState("");
  const applyUpdate = (record: TimelineRecord, payload: CareRecordCreate) => {
    setUpdatingRecordId(record.id);
    update.mutate({ record, payload });
  };

  if (!records.length) return <div className="empty-state"><p>No care records yet.</p><span>Use the quick-add button when something happens.</span></div>;
  return <>
    <div className="timeline">
      {records.map((record) => {
        const active = !record.ended_at && ["sleep", "breastfeeding", "pumping"].includes(record.record_type);
        return (
          <article className={`timeline-item ${active ? "active" : ""}`} key={record.id}>
            <div className="timeline-time"><strong>{formatTime(record.occurred_at)}</strong>{showDay && <span>{formatDay(record.occurred_at)}</span>}</div>
            <div className="timeline-dot" />
            <div className="timeline-content">
              <div className="record-heading"><div><h3>{labels[record.record_type]}</h3><p>{careRecordDetail(record)}</p></div>{record.queued ? <CloudOff aria-label="Waiting to sync" /> : record.record_type !== "imported_care_record" && (online ? <button className="ghost icon-button" aria-label="Record options" onClick={() => setMenu(menu === record.id ? null : record.id)}><Ellipsis /></button> : <CloudOff aria-label="Reconnect to edit or delete" />)}</div>
              {record.note && <p className="record-note">{record.note}</p>}
              <p className="attribution">{record.queued ? "Waiting for connection" : `by ${record.author_label}`}</p>
              {active && !record.queued && online && record.record_type === "breastfeeding" && <div className="active-actions"><button className="secondary small" onClick={() => applyUpdate(record, switchSidePayload(record))}>Switch side</button><button className="stop-button" onClick={() => applyUpdate(record, stoppedPayload(record))}><Square /> Stop</button></div>}
              {active && !record.queued && online && record.record_type === "sleep" && <button className="stop-button" onClick={() => applyUpdate(record, stoppedPayload(record))}><Square /> Stop</button>}
              {active && !record.queued && online && record.record_type === "pumping" && (finishingPump === record.id ? <div className="pump-finish"><label>Expressed volume (ml) <span className="muted">optional</span><input aria-label="Expressed volume ml" type="number" min="0" inputMode="numeric" value={pumpAmount} onChange={(event) => setPumpAmount(event.target.value)} /></label><div className="active-actions"><button className="secondary small" onClick={() => setFinishingPump(null)}>Cancel</button><button className="stop-button" onClick={() => { const payload = stoppedPayload(record); if (payload.record_type === "pumping") payload.expressed_ml = pumpAmount ? Number(pumpAmount) : null; applyUpdate(record, payload); setFinishingPump(null); setPumpAmount(""); }}><Square /> Stop & save</button></div></div> : <button className="stop-button" onClick={() => { setFinishingPump(record.id); setPumpAmount(String(record.details.expressed_ml ?? "")); }}><Square /> Stop</button>)}
              {active && !record.queued && !online && <p className="offline-notice">Reconnect to update this active record.</p>}
              {updatingRecordId === record.id && update.isError && <p className="error inline-error" role="alert">{update.error instanceof ApiError && update.error.detail === "stale_revision" ? "This record changed on another device. Review the latest version and try again." : "Could not update this record."}</p>}
              {deletingRecordId === record.id && remove.isError && <p className="error inline-error" role="alert">{remove.error instanceof ApiError && remove.error.detail === "stale_revision" ? "This record changed on another device and was not deleted." : "Could not delete this record."}</p>}
              {menu === record.id && <div className="record-menu"><button className="edit-record-button" onClick={() => { setEditing(record); setMenu(null); }}>Edit record</button><button onClick={() => { if (window.confirm("Delete this care record?")) { setDeletingRecordId(record.id); remove.mutate(record); } setMenu(null); }}>Delete record</button></div>}
            </div>
          </article>
        );
      })}
    </div>
    {editing && <EditRecordSheet record={editing} onClose={() => setEditing(null)} />}
  </>;
}
