import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const babyId = "db45be01-9eb8-49ac-b18b-a175656d5c65";
const caregiverId = "f34807e0-a432-47ab-8b33-263c74ef0139";
const secondBabyId = "92a144ff-ddf6-48f1-9858-c28a092144ff";
let unexpectedNetwork: string[] = [];

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
  occurred_at: new Date().toISOString(),
  ended_at: null,
  local_offset_minutes: 120,
  note: "Hungry after the walk",
  author_label: "Alex",
  last_modified_by_label: "Alex",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  revision: 1,
  details: { consumed_ml: 90, offered_ml: 100, contents: "breast_milk" },
};

const noteRecord = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f21",
  record_type: "note",
  occurred_at: new Date(Date.now() - 86_400_000).toISOString(),
  details: { body: "A calm afternoon" },
  note: null,
};

const importedRecord = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f22",
  record_type: "imported_care_record",
  details: { raw_label: "Other", raw_details: "Preserved source detail", raw_line: "Other Preserved source detail" },
  note: null,
};

const measurementRecord = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f23",
  record_type: "measurement",
  details: { kind: "weight", canonical_value: "7.2", canonical_unit: "kg", entered_value: "7.2", entered_unit: "kg" },
  note: null,
};

const oldActiveSleep = {
  ...bottleRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f24",
  record_type: "sleep",
  occurred_at: new Date(Date.now() - 36 * 3_600_000).toISOString(),
  details: {},
  note: null,
};

const futureRecord = {
  ...noteRecord,
  id: "a2601c80-66d5-49fd-87f2-004d7c594f25",
  occurred_at: new Date(Date.now() + 36 * 3_600_000).toISOString(),
  details: { body: "Future care" },
};

async function mockApi(page: Page) {
  let recordDeleted = false;
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
      return json([
        { id: babyId, display_name: "Mila", birth_date: "2026-01-01", due_date: null, has_profile_picture: false, updated_at: 1 },
        { id: secondBabyId, display_name: "Noah", birth_date: "2025-01-01", due_date: null, has_profile_picture: false, updated_at: 1 },
      ]);
    }
    if (path === "/api/v1/care-records/active-status") return json([{ baby_id: secondBabyId, active_types: ["sleep"] }]);
    if (path === "/api/v1/caregivers/current/quick-actions") {
      if (request.method() === "PUT") {
        const payload = request.postDataJSON() as { actions: Array<{ record_type: string; is_hidden: boolean }> };
        return json(payload.actions.map((action, position) => ({ ...action, position })));
      }
      return json(quickActions);
    }
    if (path === "/api/v1/care-records" && request.method() === "GET") {
      if (recordDeleted) return json({ items: [], next_cursor: null });
      if (url.searchParams.get("active_only") === "true") {
        return json({ items: url.searchParams.get("baby_id") === babyId ? [oldActiveSleep] : [], next_cursor: null });
      }
      if (url.searchParams.getAll("record_type").includes("imported_care_record")) {
        return json({ items: [importedRecord], next_cursor: null });
      }
      if (url.searchParams.has("cursor")) {
        return json({ items: [noteRecord], next_cursor: null });
      }
      return json({ items: [bottleRecord, measurementRecord, futureRecord], next_cursor: "older-page" });
    }
    if (path === `/api/v1/care-records/${bottleRecord.id}` && request.method() === "DELETE") {
      recordDeleted = true;
      return route.fulfill({ status: 204, body: "" });
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
  unexpectedNetwork = [];
  const observeUrl = (rawUrl: string) => {
    const url = new URL(rawUrl);
    const localRuntime = url.hostname === "127.0.0.1" && url.port === "4173";
    if (["http:", "https:", "ws:", "wss:"].includes(url.protocol) && !localRuntime) {
      unexpectedNetwork.push(url.origin);
    }
  };
  page.on("request", (request) => observeUrl(request.url()));
  page.on("websocket", (socket) => observeUrl(socket.url()));
  await mockApi(page);
});

test.afterEach(() => {
  expect(unexpectedNetwork).toEqual([]);
});

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
}

