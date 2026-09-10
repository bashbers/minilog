import type { FormEvent, ReactNode } from "react";

import { ApiError } from "../api/client";
import type { CareRecordCreate, TimelineRecord } from "../api/types";
import { careAction } from "../careActions";
import { useUpdateRecord } from "../hooks/useRecords";
import { localDateTimeValue, localOffsetMinutes, toTimestamp } from "../lib/time";

function value(record: TimelineRecord, key: string): string {
  const item = record.details[key];
  return item == null ? "" : String(item);
}

function localValue(timestamp: string | null): string {
  return timestamp ? localDateTimeValue(new Date(timestamp)) : "";
}

function optionalNumber(values: FormData, name: string): number | null {
  const item = String(values.get(name) ?? "");
  return item === "" ? null : Number(item);
}

export function editedRecordPayload(
  record: TimelineRecord,
  values: FormData,
): CareRecordCreate {
  const occurredAt = String(values.get("occurredAt"));
  const endedAt = String(values.get("endedAt") ?? "");
  const originalOccurredAt = localValue(record.occurred_at);
  const common = {
    id: record.id,
    baby_id: record.baby_id,
    occurred_at: toTimestamp(occurredAt),
    ended_at: endedAt ? toTimestamp(endedAt) : null,
    local_offset_minutes: occurredAt === originalOccurredAt
      ? record.local_offset_minutes
      : localOffsetMinutes(occurredAt),
    note: String(values.get("note") ?? "") || null,
  };

  switch (record.record_type) {
    case "breastfeeding": {
      const sides = values.getAll("intervalSide");
      const starts = values.getAll("intervalStartedAt");
      const ends = values.getAll("intervalEndedAt");
      return {
        ...common,
        record_type: "breastfeeding",
        estimated_amount_ml: optionalNumber(values, "estimatedAmountMl"),
        intervals: sides.map((side, index) => ({
          side: String(side) as "left" | "right",
          started_at: toTimestamp(String(starts[index])),
          ended_at: ends[index] ? toTimestamp(String(ends[index])) : null,
        })),
      };
    }
    case "bottle_feeding":
      return {
        ...common,
        record_type: "bottle_feeding",
        consumed_ml: Number(values.get("consumedMl")),
        offered_ml: optionalNumber(values, "offeredMl"),
        contents: String(values.get("contents")) as
          | "breast_milk"
          | "formula"
          | "mixed"
          | "other",
      };
    case "solid_food_feeding": {
      const amount = optionalNumber(values, "amount");
      return {
        ...common,
        record_type: "solid_food_feeding",
        foods: String(values.get("foods")),
        amount_value: amount,
        amount_unit: amount == null ? null : String(values.get("amountUnit")),
        reaction_note: String(values.get("reactionNote") ?? "") || null,
      };
    }
    case "sleep":
      return { ...common, record_type: "sleep" };
    case "diaper_change":
      return {
        ...common,
        record_type: "diaper_change",
        is_wet: values.get("wet") === "on",
        is_dirty: values.get("dirty") === "on",
        stool_colour: String(values.get("stoolColour") ?? "") || null,
        stool_consistency: String(values.get("stoolConsistency") ?? "") || null,
      };
    case "pumping":
      return {
        ...common,
        record_type: "pumping",
        expressed_ml: optionalNumber(values, "expressedMl"),
      };
    case "measurement":
      return {
        ...common,
        record_type: "measurement",
        kind: String(values.get("measurementKind")) as "weight" | "height" | "temperature",
        entered_value: Number(values.get("measurementValue")),
        entered_unit: String(values.get("measurementUnit")),
      };
    case "medication_administration": {
      const usesCustomUnit = record.details.custom_unit != null;
      const unit = String(values.get("medicineUnit"));
      return {
        ...common,
        record_type: "medication_administration",
        medicine_name: String(values.get("medicineName")),
        amount_value: Number(values.get("medicineAmount")),
        unit_code: usesCustomUnit ? null : unit,
        custom_unit: usesCustomUnit ? unit : null,
        route: String(values.get("route") ?? "") || null,
      };
    }
    case "note":
      return { ...common, record_type: "note", body: String(values.get("body")) };
    case "imported_care_record":
      throw new Error("Imported records are read-only");
  }
}

