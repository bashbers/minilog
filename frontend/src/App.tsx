import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Baby as BabyIcon, History, ImageOff, LogOut, Plus, Settings, Sparkles, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, ApiError } from "./api/client";
import type { Baby, Caregiver, TimelineRecord } from "./api/types";
import { careActions, careRecordSummaryValues, careRecordTypesForGroup, careSummaryCatalog, isActiveCareRecord } from "./careRecordForms";
import { LoginScreen, SetupScreen } from "./components/AuthScreens";
import { BabyOnboarding } from "./components/BabyOnboarding";
import { QuickAdd } from "./components/QuickAdd";
import { SettingsPage } from "./components/SettingsPage";
import { Timeline } from "./components/Timeline";
import { Trends } from "./components/Trends";
import { useForegroundSync } from "./hooks/useForegroundSync";
import { useRecords } from "./hooks/useRecords";
import { dateKeyInTimeZone, shiftDateKey } from "./lib/time";
import { clearLocalData, clearProfilePictureCache } from "./offline/store";

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
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setupStatus, retry: false });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });

  if (setup.isLoading || me.isLoading) return <LoadingScreen />;
  if (setup.data?.setup_required) return <SetupScreen />;
  if (me.error instanceof ApiError && me.error.status === 401) return <LoginScreen />;
  if (me.isError || !me.data) return <ErrorScreen />;
  return <HouseholdApp caregiver={me.data} />;
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
  const babies = useQuery({ queryKey: ["babies"], queryFn: api.babies });
  const household = useQuery({ queryKey: ["household"], queryFn: api.household });
  const activeStatuses = useQuery({
    queryKey: ["baby-active-statuses"],
    queryFn: api.babyActiveStatuses,
    refetchInterval: 5_000,
  });
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem("selectedBaby"));
  const [quickAdd, setQuickAdd] = useState(false);
  const queryClient = useQueryClient();
  const refreshProfilePicture = () => Promise.allSettled([
    clearProfilePictureCache(),
    queryClient.invalidateQueries({ queryKey: ["babies"] }),
  ]);
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      await clearLocalData();
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
    if (!babies.data?.length) return;
    if (!selectedId || !babies.data.some((baby) => baby.id === selectedId)) {
      setSelectedId(babies.data[0].id);
      localStorage.setItem("selectedBaby", babies.data[0].id);
    }
  }, [babies.data, selectedId]);

  if (babies.isLoading || household.isLoading) return <LoadingScreen />;
  if (!household.data) return <ErrorScreen />;
  if (!babies.data?.length) return <BabyOnboarding />;
  const baby = babies.data.find((item) => item.id === selectedId) ?? babies.data[0];
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
        <Route path="/today" element={<TodayPage baby={baby} timeZone={household.data.time_zone} />} />
        <Route path="/history" element={<HistoryPage baby={baby} />} />
        <Route path="/trends" element={<TrendsPage baby={baby} timeZone={household.data.time_zone} />} />
        <Route path="/settings" element={<SettingsPage baby={baby} caregiver={caregiver} />} />
        <Route path="*" element={<Navigate to="/today" replace />} />
      </Routes>

      <nav className="bottom-nav" aria-label="Primary navigation">
        <NavLink to="/today"><BabyIcon /><span>Today</span></NavLink>
        <NavLink to="/history"><History /><span>History</span></NavLink>
        <button className="quick-add-button" onClick={() => setQuickAdd(true)} aria-label="Add care record"><Plus /></button>
        <NavLink to="/trends"><Sparkles /><span>Trends</span></NavLink>
      </nav>
      {quickAdd && <QuickAdd babyId={baby.id} onClose={() => setQuickAdd(false)} />}
    </div>
  );
}

function BabyPicture({ baby }: { baby: Baby }) {
  if (baby.has_profile_picture) {
    return <img className="baby-picture" src={`/api/v1/babies/${baby.id}/profile-picture?v=${baby.updated_at}`} alt="" />;
  }
  return <span className="baby-picture placeholder"><BabyIcon /></span>;
}

function TodayPage({ baby, timeZone }: { baby: Baby; timeZone: string }) {
  const recentRecords = useRecords(baby.id);
  const todayKey = dateKeyInTimeZone(new Date(), timeZone);
  const dayRecords = useQuery({
    queryKey: ["today-records", baby.id, todayKey],
    queryFn: () => api.allRecords(baby.id, { dateFrom: todayKey, dateTo: todayKey }),
  });
  const activeRecords = useQuery({
    queryKey: ["active-records", baby.id],
    queryFn: () => api.allRecords(baby.id, { activeOnly: true }),
    refetchInterval: 5_000,
  });
  const today = useMemo(() => {
    const now = Date.now();
    const queued = (recentRecords.data ?? []).filter((record) => record.queued);
    const persisted = dayRecords.data ?? (recentRecords.data ?? []).filter((record) => !record.queued);
    const combined = [...queued, ...persisted, ...(activeRecords.data ?? [])];
    return [...new Map(combined.map((record) => [record.id, record])).values()]
      .filter((record) => isActiveCareRecord(record) || (
        dateKeyInTimeZone(record.occurred_at, timeZone) === todayKey
        && new Date(record.occurred_at).getTime() <= now
      ))
      .sort((left, right) => new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime());
  }, [activeRecords.data, dayRecords.data, recentRecords.data, timeZone, todayKey]);
  const active = today.filter(isActiveCareRecord);
  return (
    <main className="page">
      <div className="page-heading"><div><p className="eyebrow">{new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date())}</p><h1>{active.length ? `${active.length} active now` : "Today's care"}</h1></div><span className={`status-pill ${navigator.onLine ? "online" : "offline"}`}>{navigator.onLine ? "Synced" : "Offline"}</span></div>
      <DailySummary records={today} />
      {recentRecords.isLoading && dayRecords.isLoading ? <div className="skeleton-list" /> : <Timeline records={today} babyId={baby.id} />}
    </main>
  );
}

