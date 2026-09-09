import { CloudOff, Ellipsis, Square } from "lucide-react";
import { useState } from "react";

import type { CareRecordCreate, TimelineRecord } from "../api/types";
import { useDeleteRecord, useUpdateRecord } from "../hooks/useRecords";
import { durationMinutes, formatDay, formatTime } from "../lib/time";

const labels: Record<TimelineRecord["record_type"], string> = {
  breastfeeding: "Breastfeeding",
  bottle_feeding: "Bottle",
  solid_food_feeding: "Solid food",
  sleep: "Sleep",
  diaper_change: "Diaper",
  pumping: "Pumping",
  measurement: "Measurement",
  medication_administration: "Medicine",
  note: "Note",
  imported_care_record: "Imported record",
};

function detail(record: TimelineRecord) {
  const value = record.details;
  switch (record.record_type) {
    case "breastfeeding":
      return `${durationMinutes(record.occurred_at, record.ended_at)} min`;
    case "bottle_feeding":
      return `${value.consumed_ml ?? 0} ml · ${String(value.contents ?? "").replaceAll("_", " ")}`;
    case "solid_food_feeding":
      return String(value.foods ?? "");
    case "sleep":
      return `${durationMinutes(record.occurred_at, record.ended_at)} min${record.ended_at ? "" : " · active"}`;
    case "diaper_change":
      return [value.is_wet && "wet", value.is_dirty && "dirty"].filter(Boolean).join(" + ");
    case "pumping":
      return `${durationMinutes(record.occurred_at, record.ended_at)} min${value.expressed_ml ? ` · ${value.expressed_ml} ml` : ""}`;
    case "measurement":
      return `${value.entered_value ?? ""} ${value.entered_unit ?? ""} · ${value.kind ?? ""}`;
    case "medication_administration":
      return `${value.medicine_name ?? ""} · ${value.amount_value ?? ""} ${value.unit_code ?? value.custom_unit ?? ""}`;
    case "note":
      return String(value.body ?? "");
    case "imported_care_record":
      return String(value.raw_details ?? value.raw_line ?? "");
  }
}

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
  const intervals = Array.isArray(record.details.intervals)
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

export function Timeline({ records, babyId, showDay = false }: { records: TimelineRecord[]; babyId: string; showDay?: boolean }) {
  const update = useUpdateRecord(babyId);
  const remove = useDeleteRecord(babyId);
  const [menu, setMenu] = useState<string | null>(null);

  if (!records.length) return <div className="empty-state"><p>No care records yet.</p><span>Use the quick-add button when something happens.</span></div>;
  return (
    <div className="timeline">
      {records.map((record) => {
        const active = !record.ended_at && ["sleep", "breastfeeding", "pumping"].includes(record.record_type);
        return (
          <article className={`timeline-item ${active ? "active" : ""}`} key={record.id}>
            <div className="timeline-time"><strong>{formatTime(record.occurred_at)}</strong>{showDay && <span>{formatDay(record.occurred_at)}</span>}</div>
            <div className="timeline-dot" />
            <div className="timeline-content">
              <div className="record-heading"><div><h3>{labels[record.record_type]}</h3><p>{detail(record)}</p></div>{record.queued ? <CloudOff aria-label="Waiting to sync" /> : record.record_type !== "imported_care_record" && <button className="ghost icon-button" aria-label="Record options" onClick={() => setMenu(menu === record.id ? null : record.id)}><Ellipsis /></button>}</div>
              {record.note && <p className="record-note">{record.note}</p>}
              <p className="attribution">{record.queued ? "Waiting for connection" : `by ${record.author_label}`}</p>
              {active && !record.queued && <button className="stop-button" onClick={() => update.mutate({ record, payload: stoppedPayload(record) })}><Square /> Stop</button>}
              {menu === record.id && <div className="record-menu"><button onClick={() => { if (window.confirm("Delete this care record?")) remove.mutate(record); setMenu(null); }}>Delete record</button></div>}
            </div>
          </article>
        );
      })}
    </div>
  );
}

