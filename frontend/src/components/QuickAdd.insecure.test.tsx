import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { api, ApiError } from "../api/client";
import { clearLocalData, pendingForBaby } from "../offline/store";
import { QuickAdd } from "./QuickAdd";

afterEach(async () => {
  vi.unstubAllGlobals();
  await clearLocalData();
});

test("saves from a LAN HTTP origin where crypto.randomUUID is unavailable", async () => {
  let randomCall = 6;
  vi.stubGlobal("crypto", {
    getRandomValues: (bytes: Uint8Array) => {
      randomCall += 1;
      bytes.fill(randomCall);
      return bytes;
    },
  });
  vi.spyOn(api, "quickActions").mockResolvedValue([
    { record_type: "note", position: 0, is_hidden: false },
  ]);
  const create = vi.spyOn(api, "createRecord").mockResolvedValue({} as never);
  const close = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <QuickAdd babyId="baby-id" onClose={close} />
    </QueryClientProvider>,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Note" }));
  fireEvent.change(screen.getByLabelText("Note"), { target: { value: "LAN save" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  const [payload, mutationId] = create.mock.calls[0];
  const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  expect(payload.id).toMatch(uuidV4);
  expect(mutationId).toMatch(uuidV4);
  expect(payload.id).not.toBe(mutationId);
  expect(close).toHaveBeenCalledOnce();
  expect(screen.queryByText(/Could not save/)).not.toBeInTheDocument();
});

test("closes with the creation safely queued when startup maintenance returns 503", async () => {
  vi.spyOn(api, "quickActions").mockResolvedValue([
    { record_type: "note", position: 0, is_hidden: false },
  ]);
  vi.spyOn(api, "createRecord").mockRejectedValue(new ApiError(503, "maintenance"));
  const close = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <QuickAdd babyId="baby-id" onClose={close} />
    </QueryClientProvider>,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Note" }));
  fireEvent.change(screen.getByLabelText("Note"), { target: { value: "During upgrade" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(await pendingForBaby("baby-id")).toEqual([
    expect.objectContaining({ status: "queued" }),
  ]);
});
