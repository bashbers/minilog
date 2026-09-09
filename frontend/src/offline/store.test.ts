import { clearLocalData, pendingForBaby, queueCreation } from "./store";

test("persists offline creations by baby until synchronization", async () => {
  await clearLocalData();
  const babyId = crypto.randomUUID();
  const mutationId = crypto.randomUUID();
  await queueCreation(
    {
      id: crypto.randomUUID(),
      baby_id: babyId,
      record_type: "note",
      occurred_at: new Date().toISOString(),
      local_offset_minutes: 0,
      body: "Offline note",
    },
    mutationId,
  );

  const pending = await pendingForBaby(babyId);
  expect(pending).toHaveLength(1);
  expect(pending[0].mutationId).toBe(mutationId);

  await clearLocalData();
  expect(await pendingForBaby(babyId)).toEqual([]);
});

