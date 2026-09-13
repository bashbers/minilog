import type {
  Baby,
  BabyActiveStatus,
  BabyCreate,
  CareRecord,
  CareRecordCreate,
  CareRecordPage,
  Caregiver,
  CompatibilityStatus,
  DeviceSession,
  ImportBatch,
  ImportedDailyNote,
  Invitation,
  InvitationAccept,
  LoginRequest,
  PiyoLogPreview,
  QuickActionPreference,
  QuickActionPreferencesUpdate,
  Session,
  SetupRequest,
  SetupStatus,
  SyncPage,
  Household,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly current?: CareRecord,
    readonly oldestValidCursor?: number,
  ) {
    super(detail);
  }
}

export function isTemporaryApiFailure(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof ApiError && error.status >= 500);
}

export interface RecordListOptions {
  cursor?: string;
  recordTypes?: CareRecord["record_type"][];
  dateFrom?: string;
  dateTo?: string;
  activeOnly?: boolean;
  limit?: number;
}

function cookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const csrf = cookie("minilog_csrf");
  if (csrf && init.method && !["GET", "HEAD"].includes(init.method)) {
    headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(`/api/v1${path}`, {
    credentials: "include",
    ...init,
    headers,
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as {
      detail?: string | {
        code?: string;
        current?: CareRecord;
        oldest_valid_cursor?: number;
      };
    };
    const detail = typeof error.detail === "string" ? error.detail : error.detail?.code;
    const current = typeof error.detail === "object" ? error.detail.current : undefined;
    const oldestValidCursor = typeof error.detail === "object"
      ? error.detail.oldest_valid_cursor
      : undefined;
    throw new ApiError(
      response.status,
      detail ?? "request_failed",
      current,
      oldestValidCursor,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function careRecordListPath(babyId: string, options: RecordListOptions): string {
  const parameters = new URLSearchParams({
    baby_id: babyId,
    limit: String(options.limit ?? 200),
  });
  if (options.cursor) parameters.set("cursor", options.cursor);
  if (options.dateFrom) parameters.set("date_from", options.dateFrom);
  if (options.dateTo) parameters.set("date_to", options.dateTo);
  if (options.activeOnly) parameters.set("active_only", "true");
  options.recordTypes?.forEach((recordType) =>
    parameters.append("record_type", recordType),
  );
  return `/care-records?${parameters.toString()}`;
}

async function allCareRecords(
  babyId: string,
  options: Omit<RecordListOptions, "cursor"> = {},
): Promise<CareRecord[]> {
  const records: CareRecord[] = [];
  let cursor: string | undefined;
  do {
    const page = await request<CareRecordPage>(
      careRecordListPath(babyId, { ...options, cursor }),
    );
    records.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return records;
}

export const api = {
  compatibility: () => request<CompatibilityStatus>("/health/compatibility"),
  setupStatus: () => request<SetupStatus>("/setup"),
  setup: (payload: SetupRequest) =>
    request<Session>("/setup", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: LoginRequest) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<Caregiver>("/sessions/current"),
  logout: () => request<void>("/sessions/current", { method: "DELETE" }),
  babies: () => request<Baby[]>("/babies"),
  babyActiveStatuses: () => request<BabyActiveStatus[]>("/care-records/active-status"),
  household: () => request<Household>("/household"),
  createBaby: (payload: BabyCreate) =>
    request<Baby>("/babies", { method: "POST", body: JSON.stringify(payload) }),
  deleteBaby: (babyId: string, confirmation: string, exportAcknowledged: boolean) =>
    request<void>(`/babies/${babyId}`, {
      method: "DELETE",
      body: JSON.stringify({ confirmation, export_acknowledged: exportAcknowledged }),
    }),
  deleteHousehold: (confirmation: string) =>
    request<void>("/household", {
      method: "DELETE",
      body: JSON.stringify({ confirmation }),
    }),
  records: (babyId: string, options: RecordListOptions = {}, signal?: AbortSignal) =>
    request<CareRecordPage>(careRecordListPath(babyId, options), { signal }),
  allRecords: allCareRecords,
  createRecord: (payload: CareRecordCreate, mutationId: string, signal?: AbortSignal) =>
    request<CareRecord>("/care-records", {
      method: "POST",
      headers: { "X-Mutation-ID": mutationId },
      body: JSON.stringify(payload),
      signal,
    }),
  updateRecord: (id: string, expectedRevision: number, payload: CareRecordCreate) =>
    request<CareRecord>(`/care-records/${id}`, {
      method: "PUT",
      body: JSON.stringify({ expected_revision: expectedRevision, record: payload }),
    }),
  deleteRecord: (id: string, revision: number) =>
    request<void>(`/care-records/${id}?expected_revision=${revision}`, { method: "DELETE" }),
  sync: (after: number, signal?: AbortSignal) =>
    request<SyncPage>(`/sync?after=${after}`, { signal }),
  setProfilePicture: async (babyId: string, file: File) => {
    const body = new FormData();
    body.set("image", file);
    return request<void>(`/babies/${babyId}/profile-picture`, { method: "PUT", body });
  },
  deleteProfilePicture: (babyId: string) =>
    request<void>(`/babies/${babyId}/profile-picture`, { method: "DELETE" }),
  caregivers: () => request<Caregiver[]>("/caregivers"),
  deactivateCaregiver: (id: string) =>
    request<void>(`/caregivers/${id}`, { method: "DELETE" }),
  eraseCaregiverIdentity: (id: string) =>
    request<void>(`/caregivers/${id}/identity`, { method: "DELETE" }),
  quickActions: () =>
    request<QuickActionPreference[]>("/caregivers/current/quick-actions"),
  updateQuickActions: (payload: QuickActionPreferencesUpdate) =>
    request<QuickActionPreference[]>("/caregivers/current/quick-actions", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  createInvitation: () =>
    request<Invitation>("/invitations", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  acceptInvitation: (payload: InvitationAccept) =>
    request<Session>("/invitations/accept", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deviceSessions: () => request<DeviceSession[]>("/sessions/devices"),
  revokeDeviceSession: (id: string) =>
    request<void>(`/sessions/devices/${id}`, { method: "DELETE" }),
  imports: () => request<ImportBatch[]>("/imports/piyolog"),
  importedDailyNotes: (babyId: string) =>
    request<ImportedDailyNote[]>(
      `/imports/piyolog/daily-notes?baby_id=${encodeURIComponent(babyId)}`,
    ),
  deleteImportSource: (id: string) =>
    request<void>(`/imports/piyolog/${id}/source`, { method: "DELETE" }),
  previewPiyolog: (babyId: string, timeZone: string, file: File) => {
    const body = new FormData();
    body.set("baby_id", babyId);
    body.set("source_time_zone", timeZone);
    body.set("file", file);
    return request<PiyoLogPreview>("/imports/piyolog/preview", { method: "POST", body });
  },
  confirmPiyolog: (babyId: string, timeZone: string, file: File, retainSource: boolean, replaceModified: boolean) => {
    const body = new FormData();
    body.set("baby_id", babyId);
    body.set("source_time_zone", timeZone);
    body.set("retain_source", String(retainSource));
    body.set("replace_modified", String(replaceModified));
    body.set("file", file);
    return request<ImportBatch>("/imports/piyolog/confirm", { method: "POST", body });
  },
};
