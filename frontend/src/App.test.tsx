import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

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