function HistoryPage({ baby }: { baby: Baby }) {
  const [filter, setFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const recordTypes: TimelineRecord["record_type"][] | undefined = filter === "all"
    ? undefined
    : filter === "feeding"
      ? careRecordTypesForGroup("feeding")
      : [filter as TimelineRecord["record_type"]];
  const history = useInfiniteQuery({
    queryKey: ["history-records", baby.id, filter, dateFrom, dateTo],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.records(baby.id, {
      cursor: pageParam,
      recordTypes,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      limit: 50,
    }),
    getNextPageParam: (lastPage) => {
      return lastPage.next_cursor ?? undefined;
    },
  });
  const visible = history.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <main className="page">
      <div className="page-heading"><div><p className="eyebrow">For {baby.display_name}</p><h1>History</h1></div></div>
      <div className="history-filters" aria-label="History filters">
        <label>Care type<select className="filter" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All care</option><option value="feeding">Feeding</option>{careActions.filter((action) => !careRecordTypesForGroup("feeding").includes(action.kind)).map((action) => <option value={action.kind} key={action.kind}>{action.label}</option>)}<option value="imported_care_record">Imported care record</option></select></label>
        <label>From<input type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => setDateFrom(event.target.value)} /></label>
        <label>To<input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} /></label>
      </div>
      {filter === "all" && <ImportedDailyNotes babyId={baby.id} dateFrom={dateFrom} dateTo={dateTo} />}
      {history.isPending ? <div className="skeleton-list" /> : <Timeline records={visible} babyId={baby.id} showDay />}
      {history.isError && <p className="error" role="alert">Could not load this history. Check the connection and try again.</p>}
      {history.hasNextPage && <button className="secondary load-older" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? "Loading…" : "Load older"}</button>}
    </main>
  );
}

function ImportedDailyNotes({ babyId, dateFrom, dateTo }: { babyId: string; dateFrom: string; dateTo: string }) {
  const notes = useQuery({
    queryKey: ["imported-daily-notes", babyId],
    queryFn: () => api.importedDailyNotes(babyId),
  });
  const visible = notes.data?.filter((note) => (!dateFrom || note.local_date >= dateFrom) && (!dateTo || note.local_date <= dateTo));
  if (!visible?.length) return null;
  return <section className="daily-notes" aria-label="Imported daily notes"><p className="eyebrow">PiyoLog daily notes</p>{visible.map((note) => <article key={note.id}><time>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(`${note.local_date}T12:00:00`))}</time><p>{note.body}</p></article>)}</section>;
}

function TrendsPage({ baby, timeZone }: { baby: Baby; timeZone: string }) {
  const [days, setDays] = useState<1 | 7 | 30>(7);
  const todayKey = dateKeyInTimeZone(new Date(), timeZone);
  const dateFrom = shiftDateKey(todayKey, 1 - days);
  const records = useQuery({
    queryKey: ["trend-records", baby.id, dateFrom, todayKey],
    queryFn: () => api.allRecords(baby.id, { dateFrom, dateTo: todayKey }),
  });
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">Patterns for {baby.display_name}</p><h1>Trends</h1></div></div><Trends records={records.data ?? []} timeZone={timeZone} days={days} onDaysChange={setDays} /></main>;
}

function DailySummary({ records }: { records: TimelineRecord[] }) {
  const summaryTotal = (key: string) => records.reduce((total, record) => total + careRecordSummaryValues(record).filter((summary) => summary.key === key).reduce((recordTotal, summary) => recordTotal + summary.value, 0), 0);
  const measurements = records.filter(
    (record): record is Extract<TimelineRecord, { record_type: "measurement" }> =>
      record.record_type === "measurement",
  ).filter((record, index, all) => all.findIndex((candidate) =>
    candidate.details.kind === record.details.kind
    && candidate.details.entered_unit === record.details.entered_unit) === index);
  return <section className="daily-summary" aria-label="Today's totals">
    {careSummaryCatalog.map((metric) => <div key={metric.key}><span>{metric.label}</span><strong>{Math.round(summaryTotal(metric.key))}{metric.suffix ? ` ${metric.suffix}` : ""}</strong></div>)}
    {measurements.map((record) => <div key={record.id}><span>Latest {record.details.kind}</span><strong>{Number(record.details.entered_value)} {record.details.entered_unit}</strong></div>)}
  </section>;
}

export function App() {
  return <AuthGate />;
}
