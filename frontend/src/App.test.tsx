import {
  MutationObserver,
  QueryClient,
  QueryClientProvider,
  QueryObserver,
} from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App, clearUnauthenticatedClientData } from "./App";

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("shows a self-refreshing maintenance state while the API upgrades", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ detail: "maintenance" }),
    { status: 503, headers: { "Content-Type": "application/json" } },
  )));

  renderApp();

  expect(await screen.findByRole("heading", { name: "Minilog is upgrading" })).toBeVisible();
  expect(screen.getByText(/update automatically/i)).toBeVisible();
});

test("refuses to run against a different API contract version", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    status: "ready",
    api_contract_version: 2,
    schema_revision: "future",
  }), { headers: { "Content-Type": "application/json" } })));

  renderApp();

  expect(await screen.findByRole("heading", {
    name: "Minilog versions do not match",
  })).toBeVisible();
});

test("unauthenticated cleanup clears memory immediately and can retry browser storage", async () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["records", "private-baby"], [{ body: "private care" }]);
  queryClient.setQueryData(["me"], { id: "private-caregiver", display_name: "Caregiver" });
  const mutation = new MutationObserver(queryClient, {
    mutationFn: async (variables: { body: string }) => ({ saved: variables.body }),
  });
  await mutation.mutate({ body: "private pending care" });
  localStorage.setItem("selectedBaby", "private-baby");
  const deleteCache = vi.fn()
    .mockRejectedValueOnce(new Error("Cache Storage temporarily blocked"))
    .mockResolvedValueOnce(true);
  vi.stubGlobal("caches", { delete: deleteCache });

  await expect(clearUnauthenticatedClientData(queryClient)).rejects.toThrow(
    "Browser storage cleanup is incomplete",
  );
  expect(localStorage.getItem("selectedBaby")).toBeNull();
  expect(queryClient.getQueryData(["records", "private-baby"])).toBeUndefined();
  expect(queryClient.getQueryData(["me"])).toBeUndefined();
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);

  await expect(clearUnauthenticatedClientData(queryClient)).resolves.toBeUndefined();
  expect(deleteCache).toHaveBeenCalledTimes(2);
});

test("unauthenticated cleanup aborts delayed private queries before the final purge", async () => {
  const queryClient = new QueryClient();
  let aborted = false;
  let lateWrite = false;
  const inFlight = queryClient.fetchQuery({
    queryKey: ["records", "revoked-baby"],
    queryFn: ({ signal }) => new Promise<string>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        lateWrite = true;
        resolve("private records");
      }, 50);
      signal.addEventListener("abort", () => {
        aborted = true;
        window.clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }),
  }).catch(() => undefined);
  vi.stubGlobal("caches", { delete: vi.fn().mockResolvedValue(true) });

  await vi.waitFor(() => expect(queryClient.isFetching()).toBe(1));
  await expect(clearUnauthenticatedClientData(queryClient)).resolves.toBeUndefined();
  await inFlight;
  await new Promise((resolve) => window.setTimeout(resolve, 60));

  expect(aborted).toBe(true);
  expect(lateWrite).toBe(false);
  expect(queryClient.getQueryData(["records", "revoked-baby"])).toBeUndefined();
});

test("failed browser cleanup still clears the mounted caregiver observer", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const observer = new QueryObserver(queryClient, {
    queryKey: ["me"],
    queryFn: async () => { throw new Error("revoked"); },
  });
  const unsubscribe = observer.subscribe(() => undefined);
  queryClient.setQueryData(["me"], { id: "private-caregiver", display_name: "Caregiver" });
  expect(observer.getCurrentResult().data).toBeDefined();
  vi.stubGlobal("caches", { delete: vi.fn().mockRejectedValue(new Error("blocked")) });

  await expect(clearUnauthenticatedClientData(queryClient)).rejects.toThrow(
    "Browser storage cleanup is incomplete",
  );

  expect(observer.getCurrentResult().data).toBeUndefined();
  unsubscribe();
});
