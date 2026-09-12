import { QueryClient } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";

import { finishPermanentDeletion } from "./SettingsPage";

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
