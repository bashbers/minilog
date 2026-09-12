import { expect, test } from "@playwright/test";

test("the production worker caches a fetched profile picture for offline display", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);

  const projectSlug = testInfo.project.name.replaceAll(/[^a-z0-9-]/gi, "-");
  const pictureUrl = `/api/v1/babies/offline-cache-${projectSlug}/profile-picture?v=1`;
  const onlineBody = await page.evaluate(async (url) => (await fetch(url)).text(), pictureUrl);
  expect(onlineBody).toContain("#216869");
  await expect.poll(() => page.evaluate(async (url) => {
    const cache = await caches.open("minilog-profile-pictures");
    return Boolean(await cache.match(url));
  }, pictureUrl)).toBe(true);

  const cachedResponse = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return { body: await response.text(), status: response.status };
  }, pictureUrl);
  expect(cachedResponse).toEqual({ body: onlineBody, status: 200 });
});
