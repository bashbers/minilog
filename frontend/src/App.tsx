import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Baby as BabyIcon, History, ImageOff, LogOut, Plus, Settings, Sparkles, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, ApiError } from "./api/client";
import { removeMissingBabyQueries } from "./api/cache";
import type { Baby, Caregiver } from "./api/types";
import { LoginScreen, SetupScreen } from "./components/AuthScreens";
import { BabyOnboarding } from "./components/BabyOnboarding";
import { QuickAdd } from "./components/QuickAdd";
import { SettingsPage } from "./components/SettingsPage";
import { HistoryPage, TodayPage, TrendsPage } from "./features/care/CarePages";
import { useForegroundSync } from "./hooks/useForegroundSync";
import { configureDisplayPreferences } from "./lib/time";
import { clearLocalData, clearProfilePictureCache, reconcileBabyLocalData, retainCurrentProfilePictureCache } from "./offline/store";

const EXPECTED_API_CONTRACT_VERSION = 1;

function AuthGate() {
  const compatibility = useQuery({
    queryKey: ["compatibility"],
    queryFn: api.compatibility,
    retry: false,
    refetchInterval: 5_000,
  });

  if (compatibility.isLoading) return <LoadingScreen />;
  if (compatibility.error instanceof ApiError && compatibility.error.status === 503) {
    return <MaintenanceScreen />;
  }
  if (compatibility.isError || !compatibility.data) return <ErrorScreen />;
  if (compatibility.data.api_contract_version !== EXPECTED_API_CONTRACT_VERSION) {
    return <VersionMismatchScreen />;
  }
  return <SessionGate />;
}

function SessionGate() {
  const queryClient = useQueryClient();
  const [cleanupState, setCleanupState] = useState<"idle" | "required" | "complete">("idle");
  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: api.setupStatus,
    retry: false,
    refetchInterval: 5_000,
  });
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    refetchInterval: 5_000,
  });
  const sessionInvalid = setup.data?.setup_required === true
    || (me.error instanceof ApiError && me.error.status === 401);

  useEffect(() => {
    if (sessionInvalid && cleanupState === "idle") setCleanupState("required");
    if (cleanupState === "complete" && me.isSuccess && me.data && !setup.data?.setup_required) {
      setCleanupState("idle");
    }
  }, [cleanupState, me.data, me.isSuccess, sessionInvalid, setup.data?.setup_required]);

  useEffect(() => {
    if (cleanupState !== "required") return;
    let cleanupInFlight = false;
    const cleanup = () => {
      if (cleanupInFlight) return;
      cleanupInFlight = true;
      void clearUnauthenticatedClientData(queryClient)
        .then(() => setCleanupState("complete"))
        .catch(() => undefined)
        .finally(() => { cleanupInFlight = false; });
    };
    cleanup();
    const retry = window.setInterval(cleanup, 5_000);
    return () => window.clearInterval(retry);
  }, [cleanupState, queryClient]);

  if (cleanupState === "required" || (sessionInvalid && cleanupState !== "complete")) {
    return <LoadingScreen />;
  }
  if (setup.isLoading || me.isLoading) return <LoadingScreen />;
  if (setup.data?.setup_required) return <SetupScreen />;
  if (me.error instanceof ApiError && me.error.status === 401) return <LoginScreen />;
  if (me.isError || !me.data) return <ErrorScreen />;
  return <HouseholdApp caregiver={me.data} />;
}

export async function clearUnauthenticatedClientData(queryClient: QueryClient) {
  const isPrivateQuery = ({ queryKey }: { queryKey: readonly unknown[] }) =>
    !["compatibility", "setup"].includes(String(queryKey[0]));
  localStorage.removeItem("selectedBaby");
  const meReset = queryClient.resetQueries({ queryKey: ["me"], exact: true });
  const cancellation = queryClient.cancelQueries({ predicate: isPrivateQuery });
  queryClient.getMutationCache().clear();
  queryClient.removeQueries({ predicate: isPrivateQuery });
  await Promise.all([meReset, cancellation]);
  await clearLocalData();
}

function LoadingScreen() {
  return <main className="center-screen"><div className="brand-mark pulse"><BabyIcon /></div><p>Opening Minilog…</p></main>;
}

function ErrorScreen() {
  return <main className="center-screen"><h1>Minilog is unavailable</h1><p className="muted">Check that your private server is running, then reload.</p></main>;
}

function MaintenanceScreen() {
  return <main className="center-screen"><div className="brand-mark pulse"><BabyIcon /></div><h1>Minilog is upgrading</h1><p className="muted">Your private data is being checked. This screen will update automatically.</p></main>;
}

function VersionMismatchScreen() {
  return <main className="center-screen"><h1>Minilog versions do not match</h1><p className="muted">Update the web and API containers to the same release, then reload.</p></main>;
}

