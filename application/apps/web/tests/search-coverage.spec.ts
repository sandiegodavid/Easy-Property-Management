import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
type Schema = components["schemas"];
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
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      ownerships: [{ ownerKind: "local_operator" }],
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as Schema["PropertyMutationResponse"];
}
async function issue(request: APIRequestContext, propertyId: string) {
  const response = await request.post("/api/maintenance-issues", {
    data: {
      propertyId,
      summary: "Coverage source change",
      description: "Inspect plumbing",
      category: "plumbing",
      priority: "normal",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test("bounded search groups preserve continuations and open typed targets", async ({
  page,
  request,
}) => {
  const name = `Search54 ${crypto.randomUUID()}`;
  for (let i = 0; i < 11; i++) {
    const response = await request.post("/api/tasks", {
      data: {
        title: `${name} ${String(i).padStart(2, "0")}`,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  const calls: string[] = [];
  page.on("request", (entry) => {
    if (entry.url().includes("/api/operator/search")) calls.push(entry.url());
  });
  await page.goto(`/search?q=${name}`);
  const group = page.getByRole("region", { name: "tasks search results" });
  await expect(group).toContainText("11 matches");
  await expect(group.getByRole("link")).toHaveCount(10);
  const first = await group.getByRole("link").allTextContents();
  await group.getByRole("button", { name: "Next tasks results" }).click();
  await expect(group.getByRole("link")).toHaveCount(1);
  expect(first).not.toContain(await group.getByRole("link").innerText());
  expect(calls).toHaveLength(2);
  expect(calls[1]).toContain("group=tasks");
  await group.getByRole("link").click();
  await expect(page.getByRole("heading", { name: /Search54/ })).toBeVisible();
  await page.goBack();
  await expect(group.getByRole("link")).toHaveCount(1);
  await expect(page).toHaveURL(/tasksCursor=/);
});

test("search failure is independent and stale continuations restart with filters", async ({
  page,
  request,
}) => {
  const item = await property(request, "Search54 independent");
  await page.route("**/api/operator/search?*", async (route) => {
    if (new URL(route.request().url()).searchParams.has("cursor")) {
      await route.fulfill({ status: 409, json: { detail: "Search view changed" } });
      return;
    }
    const response = await route.fetch();
    const data = (await response.json()) as Schema["SearchResponse"];
    if (data.groups.tasks)
      data.groups.tasks = {
        ...data.groups.tasks,
        availability: "unavailable",
        reasonCode: "source_read_unavailable",
        matchingTotal: null,
        items: null,
        sourceRevision: null,
        nextCursor: null,
      };
    if (data.groups.properties) data.groups.properties.nextCursor = "expired";
    await route.fulfill({ json: data });
  });
  await page.goto("/search?q=Search54%20independent&includeArchived=true");
  await expect(page.getByRole("region", { name: "tasks search results" })).toContainText(
    "unavailable",
  );
  const retry = page.waitForRequest(
    (entry) =>
      entry.url().includes("/api/operator/search") &&
      new URL(entry.url()).searchParams.get("group") === "tasks",
  );
  await page.getByRole("button", { name: "Retry tasks search" }).click();
  await retry;
  const group = page.getByRole("region", { name: "properties search results" });
  await expect(group.getByRole("link")).toHaveAttribute("href", `/properties/${item.id}/overview`);
  await group.getByRole("button", { name: "Next properties results" }).click();
  await expect(group.getByRole("alert")).toBeVisible();
  await group.getByRole("button", { name: "Restart group" }).click();
  await expect(page.getByLabel("Search metadata")).toHaveValue("Search54 independent");
  await expect(page.getByLabel("Include archived records")).toBeChecked();
});

test("maintenance review commits a source-bound receipt and dirty forms resume", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 resume");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await expect(page.getByRole("region", { name: "maintenance coverage" })).toContainText(
    "needs review",
  );
  await page.getByRole("button", { name: "Review maintenance coverage" }).click();
  await page.getByLabel("Review reason").fill("Checked maintenance records");
  const saving = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await page.getByRole("button", { name: "Save review form" }).click();
  const saved = (await (await saving).json()) as Schema["RecoveryResponse"];
  await expect(page.getByRole("status").filter({ hasText: "Form saved" })).toBeVisible();
  await page.goto(`/coverage/reviews/${saved.id}`);
  await expect(page.getByLabel("Review reason")).toHaveValue("Checked maintenance records");
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByText(/Original review .*recorded/)).toBeVisible();
  await expect(page.getByRole("region", { name: "maintenance coverage" })).toContainText(
    "recorded · applicable",
  );
});

test("required gaps survive acknowledgment and non-applicability comes from sources", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 gaps");
  const space = item.spaces[0];
  await page.goto(`/coverage/space/${space.id}/occupancy`);
  await expect(page.getByRole("region", { name: "occupancy coverage" })).toContainText(
    "missing required information",
  );
  await page.getByRole("button", { name: "Review occupancy coverage" }).click();
  await expect(page.getByRole("option", { name: "Not applicable", exact: true })).toHaveCount(0);
  await page.getByLabel("Review reason").fill("Reviewed the unknown facts");
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByText(/Original review .*missing required information/)).toBeVisible();
  await page.goto(`/coverage/space/${space.id}/lease`);
  await expect(page.getByRole("region", { name: "lease coverage" })).toContainText(
    "not applicable",
  );
  await page.getByRole("button", { name: "Review lease coverage" }).click();
  await expect(page.getByRole("option", { name: "Not applicable", exact: true })).toHaveCount(1);
});

test("source changes retain review text and require explicit revision review", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 stale");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance coverage" }).click();
  await page.getByLabel("Review reason").fill("Keep my review text");
  await issue(request, item.id);
  await page.getByRole("button", { name: "Refresh maintenance coverage" }).click();
  await expect(page.getByText(/Source information changed/)).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue("Keep my review text");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
  await page.getByRole("button", { name: "Use displayed evidence revision" }).click();
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByText(/Original review .*recorded/)).toBeVisible();
});

