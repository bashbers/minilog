import { expect, test, type Page } from "@playwright/test";

const babyId = "db45be01-9eb8-49ac-b18b-a175656d5c65";
const caregiverId = "f34807e0-a432-47ab-8b33-263c74ef0139";

const quickActions = [
  "breastfeeding",
  "bottle_feeding",
  "solid_food_feeding",
  "sleep",
  "diaper_change",
  "pumping",
  "measurement",
  "medication_administration",
  "note",
].map((record_type, position) => ({ record_type, position, is_hidden: false }));

const bottleRecord = {
  id: "a2601c80-66d5-49fd-87f2-004d7c594f20",
  baby_id: babyId,
  record_type: "bottle_feeding",
  occurred_at: "2026-09-10T10:00:00Z",
  ended_at: null,
  local_offset_minutes: 120,
  note: "Hungry after the walk",
  author_label: "Alex",
  last_modified_by_label: "Alex",
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  revision: 1,
  details: { consumed_ml: 90, offered_ml: 100, contents: "breast_milk" },
};

const noteRecord = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f21",
  record_type: "note",
  occurred_at: "2026-09-09T10:00:00Z",
  details: { body: "A calm afternoon" },
  note: null,
};

const importedRecord = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f22",
  record_type: "imported_care_record",
  details: { raw_label: "Other", raw_details: "Preserved source detail" },
  note: null,
};

async function mockApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (path === "/api/v1/setup") return json({ setup_required: false });
    if (path === "/api/v1/sessions/current") {
      return json({ id: caregiverId, username_display: "alex", display_name: "Alex", role: "owner" });
    }
    if (path === "/api/v1/babies") {
      return json([{ id: babyId, display_name: "Mila", birth_date: "2026-01-01", due_date: null, has_profile_picture: false, updated_at: 1 }]);
    }
    if (path === "/api/v1/caregivers/current/quick-actions") {
      if (request.method() === "PUT") {
        const payload = request.postDataJSON() as { actions: Array<{ record_type: string; is_hidden: boolean }> };
        return json(payload.actions.map((action, position) => ({ ...action, position })));
      }
      return json(quickActions);
    }
    if (path === "/api/v1/care-records" && request.method() === "GET") {
      if (url.searchParams.getAll("record_type").includes("imported_care_record")) {
        return json({ items: [importedRecord], next_cursor: null });
      }
      if (url.searchParams.has("cursor")) {
        return json({ items: [noteRecord], next_cursor: null });
      }
      return json({ items: [bottleRecord], next_cursor: "older-page" });
    }
    if (path === "/api/v1/sync") {
      return json({ changes: [], next_cursor: 0, oldest_valid_cursor: 0 });
    }
    if (path === "/api/v1/imports/piyolog/daily-notes") return json([]);
    if (path === "/api/v1/sessions/devices") return json([]);
    if (path === "/api/v1/caregivers") {
      return json([{ id: caregiverId, username_display: "alex", display_name: "Alex", role: "owner" }]);
    }
    if (path === "/api/v1/imports/piyolog") return json([]);
    if (path === "/api/v1/household") {
      return json({ id: "ddf6ba4b-0d29-48f1-9858-c28a092144ff", display_name: "Home", time_zone: "Europe/Amsterdam", locale: "en", clock_format: "24h", measurement_system: "metric" });
    }
    throw new Error(`Unhandled API request: ${request.method()} ${request.url()}`);
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("quick actions and record editing remain accessible on phone and desktop", async ({ page }) => {
  const externalOrigins = new Set<string>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && url.origin !== "http://127.0.0.1:4173") {
      externalOrigins.add(url.origin);
    }
  });
  await page.goto("/");

  const add = page.getByRole("button", { name: "Add care record" });
  const addBox = await add.boundingBox();
  expect(addBox?.width).toBeGreaterThanOrEqual(44);
  expect(addBox?.height).toBeGreaterThanOrEqual(44);
  await add.click();
  await expect(page.getByRole("dialog", { name: "Add care record" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Bottle feeding" })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByLabel("Record options").click();
  await page.getByRole("button", { name: "Edit record" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Bottle feeding" })).toBeVisible();
  await expect(page.getByLabel("Consumed (ml)")).toHaveValue("90");
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Quick actions" })).toBeVisible();
  const moveDown = page.getByRole("button", { name: "Move Breastfeed down" });
  const moveBox = await moveDown.boundingBox();
  expect(moveBox?.width).toBeGreaterThanOrEqual(44);
  expect(moveBox?.height).toBeGreaterThanOrEqual(44);
  await moveDown.click();
  await page.getByLabel("Show Bottle feeding").uncheck();
  await page.getByRole("button", { name: "Save quick actions" }).click();
  await expect(page.getByRole("status")).toHaveText("Quick actions saved.");
  expect([...externalOrigins]).toEqual([]);
});

test("History filters every care type and loads an equal-timestamp-safe cursor", async ({ page }) => {
  const requestedUrls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/care-records")) requestedUrls.push(request.url());
  });
  await page.goto("/history");

  await expect(page.getByRole("heading", { name: "Bottle feeding" })).toBeVisible();
  await page.getByRole("button", { name: "Load older" }).click();
  await expect(page.getByRole("heading", { name: "Note" })).toBeVisible();

  await page.getByLabel("Care type").selectOption("imported_care_record");
  await expect(page.getByRole("heading", { name: "Imported record" })).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill("2026-09-01");
  await page.getByLabel("To", { exact: true }).fill("2026-09-10");

  await expect.poll(() => requestedUrls.some((requested) => {
    const url = new URL(requested);
    return url.searchParams.get("cursor") === "older-page";
  })).toBe(true);
  await expect.poll(() => requestedUrls.some((requested) => {
    const url = new URL(requested);
    return url.searchParams.get("record_type") === "imported_care_record"
      && url.searchParams.get("date_from") === "2026-09-01"
      && url.searchParams.get("date_to") === "2026-09-10";
  })).toBe(true);
});

test("synced records stop offering mutations when the device goes offline", async ({ page, context }) => {
  await page.goto("/");
  await expect(page.getByLabel("Record options")).toBeVisible();

  await context.setOffline(true);
  await expect(page.getByLabel("Reconnect to edit or delete")).toBeVisible();
  await expect(page.getByLabel("Record options")).toHaveCount(0);
});
