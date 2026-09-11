import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { TimelineRecord } from "../api/types";
import { Trends } from "./Trends";

function diaper(hoursAgo: number): TimelineRecord {
  const time = new Date(Date.now() - hoursAgo * 3_600_000).toISOString();
  return {
    id: crypto.randomUUID(),
    baby_id: crypto.randomUUID(),
    record_type: "diaper_change",
    occurred_at: time,
    ended_at: null,
    local_offset_minutes: 0,
    note: null,
    author_label: "Caregiver",
    last_modified_by_label: "Caregiver",
    created_at: time,
    updated_at: time,
    revision: 1,
    details: { is_wet: true, is_dirty: false, stool_colour: null, stool_consistency: null },
  };
}

test("shows factual daily, seven-day, and thirty-day controls with the medical boundary", () => {
  const onDaysChange = vi.fn();
  render(<Trends records={[diaper(1), diaper(25)]} timeZone="Europe/Amsterdam" days={7} onDaysChange={onDaysChange} />);

  expect(screen.getByRole("heading", { name: "Diaper changes" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "30 days" }));
  expect(onDaysChange).toHaveBeenCalledWith(30);
  expect(screen.getByText("Charts summarize what caregivers entered. They do not assess health or development.")).toBeInTheDocument();
});

test("charts entered measurement facts by kind and unit", () => {
  const time = new Date().toISOString();
  const measurement: TimelineRecord = {
    id: crypto.randomUUID(),
    baby_id: crypto.randomUUID(),
    record_type: "measurement",
    occurred_at: time,
    ended_at: null,
    local_offset_minutes: 0,
    note: null,
    author_label: "Caregiver",
    last_modified_by_label: "Caregiver",
    created_at: time,
    updated_at: time,
    revision: 1,
    details: {
      kind: "weight",
      canonical_value: "7.2",
      canonical_unit: "kg",
      entered_value: "7.2",
      entered_unit: "kg",
    },
  };
  render(<Trends records={[measurement]} timeZone="UTC" days={1} onDaysChange={() => undefined} />);

  expect(screen.getByRole("heading", { name: "Weight" })).toBeInTheDocument();
  expect(screen.getByText("7.2")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Measurements" })).not.toBeInTheDocument();
});
