import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components, paths } from "@epm/contracts/generated";
import axe from "axe-core";
type Schema = components["schemas"];
type Live =
  paths["/api/operator/home/attention"]["get"]["responses"][200]["content"]["application/json"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
const period = "fromOn=2026-10-01&throughOn=2026-10-31";
async function fixtures(request: APIRequestContext) {
  const full = await request.get(`/api/operator/home?${period}`);
  const live = await request.get("/api/operator/home/attention");
  expect(full.ok() && live.ok()).toBe(true);
  return { full: (await full.json()) as Schema["HomeResponse"], live: (await live.json()) as Live };
}
async function createTask(request: APIRequestContext, title: string) {
  const response = await request.post("/api/tasks", {
    data: {
      title,
      dueAtUtc: new Date(Date.now() - 3 * 86400000).toISOString(),
      dueTimezone: "UTC",
      priority: "normal",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schema["TaskCreationResponse"];
}
function hold() {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}
async function ready(page: Page) {
  await page.goto(`/home?${period}`);
  await expect(page.getByRole("region", { name: "Recorded money", exact: true })).toContainText(
    "USD",
  );
  await expect(page.getByRole("region", { name: "Home action list", exact: true })).toContainText(
    "As of",
  );
}

test("day heading uses local date and truthful complete, partial and empty action counts", async ({
  page,
  request,
}) => {
  await page.clock.setFixedTime(new Date("2026-09-23T02:00:00Z"));
  const task = await createTask(request, "Heading count fixture");
  const data = await fixtures(request);
  if (data.live.needsAction.status !== "available") throw new Error("Live fixture unavailable");
  const item = data.live.needsAction.items.find((item) => item.source.id === task.id);
  if (!item) throw new Error("Task missing from live fixture");
  const items = [0, 1, 2].map((index) => ({
    ...item,
    key: `heading-${index}`,
    propertyId:
      index === 2 ? "00000000-0000-4000-8000-000000000002" : "00000000-0000-4000-8000-000000000001",
  }));
  for (const [total, expected] of [
    [3, "3 items need action across 2 properties."],
    [30, "30 items need action."],
    [0, "No items need action in recorded information."],
  ] as const) {
    const response = structuredClone(data.live);
    if (response.needsAction.status !== "available") throw new Error("Live fixture unavailable");
    response.needsAction.items = total ? items : [];
    response.needsAction.matchingTotal = total;
    await page.route("**/api/operator/home/attention*", (route) =>
      route.fulfill({ json: response }),
    );
    await page.goto("/home");
    await expect(
      page.getByRole("heading", { name: "Your day, in view", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Home", exact: true })).toHaveCount(0);
    await expect(page.locator(".home-heading")).toContainText(expected);
    const localDate = await page.evaluate(() =>
      new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(
        new Date(),
      ),
    );
    await expect(page.locator(".home-eyebrow")).toHaveText(localDate);
    await expect(page.locator(".home-eyebrow")).toHaveCSS("text-transform", "uppercase");
    await page.unroute("**/api/operator/home/attention*");
  }
});

test("Home renders every region, exact totals, keyboard source disclosure and both themes at narrow width", async ({
  page,
  request,
}) => {
  const task = await createTask(request, `Home layout ${crypto.randomUUID()}`);
  await page.setViewportSize({ width: 390, height: 844 });
  await ready(page);
  for (const name of [
    "Needs action",
    "Waiting",
    "Upcoming",
    "Calendar and appointments",
    "Information review",
    "Recorded money",
    "Inventory",
  ]) {
    if (name === "Waiting" || name === "Upcoming" || name === "Needs action")
      await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.getByRole("region", { name, exact: true })).toBeVisible();
  }
  await page.getByRole("tab", { name: "Needs action", exact: true }).click();
  const current = await fixtures(request);
  if (current.live.needsAction.status !== "available") throw new Error("Live fixture unavailable");
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action.getByRole("link", { name: /^View all Needs action/ })).toHaveText(
    `View all Needs action (${current.live.needsAction.matchingTotal} items)`,
  );
  const row = action.getByRole("button", { name: new RegExp(task.title) });
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("aria-expanded", "true");
  await expect(action.getByRole("link", { name: "View", exact: true }).first()).toHaveAttribute(
    "href",
    new RegExp(task.id),
  );
  for (const theme of ["light", "dark"]) {
    await page.evaluate(
      (value) => document.documentElement.setAttribute("data-theme", value),
      theme,
    );
    await page.evaluate(axe.source);
    const result = await page.evaluate(async () =>
      window.axe.run(document.querySelector('section[aria-label="Home"]') ?? document.body),
    );
    expect(result.violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await row.focus();
  await page.keyboard.press("Space");
  await expect(row).toHaveAttribute("aria-expanded", "false");
  await expect(row).toBeFocused();
});

test("agenda rows retain appointment time and reach the owning issue details", async ({
  page,
  request,
}) => {
  const propertyResponse = await request.post("/api/properties", {
    data: {
      displayName: `Home agenda ${crypto.randomUUID()}`,
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
  expect(propertyResponse.ok(), await propertyResponse.text()).toBe(true);
  const property = (await propertyResponse.json()) as Schema["PropertyMutationResponse"];
  const issueResponse = await request.post("/api/maintenance-issues", {
    data: {
      propertyId: property.id,
      summary: `Agenda issue ${crypto.randomUUID()}`,
      description: "Inspect the reported plumbing problem",
      category: "plumbing",
      priority: "normal",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(issueResponse.ok(), await issueResponse.text()).toBe(true);
  const issue = (await issueResponse.json()) as Schema["IssueCommandResponse"];
  const start = new Date(Date.now() + 3600000).toISOString();
  const appointment = await request.post(`/api/maintenance-issues/${issue.id}/appointments`, {
    data: {
      startsAtUtc: start,
      endsAtUtc: new Date(Date.now() + 7200000).toISOString(),
      purpose: "Home appointment inspection",
      expectedRevision: issue.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(appointment.ok(), await appointment.text()).toBe(true);
  const recorded = (await appointment.json()) as Schema["AppointmentCommandResponse"];
  await page.goto(`/home?propertyId=${property.id}&${period}`);
  const agenda = page.getByRole("region", { name: "Calendar and appointments", exact: true });
  const row = agenda.getByRole("button", { name: new RegExp(issue.summary) });
  await expect(row).toContainText("America/Los_Angeles");
  await row.click();
  const source = agenda.getByRole("link", { name: "View", exact: true });
  await expect(source).toHaveAttribute(
    "href",
    `/maintenance?record=issue&id=${issue.id}#appointment-${recorded.id}`,
  );
  await source.click();
  await expect(page.getByRole("heading", { name: issue.summary, exact: true })).toBeVisible();
});

test("independent section failures never fabricate counts or an all-clear", async ({
  page,
  request,
}) => {
  const data = await fixtures(request);
  const capture = { ...data.full.money.capture, freshness: "unavailable" as const };
  data.full.money = { status: "unavailable", capture, reasonCode: "source_unavailable" };
  data.live.needsAction = {
    status: "unavailable",
    capture,
    collection: "needs_action",
    reasonCode: "source_unavailable",
    retryTarget: {
      kind: "home_collection",
      collection: "needs_action",
      scope: data.live.scope,
      horizonDays: 7,
    },
  };
  data.live.priorityTotals = null;
  data.live.reasonTotals = null;
  await page.route("**/api/operator/home?*", (route) => route.fulfill({ json: data.full }));
  await page.route("**/api/operator/home/attention?*", (route) =>
    route.fulfill({ json: data.live }),
  );
  await page.goto(`/home?${period}`);
  await expect(page.getByRole("region", { name: "Recorded money", exact: true })).toContainText(
    "unavailable",
  );
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action).toContainText("unavailable");
  await expect(action.getByRole("heading", { level: 4 })).toHaveCount(0);
  await expect(page.getByText("No immediate actions in recorded information.")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Inventory", exact: true })).toContainText(
    "Vacant spaces",
  );
  await page.getByRole("tab", { name: "Waiting", exact: true }).click();
  await expect(page.getByRole("region", { name: "Waiting", exact: true })).toContainText(
    "View all Waiting",
  );
});

test("slow initial reads show bounded skeletons, delayed feedback and cancellable timeout with explicit retry", async ({
  page,
}) => {
  await page.clock.install();
  const pending = hold();
  let liveReads = 0,
    fullReads = 0;
  await page.route("**/api/operator/home?*", async (route) => {
    fullReads += 1;
    await pending.promise;
    await route.abort();
  });
  await page.route("**/api/operator/home/attention?*", async (route) => {
    liveReads += 1;
    await pending.promise;
    await route.abort();
  });
  try {
    await page.goto(`/home?${period}`);
    const action = page.getByRole("region", { name: "Needs action", exact: true });
    await expect(action).toContainText("Loading Needs action");
    await expect(action.getByRole("heading", { level: 4 })).toHaveCount(0);
    await expect(page.locator(".home-skeleton")).toHaveCount(7);
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await page.getByLabel("Money from", { exact: true }).fill("2026-09-01");
    await page.clock.runFor(2100);
    await expect(action).toContainText("Still loading Needs action (2 seconds)");
    await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2026-09-01");
    await page.clock.runFor(8100);
    await expect(action).toContainText("timed out");
    await expect(
      page.getByRole("button", { name: "Retry Needs action", exact: true }),
    ).toBeEnabled();
    expect(liveReads).toBe(1);
    // Changing the money period replaces the full read, not the live attention read.
    expect(fullReads).toBe(2);
    await page.unroute("**/api/operator/home/attention?*");
    await page.getByRole("button", { name: "Retry Needs action", exact: true }).click();
    await expect(action).toContainText("View all Needs action");
    await expect(page.getByRole("region", { name: "Recorded money", exact: true })).toContainText(
      "timed out",
    );
  } finally {
    pending.release();
  }
});

test("refresh retains the original capture and form input on failure, and removes the all-clear while checking", async ({
  page,
  request,
}) => {
  const data = await fixtures(request);
  if (data.live.needsAction.status !== "available") throw new Error("Live fixture unavailable");
  data.live.needsAction = { ...data.live.needsAction, matchingTotal: 0, items: [] };
  data.live.priorityTotals = { urgent: 0, overdue: 0, today: 0, review: 0 };
  data.live.reasonTotals = {};
  let refreshing = false;
  const pending = hold();
  await page.route("**/api/operator/home?*", async (route) => {
    if (refreshing) {
      await pending.promise;
      await route.fulfill({
        status: 503,
        json: { detail: { code: "operator_storage_failure", message: "Read unavailable" } },
      });
    } else await route.fulfill({ json: data.full });
  });
  await page.route("**/api/operator/home/attention?*", async (route) => {
    if (refreshing) {
      await pending.promise;
      await route.fulfill({
        status: 503,
        json: { detail: { code: "operator_storage_failure", message: "Read unavailable" } },
      });
    } else await route.fulfill({ json: data.live });
  });
  try {
    await ready(page);
    await expect(page.getByText("No immediate actions in recorded information.")).toBeVisible();
    await page.getByRole("button", { name: "Filters", exact: true }).click();
    await page.getByLabel("Money from", { exact: true }).fill("2026-09-01");
    refreshing = true;
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.getByText("No immediate actions in recorded information.")).toHaveCount(0);
    const money = page.getByRole("region", { name: "Recorded money", exact: true });
    await expect(money).toContainText("Updating");
    await expect(money.locator(".home-capture time")).toHaveAttribute(
      "datetime",
      data.full.money.capture.asOf,
    );
    pending.release();
    await expect(money).toContainText("Stale");
    await expect(money).toContainText("USD");
    await expect(page.getByRole("region", { name: "Needs action", exact: true })).toContainText(
      "Stale",
    );
    await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2026-09-01");
    await expect(page.getByText("No immediate actions in recorded information.")).toHaveCount(0);
  } finally {
    pending.release();
  }
});

test("new attention remains announced with its exact total until the operator shows the updated list", async ({
  page,
  request,
}) => {
  await ready(page);
  const before = await fixtures(request);
  if (before.live.needsAction.status !== "available") throw new Error("Live fixture unavailable");
  await createTask(request, `New Home arrival ${crypto.randomUUID()}`);
  const updated = page.waitForResponse((response) =>
    response.url().includes("/api/operator/home/attention"),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await updated;
  await expect(page.getByText("New items need attention", { exact: false })).toBeVisible();
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action.getByRole("link", { name: /^View all Needs action/ })).toContainText(
    `(${before.live.needsAction.matchingTotal} items)`,
  );
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await page.getByLabel("Money from", { exact: true }).fill("2026-08-01");
  await expect(page.getByText("New items need attention", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Show updated list" }).click();
  await expect(action.getByRole("link", { name: /^View all Needs action/ })).toContainText(
    `(${before.live.needsAction.matchingTotal + 1} items)`,
  );
  await expect(page.getByText("New items need attention", { exact: false })).toHaveCount(0);
  await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2026-08-01");
});

test("live attention refreshes at a declared transition, coalesces focus checks and retains an expanded row", async ({
  page,
  request,
}) => {
  await page.clock.install({ time: new Date("2026-10-15T12:00:00Z") });
  const data = await fixtures(request);
  if (data.live.needsAction.status !== "available" || data.live.needsAction.items.length === 0)
    throw new Error("Live fixture needs an attention row");
  data.live.nextTransitionAt = "2026-10-15T12:00:01Z";
  let liveReads = 0;
  const pending = hold();
  await page.route("**/api/operator/home/attention?*", async (route) => {
    liveReads += 1;
    if (liveReads > 2) await pending.promise;
    await route.fulfill({ json: data.live });
  });
  try {
    await page.goto(`/home?${period}`);
    const action = page.getByRole("region", { name: "Needs action", exact: true });
    const row = action.getByRole("button", {
      name: new RegExp(data.live.needsAction.items[0].title),
    });
    await row.click();
    await expect(row).toHaveAttribute("aria-expanded", "true");
    await page.clock.runFor(1100);
    await expect.poll(() => liveReads).toBe(2);
    // Several focus events during the same in-flight freshness check must not
    // create competing attention requests.
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
    });
    await page.waitForTimeout(50);
    expect(liveReads).toBe(3);
    await expect(row).toHaveAttribute("aria-expanded", "true");
  } finally {
    pending.release();
  }
});

test("Home refresh defaults to five minutes for summary and attention", async ({
  page,
  request,
}) => {
  await page.clock.install({ time: new Date("2026-10-15T12:00:00Z") });
  const data = await fixtures(request);
  data.live.nextTransitionAt = null;
  let liveReads = 0;
  let fullReads = 0;
  await page.route("**/api/operator/home?*", async (route) => {
    fullReads += 1;
    await route.fulfill({ json: data.full });
  });
  await page.route("**/api/operator/home/attention?*", async (route) => {
    liveReads += 1;
    await route.fulfill({ json: data.live });
  });
  await page.goto(`/home?${period}`);
  await expect.poll(() => liveReads).toBe(1);
  await expect.poll(() => fullReads).toBe(1);
  await page.clock.runFor(60_100);
  expect(liveReads).toBe(1);
  expect(fullReads).toBe(1);
  await page.clock.fastForward(240_000);
  await expect.poll(() => liveReads).toBe(2);
  await expect.poll(() => fullReads).toBe(2);
});

test("Home refresh interval saves in Settings, survives reload and drives both read timers", async ({
  page,
  request,
}) => {
  await page.clock.install({ time: new Date("2026-10-15T12:00:00Z") });
  const data = await fixtures(request);
  data.live.nextTransitionAt = null;
  let liveReads = 0,
    fullReads = 0;
  await page.route("**/api/operator/home/attention?*", async (route) => {
    liveReads++;
    await route.fulfill({ json: data.live });
  });
  await page.route("**/api/operator/home?*", async (route) => {
    fullReads++;
    await route.fulfill({ json: data.full });
  });
  await page.goto("/settings");
  const setting = page.getByRole("combobox", { name: "Automatic refresh", exact: true });
  await expect(setting).toHaveAccessibleDescription(
    "Saved automatically for this browser. Home refreshes at this interval while open. Needs action may update sooner when a deadline or follow-up becomes due.",
  );
  await expect(setting).toHaveValue("5");
  await setting.selectOption("1");
  await expect(
    page.getByText("Home refresh preference saved for this browser.", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(setting).toHaveValue("1");
  await page
    .getByRole("navigation", { name: "Primary navigation", exact: true })
    .getByRole("link", { name: "Home", exact: true })
    .click();
  await expect.poll(() => liveReads).toBe(1);
  await expect.poll(() => fullReads).toBe(1);
  await page.clock.fastForward(60_100);
  await expect.poll(() => liveReads).toBe(2);
  await expect.poll(() => fullReads).toBe(2);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect.poll(() => liveReads).toBe(3);
  await expect.poll(() => fullReads).toBe(3);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await setting.selectOption("15");
  const previousLive = liveReads,
    previousFull = fullReads;
  await page.goto(`/home?${period}`);
  await expect.poll(() => liveReads).toBe(previousLive + 1);
  await expect.poll(() => fullReads).toBe(previousFull + 1);
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  const liveBefore = liveReads,
    fullBefore = fullReads;
  await page.clock.fastForward(300_100);
  expect(liveReads).toBe(liveBefore);
  expect(fullReads).toBe(fullBefore);
  await page.clock.fastForward(600_000);
  await expect.poll(() => liveReads).toBe(liveBefore + 1);
  await expect.poll(() => fullReads).toBe(fullBefore + 1);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Restore defaults", exact: true }).click();
  await expect(setting).toHaveValue("5");
  await page.reload();
  await expect(setting).toHaveValue("5");
});

test("invalid stored Home refresh intervals fall back to five minutes", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("epm.home-refresh-minutes", "-10"));
  await page.goto("/settings");
  await expect(page.getByRole("combobox", { name: "Automatic refresh", exact: true })).toHaveValue(
    "5",
  );
});
