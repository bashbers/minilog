import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Baby as BabyIcon, History, LogOut, Plus, Sparkles, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, ApiError } from "./api/client";
import type { Baby, TimelineRecord } from "./api/types";
import { LoginScreen, SetupScreen } from "./components/AuthScreens";
import { BabyOnboarding } from "./components/BabyOnboarding";
import { QuickAdd } from "./components/QuickAdd";
import { Timeline } from "./components/Timeline";
import { Trends } from "./components/Trends";
import { useForegroundSync } from "./hooks/useForegroundSync";
import { useRecords } from "./hooks/useRecords";
import { clearLocalData } from "./offline/store";

function AuthGate() {
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setupStatus, retry: false });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });

  if (setup.isLoading || me.isLoading) return <LoadingScreen />;
  if (setup.data?.setup_required) return <SetupScreen />;
  if (me.error instanceof ApiError && me.error.status === 401) return <LoginScreen />;
  if (me.isError || !me.data) return <ErrorScreen />;
  return <HouseholdApp />;
}

function LoadingScreen() {
  return <main className="center-screen"><div className="brand-mark pulse"><BabyIcon /></div><p>Opening Minilog…</p></main>;
}

function ErrorScreen() {
  return <main className="center-screen"><h1>Minilog is unavailable</h1><p className="muted">Check that your private server is running, then reload.</p></main>;
}

function HouseholdApp() {
  useForegroundSync();
  const babies = useQuery({ queryKey: ["babies"], queryFn: api.babies });
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem("selectedBaby"));
  const [quickAdd, setQuickAdd] = useState(false);
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      await clearLocalData();
      localStorage.removeItem("selectedBaby");
      queryClient.clear();
      window.location.assign("/");
    },
  });

  useEffect(() => {
    if (!babies.data?.length) return;
    if (!selectedId || !babies.data.some((baby) => baby.id === selectedId)) {
      setSelectedId(babies.data[0].id);
      localStorage.setItem("selectedBaby", babies.data[0].id);
    }
  }, [babies.data, selectedId]);

  if (babies.isLoading) return <LoadingScreen />;
  if (!babies.data?.length) return <BabyOnboarding />;
  const baby = babies.data.find((item) => item.id === selectedId) ?? babies.data[0];

  const selectBaby = (id: string) => {
    setSelectedId(id);
    localStorage.setItem("selectedBaby", id);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
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
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => { const file = event.target.files?.[0]; if (file) { await api.setProfilePicture(baby.id, file); await queryClient.invalidateQueries({ queryKey: ["babies"] }); } }} />
        </label>
        <button className="ghost icon-button" onClick={() => logout.mutate()} aria-label="Sign out"><LogOut /></button>
      </header>

      <Routes>
        <Route path="/today" element={<TodayPage baby={baby} />} />
        <Route path="/history" element={<HistoryPage baby={baby} />} />
        <Route path="/trends" element={<TrendsPage baby={baby} />} />
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

function TodayPage({ baby }: { baby: Baby }) {
  const records = useRecords(baby.id);
  const today = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return (records.data ?? []).filter((record) => new Date(record.occurred_at) >= start);
  }, [records.data]);
  const active = today.filter((record) => !record.ended_at && ["sleep", "breastfeeding", "pumping"].includes(record.record_type));
  return (
    <main className="page">
      <div className="page-heading"><div><p className="eyebrow">{new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date())}</p><h1>{active.length ? `${active.length} active now` : "Today's care"}</h1></div><span className={`status-pill ${navigator.onLine ? "online" : "offline"}`}>{navigator.onLine ? "Synced" : "Offline"}</span></div>
      <DailySummary records={today} />
      {records.isLoading ? <div className="skeleton-list" /> : <Timeline records={today} babyId={baby.id} />}
    </main>
  );
}

function HistoryPage({ baby }: { baby: Baby }) {
  const records = useRecords(baby.id);
  const [filter, setFilter] = useState("all");
  const visible = (records.data ?? []).filter((record) => {
    if (filter === "all") return true;
    if (filter === "feeding") return record.record_type.includes("feeding");
    return record.record_type === filter;
  });
  return (
    <main className="page"><div className="page-heading"><div><p className="eyebrow">For {baby.display_name}</p><h1>History</h1></div><select className="filter" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All care</option><option value="feeding">Feeding</option>{["sleep", "diaper_change", "pumping", "measurement", "medication_administration", "note"].map((type) => <option value={type} key={type}>{type.replaceAll("_", " ")}</option>)}</select></div><Timeline records={visible} babyId={baby.id} showDay /></main>
  );
}

function TrendsPage({ baby }: { baby: Baby }) {
  const records = useRecords(baby.id);
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">Patterns for {baby.display_name}</p><h1>Trends</h1></div></div><Trends records={records.data ?? []} /></main>;
}

function DailySummary({ records }: { records: TimelineRecord[] }) {
  const feeds = records.filter((record) => record.record_type.includes("feeding")).length;
  const sleep = records.filter((record) => record.record_type === "sleep").reduce((sum, record) => sum + Math.max(0, (new Date(record.ended_at ?? Date.now()).getTime() - new Date(record.occurred_at).getTime()) / 3_600_000), 0);
  const diapers = records.filter((record) => record.record_type === "diaper_change").length;
  return <section className="daily-summary" aria-label="Today's totals"><div><span>Feeds</span><strong>{feeds}</strong></div><div><span>Sleep</span><strong>{sleep.toFixed(1)}h</strong></div><div><span>Diapers</span><strong>{diapers}</strong></div></section>;
}

export function App() {
  return <AuthGate />;
}
