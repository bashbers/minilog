import { describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { api } from "./api/client";
import type { QuickActionPreference } from "./api/types";
import { careActions, orderedCareActions } from "./careActions";
import type { TimelineRecord } from "./api/types";
import { careRecordRegistry, createRecordPayload, editedRecordPayload } from "./careRecordForms";
import { QuickAdd } from "./components/QuickAdd";

it("defines a form adapter for every native care-record action", () => {
  expect(Object.keys(careRecordRegistry).sort()).toEqual(
    careActions.map((action) => action.kind).sort(),
  );
});

describe("orderedCareActions", () => {
  it("uses the product defaults until preferences have loaded", () => {
    expect(orderedCareActions().map((action) => action.kind)).toEqual(
      careActions.map((action) => action.kind),
    );
  });

  it("follows the caregiver order and removes hidden actions", () => {
    const preferences: QuickActionPreference[] = [
      { record_type: "sleep", position: 0, is_hidden: false },
      { record_type: "bottle_feeding", position: 1, is_hidden: true },
      { record_type: "note", position: 2, is_hidden: false },
    ];

    expect(orderedCareActions(preferences).map((action) => action.kind)).toEqual([
      "sleep",
      "note",
    ]);
  });

  it("allows a caregiver to hide every quick action", () => {
    const hidden = careActions.map((action, position) => ({
      record_type: action.kind,
      position,
      is_hidden: true,
    }));

    expect(orderedCareActions(hidden)).toEqual([]);
  });
});

it("does not reveal default actions when caregiver preferences fail to load", async () => {
  vi.spyOn(api, "quickActions").mockRejectedValue(new Error("offline"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><QuickAdd babyId="baby-id" onClose={() => undefined} /></QueryClientProvider>);

  expect(await screen.findByText("Quick actions could not be loaded.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Bottle feeding" })).not.toBeInTheDocument();
});

it("keeps a solid-food note separate from its observed reaction", () => {
  const values = new FormData();
  values.set("occurredAt", "2026-09-11T12:00");
  values.set("foods", "Banana");
  values.set("reactionNote", "No reaction observed");
  values.set("note", "Ate with family");

  const payload = createRecordPayload("solid_food_feeding", "baby-id", values);
  expect(payload).toMatchObject({
    record_type: "solid_food_feeding",
    reaction_note: "No reaction observed",
    note: "Ate with family",
  });
  expect(careRecordRegistry.solid_food_feeding.showCommonNote).toBe(true);

  const record: TimelineRecord = {
    id: "solid-record",
    baby_id: "baby-id",
    record_type: "solid_food_feeding",
    occurred_at: "2026-09-11T10:00:00Z",
    ended_at: null,
    local_offset_minutes: 120,
    note: "Ate with family",
    author_label: "Owner",
    last_modified_by_label: "Owner",
    created_at: "2026-09-11T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    revision: 1,
    details: {
      foods: "Banana",
      amount_value: null,
      amount_unit: null,
      reaction_note: "No reaction observed",
    },
  };
  const edited = new FormData();
  edited.set("occurredAt", "2026-09-11T12:00");
  edited.set("foods", "Banana and yoghurt");
  edited.set("reactionNote", "Mild redness");
  edited.set("note", "Tried slowly");
  expect(editedRecordPayload(record, edited)).toMatchObject({
    reaction_note: "Mild redness",
    note: "Tried slowly",
  });
});

it("distinguishes common medication units from custom units and can switch them", () => {
  const createValues = new FormData();
  createValues.set("occurredAt", "2026-09-11T12:00");
  createValues.set("medicineName", "Example medicine");
  createValues.set("medicineAmount", "2.5");
  createValues.set("medicineUnitKind", "custom");
  createValues.set("medicineCustomUnit", "sachet");
  const created = createRecordPayload("medication_administration", "baby-id", createValues);
  expect(created).toMatchObject({ unit_code: null, custom_unit: "sachet" });

  const record: TimelineRecord = {
    id: "record-id",
    baby_id: "baby-id",
    record_type: "medication_administration",
    occurred_at: "2026-09-11T10:00:00Z",
    ended_at: null,
    local_offset_minutes: 120,
    note: "With food",
    author_label: "Owner",
    last_modified_by_label: "Owner",
    created_at: "2026-09-11T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    revision: 1,
    details: {
      medicine_name: "Example medicine",
      amount_value: "2.5",
      unit_code: null,
      custom_unit: "sachet",
      route: null,
    },
  };
  const editValues = new FormData();
  editValues.set("occurredAt", "2026-09-11T12:00");
  editValues.set("medicineName", "Example medicine");
  editValues.set("medicineAmount", "3");
  editValues.set("medicineUnitKind", "mg");
  editValues.set("note", "After food");
  expect(editedRecordPayload(record, editValues)).toMatchObject({
    unit_code: "mg",
    custom_unit: null,
    note: "After food",
  });
});
