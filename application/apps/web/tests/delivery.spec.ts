import { expect, test } from "@playwright/test";

test("wheel assets mount React on direct and deep links using the generated client", async ({
  page,
}) => {
  const errors: string[] = [];
  const apiRequests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });
  for (const path of [
    "/home",
    "/properties/00000000-0000-4000-8000-000000000001/units",
    "/settings/workspace",
  ]) {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
    expect(response?.headers()["content-security-policy"]).toContain("script-src 'self'");
    expect(response?.headers()["cache-control"]).toBe("no-store");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Easy Property Management");
    await expect(page.getByRole("status")).toHaveText("Local workspace connected.");
    await expect(page.getByRole("button")).toHaveCount(0);
  }
  expect(apiRequests.length).toBeGreaterThanOrEqual(3);
  expect(apiRequests.every((url) => url === "http://127.0.0.1:18744/api/operator/bootstrap")).toBe(
    true,
  );
  expect(errors).toEqual([]);
});

test("unavailable workspace still loads real compiled assets and reports readiness", async ({
  page,
}) => {
  await page.goto("http://127.0.0.1:18745/home");
  await expect(page.getByRole("status")).toHaveText("Local workspace unavailable.");
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("API and asset failures never become HTML; compiled assets have immutable caching", async ({
  page,
  request,
}) => {
  await page.goto("/home");
  const script = await page.locator("script[src]").getAttribute("src");
  expect(script).toMatch(/^\/assets\/index-[0-9a-f]{8,64}\.js$/);
  const asset = await request.get(script ?? "");
  expect(asset.status()).toBe(200);
  expect(asset.headers()["cache-control"]).toContain("immutable");
  const head = await request.head("/properties", { headers: { Accept: "text/html" } });
  expect(head.status()).toBe(200);
  expect(await head.body()).toHaveLength(0);
  for (const path of [
    "/assets/missing.js",
    "/assets/index.js.map",
    "/api/missing",
    "/intake/review",
  ]) {
    const response = await request.get(path, { headers: { Accept: "text/html" } });
    expect(response.status()).toBe(404);
    expect(response.headers()["content-type"]).not.toContain("text/html");
  }
  for (const path of ["/openapi.json", "/docs", "/redoc", "/health"]) {
    expect((await request.get(path)).status()).toBe(200);
  }
});
