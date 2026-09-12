import { QueryClient } from "@tanstack/react-query";

import { removeMissingBabyQueries } from "./cache";

test("removes every deleted-Baby query family and mixed cache without touching current data", () => {
  const client = new QueryClient();
  const deleted = "deleted-baby";
  const retained = "retained-baby";
  const families = [
    "active-records",
    "history-records",
    "imported-daily-notes",
    "records",
    "today-records",
    "trend-records",
  ];
  for (const family of families) {
    client.setQueryData([family, deleted], "private deleted data");
    client.setQueryData([family, retained], "retained data");
  }
  client.setQueryData(["babies"], [retained]);
  client.setQueryData(["imports"], [
    { baby_id: retained, original_filename: "kept.txt" },
    { baby_id: deleted, original_filename: "private-deleted.txt" },
  ]);
  client.setQueryData(["baby-active-statuses"], [
    { baby_id: deleted, active_types: ["sleep"] },
  ]);
  client.setQueryData(["imports", "unrelated-shape"], [{ baby_id: deleted }]);

  removeMissingBabyQueries(client, [retained]);

  for (const family of families) {
    expect(client.getQueryData([family, deleted])).toBeUndefined();
    expect(client.getQueryData([family, retained])).toBe("retained data");
  }
  expect(client.getQueryData(["babies"])).toEqual([retained]);
  expect(client.getQueryData(["imports"])).toBeUndefined();
  expect(client.getQueryData(["baby-active-statuses"])).toBeUndefined();
  expect(client.getQueryData(["imports", "unrelated-shape"])).toEqual([
    { baby_id: deleted },
  ]);
});

test("keeps mixed caches that only contain current Babies", () => {
  const client = new QueryClient();
  client.setQueryData(["imports"], [{ baby_id: "current", original_filename: "kept.txt" }]);
  client.setQueryData(["baby-active-statuses"], [
    { baby_id: "current", active_types: ["sleep"] },
  ]);

  removeMissingBabyQueries(client, ["current"]);

  expect(client.getQueryData(["imports"])).toBeDefined();
  expect(client.getQueryData(["baby-active-statuses"])).toBeDefined();
});
