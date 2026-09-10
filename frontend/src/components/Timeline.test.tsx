import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { api, ApiError } from "../api/client";
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

afterEach(() => vi.restoreAllMocks());

test("renders a readable care record without interpreting it", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[record]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: "Bottle feeding" })).toBeInTheDocument();
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

test("opens the online editor from record options", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[record]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  fireEvent.click(screen.getByLabelText("Record options"));
  fireEvent.click(screen.getByRole("button", { name: "Edit record" }));

  expect(screen.getByRole("dialog", { name: "Edit Bottle feeding" })).toBeInTheDocument();
  expect(screen.getByLabelText("Consumed (ml)")).toHaveValue(90);
});

test("does not offer edit or delete while offline", () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[record]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  expect(screen.getByLabelText("Reconnect to edit or delete")).toBeInTheDocument();
  expect(screen.queryByLabelText("Record options")).not.toBeInTheDocument();
});

test("shows a stale conflict when deletion loses a revision race", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(api, "deleteRecord").mockRejectedValue(new ApiError(409, "stale_revision"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Timeline records={[record]} babyId={record.baby_id} />
    </QueryClientProvider>,
  );

  fireEvent.click(screen.getByLabelText("Record options"));
  fireEvent.click(screen.getByRole("button", { name: "Delete record" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This record changed on another device and was not deleted.",
  );
});