test("quick actions and record editing remain accessible on phone and desktop", async ({ page }) => {
  test.setTimeout(45_000);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sleep" })).toBeVisible();
  await expect(page.getByText("Future care")).toHaveCount(0);
  await expectAccessible(page);
  const noahActive = page.getByRole("button", { name: "Noah 1 active" });
  await expect(noahActive).toBeVisible();
  await noahActive.click();
  await expect(noahActive).toBeVisible();
  await expect(noahActive).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Selected Baby").selectOption(babyId);
  await expect(noahActive).toBeVisible();

  const add = page.getByRole("button", { name: "Add care record" });
  const addBox = await add.boundingBox();
  expect(addBox?.width).toBeGreaterThanOrEqual(44);
  expect(addBox?.height).toBeGreaterThanOrEqual(44);
  await add.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Add care record" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Bottle feeding" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Note" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Close" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();

  const bottleArticle = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Bottle feeding" }) });
  const bottleOptions = bottleArticle.getByLabel("Record options");
  await bottleOptions.click();
  await page.getByRole("button", { name: "Edit record" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Bottle feeding" })).toBeVisible();
  await expect(page.getByLabel("Consumed (ml)")).toHaveValue("90");
  await page.keyboard.press("Escape");
  await expect(bottleOptions).toBeFocused();

  await bottleOptions.click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete record" }).click();
  await expect(page.getByRole("heading", { name: "Bottle feeding" })).toHaveCount(0);

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Quick actions" })).toBeVisible();
  const moveDown = page.getByRole("button", { name: "Move Breastfeeding down" });
  const moveBox = await moveDown.boundingBox();
  expect(moveBox?.width).toBeGreaterThanOrEqual(44);
  expect(moveBox?.height).toBeGreaterThanOrEqual(44);
  await moveDown.click();
  await page.getByLabel("Show Bottle feeding").uncheck();
  await page.getByRole("button", { name: "Save quick actions" }).click();
  await expect(page.getByRole("status")).toHaveText("Quick actions saved.");
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  const background = await page.locator("body").evaluate((element) => getComputedStyle(element).backgroundColor);
  const channels = background.match(/\d+/g)?.slice(0, 3).map(Number) ?? [255, 255, 255];
  expect(channels.reduce((sum, channel) => sum + channel, 0)).toBeLessThan(180);
  const reducedAnimationSeconds = await page.evaluate(() => {
    const skeleton = document.createElement("div");
    skeleton.className = "skeleton-list";
    document.body.append(skeleton);
    const duration = Number.parseFloat(getComputedStyle(skeleton).animationDuration);
    skeleton.remove();
    return duration;
  });
  expect(reducedAnimationSeconds).toBeLessThanOrEqual(0.00001);
  await expectAccessible(page);
});

test("History filters every care type and loads an equal-timestamp-safe cursor", async ({ page }) => {
  const requestedUrls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/care-records")) requestedUrls.push(request.url());
  });
  await page.goto("/history");

  await expect(page.getByRole("heading", { name: "Bottle feeding" })).toBeVisible();
  await page.getByRole("button", { name: "Load older" }).click();
  await expect(page.getByRole("article").filter({ hasText: "A calm afternoon" }).getByRole("heading", { name: "Note" })).toBeVisible();

  await page.getByLabel("Care type").selectOption("imported_care_record");
  await expect(page.getByRole("heading", { name: "Imported care record" })).toBeVisible();
  await page.getByLabel("From", { exact: true }).fill("2026-09-01");
  await page.getByLabel("To", { exact: true }).fill("2026-09-10");

  await expect.poll(() => requestedUrls.some((requested) => {
    const url = new URL(requested);
    return url.searchParams.get("cursor") === "older-page";
  })).toBe(true);
  await expectAccessible(page);
  await expect.poll(() => requestedUrls.some((requested) => {
    const url = new URL(requested);
    return url.searchParams.get("record_type") === "imported_care_record"
      && url.searchParams.get("date_from") === "2026-09-01"
      && url.searchParams.get("date_to") === "2026-09-10";
  })).toBe(true);
});

test("synced records stop offering mutations when the device goes offline", async ({ page, context }) => {
  await page.goto("/");
  await expect(page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Bottle feeding" }) }).getByLabel("Record options")).toBeVisible();

  await context.setOffline(true);
  await expect(page.getByLabel("Reconnect to edit or delete").first()).toBeVisible();
  await expect(page.getByLabel("Record options")).toHaveCount(0);
  await expectAccessible(page);
});

test("Trends exposes complete periods and entered measurement facts", async ({ page }) => {
  const requestedUrls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/care-records")) requestedUrls.push(request.url());
  });
  await page.goto("/trends");

  await expect(page.getByRole("button", { name: "Daily" })).toBeVisible();
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "30 days" }).click();
  await expect(page.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Weight" })).toBeVisible();
  await expect(page.getByText("7.2")).toBeVisible();
  await expect.poll(() => requestedUrls.some((requested) => {
    const url = new URL(requested);
    return url.searchParams.get("date_from") !== null
      && url.searchParams.get("date_to") !== null
      && url.searchParams.get("cursor") === "older-page";
  })).toBe(true);
  await expectAccessible(page);
});
