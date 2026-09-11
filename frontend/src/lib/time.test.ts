import { expect, test } from "vitest";

import { dateKeyInTimeZone, shiftDateKey } from "./time";

test("uses the Household time zone for calendar dates", () => {
  const instant = "2026-09-10T22:30:00Z";
  expect(dateKeyInTimeZone(instant, "Europe/Amsterdam")).toBe("2026-09-11");
  expect(dateKeyInTimeZone(instant, "America/New_York")).toBe("2026-09-10");
});

test("shifts date keys without device-time-zone arithmetic", () => {
  expect(shiftDateKey("2026-03-01", -1)).toBe("2026-02-28");
  expect(shiftDateKey("2026-12-31", 1)).toBe("2027-01-01");
});
