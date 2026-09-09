import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import type { TimelineRecord } from "../api/types";
import { Timeline } from "./Timeline";

const record: TimelineRecord = {
  id: "a2601c80-66d5-49fd-87f2-004d7c594f20",
  baby_id: "db45be01-9eb8-49ac-b18b-a175656d5c65",
  record_type: "bottle_feeding",
  occurred_at: "2026-09-09T10:00:00Z",
  ended_at: null,
  local_offset_minutes: 120,
  note: "Hungry after the walk",
  author_label: "Alex",
  last_modified_by_label: "Alex",
  created_at: "2026-09-09T10:00:00Z",
  updated_at: "2026-09-09T10:00:00Z",
  revision: 1,
  details: { consumed_ml: 90, contents: "breast_milk" },
};

test("renders a readable care record without interpreting it", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[record]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: "Bottle" })).toBeInTheDocument();
  expect(screen.getByText("90 ml · breast milk")).toBeInTheDocument();
  expect(screen.getByText("Hungry after the walk")).toBeInTheDocument();
  expect(screen.getByText("by Alex")).toBeInTheDocument();
});

test("marks offline creations without exposing edit controls", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[{ ...record, queued: true }]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  expect(screen.getByLabelText("Waiting to sync")).toBeInTheDocument();
  expect(screen.queryByLabelText("Record options")).not.toBeInTheDocument();
});

