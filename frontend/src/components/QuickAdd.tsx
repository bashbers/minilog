import { useQuery } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useState } from "react";

import { api } from "../api/client";
import type { CareRecordCreate } from "../api/types";
import { careAction, orderedCareActions, type CareActionKind } from "../careActions";
import { useCreateRecord } from "../hooks/useRecords";
import { localDateTimeValue, localOffsetMinutes, toTimestamp } from "../lib/time";

export function QuickAdd({ babyId, onClose }: { babyId: string; onClose: () => void }) {
  const [kind, setKind] = useState<CareActionKind | null>(null);
  const mutation = useCreateRecord(babyId);
  const preferences = useQuery({
    queryKey: ["quick-actions"],
    queryFn: api.quickActions,
    staleTime: 60_000,
  });
  const actions = orderedCareActions(preferences.data);
  const [occurredAt] = useState(() => localDateTimeValue());

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!kind) return;
    const values = new FormData(event.currentTarget);
    const localTime = String(values.get("occurredAt"));
    const common = {
      baby_id: babyId,
      occurred_at: toTimestamp(localTime),
      local_offset_minutes: localOffsetMinutes(localTime),
      note: String(values.get("note") || "") || null,
    };
    let payload: CareRecordCreate;
    switch (kind) {
      case "breastfeeding": {
        const side = String(values.get("side")) as "left" | "right";
        payload = {
          ...common,
          record_type: kind,
          intervals: [{ side, started_at: common.occurred_at }],
        };
        break;
      }
      case "bottle_feeding":
        payload = {
          ...common,
          record_type: kind,
          consumed_ml: Number(values.get("consumedMl")),
          offered_ml: values.get("offeredMl") ? Number(values.get("offeredMl")) : null,
          contents: String(values.get("contents")) as
            | "breast_milk"
            | "formula"
            | "mixed"
            | "other",
        };
        break;
      case "solid_food_feeding":
        payload = {
          ...common,
          record_type: kind,
          foods: String(values.get("foods")),
          amount_value: values.get("amount") ? Number(values.get("amount")) : null,
          amount_unit: values.get("amount") ? String(values.get("amountUnit")) : null,
          reaction_note: String(values.get("reactionNote") || "") || null,
        };
        break;
      case "sleep":
        payload = { ...common, record_type: kind };
        break;
      case "diaper_change":
        payload = {
          ...common,
          record_type: kind,
          is_wet: values.get("wet") === "on",
          is_dirty: values.get("dirty") === "on",
          stool_colour: String(values.get("stoolColour") || "") || null,
          stool_consistency: String(values.get("stoolConsistency") || "") || null,
        };
        break;
      case "pumping":
        payload = { ...common, record_type: kind, expressed_ml: null };
        break;
      case "measurement": {
        const measurementKind = String(values.get("measurementKind")) as
          | "weight"
          | "height"
          | "temperature";
        const defaultUnit = { weight: "kg", height: "cm", temperature: "celsius" }[
          measurementKind
        ];
        payload = {
          ...common,
          record_type: kind,
          kind: measurementKind,
          entered_value: Number(values.get("measurementValue")),
          entered_unit: String(values.get("measurementUnit") || defaultUnit),
        };
        break;
      }
      case "medication_administration":
        payload = {
          ...common,
          record_type: kind,
          medicine_name: String(values.get("medicineName")),
          amount_value: Number(values.get("medicineAmount")),
          unit_code: String(values.get("medicineUnit") || "ml"),
          custom_unit: null,
          route: String(values.get("route") || "") || null,
        };
        break;
      case "note":
        payload = { ...common, record_type: kind, body: String(values.get("body")) };
        break;
    }
    await mutation.mutateAsync(payload);
    onClose();
  };

  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="bottom-sheet" role="dialog" aria-modal="true" aria-label="Add care record" onMouseDown={(event) => event.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="sheet-header">
          <div><p className="eyebrow">Quick add</p><h2>{kind ? careAction(kind).label : "What happened?"}</h2></div>
          <button className="ghost icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
        {!kind ? (
          <div className="action-grid">
            {actions.map(({ kind: actionKind, label, icon: Icon }) => (
              <button key={actionKind} onClick={() => setKind(actionKind)} className="care-action">
                <Icon aria-hidden="true" /> <span>{label}</span>
              </button>
            ))}
          </div>
        ) : (
          <form onSubmit={submit} className="form-stack care-form">
            <label>When<input type="datetime-local" name="occurredAt" defaultValue={occurredAt} required /></label>
            {kind === "breastfeeding" && <label>Starting side<select name="side"><option value="left">Left</option><option value="right">Right</option></select></label>}
            {kind === "bottle_feeding" && <>
              <div className="field-row"><label>Consumed (ml)<input name="consumedMl" type="number" min="0" inputMode="numeric" required /></label><label>Offered (ml)<input name="offeredMl" type="number" min="0" inputMode="numeric" /></label></div>
              <label>Contents<select name="contents"><option value="breast_milk">Breast milk</option><option value="formula">Formula</option><option value="mixed">Mixed</option><option value="other">Other</option></select></label>
            </>}
            {kind === "solid_food_feeding" && <>
              <label>Foods<input name="foods" required placeholder="Banana, yoghurt…" /></label>
              <div className="field-row"><label>Amount<input name="amount" type="number" min="0" step="any" inputMode="decimal" /></label><label>Unit<input name="amountUnit" defaultValue="spoons" /></label></div>
              <label>Observed reaction<textarea name="reactionNote" rows={2} /></label>
            </>}
            {kind === "diaper_change" && <>
              <fieldset><legend>Diaper</legend><div className="choice-row"><label className="choice"><input type="checkbox" name="wet" defaultChecked /> Wet</label><label className="choice"><input type="checkbox" name="dirty" /> Dirty</label></div></fieldset>
              <div className="field-row"><label>Colour<input name="stoolColour" /></label><label>Consistency<input name="stoolConsistency" /></label></div>
            </>}
            {kind === "measurement" && <>
              <label>Measurement<select name="measurementKind"><option value="weight">Weight</option><option value="height">Height</option><option value="temperature">Temperature</option></select></label>
              <div className="field-row"><label>Value<input name="measurementValue" type="number" step="any" required inputMode="decimal" /></label><label>Unit<input name="measurementUnit" placeholder="kg" /></label></div>
            </>}
            {kind === "medication_administration" && <>
              <label>Medicine name<input name="medicineName" required /></label>
              <div className="field-row"><label>Amount<input name="medicineAmount" type="number" min="0" step="any" required inputMode="decimal" /></label><label>Unit<input name="medicineUnit" defaultValue="ml" required /></label></div>
              <label>Route <span className="muted">optional</span><input name="route" placeholder="Oral" /></label>
            </>}
            {kind === "note" && <label>Note<textarea name="body" rows={4} required autoFocus /></label>}
            {!['note', 'solid_food_feeding'].includes(kind) && <label>Note <span className="muted">optional</span><textarea name="note" rows={2} /></label>}
            {mutation.isError && <p className="error" role="alert">Could not save. Check the values and try again.</p>}
            <div className="sheet-actions"><button type="button" className="secondary" onClick={() => setKind(null)}>Back</button><button className="primary" disabled={mutation.isPending}>{['sleep', 'breastfeeding', 'pumping'].includes(kind) ? "Start" : "Save"}</button></div>
          </form>
        )}
      </section>
    </div>
  );
}
