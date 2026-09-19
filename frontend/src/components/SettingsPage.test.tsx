import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { finishPermanentDeletion, SettingsPage } from "./SettingsPage";

test("finishes permanent-deletion cleanup even when browser storage rejects it", async () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["records", "private-baby"], [{ body: "private" }]);
  localStorage.setItem("selectedBaby", "private-baby");
  const cleanup = vi.fn().mockRejectedValue(new Error("IndexedDB unavailable"));
  const navigate = vi.fn();

  await expect(
    finishPermanentDeletion(cleanup, queryClient, navigate),
  ).resolves.toBeUndefined();

  expect(cleanup).toHaveBeenCalledOnce();
  expect(queryClient.getQueryCache().getAll()).toEqual([]);
  expect(localStorage.getItem("selectedBaby")).toBeNull();
  expect(navigate).toHaveBeenCalledOnce();
});

test("owners can manage the household and Baby identities", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  queryClient.setQueryData(["household"], {
    id: crypto.randomUUID(),
    display_name: "Home",
    time_zone: "Europe/Amsterdam",
    locale: "en",
    clock_format: "24h",
    measurement_system: "metric",
  });
  queryClient.setQueryData(["quick-actions"], []);
  queryClient.setQueryData(["device-sessions"], []);
  queryClient.setQueryData(["caregivers"], []);
  queryClient.setQueryData(["imports"], []);
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage
        baby={{
          id: crypto.randomUUID(),
          display_name: "Mila",
          birth_date: "2026-01-01",
          due_date: null,
          has_profile_picture: false,
          updated_at: Date.now(),
        }}
        caregiver={{
          id: crypto.randomUUID(),
          username_display: "owner",
          display_name: "Owner",
          role: "owner",
          is_active: true,
          identity_erased_at: null,
        }}
      />
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: "Household" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Babies" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save Mila" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Baby" })).toBeInTheDocument();
});
