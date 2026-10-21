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
    await expect(page.getByRole("region", { name: "Home action list" })).toContainText("As of");
    await expect(page.getByText("Loading Home summary…", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2028-02-01");
    await expect(page.getByLabel("Money through", { exact: true })).toHaveValue("2028-02-29");
    expect(fullRequests).toHaveLength(1);
    expect(liveRequests).toHaveLength(1);
    expect(fullRequests[0].searchParams.get("fromOn")).toBe("2028-02-01");
    expect(fullRequests[0].searchParams.get("throughOn")).toBe("2028-02-29");
    expect(liveRequests[0].searchParams.has("fromOn")).toBe(false);
    await page
      .getByRole("navigation", { name: "Primary navigation", exact: true })
      .getByRole("link", { name: "Properties", exact: true })
      .click();
    await expect(page).toHaveURL(/\/properties$/);
    await expect(page.getByRole("heading", { name: "Properties", exact: true })).toBeVisible();
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
    await page
      .getByRole("combobox", { name: "Property", exact: true })
      .selectOption({ label: second.displayName });
    await expect.poll(() => latestCapture).not.toBe("");
    const summary = page.getByRole("region", { name: "Recorded money", exact: true });
    await expect(summary.locator(".home-capture time")).toHaveAttribute("datetime", latestCapture);
    await expect.poll(() => cancelled.some((url) => url.includes(first.id))).toBe(true);
    release();
    await expect.poll(() => oldFinished).toBe(true);
    await expect(summary.locator(".home-capture time")).toHaveAttribute("datetime", latestCapture);
    await expect(page.getByRole("combobox", { name: "Property", exact: true })).toHaveValue(
      second.id,
    );
    await expect(page.locator(".home-scope")).toContainText(`Scope: ${second.displayName}.`);
    await expect(page.locator(".home-scope")).not.toContainText(second.id);
  } finally {
    release();
  }
});

