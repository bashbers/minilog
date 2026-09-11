import type { components } from "./schema";

export type Baby = components["schemas"]["BabyOut"];
export type BabyCreate = components["schemas"]["BabyCreate"];
export type BabyActiveStatus = components["schemas"]["BabyActiveStatus"];
export type Caregiver = components["schemas"]["CaregiverOut"];
export type CareRecord = components["schemas"]["CareRecordOut"];
export type CareRecordPage = components["schemas"]["CareRecordPage"];
export type Household = components["schemas"]["HouseholdOut"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type Session = components["schemas"]["SessionOut"];
export type SetupRequest = components["schemas"]["SetupRequest"];
export type SetupStatus = components["schemas"]["SetupStatus"];
export type SyncPage = components["schemas"]["SyncPage"];
export type PiyoLogPreview = components["schemas"]["PiyoLogPreview"];
export type ImportBatch = components["schemas"]["ImportBatchOut"];
export type Invitation = components["schemas"]["InvitationOut"];
export type InvitationAccept = components["schemas"]["InvitationAccept"];
export type DeviceSession = components["schemas"]["DeviceSessionOut"];
export type ImportedDailyNote = components["schemas"]["ImportedDailyNoteOut"];
export type QuickActionPreference = Omit<
  components["schemas"]["QuickActionPreferenceOut"],
  "record_type"
> & { record_type: CareRecordCreate["record_type"] };
export type QuickActionPreferencesUpdate = components["schemas"]["QuickActionPreferencesUpdate"];

export type CareRecordCreate =
  | components["schemas"]["BreastfeedingCreate"]
  | components["schemas"]["BottleFeedingCreate"]
  | components["schemas"]["SolidFoodFeedingCreate"]
  | components["schemas"]["SleepCreate"]
  | components["schemas"]["DiaperChangeCreate"]
  | components["schemas"]["PumpingCreate"]
  | components["schemas"]["MeasurementCreate"]
  | components["schemas"]["MedicationAdministrationCreate"]
  | components["schemas"]["NoteCreate"];

type TimelineRecordOf<
  Kind extends CareRecord["record_type"],
  Details,
> = Omit<CareRecord, "record_type" | "details"> & {
  record_type: Kind;
  details: Details;
  queued?: boolean;
};

export type BreastfeedingTimelineRecord = TimelineRecordOf<"breastfeeding", {
  estimated_amount_ml: number | null;
  intervals: Array<{
    side: "left" | "right";
    started_at: string;
    ended_at: string | null;
  }>;
}>;
export type BottleFeedingTimelineRecord = TimelineRecordOf<"bottle_feeding", {
  consumed_ml: number;
  offered_ml: number | null;
  contents: "breast_milk" | "formula" | "mixed" | "other";
}>;
export type SolidFoodTimelineRecord = TimelineRecordOf<"solid_food_feeding", {
  foods: string;
  amount_value: number | string | null;
  amount_unit: string | null;
  reaction_note: string | null;
}>;
export type SleepTimelineRecord = TimelineRecordOf<"sleep", Record<string, never>>;
export type DiaperChangeTimelineRecord = TimelineRecordOf<"diaper_change", {
  is_wet: boolean;
  is_dirty: boolean;
  stool_colour: string | null;
  stool_consistency: string | null;
}>;
export type PumpingTimelineRecord = TimelineRecordOf<"pumping", {
  expressed_ml: number | null;
}>;
export type MeasurementTimelineRecord = TimelineRecordOf<"measurement", {
  kind: "weight" | "height" | "temperature";
  canonical_value: number | string;
  canonical_unit: string;
  entered_value: number | string;
  entered_unit: string;
}>;
export type MedicationTimelineRecord = TimelineRecordOf<"medication_administration", {
  medicine_name: string;
  amount_value: number | string;
  unit_code: string | null;
  custom_unit: string | null;
  route: string | null;
}>;
export type NoteTimelineRecord = TimelineRecordOf<"note", { body: string }>;
export type ImportedTimelineRecord = TimelineRecordOf<"imported_care_record", {
  raw_label: string;
  raw_details: string | null;
  raw_line: string;
}>;

export type NativeTimelineRecord =
  | BreastfeedingTimelineRecord
  | BottleFeedingTimelineRecord
  | SolidFoodTimelineRecord
  | SleepTimelineRecord
  | DiaperChangeTimelineRecord
  | PumpingTimelineRecord
  | MeasurementTimelineRecord
  | MedicationTimelineRecord
  | NoteTimelineRecord;
export type TimelineRecord = NativeTimelineRecord | ImportedTimelineRecord;
