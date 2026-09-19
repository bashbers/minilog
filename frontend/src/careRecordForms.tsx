import {
  Beef,
  Bed,
  BookHeart,
  Milk,
  Pill,
  Ruler,
  Scale,
  TestTubeDiagonal,
} from "lucide-react";
import { useState } from "react";
import type { AriaAttributes, ComponentType, ReactNode } from "react";

import type {
  BottleFeedingTimelineRecord,
  BreastfeedingTimelineRecord,
  CareRecordCreate,
  DiaperChangeTimelineRecord,
  MeasurementTimelineRecord,
  MedicationTimelineRecord,
  NativeTimelineRecord,
  NoteTimelineRecord,
  PumpingTimelineRecord,
  SleepTimelineRecord,
  SolidFoodTimelineRecord,
  TimelineRecord,
} from "./api/types";
import {
  defaultMeasurementUnit,
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

export type CareActionKind = CareRecordCreate["record_type"];
export type ActiveTimedTimelineRecord =
  | BreastfeedingTimelineRecord
  | PumpingTimelineRecord
  | SleepTimelineRecord;
type ActionIcon = ComponentType<Pick<AriaAttributes, "aria-hidden">>;
type NativeRecordByKind = {
  breastfeeding: BreastfeedingTimelineRecord;
  bottle_feeding: BottleFeedingTimelineRecord;
  solid_food_feeding: SolidFoodTimelineRecord;
  sleep: SleepTimelineRecord;
  diaper_change: DiaperChangeTimelineRecord;
  pumping: PumpingTimelineRecord;
  measurement: MeasurementTimelineRecord;
  medication_administration: MedicationTimelineRecord;
  note: NoteTimelineRecord;
};
type NativePayloadByKind = {
  [Kind in CareActionKind]: Extract<CareRecordCreate, { record_type: Kind }>;
};
type BivariantCallback<Arguments extends unknown[], Result> = {
  call(...parameters: Arguments): Result;
}["call"];

export interface CareSummaryAdapter<RecordType extends NativeTimelineRecord> {
  key: string;
  label: string;
  suffix: string;
  priority: number;
  value: BivariantCallback<[RecordType], number>;
}

interface CareRecordDefinition<Kind extends CareActionKind> {
  kind: Kind;
  label: string;
  icon: ActionIcon;
  historyGroup?: "feeding";
  timed: boolean;
  showCommonNote: boolean;
  detail: BivariantCallback<[NativeRecordByKind[Kind]], string>;
  summaries: Array<CareSummaryAdapter<NativeRecordByKind[Kind]>>;
  createFields: () => ReactNode;
  editFields: BivariantCallback<[NativeRecordByKind[Kind]], ReactNode>;
  createPayload: (common: CommonRecordInput, values: FormData) => CareRecordCreate;
  editPayload: BivariantCallback<[
    CommonRecordInput,
    NativeRecordByKind[Kind],
    FormData,
  ], CareRecordCreate>;
  queuedDetails: BivariantCallback<[
    NativePayloadByKind[Kind],
  ], NativeRecordByKind[Kind]["details"]>;
}

type CareRecordRegistry = {
  [Kind in CareActionKind]: CareRecordDefinition<Kind>;
};

function formValue(item: unknown): string {
  return item == null ? "" : String(item);
}

function BabyDiaperIcon(_props: Pick<AriaAttributes, "aria-hidden">) {
  return <span aria-hidden="true" className="emoji-icon">◡</span>;
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

function bottlePayload(common: CommonRecordInput, values: FormData): CareRecordCreate {
  return {
    ...common,
    record_type: "bottle_feeding",
    consumed_ml: Number(values.get("consumedMl")),
    offered_ml: optionalNumber(values, "offeredMl"),
    contents: String(values.get("contents")) as "breast_milk" | "formula" | "mixed" | "other",
  };
}

function solidFoodPayload(common: CommonRecordInput, values: FormData): CareRecordCreate {
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

function sleepPayload(common: CommonRecordInput): CareRecordCreate {
  return { ...common, record_type: "sleep" };
}

function diaperChangePayload(common: CommonRecordInput, values: FormData): CareRecordCreate {
  return {
    ...common,
    record_type: "diaper_change",
    is_wet: values.get("wet") === "on",
    is_dirty: values.get("dirty") === "on",
    stool_colour: String(values.get("stoolColour") ?? "") || null,
    stool_consistency: String(values.get("stoolConsistency") ?? "") || null,
  };
}

function notePayload(common: CommonRecordInput, values: FormData): CareRecordCreate {
  return { ...common, record_type: "note", body: String(values.get("body")) };
}

type MedicationPayload = Extract<
  CareRecordCreate,
  { record_type: "medication_administration" }
>;
type CommonMedicationUnit = NonNullable<MedicationPayload["unit_code"]>;
const commonMedicationUnits: Array<{ code: CommonMedicationUnit; label: string }> = [
  { code: "ml", label: "Millilitres (ml)" },
  { code: "mg", label: "Milligrams (mg)" },
  { code: "g", label: "Grams (g)" },
  { code: "mcg", label: "Micrograms (mcg)" },
  { code: "tablet", label: "Tablet(s)" },
  { code: "drop", label: "Drop(s)" },
];

function MedicationUnitFields({
  unitCode = "ml",
  customUnit = null,
}: {
  unitCode?: CommonMedicationUnit | null;
  customUnit?: string | null;
}) {
  const [selection, setSelection] = useState<CommonMedicationUnit | "custom">(
    customUnit ? "custom" : unitCode ?? "ml",
  );
  return <div className="field-row">
    <label>Unit type<select name="medicineUnitKind" value={selection} onChange={(event) => setSelection(event.target.value as CommonMedicationUnit | "custom")}>
      {commonMedicationUnits.map(({ code, label }) => <option value={code} key={code}>{label}</option>)}
      <option value="custom">Custom unit</option>
    </select></label>
    {selection === "custom" && <label>Custom unit<input name="medicineCustomUnit" required defaultValue={customUnit ?? ""} placeholder="e.g. sachet" /></label>}
  </div>;
}

function medicationUnit(values: FormData): Pick<MedicationPayload, "unit_code" | "custom_unit"> {
  const selection = String(values.get("medicineUnitKind"));
  if (selection === "custom") {
    return { unit_code: null, custom_unit: String(values.get("medicineCustomUnit")) };
  }
  return { unit_code: selection as CommonMedicationUnit, custom_unit: null };
}

export const careRecordRegistry = {
  breastfeeding: {
    kind: "breastfeeding",
    label: "Breastfeeding",
    icon: Milk,
    historyGroup: "feeding",
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min`,
    summaries: [{ key: "feeds", label: "Feeds", suffix: "", priority: 30, value: () => 1 }],
    createFields: () => <label>Starting side<select name="side"><option value="left">Left</option><option value="right">Right</option></select></label>,
    editFields: (record) => {
      const intervals = record.details.intervals;
      return <>
        <label>Estimated amount (ml) <span className="muted">optional</span><input name="estimatedAmountMl" type="number" min="0" inputMode="numeric" defaultValue={formValue(record.details.estimated_amount_ml)} /></label>
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
    queuedDetails: (payload) => ({
      estimated_amount_ml: payload.estimated_amount_ml ?? null,
      intervals: payload.intervals ?? [],
    }),
  },
  bottle_feeding: {
    kind: "bottle_feeding",
    label: "Bottle feeding",
    icon: TestTubeDiagonal,
    historyGroup: "feeding",
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.consumed_ml ?? 0} ml · ${String(record.details.contents ?? "").replaceAll("_", " ")}`,
    summaries: [
      { key: "bottle_feeding", label: "Bottle feeding", suffix: "ml", priority: 20, value: (record) => Number(record.details.consumed_ml) || 0 },
      { key: "feeds", label: "Feeds", suffix: "", priority: 30, value: () => 1 },
    ],
    createFields: () => <>
      <div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" inputMode="numeric" required /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" inputMode="numeric" /></label></div>
      <label>Contents<select name="contents"><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label>
    </>,
    editFields: (record) => <><div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" required defaultValue={formValue(record.details.consumed_ml)} /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" defaultValue={formValue(record.details.offered_ml)} /></label></div><label>Contents<select name="contents" defaultValue={record.details.contents}><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label></>,
    createPayload: bottlePayload,
    editPayload: (common, _record, values) => bottlePayload(common, values),
    queuedDetails: (payload) => ({
      consumed_ml: payload.consumed_ml,
      offered_ml: payload.offered_ml ?? null,
      contents: payload.contents,
    }),
  },
  solid_food_feeding: {
    kind: "solid_food_feeding",
    label: "Solid-food feeding",
    icon: Beef,
    historyGroup: "feeding",
    timed: false,
    showCommonNote: true,
    detail: (record) => String(record.details.foods ?? ""),
    summaries: [{ key: "feeds", label: "Feeds", suffix: "", priority: 30, value: () => 1 }],
    createFields: () => <>
      <label>Foods<input name="foods" required placeholder="Banana, yoghurt…" /></label>
      <div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" inputMode="decimal" /></label><label>Unit<input name="amountUnit" defaultValue="spoons" /></label></div>
      <label>Observed reaction<textarea name="reactionNote" rows={2} /></label>
    </>,
    editFields: (record) => <><label>Foods<input name="foods" required defaultValue={record.details.foods} /></label><div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" defaultValue={formValue(record.details.amount_value)} /></label><label>Unit<input name="amountUnit" defaultValue={formValue(record.details.amount_unit)} /></label></div><label>Observed reaction<textarea name="reactionNote" rows={2} defaultValue={formValue(record.details.reaction_note)} /></label></>,
    createPayload: solidFoodPayload,
    editPayload: (common, _record, values) => solidFoodPayload(common, values),
    queuedDetails: (payload) => ({
      foods: payload.foods,
      amount_value: payload.amount_value == null ? null : String(payload.amount_value),
      amount_unit: payload.amount_unit ?? null,
      reaction_note: payload.reaction_note ?? null,
    }),
  },
  sleep: {
    kind: "sleep",
    label: "Sleep",
    icon: Bed,
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min${record.ended_at ? "" : " · active"}`,
    summaries: [{ key: "sleep", label: "Sleep", suffix: "min", priority: 10, value: (record) => durationMinutes(record.occurred_at, record.ended_at) }],
    createFields: noFields,
    editFields: noFields,
    createPayload: sleepPayload,
    editPayload: sleepPayload,
    queuedDetails: () => ({}),
  },
  diaper_change: {
    kind: "diaper_change",
    label: "Diaper change",
    icon: BabyDiaperIcon,
    timed: false,
    showCommonNote: true,
    detail: (record) => [record.details.is_wet && "wet", record.details.is_dirty && "dirty"].filter(Boolean).join(" + "),
    summaries: [{ key: "diaper_changes", label: "Diaper changes", suffix: "", priority: 40, value: () => 1 }],
    createFields: () => <>
      <fieldset><legend>Diaper change</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked /> Wet</label><label className="choice"><input type="checkbox" name="dirty" /> Dirty</label></div></fieldset>
      <div className="field-row"><label>Colour<input name="stoolColour" /></label><label>Consistency<input name="stoolConsistency" /></label></div>
    </>,
    editFields: (record) => <><fieldset><legend>Diaper change</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked={record.details.is_wet} /> Wet</label><label className="choice"><input type="checkbox" name="dirty" defaultChecked={record.details.is_dirty} /> Dirty</label></div></fieldset><div className="field-row"><label>Colour<input name="stoolColour" defaultValue={formValue(record.details.stool_colour)} /></label><label>Consistency<input name="stoolConsistency" defaultValue={formValue(record.details.stool_consistency)} /></label></div></>,
    createPayload: diaperChangePayload,
    editPayload: (common, _record, values) => diaperChangePayload(common, values),
    queuedDetails: (payload) => ({
      is_wet: payload.is_wet,
      is_dirty: payload.is_dirty,
      stool_colour: payload.stool_colour ?? null,
      stool_consistency: payload.stool_consistency ?? null,
    }),
  },
  pumping: {
    kind: "pumping",
    label: "Pumping",
    icon: Scale,
    timed: true,
    showCommonNote: true,
    detail: (record) => `${durationMinutes(record.occurred_at, record.ended_at)} min${record.details.expressed_ml ? ` · ${record.details.expressed_ml} ml` : ""}`,
    summaries: [{ key: "pumping", label: "Pumping", suffix: "ml", priority: 50, value: (record) => Number(record.details.expressed_ml) || 0 }],
    createFields: noFields,
    editFields: (record) => <label>Expressed volume (ml) <span className="muted">optional</span><input name="expressedMl" type="number" min="0" inputMode="numeric" defaultValue={formValue(record.details.expressed_ml)} /></label>,
    createPayload: (common) => ({ ...common, record_type: "pumping", expressed_ml: null }),
    editPayload: (common, _record, values) => ({ ...common, record_type: "pumping", expressed_ml: optionalNumber(values, "expressedMl") }),
    queuedDetails: (payload) => ({ expressed_ml: payload.expressed_ml ?? null }),
  },
  measurement: {
    kind: "measurement",
    label: "Measurement",
    icon: Ruler,
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.entered_value ?? ""} ${record.details.entered_unit ?? ""} · ${record.details.kind ?? ""}`,
    summaries: [],
    createFields: () => <>
      <label>Measurement<select name="measurementKind"><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label>
      <div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required inputMode="decimal" /></label><label>Unit<input name="measurementUnit" placeholder="Uses household default" /></label></div>
    </>,
    editFields: (record) => <><label>Measurement<select name="measurementKind" defaultValue={record.details.kind}><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label><div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required defaultValue={formValue(record.details.entered_value)} /></label><label>Unit<input name="measurementUnit" required defaultValue={record.details.entered_unit} /></label></div></>,
    createPayload: (common, values) => {
      const kind = String(values.get("measurementKind")) as "weight" | "height" | "temperature";
      const defaultUnit = defaultMeasurementUnit(kind);
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
    queuedDetails: (payload) => ({
      kind: payload.kind,
      canonical_value: String(payload.entered_value),
      canonical_unit: payload.entered_unit,
      entered_value: String(payload.entered_value),
      entered_unit: payload.entered_unit,
    }),
  },
  medication_administration: {
    kind: "medication_administration",
    label: "Medication administration",
    icon: Pill,
    timed: false,
    showCommonNote: true,
    detail: (record) => `${record.details.medicine_name ?? ""} · ${record.details.amount_value ?? ""} ${record.details.unit_code ?? record.details.custom_unit ?? ""}`,
    summaries: [],
    createFields: () => <>
      <label>Medicine name<input name="medicineName" required /></label>
      <label>Amount<input name="medicineAmount" type="number" min="0" step="any" required inputMode="decimal" /></label>
      <MedicationUnitFields />
      <label>Route <span className="muted">optional</span><input name="route" placeholder="Oral" /></label>
    </>,
    editFields: (record) => <><label>Medicine name<input name="medicineName" required defaultValue={record.details.medicine_name} /></label><label>Amount<input name="medicineAmount" type="number" min="0" step="any" required defaultValue={formValue(record.details.amount_value)} /></label><MedicationUnitFields unitCode={record.details.unit_code} customUnit={record.details.custom_unit} /><label>Route <span className="muted">optional</span><input name="route" defaultValue={formValue(record.details.route)} /></label></>,
    createPayload: (common, values) => ({
      ...common,
      record_type: "medication_administration",
      medicine_name: String(values.get("medicineName")),
      amount_value: Number(values.get("medicineAmount")),
      ...medicationUnit(values),
      route: String(values.get("route") ?? "") || null,
    }),
    editPayload: (common, _record, values) => ({
      ...common,
      record_type: "medication_administration",
      medicine_name: String(values.get("medicineName")),
      amount_value: Number(values.get("medicineAmount")),
      ...medicationUnit(values),
      route: String(values.get("route") ?? "") || null,
    }),
    queuedDetails: (payload) => ({
      medicine_name: payload.medicine_name,
      amount_value: String(payload.amount_value),
      unit_code: payload.unit_code ?? null,
      custom_unit: payload.custom_unit ?? null,
      route: payload.route ?? null,
    }),
  },
  note: {
    kind: "note",
    label: "Note",
    icon: BookHeart,
    timed: false,
    showCommonNote: false,
    detail: (record) => String(record.details.body ?? ""),
    summaries: [],
    createFields: () => <label>Note<textarea name="body" rows={4} required autoFocus /></label>,
    editFields: (record) => <label>Note<textarea name="body" rows={4} required defaultValue={record.details.body} /></label>,
    createPayload: notePayload,
    editPayload: (common, _record, values) => notePayload(common, values),
    queuedDetails: (payload) => ({ body: payload.body }),
  },
} satisfies CareRecordRegistry;

type UniformCareRecordDefinition = CareRecordDefinition<CareActionKind>;

const uniformRegistry: Record<CareActionKind, UniformCareRecordDefinition> =
  careRecordRegistry;

export interface CareAction {
  kind: CareActionKind;
  label: string;
  icon: ActionIcon;
}

export const careActions: CareAction[] = Object.values(careRecordRegistry).map(
  ({ kind, label, icon }) => ({ kind, label, icon }),
);

const actionsByKind = new Map(
  careActions.map((action) => [action.kind, action]),
);

export function orderedCareActions(
  preferences?: import("./api/types").QuickActionPreference[],
): CareAction[] {
  if (!preferences) return careActions;
  return preferences
    .filter((preference) => !preference.is_hidden)
    .map((preference) => actionsByKind.get(preference.record_type))
    .filter((action): action is CareAction => action !== undefined);
}

export function careAction(kind: CareActionKind): CareAction {
  return careRecordRegistry[kind];
}

export function careRecordForm(kind: CareActionKind) {
  return uniformRegistry[kind];
}

export function careRecordTypesForGroup(group: "feeding"): CareActionKind[] {
  return careActions
    .filter((action) => uniformRegistry[action.kind].historyGroup === group)
    .map((action) => action.kind);
}

export function isActiveCareRecord(
  record: TimelineRecord,
): record is ActiveTimedTimelineRecord {
  return record.record_type !== "imported_care_record"
    && uniformRegistry[record.record_type].timed
    && record.ended_at === null;
}

export function careRecordLabel(record: TimelineRecord): string {
  return record.record_type === "imported_care_record"
    ? "Imported care record"
    : careRecordRegistry[record.record_type].label;
}

export interface CareSummaryValue {
  key: string;
  label: string;
  suffix: string;
  priority: number;
  value: number;
}

export const careSummaryCatalog = Array.from(
  new Map(
    Object.values(uniformRegistry)
      .flatMap((definition) => definition.summaries)
      .map(({ key, label, suffix, priority }) => [
        key,
        { key, label, suffix, priority },
      ]),
  ).values(),
).sort((left, right) => left.priority - right.priority);

function nativeDetail<Kind extends CareActionKind>(
  record: NativeRecordByKind[Kind],
): string {
  return uniformRegistry[record.record_type].detail(record);
}

function nativeSummaryValues<Kind extends CareActionKind>(
  record: NativeRecordByKind[Kind],
): CareSummaryValue[] {
  return uniformRegistry[record.record_type].summaries.map((summary) => ({
    key: summary.key,
    label: summary.label,
    suffix: summary.suffix,
    priority: summary.priority,
    value: summary.value(record),
  }));
}

export function careRecordDetail(record: TimelineRecord): string {
  if (record.record_type === "imported_care_record") {
    return String(record.details.raw_details ?? record.details.raw_line ?? "");
  }
  return nativeDetail(record);
}

export function careRecordSummaryValues(record: TimelineRecord): CareSummaryValue[] {
  if (record.record_type === "imported_care_record") return [];
  return nativeSummaryValues(record);
}

export function queuedTimelineRecord(
  payload: CareRecordCreate,
  mutationId: string,
  status: "queued" | "failed" = "queued",
  errorCode?: string,
): TimelineRecord {
  const now = new Date().toISOString();
  const record = {
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
    details: uniformRegistry[payload.record_type].queuedDetails(payload),
    queued: true,
    queueState: { mutationId, status, errorCode },
  };

  // The registry preserves the discriminator/details pairing of the generated API union.
  return record as TimelineRecord;
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
  return careRecordRegistry[kind].createPayload(common, values);
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
  return uniformRegistry[record.record_type].editPayload(common, record, values);
}