test("Home property dropdown loads bounded pages automatically and filters clear together", async ({
  page,
  request,
}) => {
  const first = await property(request, `Picker first ${crypto.randomUUID()}`);
  const second = await property(request, `Picker archived ${crypto.randomUUID()}`);
  const excluded = await property(request, `No Home items ${crypto.randomUUID()}`);
  const calendarOnly = await property(request, `Calendar only ${crypto.randomUUID()}`);
  const reviewOnly = await property(request, `Review only ${crypto.randomUUID()}`);
  const upcomingOnly = await property(request, `Upcoming only ${crypto.randomUUID()}`);
  const taskResponse = await request.post("/api/tasks", {
    data: {
      title: "Picker task",
      relatedEntityType: "property",
      relatedEntityId: first.id,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(taskResponse.ok()).toBe(true);
  const templateResponse = await request.get(
    `/api/operator/home/items?collection=needs_action&propertyId=${first.id}&horizonDays=90&limit=100`,
  );
  const template = (await templateResponse.json()) as Schemas["CollectionResponse"];
  if (template.result.status !== "available") throw new Error("Task fixture unavailable.");
  const task = template.result.items[0];
  const selections: URL[] = [];
  await page.route("**/api/operator/home/items?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("propertyId") || url.searchParams.get("limit") !== "100")
      return route.continue();
    selections.push(url);
    const collection = url.searchParams.get("collection") as Schemas["HomeItem"]["collection"];
    const horizonDays = Number(url.searchParams.get("horizonDays"));
    const later = url.searchParams.has("cursor");
    const other =
      collection === "appointments"
        ? calendarOnly
        : collection === "information_review"
          ? reviewOnly
          : collection === "upcoming" && horizonDays === 90
            ? upcomingOnly
            : collection === "waiting"
              ? first
              : undefined;
    await route.fulfill({
      json: {
        ...template,
        scope: { kind: "portfolio", propertyId: null },
        result: {
          ...template.result,
          collection,
          viewAllTarget: {
            collection,
            horizonDays,
            scope: { kind: "portfolio", propertyId: null },
          },
          items:
            collection === "needs_action"
              ? [
                  {
                    ...task,
                    key: later ? "picker-second" : task.key,
                    propertyId: later ? second.id : first.id,
                    propertyName: later ? second.displayName : first.displayName,
                    propertyArchived: later,
                  },
                ]
              : other
                ? [
                    {
                      ...task,
                      key: `${collection}:${other.id}`,
                      collection,
                      propertyId: other.id,
                      propertyName: other.displayName,
                      propertyArchived: false,
                    },
                  ]
                : [],
          matchingTotal: collection === "needs_action" ? 2 : other ? 1 : 0,
          nextCursor: collection === "needs_action" && !later ? "picker-next-page" : null,
        },
      },
    });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(
    `/home?propertyId=${first.id}&horizonDays=90&fromOn=2020-01-01&throughOn=2020-01-31`,
  );
  await expect(page.locator(".home-scope")).toContainText(first.displayName);
  expect(selections).toHaveLength(0);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const picker = page.getByRole("combobox", { name: "Property", exact: true });
  await expect(picker.getByRole("option", { name: first.displayName, exact: true })).toHaveCount(1);
  await expect(
    picker.getByRole("option", { name: `${second.displayName} · Archived`, exact: true }),
  ).toHaveCount(1);
  await expect(picker).toHaveValue(first.id);
  for (const property of [calendarOnly, reviewOnly, upcomingOnly]) {
    await expect(
      picker.getByRole("option", { name: property.displayName, exact: true }),
    ).toHaveCount(1);
  }
  await expect(picker.getByRole("option", { name: excluded.displayName, exact: true })).toHaveCount(
    0,
  );
  await expect(page.locator('label[for="' + (await picker.getAttribute("id")) + '"]')).toHaveClass(
    "ui-sr-only",
  );
  await picker.selectOption(upcomingOnly.id);
  await page.getByLabel("Upcoming horizon").selectOption("7");
  await expect(picker.locator("option:checked")).toHaveText(
    `${upcomingOnly.displayName} · No Home items`,
  );
  await page.getByLabel("Upcoming horizon").selectOption("30");
  await expect(page).toHaveURL(new RegExp(`propertyId=${upcomingOnly.id}.*horizonDays=30`));
  await page.getByLabel("Upcoming horizon").selectOption("90");
  await expect(
    picker.getByRole("option", { name: upcomingOnly.displayName, exact: true }),
  ).toHaveCount(1);
  await picker.selectOption(second.id);
  await expect(page.locator(".home-scope")).toContainText(second.displayName);
  await expect(page.locator(".home-scope")).not.toContainText(second.id);
  await expect(page.getByRole("searchbox", { name: "Find a property" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next properties", exact: true })).toHaveCount(0);
  const controls = [
    picker,
    page.getByLabel("Upcoming horizon"),
    page.getByLabel("Money from"),
    page.getByLabel("Money through"),
    page.getByRole("button", { name: "Clear filters", exact: true }),
  ];
  const boxes = await Promise.all(controls.map((control) => control.boundingBox()));
  expect(boxes.every((box) => box !== null)).toBe(true);
  const bottoms = boxes.map((box) => box!.y + box!.height);
  expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThan(2);
  const bootstrap = await request.get("/api/operator/bootstrap");
  const { serverTimeUtc } = (await bootstrap.json()) as Schemas["BootstrapResponse"];
  const defaults = homeFilters(new URLSearchParams(), serverTimeUtc);
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page.locator(".home-scope")).toContainText("Scope: All properties.");
  await expect(page).not.toHaveURL(/propertyId=/);
  await expect(page.getByLabel("Upcoming horizon")).toHaveValue("7");
  await expect(page.getByLabel("Money from")).toHaveValue(defaults.fromOn);
  await expect(page.getByLabel("Money through")).toHaveValue(defaults.throughOn);
  await expect(
    picker.getByRole("option", { name: upcomingOnly.displayName, exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Clear filters", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(
    selections.every(
      (url) => url.searchParams.get("limit") === "100" && !url.searchParams.has("propertyId"),
    ),
  ).toBe(true);
  expect(new Set(selections.map((url) => url.searchParams.get("collection")))).toEqual(
    new Set(["needs_action", "waiting", "upcoming", "appointments", "information_review"]),
  );
  expect(selections.some((url) => url.searchParams.get("horizonDays") === "90")).toBe(true);
  expect(selections.some((url) => url.searchParams.get("horizonDays") === "7")).toBe(true);
  expect(selections.some((url) => url.searchParams.get("cursor") === "picker-next-page")).toBe(
    true,
  );
  await page.unrouteAll({ behavior: "wait" });
});

test("Home property choices do not use partial lists when a source fails and can be retried", async ({
  page,
  request,
}) => {
  const selected = await property(request, `Retain selected scope ${crypto.randomUUID()}`);
  let fail = true;
  await page.route("**/api/operator/home/items?*", (route) => {
    const url = new URL(route.request().url());
    return fail &&
      !url.searchParams.has("propertyId") &&
      url.searchParams.get("limit") === "100" &&
      url.searchParams.get("collection") === "waiting"
      ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
      : route.continue();
  });
  await page.goto(`/home?propertyId=${selected.id}`);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const picker = page.getByRole("combobox", { name: "Property", exact: true });
  await expect(
    page.getByText("Property choices unavailable. Try again.", { exact: true }),
  ).toBeVisible();
  await expect(picker).toHaveValue(selected.id);
  await expect(page.locator(".home-scope")).toContainText(selected.displayName);
  await expect(
    page.getByText("No properties have Home items for this horizon.", { exact: true }),
  ).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Retry properties", exact: true }).click();
  await expect(
    page.getByText("Property choices unavailable. Try again.", { exact: true }),
  ).toHaveCount(0);
  await expect(picker).toHaveValue(selected.id);
  await page.unrouteAll({ behavior: "wait" });
});

test("unavailable property names never disclose IDs or silently widen Home scope", async ({
  page,
  request,
}) => {
  const selected = await property(request, `Unavailable picker ${crypto.randomUUID()}`);
  await page.route(`**/api/properties/${selected.id}`, (route) =>
    route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
  );
  await page.goto(`/home?propertyId=${selected.id}`);
  await expect(page.locator(".home-scope")).toContainText("Selected property (name unavailable)");
  await expect(page.locator(".home-scope")).not.toContainText(selected.id);
  await expect(page).toHaveURL(new RegExp(`propertyId=${selected.id}`));
});

test("missing readiness suppresses Home reads and runtime mismatches withhold results", async ({
  page,
  request,
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
  const bootstrap = (await (
    await request.get("/api/operator/bootstrap")
  ).json()) as Schemas["BootstrapResponse"];
  const filters = homeParams(homeFilters(new URLSearchParams(), bootstrap.serverTimeUtc));
  const response = await request.get(`/api/operator/home?${filters}`);
  expect(response.ok(), await response.text()).toBe(true);
  const result = (await response.json()) as Schemas["HomeResponse"];
  await page.route("**/api/operator/home?*", async (route) => {
    await route.fulfill({ json: { ...result, runtimeEpoch: crypto.randomUUID() } });
  });
  await page.reload();
  await expect(page.getByRole("region", { name: "Home summary" })).toContainText(
    "no longer matches",
  );
  await expect(page.getByRole("region", { name: "Home action list" })).toContainText("As of");
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
  const live = page.getByRole("region", { name: "Home action list" });
  await expect(live).toContainText("As of");
  const capture = await live.textContent();
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByLabel("Money from", { exact: true }).fill("2026-01-01");
  await page.getByLabel("Money through", { exact: true }).fill("2026-01-31");
  const refreshed = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/operator/home" && url.searchParams.get("horizonDays") === "30";
  });
  await page.getByLabel("Upcoming horizon").selectOption("30");
  expect((await refreshed).ok()).toBe(true);
  await expect(page).toHaveURL(/horizonDays=30.*fromOn=2026-01-01.*throughOn=2026-01-31/);
  await expect(
    page.getByRole("region", { name: "Recorded money", exact: true }).locator(".home-capture time"),
  ).toBeVisible();
  expect(fullReads).toBe(2);
  expect(liveReads).toBe(1);
  await expect(live).toHaveText(capture ?? "");
});
