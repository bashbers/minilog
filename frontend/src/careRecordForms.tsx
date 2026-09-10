import type { ReactNode } from "react";

import type { CareRecordCreate, TimelineRecord } from "./api/types";
import type { CareActionKind } from "./careActions";
import {
  durationMinutes,
  localDateTimeValue,
  localOffsetMinutes,
  toTimestamp,
} from "./lib/time";

interface CommonRecordInput {
  id?: string;
  baby_id: string;
  occurred_at: string;
  ended_at?: string | null;
  local_offset_minutes: number;
  note: string | null;
}

interface CareRecordFormDefinition {
  timed: boolean;
  showCommonNote: boolean;
  detail: (record: TimelineRecord) => string;
  createFields: () => ReactNode;
  editFields: (record: TimelineRecord) => ReactNode;
  createPayload: (common: CommonRecordInput, values: FormData) => CareRecordCreate;
  editPayload: (
    common: CommonRecordInput,
    record: TimelineRecord,
    values: FormData,
  ) => CareRecordCreate;
}

function detailValue(record: TimelineRecord, key: string): string {
  const item = record.details[key];
  return item == null ? "" : String(item);
}

export function localFormValue(timestamp: string | null): string {
  return timestamp ? localDateTimeValue(new Date(timestamp)) : "";
}

function optionalNumber(values: FormData, name: string): number | null {
  const item = String(values.get(name) ?? "");
  return item === "" ? null : Number(item);
}

function noFields() {
  return null;
}

