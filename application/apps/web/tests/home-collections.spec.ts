import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function seed(request: APIRequestContext, count: number) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: `Collection property ${crypto.randomUUID()}`,
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
  const property = (await response.json()) as Schema["PropertyMutationResponse"];
  const tasks: Schema["TaskCreationResponse"][] = [];
  for (let i = 0; i < count; i += 1) {
    const result = await request.post("/api/tasks", {
      data: {
        title: `Collection Task ${i}`,
        relatedEntityType: "property",
        relatedEntityId: property.id,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(result.ok(), await result.text()).toBe(true);
    tasks.push((await result.json()) as Schema["TaskCreationResponse"]);
  }
  return { property, tasks };
}

test("View all keeps preview capture and exact total, bounds pages and preserves source return and scroll", async ({
  page,
  request,
}) => {
  const { property } = await seed(request, 55);
  await page.goto(
    `/home?propertyId=${property.id}&horizonDays=30&fromOn=2026-09-01&throughOn=2026-09-30`,
  );
  const preview = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(preview.getByRole("heading", { level: 4 })).toHaveText("55 recorded items");
  const capture = await preview.locator(".home-capture time").getAttribute("datetime");
  const response = page.waitForResponse(
    (result) =>
      new URL(result.url()).pathname === "/api/operator/home/items" &&
      new URL(result.url()).searchParams.get("limit") === "50",
  );
  await preview.getByRole("link", { name: "View all Needs action (55)", exact: true }).click();
  const body = (await (await response).json()) as Schema["CollectionResponse"];
  expect(body.asOf).toBe(capture);
  if (body.result.status !== "available") throw new Error("Collection unavailable");
  expect(body.result.items).toHaveLength(50);
  await expect(
    page
      .getByRole("region", { name: "Needs action", exact: true })
      .getByRole("heading", { level: 4 }),
  ).toHaveText("55 recorded items");
  const firstKeys = body.result.items.map((item) => item.key);
  const nextResponse = page.waitForResponse(
    (result) => new URL(result.url()).pathname === "/api/operator/home/items",
  );
  await page.getByRole("link", { name: "Next collection page", exact: true }).click();
  const next = (await (await nextResponse).json()) as Schema["CollectionResponse"];
  expect(next.asOf).toBe(capture);
  if (next.result.status !== "available") throw new Error("Collection unavailable");
  expect(next.result.items).toHaveLength(5);
  expect(new Set([...firstKeys, ...next.result.items.map((item) => item.key)]).size).toBe(55);
  await page.goBack();
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  const row = action.getByRole("button").nth(20);
  await row.click();
  const source = action.getByRole("link", { name: "View task details", exact: true });
  await source.scrollIntoViewIfNeeded();
  const returnUrl = page.url(),
    scroll = await page.evaluate(() => scrollY);
  expect(scroll).toBeGreaterThan(0);
  await source.click();
  await expect(page).toHaveURL(/\/tasks\?record=task/);
  await page
    .getByRole("link", { name: "Return to Home collection or preview", exact: true })
    .click();
  await expect(page).toHaveURL(returnUrl);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeCloseTo(scroll, 0);
  await page.getByLabel("Page size").fill("100");
  const maximum = page.waitForResponse(
    (result) =>
      new URL(result.url()).pathname === "/api/operator/home/items" &&
      new URL(result.url()).searchParams.get("limit") === "100",
  );
  const all = (await (await maximum).json()) as Schema["CollectionResponse"];
  if (all.result.status !== "available") throw new Error("Collection unavailable");
  expect(all.result.items).toHaveLength(55);
  await expect(page.getByRole("link", { name: "Next collection page" })).toHaveCount(0);
  await page.getByRole("link", { name: "Return Home", exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(
      `propertyId=${property.id}.*horizonDays=30.*fromOn=2026-09-01.*throughOn=2026-09-30`,
    ),
  );
});

test("one-row pages have no gaps and filter changes discard incompatible continuations", async ({
  page,
  request,
}) => {
  const { property, tasks } = await seed(request, 3);
  const other = await seed(request, 0);
  const keys: string[] = [];
  await page.route("**/api/operator/home/items?*", async (route) => {
    const response = await route.fetch();
    const result = (await response.json()) as Schema["CollectionResponse"];
    if (result.result.status === "available")
      keys.push(...result.result.items.map((item) => item.key));
    await route.fulfill({ json: result });
  });
  await page.goto(`/home/collections/needs_action?propertyId=${property.id}&limit=1`);
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action.getByRole("heading", { level: 4 })).toHaveText("3 recorded items");
  await page.getByRole("link", { name: "Next collection page" }).click();
  await expect.poll(() => keys.length).toBe(2);
  await page.getByRole("link", { name: "Next collection page" }).click();
  await expect.poll(() => keys.length).toBe(3);
  expect(new Set(keys)).toEqual(new Set(tasks.map((task) => `task:${task.id}`)));
  await expect(page.getByRole("link", { name: "Next collection page" })).toHaveCount(0);
  const changed = page.waitForResponse((result) => {
    const url = new URL(result.url());
    return (
      url.pathname === "/api/operator/home/items" && url.searchParams.get("horizonDays") === "90"
    );
  });
  await page.getByLabel("Upcoming horizon").selectOption("90");
  expect(new URL((await changed).url()).searchParams.has("cursor")).toBe(false);
  await expect(page).not.toHaveURL(/cursor=/);
  const continued = page.waitForResponse(
    (result) => new URL(result.url()).pathname === "/api/operator/home/items",
  );
  await page.getByRole("link", { name: "Next collection page" }).click();
  await continued;
  const rescope = page.waitForResponse(
    (result) =>
      new URL(result.url()).pathname === "/api/operator/home/items" &&
      new URL(result.url()).searchParams.get("propertyId") === other.property.id,
  );
  await page.getByLabel("Property ID", { exact: false }).fill(other.property.id);
  expect(new URL((await rescope).url()).searchParams.has("cursor")).toBe(false);
  await expect(action.getByRole("heading", { level: 4 })).toHaveText("0 recorded items");
});

test("changed sources and changed runtime cursors require a fresh restart with the same filters", async ({
  page,
  request,
}) => {
  const { property, tasks } = await seed(request, 3);
  await page.goto(`/home?propertyId=${property.id}`);
  const preview = page.getByRole("region", { name: "Needs action", exact: true });
  const link = preview.getByRole("link", { name: "View all Needs action (3)", exact: true });
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  expect(href).toBeTruthy();
  const completed = await request.post(`/api/tasks/${tasks[0].id}/complete`, {
    data: {
      expectedRevision: tasks[0].revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  });
  expect(completed.ok(), await completed.text()).toBe(true);
  await link.click();
  await expect(page.getByRole("alert")).toContainText("Restart with the same filters");
  await expect(page.getByRole("link", { name: "Next collection page" })).toHaveCount(0);
  await page.getByRole("button", { name: "Restart collection with current filters" }).click();
  await expect(
    page
      .getByRole("region", { name: "Needs action", exact: true })
      .getByRole("heading", { level: 4 }),
  ).toHaveText("2 recorded items");
  await expect(page).toHaveURL(new RegExp(`propertyId=${property.id}`));
  await expect(page).not.toHaveURL(/cursor=/);
  const current = await request.get(
    `/api/operator/home/items?collection=needs_action&propertyId=${property.id}`,
  );
  const fresh = (await current.json()) as Schema["CollectionResponse"];
  if (fresh.result.status !== "available") throw new Error("Collection unavailable");
  const stale = new URL(href ?? "/", "http://127.0.0.1:18744");
  stale.searchParams.set("cursor", fresh.result.viewAllCursor ?? "");
  const token = stale.searchParams.get("cursor") ?? "";
  const payload = JSON.parse(Buffer.from(token, "base64url").toString()) as { identity: string[] };
  payload.identity[1] = crypto.randomUUID();
  stale.searchParams.set("cursor", Buffer.from(JSON.stringify(payload)).toString("base64url"));
  await page.goto(stale.pathname + stale.search);
  await expect(page.getByRole("alert")).toContainText("continuation expired");
});

test("every collection has a deep link and missing readiness never dispatches a collection query", async ({
  page,
}) => {
  for (const collection of ["waiting", "upcoming", "appointments", "information_review"]) {
    await page.goto(`/home/collections/${collection}`);
    await expect(page.getByRole("region", { name: "Home collection page" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Restart collection with current filters" }),
    ).toBeEnabled();
  }
  let requests = 0;
  page.on("request", (pending) => {
    if (pending.url().includes("/api/operator/home/items")) requests += 1;
  });
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as Schema["BootstrapResponse"];
    await route.fulfill({
      json: {
        ...data,
        capabilities: data.capabilities.filter((value) => value !== "operator.home"),
      },
    });
  });
  await page.goto("/home/collections/needs_action");
  await expect(page.getByRole("alert")).toContainText("Home collections are unavailable");
  expect(requests).toBe(0);
});

test("hidden destinations remain reachable from collection source links with a preserved return", async ({
  page,
  request,
}) => {
  const { property } = await seed(request, 0);
  const response = await request.post("/api/maintenance-issues", {
    data: {
      propertyId: property.id,
      summary: `Hidden source ${crypto.randomUUID()}`,
      description: "Review the plumbing report",
      category: "plumbing",
      priority: "normal",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const issue = (await response.json()) as Schema["IssueCommandResponse"];
  await page.goto("/settings/navigation");
  await page.getByRole("checkbox", { name: "Maintenance", exact: true }).uncheck();
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  await page.goto(`/home/collections/needs_action?propertyId=${property.id}`);
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Maintenance", exact: true }),
  ).toHaveCount(0);
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await action.getByRole("button", { name: new RegExp(issue.summary) }).click();
  const returnUrl = page.url();
  await action.getByRole("link", { name: "View maintenance issue details" }).click();
  await expect(page.getByRole("heading", { name: issue.summary, exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Return to Home collection or preview" }).click();
  await expect(page).toHaveURL(returnUrl);
  await page.goto("/settings/navigation");
  await page.getByRole("checkbox", { name: "Maintenance", exact: true }).check();
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
});
