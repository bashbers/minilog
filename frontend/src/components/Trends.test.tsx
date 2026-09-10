import { render, screen } from "@testing-library/react";

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
    details: { is_wet: true, is_dirty: false },
  };
}

test("shows factual seven-day totals and the medical boundary", () => {
  render(<Trends records={[diaper(1), diaper(25)]} />);

  expect(screen.getByRole("heading", { name: "Diaper changes" })).toBeInTheDocument();
  expect(screen.getByText("Charts summarize what caregivers entered. They do not assess health or development.")).toBeInTheDocument();
});