export const careRecordForms: Record<CareActionKind, CareRecordFormDefinition> = {
  breastfeeding: {
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min`,
    createFields: () => <label>Starting side<select name="side"><option value="left">Left</option><option value="right">Right</option></select></label>,
    editFields: (record) => {
      const intervals = Array.isArray(record.details.intervals)
        ? record.details.intervals as Array<Record<string, unknown>>
        : [];
      return <>
        <label>Estimated amount (ml) <span className="muted">optional</span><input name="estimatedAmountMl" type="number" min="0" inputMode="numeric" defaultValue={detailValue(record, "estimated_amount_ml")} /></label>
        <fieldset><legend>Side intervals</legend><div className="form-stack compact-stack">{intervals.map((interval, index) => <div className="interval-fields" key={index}>
          <label>Side<select name="intervalSide" defaultValue={String(interval.side)}><option value="left">Left</option><option value="right">Right</option></select></label>
          <label>Started<input name="intervalStartedAt" type="datetime-local" required defaultValue={localFormValue(String(interval.started_at))} /></label>
          <label>Ended<input name="intervalEndedAt" type="datetime-local" defaultValue={localFormValue(interval.ended_at ? String(interval.ended_at) : null)} /></label>
        </div>)}</div></fieldset>
      </>;
    },
    createPayload: (common, values) => ({
      ...common,
      record_type: "breastfeeding",
      intervals: [{
        side: String(values.get("side")) as "left" | "right",
        started_at: common.occurred_at,
      }],
    }),
    editPayload: (common, _record, values) => {
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
    },
  },
  bottle_feeding: {
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.consumed_ml ?? 0} ml · ${String(record.details.contents ?? "").replaceAll("_", " ")}`,
    createFields: () => <>
      <div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" inputMode="numeric" required /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" inputMode="numeric" /></label></div>
      <label>Contents<select name="contents"><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label>
    </>,
    editFields: (record) => <><div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" required defaultValue={detailValue(record, "consumed_ml")} /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" defaultValue={detailValue(record, "offered_ml")} /></label></div><label>Contents<select name="contents" defaultValue={detailValue(record, "contents")}><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label></>,
    createPayload: (common, values) => ({
      ...common,
      record_type: "bottle_feeding",
      consumed_ml: Number(values.get("consumedMl")),
      offered_ml: optionalNumber(values, "offeredMl"),
      contents: String(values.get("contents")) as "breast_milk" | "formula" | "mixed" | "other",
    }),
    editPayload: (common, _record, values) => ({
      ...common,
      record_type: "bottle_feeding",
      consumed_ml: Number(values.get("consumedMl")),
      offered_ml: optionalNumber(values, "offeredMl"),
      contents: String(values.get("contents")) as "breast_milk" | "formula" | "mixed" | "other",
    }),
  },
  solid_food_feeding: {
    timed: false,
    showCommonNote: false,
    detail: (record) => String(record.details.foods ?? ""),
    createFields: () => <>
      <label>Foods<input name="foods" required placeholder="Banana, yoghurt…" /></label>
      <div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" inputMode="decimal" /></label><label>Unit<input name="amountUnit" defaultValue="spoons" /></label></div>
      <label>Observed reaction<textarea name="reactionNote" rows={2} /></label>
    </>,
    editFields: (record) => <><label>Foods<input name="foods" required defaultValue={detailValue(record, "foods")} /></label><div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" defaultValue={detailValue(record, "amount_value")} /></label><label>Unit<input name="amountUnit" defaultValue={detailValue(record, "amount_unit")} /></label></div><label>Observed reaction<textarea name="reactionNote" rows={2} defaultValue={detailValue(record, "reaction_note")} /></label></>,
    createPayload: (common, values) => {
      const amount = optionalNumber(values, "amount");
      return {
        ...common,
        record_type: "solid_food_feeding",
        foods: String(values.get("foods")),
        amount_value: amount,
        amount_unit: amount == null ? null : String(values.get("amountUnit")),
        reaction_note: String(values.get("reactionNote") ?? "") || null,
      };
    },
    editPayload: (common, _record, values) => {
      const amount = optionalNumber(values, "amount");
      return {
        ...common,
        record_type: "solid_food_feeding",
        foods: String(values.get("foods")),
        amount_value: amount,
        amount_unit: amount == null ? null : String(values.get("amountUnit")),
        reaction_note: String(values.get("reactionNote") ?? "") || null,
      };
    },
  },
  sleep: {
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min${record.ended_at ? "" : " · active"}`,
    createFields: noFields,
    editFields: noFields,
    createPayload: (common) => ({ ...common, record_type: "sleep" }),
    editPayload: (common) => ({ ...common, record_type: "sleep" }),
  },
  diaper_change: {
    timed: false,
    showCommonNote: true,
    detail: (record) => [record.details.is_wet && "wet", record.details.is_dirty && "dirty"].filter(Boolean).join(" + "),
    createFields: () => <>
      <fieldset><legend>Diaper change</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked /> Wet</label><label className="choice"><input type="checkbox" name="dirty" /> Dirty</label></div></fieldset>
      <div className="field-row"><label>Colour<input name="stoolColour" /></label><label>Consistency<input name="stoolConsistency" /></label></div>
    </>,
    editFields: (record) => <><fieldset><legend>Diaper change</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked={Boolean(record.details.is_wet)} /> Wet</label><label className="choice"><input type="checkbox" name="dirty" defaultChecked={Boolean(record.details.is_dirty)} /> Dirty</label></div></fieldset><div className="field-row"><label>Colour<input name="stoolColour" defaultValue={detailValue(record, "stool_colour")} /></label><label>Consistency<input name="stoolConsistency" defaultValue={detailValue(record, "stool_consistency")} /></label></div></>,
    createPayload: (common, values) => ({
      ...common,
      record_type: "diaper_change",
      is_wet: values.get("wet") === "on",
      is_dirty: values.get("dirty") === "on",
      stool_colour: String(values.get("stoolColour") ?? "") || null,
      stool_consistency: String(values.get("stoolConsistency") ?? "") || null,
    }),
    editPayload: (common, _record, values) => ({
      ...common,
      record_type: "diaper_change",
      is_wet: values.get("wet") === "on",
      is_dirty: values.get("dirty") === "on",
      stool_colour: String(values.get("stoolColour") ?? "") || null,
      stool_consistency: String(values.get("stoolConsistency") ?? "") || null,
    }),
  },
  pumping: {
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min${record.details.expressed_ml ? ` · ${record.details.expressed_ml} ml` : ""}`,
    createFields: noFields,
    editFields: (record) => <label>Expressed volume (ml) <span className="muted">optional</span><input name="expressedMl" type="number" min="0" inputMode="numeric" defaultValue={detailValue(record, "expressed_ml")} /></label>,
    createPayload: (common) => ({ ...common, record_type: "pumping", expressed_ml: null }),
    editPayload: (common, _record, values) => ({ ...common, record_type: "pumping", expressed_ml: optionalNumber(values, "expressedMl") }),
  },
  measurement: {
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.entered_value ?? ""} ${record.details.entered_unit ?? ""} · ${record.details.kind ?? ""}`,
    createFields: () => <>
      <label>Measurement<select name="measurementKind"><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label>
      <div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required inputMode="decimal" /></label><label>Unit<input name="measurementUnit" placeholder="kg" /></label></div>
    </>,
    editFields: (record) => <><label>Measurement<select name="measurementKind" defaultValue={detailValue(record, "kind")}><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label><div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required defaultValue={detailValue(record, "entered_value")} /></label><label>Unit<input name="measurementUnit" required defaultValue={detailValue(record, "entered_unit")} /></label></div></>,
    createPayload: (common, values) => {
      const kind = String(values.get("measurementKind")) as "weight" | "height" | "temperature";
      const defaultUnit = { weight: "kg", height: "cm", temperature: "celsius" }[kind];
      return {
        ...common,
        record_type: "measurement",
        kind,
        entered_value: Number(values.get("measurementValue")),
        entered_unit: String(values.get("measurementUnit") || defaultUnit),
      };
    },
    editPayload: (common, _record, values) => ({
      ...common,
      record_type: "measurement",
      kind: String(values.get("measurementKind")) as "weight" | "height" | "temperature",
      entered_value: Number(values.get("measurementValue")),
      entered_unit: String(values.get("measurementUnit")),
    }),
  },
  medication_administration: {
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.medicine_name ?? ""} · ${record.details.amount_value ?? ""} ${record.details.unit_code ?? record.details.custom_unit ?? ""}`,
    createFields: () => <>
      <label>Medicine name<input name="medicineName" required /></label>
      <div className="field-row"><label>Amount<input name="medicineAmount" type="number" min="0" step="any" required inputMode="decimal" /></label><label>Unit<input name="medicineUnit" defaultValue="ml" required /></label></div>
      <label>Route <span className="muted">optional</span><input name="route" placeholder="Oral" /></label>
    </>,
    editFields: (record) => <><label>Medicine name<input name="medicineName" required defaultValue={detailValue(record, "medicine_name")} /></label><div className="field-row"><label>Amount<input name="medicineAmount" type="number" min="0" step="any" required defaultValue={detailValue(record, "amount_value")} /></label><label>Unit<input name="medicineUnit" required defaultValue={detailValue(record, "unit_code") || detailValue(record, "custom_unit")} /></label></div><label>Route <span className="muted">optional</span><input name="route" defaultValue={detailValue(record, "route")} /></label></>,
    createPayload: (common, values) => ({
      ...common,
      record_type: "medication_administration",
      medicine_name: String(values.get("medicineName")),
      amount_value: Number(values.get("medicineAmount")),
      unit_code: String(values.get("medicineUnit") || "ml"),
      custom_unit: null,
      route: String(values.get("route") ?? "") || null,
    }),
    editPayload: (common, record, values) => {
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
    },
  },
  note: {
    timed: false,
    showCommonNote: false,
    detail: (record) => String(record.details.body ?? ""),
    createFields: () => <label>Note<textarea name="body" rows={4} required autoFocus /></label>,
    editFields: (record) => <label>Note<textarea name="body" rows={4} required defaultValue={detailValue(record, "body")} /></label>,
    createPayload: (common, values) => ({ ...common, record_type: "note", body: String(values.get("body")) }),
    editPayload: (common, _record, values) => ({ ...common, record_type: "note", body: String(values.get("body")) }),
  },
};