test("lost review response reconciles the original attempt after reload", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 interruption");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance coverage" }).click();
  await page.getByLabel("Review reason").fill("Original interrupted review");
  let recoveryId = "";
  page.on("response", async (response) => {
    if (response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"))
      recoveryId = ((await response.json()) as Schema["RecoveryResponse"]).id;
  });
  await page.route("**/coverage/property/*/maintenance/reviews", async (route) => {
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByRole("button", { name: "Reconcile review" })).toBeVisible();
  expect(recoveryId).toBeTruthy();
  await page.goto(`/coverage/reviews/${recoveryId}`);
  await page.getByRole("button", { name: "Reconcile review" }).click();
  await expect(page.getByText(/Original review .*recorded/)).toBeVisible();
  const events = await request.get(
    `/api/audit/events/operator_coverage_review/${((await (await request.get(`/api/operator/recovery/${recoveryId}`)).json()) as Schema["RecoveryResponse"]).receipt?.receiptId}`,
  );
  expect(events.ok()).toBeTruthy();
});

test("coverage absence, membership failure and hidden destinations remain truthful", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 availability");
  const unsupported = await page.goto(`/coverage/property/${item.id}/lease`);
  expect(unsupported?.status()).toBe(404);
  await page.goto(`/coverage/property/${crypto.randomUUID()}/maintenance`);
  await expect(page.getByRole("alert")).toBeVisible();
  await page.route(`**/api/operator/coverage/property/${item.id}/maintenance`, (route) =>
    route.fulfill({
      json: {
        subjectKind: "property",
        subjectId: item.id,
        area: "maintenance",
        availability: "unavailable",
        state: null,
        causes: [],
        asOf: new Date().toISOString(),
      },
    }),
  );
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await expect(page.getByText(/Coverage source unavailable/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Review maintenance coverage" })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as Schema["BootstrapResponse"];
    if (data.preferences) data.preferences.hiddenDestinationIds = ["properties"];
    await route.fulfill({ json: data });
  });
  await page.goto("/search?q=Coverage54%20availability");
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Properties" }),
  ).toHaveCount(0);
  await page
    .getByRole("region", { name: "properties search results" })
    .getByRole("link", { name: "Coverage54 availability" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Coverage54 availability", exact: true }),
  ).toBeVisible();
});

test("stale review admission preserves edits and blocks a new attempt", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 race");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance coverage" }).click();
  await page.getByLabel("Review reason").fill("Retain my stale review");
  await page.route("**/coverage/property/*/maintenance/reviews", async (route) => {
    await issue(request, item.id);
    await route.fulfill({ response: await route.fetch() });
  });
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByRole("alert")).toContainText("Coverage evidence has changed");
  await expect(page.getByLabel("Review reason")).toHaveValue("Retain my stale review");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
  const current = await request.get(`/api/operator/coverage/property/${item.id}/maintenance`);
  expect(((await current.json()) as Schema["CoverageResult"]).lastManualReviewAt).toBeNull();
});

test("a coverage outage preserves an open review form", async ({ page, request }) => {
  const item = await property(request, "Coverage54 dirty outage");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance coverage" }).click();
  await page.getByLabel("Review reason").fill("Retain this during an outage");
  await page.route(`**/api/operator/coverage/property/${item.id}/maintenance`, (route) =>
    route.fulfill({
      json: {
        subjectKind: "property",
        subjectId: item.id,
        area: "maintenance",
        availability: "unavailable",
        state: null,
        causes: [],
        asOf: new Date().toISOString(),
      },
    }),
  );
  await page.getByRole("button", { name: "Refresh maintenance coverage" }).click();
  await expect(page.getByText(/Coverage source unavailable/)).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue("Retain this during an outage");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
});
