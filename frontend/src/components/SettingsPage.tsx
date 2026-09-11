import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Download,
  FileUp,
  Link as LinkIcon,
  ListChecks,
  ShieldCheck,
  Smartphone,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import { invalidateCareRecordQueries } from "../api/cache";
import type { Baby, Caregiver, PiyoLogPreview, QuickActionPreference } from "../api/types";
import { careAction } from "../careActions";
import { clearBabyLocalData, clearLocalData } from "../offline/store";

export function SettingsPage({ baby, caregiver }: { baby: Baby; caregiver: Caregiver }) {
  const owner = caregiver.role === "owner";
  return (
    <main className="page settings-page">
      <div className="page-heading">
        <div><p className="eyebrow">Private household</p><h1>Settings</h1></div>
      </div>
      <div className="settings-grid">
        <QuickActionsCard />
        <DeviceCard />
        {owner && <CaregiverCard currentCaregiverId={caregiver.id} />}
        {owner && <ImportCard baby={baby} />}
        {owner && <ExportCard baby={baby} />}
        {owner && <DangerCard baby={baby} />}
      </div>
    </main>
  );
}

function QuickActionsCard() {
  const queryClient = useQueryClient();
  const preferences = useQuery({ queryKey: ["quick-actions"], queryFn: api.quickActions });
  const [draft, setDraft] = useState<QuickActionPreference[]>([]);
  const save = useMutation({
    mutationFn: () =>
      api.updateQuickActions({
        actions: draft.map(({ record_type, is_hidden }) => ({ record_type, is_hidden })),
      }),
    onSuccess: (actions) => {
      setDraft(actions);
      queryClient.setQueryData(["quick-actions"], actions);
    },
  });

  useEffect(() => {
    if (preferences.data) setDraft(preferences.data);
  }, [preferences.data]);

  const move = (index: number, delta: -1 | 1) => {
    setDraft((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const reordered = [...current];
      [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
      return reordered.map((item, position) => ({ ...item, position }));
    });
  };

  return (
    <section className="settings-card span-two">
      <div className="card-title"><ListChecks /><div><h2>Quick actions</h2><p>Choose what appears in the add sheet and put frequent actions first.</p></div></div>
      <div className="quick-action-list">
        {draft.map((preference, index) => {
          const action = careAction(preference.record_type);
          const Icon = action.icon;
          return (
            <div className="quick-action-row" key={preference.record_type}>
              <div className="quick-action-name"><Icon aria-hidden="true" /><strong>{action.label}</strong></div>
              <label className="quick-action-visible">
                <input
                  type="checkbox"
                  checked={!preference.is_hidden}
                  aria-label={`Show ${action.label}`}
                  onChange={(event) => setDraft((current) => current.map((item) => item.record_type === preference.record_type ? { ...item, is_hidden: !event.target.checked } : item))}
                />
                <span>Show</span>
              </label>
              <div className="quick-action-order">
                <button type="button" className="secondary icon-button" disabled={index === 0} aria-label={`Move ${action.label} up`} onClick={() => move(index, -1)}><ArrowUp /></button>
                <button type="button" className="secondary icon-button" disabled={index === draft.length - 1} aria-label={`Move ${action.label} down`} onClick={() => move(index, 1)}><ArrowDown /></button>
              </div>
            </div>
          );
        })}
      </div>
      {preferences.isError && <p className="error" role="alert">Could not load quick actions.</p>}
      {save.isError && <p className="error" role="alert">Could not save quick actions.</p>}
      {save.isSuccess && <p className="save-confirmation" role="status">Quick actions saved.</p>}
      <button className="primary" disabled={!draft.length || save.isPending} onClick={() => save.mutate()}>Save quick actions</button>
    </section>
  );
}

function DeviceCard() {
  const queryClient = useQueryClient();
  const devices = useQuery({ queryKey: ["device-sessions"], queryFn: api.deviceSessions });
  const revoke = useMutation({
    mutationFn: api.revokeDeviceSession,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["device-sessions"] }),
  });
  return (
    <section className="settings-card">
      <div className="card-title"><Smartphone /><div><h2>Your devices</h2><p>Revoke a session you no longer use.</p></div></div>
      <div className="stack-list">
        {devices.data?.map((device) => <div className="list-row" key={device.id}><div><strong>{device.device_name || "Unnamed device"}</strong><span>{device.current ? "This device" : `Seen ${new Date(device.last_seen_at).toLocaleDateString()}`}</span></div>{!device.current && <button className="secondary small" onClick={() => revoke.mutate(device.id)}>Revoke</button>}</div>)}
      </div>
    </section>
  );
}