export function careRecordDetail(record: TimelineRecord): string {
  if (record.record_type === "imported_care_record") {
    return String(record.details.raw_details ?? record.details.raw_line ?? "");
  }
  return careRecordForms[record.record_type].detail(record);
}

export function createRecordPayload(
  kind: CareActionKind,
  babyId: string,
  values: FormData,
): CareRecordCreate {
  const localTime = String(values.get("occurredAt"));
  const common: CommonRecordInput = {
    baby_id: babyId,
    occurred_at: toTimestamp(localTime),
    local_offset_minutes: localOffsetMinutes(localTime),
    note: String(values.get("note") ?? "") || null,
  };
  return careRecordForms[kind].createPayload(common, values);
}

export function editedRecordPayload(
  record: TimelineRecord,
  values: FormData,
): CareRecordCreate {
  if (record.record_type === "imported_care_record") {
    throw new Error("Imported records are read-only");
  }
  const occurredAt = String(values.get("occurredAt"));
  const endedAt = String(values.get("endedAt") ?? "");
  const common: CommonRecordInput = {
    id: record.id,
    baby_id: record.baby_id,
    occurred_at: toTimestamp(occurredAt),
    ended_at: endedAt ? toTimestamp(endedAt) : null,
    local_offset_minutes: occurredAt === localFormValue(record.occurred_at)
      ? record.local_offset_minutes
      : localOffsetMinutes(occurredAt),
    note: String(values.get("note") ?? "") || null,
  };
  return careRecordForms[record.record_type].editPayload(common, record, values);
}
