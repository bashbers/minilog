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

type WithQueued<Record> = Record extends unknown ? Record & { queued?: boolean } : never;

export type TimelineRecord = WithQueued<CareRecord>;
export type NativeTimelineRecord = Exclude<
  TimelineRecord,
  { record_type: "imported_care_record" }
>;
export type BreastfeedingTimelineRecord = Extract<TimelineRecord, { record_type: "breastfeeding" }>;
export type BottleFeedingTimelineRecord = Extract<TimelineRecord, { record_type: "bottle_feeding" }>;
export type SolidFoodTimelineRecord = Extract<TimelineRecord, { record_type: "solid_food_feeding" }>;
export type SleepTimelineRecord = Extract<TimelineRecord, { record_type: "sleep" }>;
export type DiaperChangeTimelineRecord = Extract<TimelineRecord, { record_type: "diaper_change" }>;
export type PumpingTimelineRecord = Extract<TimelineRecord, { record_type: "pumping" }>;
export type MeasurementTimelineRecord = Extract<TimelineRecord, { record_type: "measurement" }>;
export type MedicationTimelineRecord = Extract<
  TimelineRecord,
  { record_type: "medication_administration" }
>;
export type NoteTimelineRecord = Extract<TimelineRecord, { record_type: "note" }>;
export type ImportedTimelineRecord = Extract<
  TimelineRecord,
  { record_type: "imported_care_record" }
>;