function CaregiverCard({ currentCaregiverId }: { currentCaregiverId: string }) {
  const queryClient = useQueryClient();
  const caregivers = useQuery({ queryKey: ["caregivers"], queryFn: api.caregivers });
  const invitation = useMutation({ mutationFn: api.createInvitation });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["caregivers"] });
  const deactivate = useMutation({ mutationFn: api.deactivateCaregiver, onSuccess: refresh });
  const erase = useMutation({ mutationFn: api.eraseCaregiverIdentity, onSuccess: refresh });
  return (
    <section className="settings-card">
      <div className="card-title"><LinkIcon /><div><h2>Caregivers</h2><p>Invite with a one-use code that expires in 24 hours.</p></div></div>
      <div className="stack-list">{caregivers.data?.map((item) => <div className="list-row" key={item.id}><div><strong>{item.display_name}</strong><span>{item.identity_erased_at ? "Identity erased" : item.is_active ? item.role : "Access removed"}</span></div>{item.id !== currentCaregiverId && item.is_active && <button className="secondary small" disabled={deactivate.isPending} onClick={() => deactivate.mutate(item.id)}>Remove access</button>}{item.id !== currentCaregiverId && !item.is_active && !item.identity_erased_at && <button className="danger-button small" disabled={erase.isPending} onClick={() => erase.mutate(item.id)}>Erase identity</button>}</div>)}</div>
      {(deactivate.isError || erase.isError) && <p className="error" role="alert">Could not update this caregiver.</p>}
      <button className="secondary" onClick={() => invitation.mutate()} disabled={invitation.isPending}>Create invitation code</button>
      {invitation.data && <div className="secret-output"><span>Share privately, once</span><code>{invitation.data.token}</code></div>}
    </section>
  );
}

function ImportCard({ baby }: { baby: Baby }) {
  const [file, setFile] = useState<File | null>(null);
  const [timeZone, setTimeZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [retainSource, setRetainSource] = useState(true);
  const [replaceModified, setReplaceModified] = useState(false);
  const [preview, setPreview] = useState<PiyoLogPreview | null>(null);
  const queryClient = useQueryClient();
  const imports = useQuery({ queryKey: ["imports"], queryFn: api.imports });
  const previewMutation = useMutation({
    mutationFn: () => api.previewPiyolog(baby.id, timeZone, file!),
    onSuccess: setPreview,
  });
  const confirmMutation = useMutation({
    mutationFn: () => api.confirmPiyolog(baby.id, timeZone, file!, retainSource, replaceModified),
    onSuccess: async () => {
      setPreview(null);
      setFile(null);
      await invalidateCareRecordQueries(queryClient, baby.id);
      await queryClient.invalidateQueries({ queryKey: ["imported-daily-notes", baby.id] });
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    },
  });
  const error = previewMutation.error ?? confirmMutation.error;
  return (
    <section className="settings-card span-two">
      <div className="card-title"><FileUp /><div><h2>Import from PiyoLog</h2><p>English and Japanese day or month text exports. Nothing is written until you confirm.</p></div></div>
      <div className="field-row"><label>Text export<input type="file" accept="text/plain,.txt" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); }} /></label><label>Source time zone<input value={timeZone} onChange={(event) => setTimeZone(event.target.value)} /></label></div>
      <label className="choice"><input type="checkbox" checked={retainSource} onChange={(event) => setRetainSource(event.target.checked)} /> Retain the source text for audit and re-import</label>
      <button className="secondary" disabled={!file || previewMutation.isPending} onClick={() => previewMutation.mutate()}>Preview import</button>
      {error && <p role="alert" className="error">{error instanceof ApiError ? error.detail.replaceAll("_", " ") : "Import failed"}</p>}
      {preview && <div className="import-preview">
        <div className="list-row"><div><strong>{preview.date_from || "Unknown date"} → {preview.date_to || "Unknown date"}</strong><span>{preview.detected_locale === "ja" ? "Japanese" : "English"} export · SHA-256 checked</span></div></div>
        <div className="count-chips">{Object.entries(preview.counts).map(([kind, count]) => <span key={kind}>{kind.replaceAll("_", " ")} <strong>{count}</strong></span>)}</div>
        {preview.warnings.map((warning) => <p className="muted" key={warning}>{warning}</p>)}
        {(preview.conflicts?.locally_modified ?? 0) > 0 ? <label className="choice"><input type="checkbox" checked={replaceModified} onChange={(event) => setReplaceModified(event.target.checked)} /> Replace {preview.conflicts?.locally_modified ?? 0} locally corrected imported record{preview.conflicts?.locally_modified === 1 ? "" : "s"}</label> : null}
        {(preview.conflicts?.replaceable ?? 0) > 0 ? <p className="muted">{preview.conflicts?.replaceable ?? 0} unchanged record{preview.conflicts?.replaceable === 1 ? "" : "s"} from an earlier import will be safely replaced.</p> : null}
        {preview.duplicate_import_id ? <p className="error">This exact file was already imported.</p> : <button className="primary" disabled={confirmMutation.isPending} onClick={() => confirmMutation.mutate()}>Confirm import for {baby.display_name}</button>}
      </div>}
      {imports.data?.length ? <p className="muted small-copy">{imports.data.length} confirmed import{imports.data.length === 1 ? "" : "s"} retained in the audit trail.</p> : null}
    </section>
  );
}

