import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import { homeFilters, homeParams } from "../src/shared/home-transport";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function property(request: APIRequestContext, name: string) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: name,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "single_family_home",
      ownerships: [{ ownerKind: "local_operator" }],
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schemas["PropertyMutationResponse"];
}

test("Home filters normalize calendar bounds, scope and horizon from server UTC", () => {
  const defaults = homeFilters(
    new URLSearchParams("horizonDays=8&fromOn=2028-02-30&propertyId=bad"),
    "2028-02-29T23:30:00Z",
  );
  expect(defaults).toEqual({
    propertyId: undefined,
    horizonDays: 7,
    fromOn: "2028-02-01",
    throughOn: "2028-02-29",
  });
  const id = "ABCDEFAB-1234-1234-1234-123456789ABC";
  const selected = homeFilters(
    new URLSearchParams({
      propertyId: id,
      horizonDays: "90",
      fromOn: "2028-12-01",
      throughOn: "2028-12-31",
    }),
    "2028-02-29T23:30:00Z",
  );
  expect(selected.propertyId).toBe(id.toLowerCase());
  expect(homeParams(selected).get("horizonDays")).toBe("90");
  expect(
    homeFilters(
      new URLSearchParams("fromOn=2028-03-02&throughOn=2028-03-01"),
      "2028-12-31T23:59:00Z",
    ).throughOn,
  ).toBe("2028-12-31");
});

test("live attention starts independently, defaults use server month and navigation stays usable", async ({
  page,
}) => {
  let release = () => {};
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fullRequests: URL[] = [],
    liveRequests: URL[] = [];
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const bootstrap = (await response.json()) as Schemas["BootstrapResponse"];
    await route.fulfill({ json: { ...bootstrap, serverTimeUtc: "2028-02-29T23:30:00Z" } });
  });
  await page.route("**/api/operator/home?*", async (route) => {
    fullRequests.push(new URL(route.request().url()));
    await hold;
    await route.abort();
  });
  await page.route("**/api/operator/home/attention?*", async (route) => {
    liveRequests.push(new URL(route.request().url()));
    await route.continue();
  });
  try {
    await page.goto("/home");
    await expect(page.getByRole("region", { name: "Live Home attention" })).toContainText("As of");
    await expect(page.getByText("Loading Home summary…", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2028-02-01");
    await expect(page.getByLabel("Money through", { exact: true })).toHaveValue("2028-02-29");
    expect(fullRequests).toHaveLength(1);
    expect(liveRequests).toHaveLength(1);
    expect(fullRequests[0].searchParams.get("fromOn")).toBe("2028-02-01");
    expect(fullRequests[0].searchParams.get("throughOn")).toBe("2028-02-29");
    expect(liveRequests[0].searchParams.has("fromOn")).toBe(false);
    await page.getByRole("link", { name: "Task deadlines and reminders" }).click();
    await expect(page).toHaveURL(/\/tasks$/);
  } finally {
    release();
  }
});

test("scope changes cancel old reads and discard a late summary", async ({ page, request }) => {
  const first = await property(request, `Home first ${crypto.randomUUID()}`);
  const second = await property(request, `Home second ${crypto.randomUUID()}`);
  let release = () => {};
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldStarted = false,
    oldFinished = false,
    latestCapture = "";
  const cancelled: string[] = [];
  page.on("requestfailed", (pending) => {
    cancelled.push(pending.url());
  });
  await page.route("**/api/operator/home?*", async (route) => {
    const response = await route.fetch();
    const result = (await response.json()) as Schemas["HomeResponse"];
    const old = new URL(route.request().url()).searchParams.get("propertyId") === first.id;
    if (old) {
      oldStarted = true;
      await hold;
    } else latestCapture = result.money.capture.asOf;
    await route.fulfill({ json: result });
    if (old) oldFinished = true;
  });
  try {
    await page.goto(`/home?propertyId=${first.id}`);
    await expect.poll(() => oldStarted).toBe(true);
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await page.getByLabel("Property ID", { exact: false }).fill(second.id);
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect.poll(() => latestCapture).not.toBe("");
    const summary = page.getByRole("region", { name: "Recorded money", exact: true });
    await expect(summary.locator(".home-capture time")).toHaveAttribute("datetime", latestCapture);
    await expect.poll(() => cancelled.some((url) => url.includes(first.id))).toBe(true);
    release();
    await expect.poll(() => oldFinished).toBe(true);
    await expect(summary.locator(".home-capture time")).toHaveAttribute("datetime", latestCapture);
    await expect(page.getByLabel("Property ID", { exact: false })).toHaveValue(second.id);
  } finally {
    release();
  }
});

test("missing readiness suppresses Home reads and runtime mismatches withhold results", async ({
  page,
}) => {
  let homeReads = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/operator/home")) homeReads += 1;
  });
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const bootstrap = (await response.json()) as Schemas["BootstrapResponse"];
    await route.fulfill({
      json: {
        ...bootstrap,
        capabilities: bootstrap.capabilities.filter((item) => item !== "operator.home"),
      },
    });
  });
  await page.goto("/home");
  await expect(
    page.getByText("The combined Home work queue and calendar are not available yet.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(homeReads).toBe(0);
  await page.unroute("**/api/operator/bootstrap");
  await page.route("**/api/operator/home?*", async (route) => {
    const response = await route.fetch();
    const result = (await response.json()) as Schemas["HomeResponse"];
    await route.fulfill({ json: { ...result, runtimeEpoch: crypto.randomUUID() } });
  });
  await page.reload();
  await expect(page.getByRole("region", { name: "Home summary" })).toContainText(
    "no longer matches",
  );
  await expect(page.getByRole("region", { name: "Live Home attention" })).toContainText("As of");
});

test("money and horizon changes restart only full Home while retaining live capture", async ({
  page,
}) => {
  let fullReads = 0,
    liveReads = 0;
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path === "/api/operator/home") fullReads += 1;
    if (path === "/api/operator/home/attention") liveReads += 1;
  });
  await page.goto("/home");
  await expect(
    page.getByRole("region", { name: "Recorded money", exact: true }).locator(".home-capture time"),
  ).toBeVisible();
  const live = page.getByRole("region", { name: "Live Home attention" });
  await expect(live).toContainText("As of");
  const capture = await live.textContent();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByLabel("Money from", { exact: true }).fill("2026-01-01");
  await page.getByLabel("Money through", { exact: true }).fill("2026-01-31");
  await page.getByLabel("Upcoming horizon").selectOption("30");
  const refreshed = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/operator/home" && url.searchParams.get("horizonDays") === "30";
  });
  await page.getByRole("button", { name: "Apply filters" }).click();
  expect((await refreshed).ok()).toBe(true);
  await expect(page).toHaveURL(/horizonDays=30.*fromOn=2026-01-01.*throughOn=2026-01-31/);
  await expect(
    page.getByRole("region", { name: "Recorded money", exact: true }).locator(".home-capture time"),
  ).toBeVisible();
  expect(fullReads).toBe(2);
  expect(liveReads).toBe(1);
  await expect(live).toHaveText(capture ?? "");
});