function HouseholdApp({ caregiver }: { caregiver: Caregiver }) {
  useForegroundSync();
  const babies = useQuery({
    queryKey: ["babies"],
    queryFn: api.babies,
    refetchInterval: 5_000,
  });
  const household = useQuery({
    queryKey: ["household"],
    queryFn: api.household,
    refetchInterval: 5_000,
  });
  const activeStatuses = useQuery({
    queryKey: ["baby-active-statuses"],
    queryFn: api.babyActiveStatuses,
    refetchInterval: 5_000,
  });
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem("selectedBaby"));
  const [quickAdd, setQuickAdd] = useState(false);
  const queryClient = useQueryClient();
  const refreshProfilePicture = async () => {
    await clearProfilePictureCache().catch(() => undefined);
    await queryClient.invalidateQueries({ queryKey: ["babies"] });
  };
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      await clearLocalData().catch(() => undefined);
      localStorage.removeItem("selectedBaby");
      queryClient.clear();
      window.location.assign("/");
    },
  });
  const removeProfilePicture = useMutation({
    mutationFn: api.deleteProfilePicture,
    onSuccess: refreshProfilePicture,
  });

  useEffect(() => {
    if (!babies.data) return;
    if (babies.data.length === 0) {
      setQuickAdd(false);
      setSelectedId(null);
      localStorage.removeItem("selectedBaby");
      return;
    }
    if (!selectedId || !babies.data.some((baby) => baby.id === selectedId)) {
      setQuickAdd(false);
      setSelectedId(babies.data[0].id);
      localStorage.setItem("selectedBaby", babies.data[0].id);
    }
  }, [babies.data, babies.dataUpdatedAt, selectedId]);

  const selectedBaby = babies.data?.find((item) => item.id === selectedId) ?? babies.data?.[0];
  useEffect(() => {
    if (!babies.data) return;
    const currentBabyIds = babies.data.map((baby) => baby.id);
    removeMissingBabyQueries(queryClient, currentBabyIds);
    void reconcileBabyLocalData(currentBabyIds, selectedBaby?.id ?? null);
  }, [babies.data, babies.dataUpdatedAt, queryClient, selectedBaby?.id]);

  useEffect(() => {
    if (!babies.data) return;
    const pictureUrl = selectedBaby?.has_profile_picture
      ? `/api/v1/babies/${selectedBaby.id}/profile-picture?v=${selectedBaby.updated_at}`
      : null;
    void retainCurrentProfilePictureCache(pictureUrl);
  }, [babies.data, babies.dataUpdatedAt, selectedBaby?.has_profile_picture, selectedBaby?.id, selectedBaby?.updated_at]);

  if (babies.isLoading || household.isLoading) return <LoadingScreen />;
  if (!household.data) return <ErrorScreen />;
  if (!babies.data?.length) return <BabyOnboarding />;
  configureDisplayPreferences({
    locale: household.data.locale,
    timeZone: household.data.time_zone,
    clockFormat: household.data.clock_format,
    measurementSystem: household.data.measurement_system,
  });
  const baby = selectedBaby ?? babies.data[0];
  const activeByBaby = new Map(
    (activeStatuses.data ?? []).map((status) => [status.baby_id, status.active_types.length]),
  );

  const selectBaby = (id: string) => {
    setSelectedId(id);
    localStorage.setItem("selectedBaby", id);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-main">
          <label className="baby-picker">
            <span className="sr-only">Selected Baby</span>
            <BabyPicture baby={baby} />
            <select value={baby.id} onChange={(event) => selectBaby(event.target.value)}>
              {babies.data.map((item) => <option value={item.id} key={item.id}>{item.display_name}</option>)}
            </select>
          </label>
          <label className="picture-upload" title="Change profile picture">
            <Upload aria-hidden="true" />
            <span className="sr-only">Change profile picture</span>
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => { const file = event.target.files?.[0]; if (file) { await api.setProfilePicture(baby.id, file); await refreshProfilePicture(); } }} />
          </label>
          {baby.has_profile_picture && <button className="ghost icon-button" aria-label="Remove profile picture" disabled={removeProfilePicture.isPending} onClick={() => removeProfilePicture.mutate(baby.id)}><ImageOff /></button>}
          <NavLink className="ghost icon-button topbar-link" to="/settings" aria-label="Settings"><Settings /></NavLink>
          <button className="ghost icon-button" onClick={() => logout.mutate()} aria-label="Sign out"><LogOut /></button>
        </div>
        {[...activeByBaby.values()].some((count) => count > 0) && <div className="active-baby-strip" aria-label="Active care by Baby">
          {babies.data.filter((item) => (activeByBaby.get(item.id) ?? 0) > 0).map((item) => <button type="button" key={item.id} aria-pressed={item.id === baby.id} onClick={() => selectBaby(item.id)}><span>{item.display_name}</span><strong>{activeByBaby.get(item.id)} active</strong></button>)}
        </div>}
      </header>

      <Routes>
        <Route path="/today" element={<TodayPage key={baby.id} baby={baby} timeZone={household.data.time_zone} />} />
        <Route path="/history" element={<HistoryPage key={baby.id} baby={baby} />} />
        <Route path="/trends" element={<TrendsPage key={baby.id} baby={baby} timeZone={household.data.time_zone} />} />
        <Route path="/settings" element={<SettingsPage key={baby.id} baby={baby} caregiver={caregiver} />} />
        <Route path="*" element={<Navigate to="/today" replace />} />
      </Routes>

      <nav className="bottom-nav" aria-label="Primary navigation">
        <NavLink to="/today"><BabyIcon /><span>Today</span></NavLink>
        <NavLink to="/history"><History /><span>History</span></NavLink>
        <button className="quick-add-button" onClick={() => setQuickAdd(true)} aria-label="Add care record"><Plus /></button>
        <NavLink to="/trends"><Sparkles /><span>Trends</span></NavLink>
      </nav>
      {quickAdd && <QuickAdd key={baby.id} babyId={baby.id} onClose={() => setQuickAdd(false)} />}
    </div>
  );
}

function BabyPicture({ baby }: { baby: Baby }) {
  if (baby.has_profile_picture) {
    return <img className="baby-picture" src={`/api/v1/babies/${baby.id}/profile-picture?v=${baby.updated_at}`} alt="" />;
  }
  return <span className="baby-picture placeholder"><BabyIcon /></span>;
}

export function App() {
  return <AuthGate />;
}