function FieldGroup({ record }: { record: TimelineRecord }): ReactNode {
  switch (record.record_type) {
    case "breastfeeding": {
      const intervals = Array.isArray(record.details.intervals)
        ? record.details.intervals as Array<Record<string, unknown>>
        : [];
      return <>
        <label>Estimated amount (ml) <span className="muted">optional</span><input name="estimatedAmountMl" type="number" min="0" inputMode="numeric" defaultValue={value(record, "estimated_amount_ml")} /></label>
        <fieldset><legend>Side intervals</legend><div className="form-stack compact-stack">{intervals.map((interval, index) => <div className="interval-fields" key={index}>
          <label>Side<select name="intervalSide" defaultValue={String(interval.side)}><option value="left">Left</option><option value="right">Right</option></select></label>
          <label>Started<input name="intervalStartedAt" type="datetime-local" required defaultValue={localValue(String(interval.started_at))} /></label>
          <label>Ended<input name="intervalEndedAt" type="datetime-local" defaultValue={localValue(interval.ended_at ? String(interval.ended_at) : null)} /></label>
        </div>)}</div></fieldset>
      </>;
    }
    case "bottle_feeding":
      return <><div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" required defaultValue={value(record, "consumed_ml")} /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" defaultValue={value(record, "offered_ml")} /></label></div><label>Contents<select name="contents" defaultValue={value(record, "contents")}><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label></>;
    case "solid_food_feeding":
      return <><label>Foods<input name="foods" required defaultValue={value(record, "foods")} /></label><div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" defaultValue={value(record, "amount_value")} /></label><label>Unit<input name="amountUnit" defaultValue={value(record, "amount_unit")} /></label></div><label>Observed reaction<textarea name="reactionNote" rows={2} defaultValue={value(record, "reaction_note")} /></label></>;
    case "sleep":
      return null;
    case "diaper_change":
      return <><fieldset><legend>Diaper</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked={Boolean(record.details.is_wet)} /> Wet</label><label className="choice"><input type="checkbox" name="dirty" defaultChecked={Boolean(record.details.is_dirty)} /> Dirty</label></div></fieldset><div className="field-row"><label>Colour<input name="stoolColour" defaultValue={value(record, "stool_colour")} /></label><label>Consistency<input name="stoolConsistency" defaultValue={value(record, "stool_consistency")} /></label></div></>;
    case "pumping":
      return <label>Expressed volume (ml) <span className="muted">optional</span><input name="expressedMl" type="number" min="0" inputMode="numeric" defaultValue={value(record, "expressed_ml")} /></label>;
    case "measurement":
      return <><label>Measurement<select name="measurementKind" defaultValue={value(record, "kind")}><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label><div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required defaultValue={value(record, "entered_value")} /></label><label>Unit<input name="measurementUnit" required defaultValue={value(record, "entered_unit")} /></label></div></>;
    case "medication_administration":
      return <><label>Medicine name<input name="medicineName" required defaultValue={value(record, "medicine_name")} /></label><div className="field-row"><label>Amount<input name="medicineAmount" type="number" min="0" step="any" required defaultValue={value(record, "amount_value")} /></label><label>Unit<input name="medicineUnit" required defaultValue={value(record, "unit_code") || value(record, "custom_unit")} /></label></div><label>Route <span className="muted">optional</span><input name="route" defaultValue={value(record, "route")} /></label></>;
    case "note":
      return <label>Note<textarea name="body" rows={4} required defaultValue={value(record, "body")} /></label>;
    case "imported_care_record":
      return null;
  }
}

export function EditRecordSheet({ record, onClose }: { record: TimelineRecord; onClose: () => void }) {
  const update = useUpdateRecord(record.baby_id);
  const timed = ["sleep", "breastfeeding", "pumping"].includes(record.record_type);
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
        <div className="field-row"><label>When<input type="datetime-local" name="occurredAt" required defaultValue={localValue(record.occurred_at)} /></label>{timed && <label>Ended <span className="muted">leave blank if active</span><input type="datetime-local" name="endedAt" defaultValue={localValue(record.ended_at)} /></label>}</div>
        <FieldGroup record={record} />
        {record.record_type !== "note" && <label>Note <span className="muted">optional</span><textarea name="note" rows={2} defaultValue={record.note ?? ""} /></label>}
        {stale ? <p className="error" role="alert">This record changed on another device. Close this editor, review the latest version, and try again.</p> : update.isError && <p className="error" role="alert">Could not save these changes. Check the values and try again.</p>}
        <div className="sheet-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={update.isPending}>Save changes</button></div>
      </form>
    </section>
  </div>;
}
