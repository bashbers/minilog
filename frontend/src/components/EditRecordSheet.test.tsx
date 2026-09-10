import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { api, ApiError } from "../api/client";
import type { TimelineRecord } from "../api/types";
import { EditRecordSheet } from "./EditRecordSheet";

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
  revision: 3,
  details: { consumed_ml: 90, offered_ml: 100, contents: "breast_milk" },
};

afterEach(() => vi.restoreAllMocks());

test("keeps the editor open and explains a stale revision conflict", async () => {
  const update = vi.spyOn(api, "updateRecord").mockRejectedValue(
    new ApiError(409, "stale_revision"),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <EditRecordSheet record={record} onClose={vi.fn()} />
    </QueryClientProvider>,
  );

  fireEvent.change(screen.getByLabelText("Consumed (ml)"), { target: { value: "95" } });
  fireEvent.submit(screen.getByRole("button", { name: "Save changes" }).closest("form")!);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This record changed on another device",
  );
  expect(update).toHaveBeenCalledWith(
    record.id,
    3,
    expect.objectContaining({
      record_type: "bottle_feeding",
      consumed_ml: 95,
      offered_ml: 100,
      contents: "breast_milk",
      local_offset_minutes: 120,
    }),
  );
});
