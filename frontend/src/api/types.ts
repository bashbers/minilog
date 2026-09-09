import type { components } from "./schema";

export type Baby = components["schemas"]["BabyOut"];
export type BabyCreate = components["schemas"]["BabyCreate"];
export type Caregiver = components["schemas"]["CaregiverOut"];
export type CareRecord = components["schemas"]["CareRecordOut"];
export type CareRecordPage = components["schemas"]["CareRecordPage"];
export type Household = components["schemas"]["HouseholdOut"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type Session = components["schemas"]["SessionOut"];
export type SetupRequest = components["schemas"]["SetupRequest"];
export type SetupStatus = components["schemas"]["SetupStatus"];
export type SyncPage = components["schemas"]["SyncPage"];

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

export type TimelineRecord = CareRecord & { queued?: boolean };

