import type {
  Baby,
  BabyCreate,
  CareRecord,
  CareRecordCreate,
  CareRecordPage,
  Caregiver,
  LoginRequest,
  Session,
  SetupRequest,
  SetupStatus,
  SyncPage,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
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
    const error = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(response.status, error.detail ?? "request_failed");
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  setupStatus: () => request<SetupStatus>("/setup"),
  setup: (payload: SetupRequest) =>
    request<Session>("/setup", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: LoginRequest) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<Caregiver>("/sessions/current"),
  logout: () => request<void>("/sessions/current", { method: "DELETE" }),
  babies: () => request<Baby[]>("/babies"),
  createBaby: (payload: BabyCreate) =>
    request<Baby>("/babies", { method: "POST", body: JSON.stringify(payload) }),
  records: (babyId: string) =>
    request<CareRecordPage>(`/care-records?baby_id=${encodeURIComponent(babyId)}&limit=200`),
  createRecord: (payload: CareRecordCreate, mutationId: string) =>
    request<CareRecord>("/care-records", {
      method: "POST",
      headers: { "X-Mutation-ID": mutationId },
      body: JSON.stringify(payload),
    }),
  updateRecord: (id: string, expectedRevision: number, payload: CareRecordCreate) =>
    request<CareRecord>(`/care-records/${id}`, {
      method: "PUT",
      body: JSON.stringify({ expected_revision: expectedRevision, record: payload }),
    }),
  deleteRecord: (id: string, revision: number) =>
    request<void>(`/care-records/${id}?expected_revision=${revision}`, { method: "DELETE" }),
  sync: (after: number) => request<SyncPage>(`/sync?after=${after}`),
  setProfilePicture: async (babyId: string, file: File) => {
    const body = new FormData();
    body.set("image", file);
    return request<void>(`/babies/${babyId}/profile-picture`, { method: "PUT", body });
  },
};