function ExportCard({ baby }: { baby: Baby }) {
  return (
    <section className="settings-card">
      <div className="card-title"><Download /><div><h2>Take your data</h2><p>Exports contain private family information. Store them securely.</p></div></div>
      <a className="primary" href="/api/v1/exports/minilog" download>Download lossless ZIP</a>
      <a className="secondary" href={`/api/v1/exports/timeline.csv?baby_id=${encodeURIComponent(baby.id)}`} download>Download timeline CSV</a>
      <div className="privacy-note"><ShieldCheck /><span>No analytics, ads, cloud relay, or third-party runtime requests.</span></div>
    </section>
  );
}

function DangerCard({ baby }: { baby: Baby }) {
  const household = useQuery({ queryKey: ["household"], queryFn: api.household });
  const [babyConfirmation, setBabyConfirmation] = useState("");
  const [exportAcknowledged, setExportAcknowledged] = useState(false);
  const [householdConfirmation, setHouseholdConfirmation] = useState("");
  const removeBaby = useMutation({
    mutationFn: () => api.deleteBaby(baby.id, babyConfirmation, exportAcknowledged),
    onSuccess: async () => {
      await clearBabyLocalData(baby.id);
      localStorage.removeItem("selectedBaby");
      window.location.assign("/");
    },
  });
  const removeHousehold = useMutation({
    mutationFn: () => api.deleteHousehold(householdConfirmation),
    onSuccess: async () => {
      await clearLocalData();
      localStorage.removeItem("selectedBaby");
      window.location.assign("/");
    },
  });
  const householdPhrase = household.data ? `DELETE ${household.data.display_name}` : "";
  return (
    <section className="settings-card span-two danger-card">
      <div className="card-title"><Trash2 /><div><h2>Permanent deletion</h2><p>Existing copies in operator backups or downloaded exports cannot be erased by Minilog.</p></div></div>
      <div className="danger-grid">
        <div><h3>Delete {baby.display_name}</h3><p>Download an export first. Then type the Baby's name exactly.</p><label className="choice"><input type="checkbox" checked={exportAcknowledged} onChange={(event) => setExportAcknowledged(event.target.checked)} /> I saved an export or accept proceeding without one</label><input aria-label={`Type ${baby.display_name} to delete this Baby`} value={babyConfirmation} onChange={(event) => setBabyConfirmation(event.target.value)} /><button className="danger-button" disabled={!exportAcknowledged || babyConfirmation !== baby.display_name || removeBaby.isPending} onClick={() => removeBaby.mutate()}>Permanently delete {baby.display_name}</button></div>
        <div><h3>Delete the household</h3><p>This removes every Baby, caregiver, care record, picture, and retained import. Type <strong>{householdPhrase}</strong>.</p><input aria-label="Type the household deletion phrase" value={householdConfirmation} onChange={(event) => setHouseholdConfirmation(event.target.value)} /><button className="danger-button" disabled={!householdPhrase || householdConfirmation !== householdPhrase || removeHousehold.isPending} onClick={() => removeHousehold.mutate()}>Permanently delete everything</button></div>
      </div>
    </section>
  );
}
