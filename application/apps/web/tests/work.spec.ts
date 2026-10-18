import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}
async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}
async function home(request: APIRequestContext) {
  return post<Schemas["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Slice53 home ${crypto.randomUUID()}`,
    addressLine1: "10 Maple Street",
    city: "Portland",
    region: "OR",
    postalCode: "97201",
    countryCode: "US",
    propertyType: "single_family_home",
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerships: [
      {
        ownerKind: "client_owner",
        inlineParty: {
          partyKind: "individual",
          displayName: `Slice53 owner ${crypto.randomUUID()}`,
        },
      },
    ],
  });
}
async function issue(request: APIRequestContext) {
  const property = await home(request);
  const value = await post<Schemas["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
    propertyId: property.id,
    summary: `Leak ${crypto.randomUUID()}`,
    description: "Water under sink",
    category: "plumbing",
    priority: "urgent",
    reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
    reporter: { role: "manager", subjectKind: "local_operator" },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  return { property, issue: value };
}
async function task(request: APIRequestContext) {
  return post<Schemas["TaskCreationResponse"]>(request, "/api/tasks", {
    title: `Follow up ${crypto.randomUUID()}`,
    priority: "urgent",
    dueAtUtc: new Date(Date.now() + 86400000).toISOString(),
    dueTimezone: "America/Los_Angeles",
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
}
async function save(page: Page, title: string) {
  await test.step(title, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
}
async function openAction(page: Page, key: string, id: string, child?: string) {
  const family = key.startsWith("task.")
    ? "tasks"
    : key.startsWith("communication.")
      ? "conversations"
      : "maintenance";
  await page.goto(`/${family}?workflow=${key}&target=${id}${child ? `&child=${child}` : ""}`);
  await expect(page.getByRole("group", { name: "Requested change", exact: true })).toBeVisible();
}

test("maintenance directory organizes issues, named property search and secondary filters", async ({
  page,
  request,
}, testInfo) => {
  const f = await issue(request);
  const reads: string[] = [];
  const detailReads: string[] = [];
  page.on("request", (entry) => {
    const url = new URL(entry.url());
    if (url.pathname === "/api/maintenance-issues") reads.push(entry.url());
    else if (url.pathname.startsWith("/api/maintenance-issues/")) detailReads.push(entry.url());
  });
  await page.goto(`/maintenance?propertyId=${f.property.id}`);
  const workspace = page.getByRole("region", { name: "Work workspace", exact: true });
  await expect(workspace.getByRole("heading", { name: "Maintenance", exact: true })).toBeVisible();
  await expect(
    workspace.getByRole("button", { name: "Report maintenance issue", exact: true }),
  ).toBeVisible();
  await expect(workspace.getByRole("navigation", { name: "Work views" })).toHaveCount(0);
  await expect(workspace.getByText(/Recording a conversation|retained attribution/)).toHaveCount(0);
  const card = workspace.locator(".maintenance-issue-card");
  await expect(card).toContainText(f.issue.summary);
  await expect(card).toContainText(f.property.displayName);
  await expect(card).toContainText("Urgent priority");
  await expect(workspace.getByLabel("Property ID", { exact: true })).toHaveCount(0);
  await expect(
    workspace.getByRole("combobox", { name: "Reporter role", exact: true }),
  ).toBeHidden();
  expect(reads).toHaveLength(1);
  expect(detailReads).toHaveLength(0);
  expect(new URL(reads[0]).searchParams.get("pageSize")).toBe("25");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await workspace.screenshot({
        path: testInfo.outputPath(`maintenance-${theme}-${width}.png`),
      });
    }
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(".maintenance-directory", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
  }
  await workspace.getByRole("combobox", { name: "Status", exact: true }).selectOption("resolved");
  await expect(
    workspace.getByText("No maintenance issues match these filters.", { exact: true }),
  ).toBeVisible();
  await workspace.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(workspace.getByRole("searchbox", { name: "Property", exact: true })).toHaveValue("");
  await expect(workspace.getByRole("combobox", { name: "Status", exact: true })).toHaveValue("");
  await workspace
    .getByRole("searchbox", { name: "Property", exact: true })
    .fill(f.property.displayName);
  await workspace.getByRole("button", { name: f.property.displayName, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`propertyId=${f.property.id}`));
  await expect(card).toHaveCount(1);
  await card.click();
  await expect(page).toHaveURL(new RegExp(`record=issue&id=${f.issue.id}`));
});

test("maintenance directory can retry a failed read without losing its property filter", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  let attempts = 0;
  await page.route("**/api/maintenance-issues?*", async (route) => {
    attempts += 1;
    if (attempts === 1)
      await route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
    else await route.continue();
  });
  await page.goto(`/maintenance?propertyId=${f.property.id}`);
  const directory = page.getByRole("region", { name: "Work directory", exact: true });
  await expect(directory.getByRole("alert")).toContainText("Records unavailable");
  await expect(
    directory.getByText("No maintenance issues match these filters.", { exact: true }),
  ).toHaveCount(0);
  await directory.getByRole("button", { name: "Retry loading issues", exact: true }).click();
  await expect(directory.locator(".maintenance-issue-card")).toContainText(f.issue.summary);
  expect(attempts).toBe(2);
  await expect(page).toHaveURL(new RegExp(`propertyId=${f.property.id}`));
});

test("issue detail has a top link back to Maintenance", async ({ page, request }) => {
  const f = await issue(request);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const detail = page.getByRole("region", { name: "Work record", exact: true });
  const back = detail.getByRole("link", { name: "← Back to Maintenance", exact: true });
  await expect(back).toHaveAttribute("href", "/maintenance");
  const heading = detail.getByRole("heading", { level: 2 });
  await expect(heading).toBeVisible();
  expect((await back.boundingBox())!.y).toBeLessThan((await heading.boundingBox())!.y);
  await back.click();
  await expect(page).toHaveURL(/\/maintenance$/);
});

test("issue details prioritize description, named property and grouped actions", async ({
  page,
  request,
}, testInfo) => {
  const f = await issue(request);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const detail = page.getByRole("region", { name: "Work record", exact: true });
  await expect(
    detail.getByRole("link", { name: f.property.displayName, exact: true }),
  ).toBeVisible();
  await expect(detail.locator(".issue-detail-description")).toHaveText("Water under sink");
  await expect(detail.locator(".issue-detail-facts")).toContainText("You · manager");
  await expect(detail.locator(".issue-detail-facts")).not.toContainText("Revision");
  await expect(
    detail
      .getByRole("navigation", { name: "Issue actions", exact: true })
      .getByRole("link", { name: "Start work", exact: true }),
  ).toBeVisible();
  await expect(detail.getByText("Not recorded", { exact: true })).toHaveCount(0);
  await expect(
    detail.locator("summary", { hasText: "Appointments · None recorded" }),
  ).toBeVisible();
  await expect(detail.getByText(f.issue.id, { exact: true })).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: testInfo.outputPath(`issue-${theme}-${width}.png`),
        fullPage: true,
      });
      await page.evaluate(axe.source);
      const violations = await page.evaluate(
        async () =>
          (
            await window.axe.run(".issue-detail", {
              runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
            })
          ).violations,
      );
      expect(violations).toEqual([]);
    }
  }
  await detail.getByText("More issue actions", { exact: true }).click();
  await expect(
    detail.getByRole("link", { name: "Schedule appointment", exact: true }),
  ).toBeVisible();
  await detail
    .getByRole("navigation", { name: "Issue actions", exact: true })
    .getByRole("link", { name: "Edit issue", exact: true })
    .click();
  await expect(page).toHaveURL(/workflow=maintenance.issue.patch/);
});

test("issue facts and actions stay available when the property name cannot load", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.route(`**/api/properties/${f.property.id}`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Temporarily unavailable" }),
    }),
  );
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const detail = page.getByRole("region", { name: "Work record", exact: true });
  await expect(detail.getByText("Property name unavailable", { exact: false })).toBeVisible();
  await expect(detail.locator(".issue-detail-description")).toHaveText("Water under sink");
  await expect(detail.getByRole("link", { name: "Edit issue", exact: true })).toBeVisible();
});

test("Task creation uses original recovery identity and saved forms survive reload", async ({
  page,
  request,
}) => {
  await page.goto("/tasks?workflow=task.create");
  await expect(
    page.getByRole("group", { name: "Form actions", exact: true }).getByRole("button"),
  ).toHaveText(["Create task", "Save unfinished form"]);
  await page
    .getByLabel("Title (required)", { exact: true })
    .fill(`Browser task ${crypto.randomUUID()}`);
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await page.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  const recovery = (await (await saved).json()) as Schemas["RecoveryResponse"];
  await expect(page.getByText("Draft saved", { exact: false })).toBeVisible();
  await page.goto(`/tasks?workflow=task.create&resume=${recovery.id}`);
  await expect(page.getByLabel("Title (required)", { exact: true })).not.toHaveValue("");
  await save(page, "Create task");
  const currentLink = page.getByRole("link", { name: "Open current work record" });
  const target = new URL(
    (await currentLink.getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  const created = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${target}`);
  expect(created.status).toBe("open");
  await currentLink.click();
  await expect(page.getByRole("heading", { name: created.title })).toBeVisible();
});

test("Waiting preserves deadline and urgency; clearing is not completion", async ({
  page,
  request,
}) => {
  const original = await task(request);
  await openAction(page, "task.waiting.set", original.id);
  await page.getByLabel("Waiting for kind").selectOption("organization");
  await page.getByLabel("Waiting for label").fill("Plumber reply");
  await page
    .getByLabel("Follow up at", { exact: true })
    .fill(new Date(Date.now() + 3600000).toISOString());
  await page.getByLabel("Follow up timezone", { exact: true }).fill("America/Los_Angeles");
  await save(page, "Set waiting context");
  const waiting = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`);
  expect(waiting.isWaiting).toBe(true);
  expect(waiting.priority).toBe(original.priority);
  expect(waiting.dueAtUtc).toBe(original.dueAtUtc);
  await page.goto(`/tasks?record=task&id=${original.id}`);
  await expect(page.getByText("Plumber reply", { exact: true })).toBeVisible();
  await openAction(page, "task.waiting.clear", original.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Clear waiting context");
  expect((await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`)).status).toBe(
    "open",
  );
});

test("Waiting replacement and date removal retain deadline, reminder and unscheduled context", async ({
  page,
  request,
}) => {
  const original = await task(request);
  const reminder = await post<Schemas["TaskMutationResponse"]>(
    request,
    `/api/tasks/${original.id}/reminders`,
    {
      expectedRevision: original.revision,
      idempotencyKey: crypto.randomUUID(),
      remindAtUtc: new Date(Date.now() + 7200000).toISOString(),
    },
  );
  await openAction(page, "task.waiting.set", original.id);
  await page.getByLabel("Waiting for kind").selectOption("organization");
  await page.getByLabel("Waiting for label").fill("Contractor response");
  await page
    .getByLabel("Follow up at", { exact: true })
    .fill(new Date(Date.now() + 3600000).toISOString());
  await page.getByLabel("Follow up timezone", { exact: true }).fill("America/Los_Angeles");
  await save(page, "Set waiting context");
  await page.goto(`/tasks?record=task&id=${original.id}`);
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Set waiting context", exact: true }).click();
  await page.getByLabel("Waiting for label").fill("Replacement contractor response");
  await save(page, "Set waiting context");
  await openAction(page, "task.waiting.reschedule", original.id);
  await page.getByRole("checkbox", { name: "Clear follow up at", exact: true }).check();
  await page.getByRole("checkbox", { name: "Clear follow up timezone", exact: true }).check();
  await page.getByRole("checkbox", { name: "Clear follow up", exact: true }).check();
  await save(page, "Reschedule follow-up");
  const current = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`);
  expect(current.waitingForLabel).toBe("Replacement contractor response");
  expect(current.followUpAt).toBeNull();
  expect(current.followUpState).toBe("unscheduled");
  expect(current.dueAtUtc).toBe(original.dueAtUtc);
  expect(current.priority).toBe(original.priority);
  const reminders = await get<Schemas["ReminderResponse"][]>(
    request,
    `/api/tasks/${original.id}/reminders`,
  );
  expect(reminders.find((item) => item.id === reminder.reminder!.id)?.status).toBe("pending");
  await page.goto("/tasks?followUps=true&state=unscheduled");
  await page
    .getByRole("region", { name: "Work directory", exact: true })
    .getByText(original.title, { exact: true })
    .click();
  await expect(page.getByText("Follow-up: Not scheduled", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Task deadline:/)).toContainText(original.dueTimezone!);
});

test("Waiting reschedule lost response recovers one overdue follow-up without resolving the Task", async ({
  page,
  request,
}) => {
  const original = await task(request);
  await openAction(page, "task.waiting.set", original.id);
  await page.getByLabel("Waiting for kind").selectOption("organization");
  await page.getByLabel("Waiting for label").fill("Supplier reply");
  await save(page, "Set waiting context");
  await openAction(page, "task.waiting.reschedule", original.id);
  await page.getByRole("checkbox", { name: "Clear follow up at", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "Clear follow up timezone", exact: true }).uncheck();
  await page
    .getByLabel("Follow up at", { exact: true })
    .fill(new Date(Date.now() - 3600000).toISOString());
  await page.getByLabel("Follow up timezone", { exact: true }).fill("America/Los_Angeles");
  let dispatches = 0;
  await page.route(`**/api/tasks/${original.id}/waiting/follow-up`, async (route) => {
    dispatches++;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort();
  });
  await page.getByRole("button", { name: "Save reschedule follow-up", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  const current = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`);
  expect(current.followUpState).toBe("overdue");
  expect(current.followUpActionable).toBe(true);
  expect(current.status).toBe("open");
  expect(current.dueAtUtc).toBe(original.dueAtUtc);
  expect(dispatches).toBe(1);
});

test("Task priority and due filters combine with context and preserve cursor pages", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const ids = new Set<string>();
  for (let index = 0; index < 26; index++) {
    const created = await post<Schemas["TaskCreationResponse"]>(request, "/api/tasks", {
      title: `Filtered task ${index}`,
      priority: "high",
      relatedEntityType: "maintenance_issue",
      relatedEntityId: f.issue.id,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    ids.add(created.id);
  }
  await post(request, "/api/tasks", {
    title: "Excluded normal task",
    priority: "normal",
    relatedEntityType: "maintenance_issue",
    relatedEntityId: f.issue.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await post(request, "/api/tasks", {
    title: "Excluded dated task",
    priority: "high",
    dueAtUtc: new Date(Date.now() + 86400000).toISOString(),
    dueTimezone: "America/Los_Angeles",
    relatedEntityType: "maintenance_issue",
    relatedEntityId: f.issue.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/tasks?entityType=maintenance_issue&entityId=${f.issue.id}`);
  const directory = page.getByRole("region", { name: "Work directory" });
  await directory.getByRole("combobox", { name: "Priority", exact: true }).selectOption("high");
  await directory.getByRole("combobox", { name: "Due period", exact: true }).selectOption("nodate");
  await expect(directory.getByRole("link", { name: /^Filtered task / })).toHaveCount(25);
  await expect(directory).not.toContainText("Excluded");
  const seen = new Set(
    await directory
      .getByRole("link", { name: /^Filtered task / })
      .evaluateAll((links) =>
        links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("id")!),
      ),
  );
  await directory.getByRole("button", { name: "Next work page" }).click();
  await expect(directory.getByRole("link", { name: /^Filtered task / })).toHaveCount(1);
  expect(new URL(page.url()).searchParams.get("priority")).toBe("high");
  const last = new URL(
    (await directory.getByRole("link", { name: /^Filtered task / }).getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  expect(seen.has(last)).toBe(false);
  seen.add(last);
  expect(seen).toEqual(ids);
  await directory.getByRole("combobox", { name: "Priority", exact: true }).selectOption("normal");
  expect(new URL(page.url()).searchParams.has("cursor")).toBe(false);
  await expect(directory.getByRole("link", { name: "Excluded normal task" })).toBeVisible();
  for (const due of ["overdue", "today", "next7days", ""]) {
    await directory.getByRole("combobox", { name: "Due period", exact: true }).selectOption(due);
    const response = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/tasks" &&
        (url.searchParams.get("due") ?? "") === due &&
        response.request().method() === "GET"
      );
    });
    expect((await response).ok()).toBe(true);
  }
});

test("Task quick add preserves optional input and explicitly clears a deadline", async ({
  page,
  request,
}) => {
  await page.goto("/tasks");
  await page.getByText("Quick add task", { exact: true }).click();
  const quick = page.getByRole("region", { name: "Create task", exact: true });
  await expect(quick.getByLabel("Notes", { exact: true })).not.toBeVisible();
  await quick.getByLabel("Title (required)", { exact: true }).fill("Compact task");
  await quick.getByLabel("No due date", { exact: true }).uncheck();
  await quick.getByText("Optional Task details", { exact: true }).click();
  await quick
    .getByLabel("Due at utc", { exact: true })
    .fill(new Date(Date.now() + 86400000).toISOString());
  await quick.getByLabel("Due timezone", { exact: true }).fill("America/Los_Angeles");
  await quick.getByLabel("Notes", { exact: true }).fill("Keep optional input");
  await quick.getByRole("combobox", { name: "Priority", exact: true }).selectOption("high");
  await quick.getByLabel("No due date", { exact: true }).check();
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await quick.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  const recovery = (await (await saved).json()) as Schemas["RecoveryResponse"];
  await page.goto(`/tasks?workflow=task.create&resume=${recovery.id}`);
  await expect(page.getByLabel("No due date", { exact: true })).toBeChecked();
  await page.getByText("Optional Task details", { exact: true }).click();
  await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("Keep optional input");
  await save(page, "Create task");
  const id = new URL(
    (await page.getByRole("link", { name: "Open current work record" }).getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  const created = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${id}`);
  expect(created.dueAtUtc).toBeNull();
  expect(created.dueTimezone).toBeNull();
  expect(created.priority).toBe("high");
  expect(created.notes).toBe("Keep optional input");
  await page.goto("/tasks?workflow=task.create");
  await page.getByLabel("Title (required)", { exact: true }).fill("Scheduled compact task");
  await page.getByLabel("No due date", { exact: true }).uncheck();
  const deadline = await page.evaluate(() => {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(0, 0, 0, 0);
    return {
      date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
      instant: date.toISOString(),
      zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
  });
  await page.getByLabel("Due date", { exact: true }).fill(deadline.date);
  await save(page, "Create task");
  const scheduledId = new URL(
    (await page.getByRole("link", { name: "Open current work record" }).getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  const scheduled = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${scheduledId}`);
  expect(Date.parse(scheduled.dueAtUtc!)).toBe(Date.parse(deadline.instant));
  expect(scheduled.dueTimezone).toBe(deadline.zone);
  expect(scheduled.isAllDay).toBe(true);
});

test("Task row completion requires confirmation and terminal history shows the retained outcome", async ({
  page,
  request,
}) => {
  const original = await task(request);
  await page.goto("/tasks");
  const deadlines = page.getByRole("region", { name: "Task deadlines and reminders", exact: true });
  const row = deadlines.getByRole("button", { name: new RegExp(original.title) }).first();
  await row.click();
  await deadlines.getByLabel(`Complete Task: ${original.title}`, { exact: true }).click();
  expect((await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`)).status).toBe(
    "open",
  );
  await page.getByRole("button", { name: "Save complete task", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Outcome note", { exact: true }).fill("Confirmed response received");
  await save(page, "Complete task");
  const completed = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`);
  await page.goto("/tasks?status=completed");
  const directory = page.getByRole("region", { name: "Work directory" });
  const history = directory.getByRole("listitem").filter({ hasText: original.title });
  await expect(history).toContainText("Confirmed response received");
  await expect(history).toContainText(completed.completedAtUtc!);
  await expect(history.getByRole("checkbox")).toHaveCount(0);
  await history.getByRole("link", { name: original.title }).click();
  await expect(page.getByRole("region", { name: "Task outcome history" })).toContainText(
    "Confirmed response received",
  );
  const cancelled = await task(request);
  await post(request, `/api/tasks/${cancelled.id}/cancel`, {
    expectedRevision: cancelled.revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    outcomeNote: "No longer required",
  });
  await page.goto("/tasks?status=cancelled");
  await expect(page.getByRole("region", { name: "Work directory" })).toContainText(
    "No longer required",
  );
  const cancelledResult = await get<Schemas["TaskResponse"]>(request, `/api/tasks/${cancelled.id}`);
  await expect(page.getByRole("region", { name: "Work directory" })).toContainText(
    cancelledResult.cancelledAtUtc!,
  );
});

test("Reminder acknowledgement and Task completion are separate and recoverable", async ({
  page,
  request,
}) => {
  const original = await task(request);
  await openAction(page, "task.reminder.add", original.id);
  await page.getByLabel("Remind at utc").fill(new Date(Date.now() + 3600000).toISOString());
  await save(page, "Add task reminder");
  const reminders = await get<Schemas["ReminderResponse"][]>(
    request,
    `/api/tasks/${original.id}/reminders`,
  );
  await openAction(page, "task.reminder.acknowledge", original.id, reminders[0].id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Acknowledge reminder");
  expect((await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`)).status).toBe(
    "open",
  );
  await openAction(page, "task.complete", original.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Outcome note", { exact: true }).fill("Reply received");
  await save(page, "Complete task");
  expect((await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`)).status).toBe(
    "completed",
  );
});

test("Task edit stale source preserves edits and explicit source review", async ({
  page,
  request,
}) => {
  const original = await task(request);
  await openAction(page, "task.edit", original.id);
  await page.getByLabel("Title", { exact: true }).fill("Retained edit");
  await post(request, `/api/tasks/${original.id}/start`, {
    expectedRevision: original.revision,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.getByRole("button", { name: "Save task changes", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Retained edit");
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await save(page, "Edit task");
  expect((await get<Schemas["TaskResponse"]>(request, `/api/tasks/${original.id}`)).title).toBe(
    "Retained edit",
  );
});

test("Issue creation records attribution and related Property, not physical verification", async ({
  page,
  request,
}) => {
  const property = await home(request);
  await page.goto("/maintenance?workflow=maintenance.issue.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page
    .getByRole("combobox", { name: "Space id", exact: true })
    .selectOption(property.spaces[0].id);
  await page.getByLabel("Summary (required)").fill("Browser sink leak");
  await page.getByLabel("Description (required)").fill("Water visible");
  await page.getByLabel("Category (required)").selectOption("plumbing");
  await page
    .getByLabel("Reported at utc (required)")
    .fill(new Date(Date.now() - 60000).toISOString());
  await save(page, "Report maintenance issue");
  await page.getByRole("link", { name: "Open current work record" }).click();
  await expect(page.getByRole("heading", { name: "Browser sink leak" })).toBeVisible();
  await expect(page.getByRole("link", { name: property.displayName, exact: true })).toBeVisible();
  await expect(page.locator(".issue-detail-facts")).toContainText("You");
});

test("Party owner reporter correction preserves originating communication and reporter filters", async ({
  page,
  request,
}) => {
  const property = await home(request),
    ownerId = property.ownerships[0].partyId!;
  const owner = await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
    request,
    `/api/parties/${ownerId}`,
  );
  await page.goto("/maintenance?workflow=maintenance.issue.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page.getByLabel("Summary (required)").fill("Owner attribution workflow");
  await page.getByLabel("Description (required)").fill("Owner observed a leak");
  await page.getByLabel("Category (required)").selectOption("plumbing");
  await page.getByLabel("Reported at utc (required)").fill(new Date().toISOString());
  const reporter = page.getByRole("group", { name: "Reporter", exact: true });
  await reporter.getByLabel("Role (required)").selectOption("owner");
  await reporter.getByLabel("Subject kind (required)").selectOption("party");
  await page.getByLabel("Find reporter by name").fill(owner.displayName);
  await page.getByRole("button", { name: "Search reporter identities", exact: true }).click();
  await page
    .getByRole("button", { name: `Use ${owner.displayName} as reporter`, exact: true })
    .click();
  await save(page, "Report maintenance issue");
  await page.getByRole("link", { name: "Open current work record" }).click();
  const issueId = new URL(page.url()).searchParams.get("id")!;
  await expect(page.locator(".issue-detail-facts")).toContainText(owner.displayName);
  await page.getByRole("link", { name: "Record linked conversation", exact: true }).click();
  await expect(page.getByLabel("Existing identity (required)")).toHaveValue(ownerId);
  await expect(page.getByLabel("Role (required)")).toHaveValue("reporter");
  await page.getByLabel("Subject (required)").fill("Owner's original report");
  await page.getByLabel("Body (required)").fill("Owner contacted operator about leak");
  await page.getByLabel("Occurred at utc (required)").fill(new Date().toISOString());
  await page.getByLabel("Occurred timezone (required)").fill("America/Los_Angeles");
  await page.getByLabel("Record", { exact: true }).check();
  await save(page, "Create conversation");
  await openAction(page, "maintenance.reporter.correct", issueId);
  const correction = page.getByRole("group", { name: "Reporter", exact: true });
  await expect(correction.getByLabel("Role (required)")).toHaveValue("owner");
  await correction.getByLabel("Role (required)").selectOption("staff");
  await expect(correction.getByLabel("Subject kind (required)")).toHaveValue("local_operator");
  await expect(correction.getByText("Historical selection reason", { exact: true })).toHaveCount(0);
  await page
    .getByLabel("Reason (required)")
    .fill("Operator staff observed the issue; retain owner conversation");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Correct issue reporter");
  const current = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${issueId}`,
  );
  expect(current.reporter).toMatchObject({
    role: "staff",
    subjectKind: "local_operator",
    partyId: null,
    displayName: "Local operator",
  });
  const communications = await get<Schemas["CommunicationPage"]>(
    request,
    `/api/communications?entityType=maintenance_issue&entityId=${issueId}`,
  );
  const communication = await get<Schemas["CommunicationResponse"]>(
    request,
    `/api/communications/${communications.items[0].id}`,
  );
  expect(communication.participants[0].partyId).toBe(ownerId);
  await page.goto(`/maintenance?propertyId=${property.id}`);
  await page.getByText("More filters", { exact: true }).click();
  await page.getByRole("combobox", { name: "Reporter role", exact: true }).selectOption("staff");
  await page
    .getByRole("combobox", { name: "Reporter subject", exact: true })
    .selectOption("local_operator");
  await expect(page.getByRole("link", { name: /Owner attribution workflow/ })).toBeVisible();
  await page.getByRole("combobox", { name: "Reporter role", exact: true }).selectOption("owner");
  await expect(page.getByRole("link", { name: /Owner attribution workflow/ })).toHaveCount(0);
});

test("tenant reporter is rejected for a draft lease and accepted after explicit execution", async ({
  page,
  request,
}) => {
  const property = await home(request);
  const tenant = await post<Schemas["TenantMutationResponse"]>(request, "/api/tenants", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    partyKind: "individual",
    displayName: `Reporter tenant ${crypto.randomUUID()}`,
  });
  const lease = await post<Schemas["LeaseMutationResponse"]>(request, "/api/leases", {
    expectedLeaseRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    spaceId: property.spaces[0].id,
    leaseKind: "residential",
    contractStartsOn: property.effectiveLocalDate,
    occupancyStartsOn: property.effectiveLocalDate,
    initialTerm: {
      baseRentMinor: 100000,
      currencyCode: "USD",
      paymentFrequency: "monthly",
      paymentDueDay: 1,
      agreedSecurityDepositMinor: 100000,
    },
    participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
  });
  const fill = async () => {
    await page.goto("/maintenance?workflow=maintenance.issue.create");
    await page.getByLabel("Property id (required)").selectOption(property.id);
    await page
      .getByRole("combobox", { name: "Space id", exact: true })
      .selectOption(property.spaces[0].id);
    await page.getByLabel("Summary (required)").fill("Tenant leak report");
    await page.getByLabel("Description (required)").fill("Occupant reported the issue");
    await page.getByLabel("Category (required)").selectOption("plumbing");
    await page.getByLabel("Reported at utc (required)").fill(new Date().toISOString());
    await page
      .getByRole("group", { name: "Reporter", exact: true })
      .getByLabel("Role (required)")
      .selectOption("tenant");
    await page.getByLabel("Find reporter by name").fill(tenant.displayName);
    await page.getByRole("button", { name: "Search reporter identities", exact: true }).click();
    await page
      .getByRole("button", { name: `Use ${tenant.displayName} as reporter`, exact: true })
      .click();
  };
  await fill();
  const rejected = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/maintenance-issues") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Report maintenance issue", exact: true }).click();
  const rejection = await rejected;
  expect(rejection.status(), await rejection.text()).toBe(409);
  expect(await rejection.text()).toContain("reporter_relationship");
  expect(
    (
      await get<Schemas["IssuePageResponse"]>(
        request,
        `/api/maintenance-issues?propertyId=${property.id}`,
      )
    ).items,
  ).toHaveLength(0);
  await post(request, `/api/leases/${lease.id}/execute`, {
    expectedLeaseRevision: lease.leaseRevision,
    expectedRevision: property.spaces[0].revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    executedOn: property.effectiveLocalDate,
  });
  await fill();
  await save(page, "Report maintenance issue");
  const issues = await get<Schemas["IssuePageResponse"]>(
    request,
    `/api/maintenance-issues?propertyId=${property.id}`,
  );
  expect(issues.items).toHaveLength(1);
  expect(issues.items[0].reporter.partyId).toBe(tenant.id);
});

test("archived owner selection requires historical confirmation and preserves the correction date", async ({
  page,
  request,
}) => {
  const property = await post<Schemas["PropertyMutationResponse"]>(
      request,
      "/__test__/historical-owner",
      {},
    ),
    ownerId = property.ownerships[0].partyId!;
  const owner = await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
    request,
    `/api/parties/${ownerId}`,
  );
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const replaced = await request.put(`/api/properties/${property.id}/ownerships`, {
    data: {
      expectedPropertyRevision: property.propertyRevision,
      idempotencyKey: crypto.randomUUID(),
      effectiveOn: today,
      ownerships: [{ ownerKind: "local_operator" }],
    },
  });
  expect(replaced.ok(), await replaced.text()).toBe(true);
  await post(request, `/api/parties/${ownerId}/archive`, {
    expectedRevision: owner.revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
  });
  const reported = `${property.effectiveLocalDate}T20:00:00Z`;
  const current = await post<Schemas["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    propertyId: property.id,
    summary: "Historical owner correction",
    description: "Backdated attribution",
    category: "plumbing",
    priority: "normal",
    reportedAtUtc: reported,
    reporter: { role: "manager", subjectKind: "local_operator" },
  });
  await openAction(page, "maintenance.reporter.correct", current.id);
  const attribution = page.getByRole("group", { name: "Reporter", exact: true });
  await attribution.getByLabel("Role (required)").selectOption("owner");
  await attribution.getByLabel("Subject kind (required)").selectOption("party");
  await page.getByLabel("Find reporter by name").fill(owner.displayName);
  await page.getByRole("button", { name: "Search reporter identities", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: `Use ${owner.displayName} as reporter (archived)`,
      exact: true,
    }),
  ).toHaveCount(0);
  await page.getByLabel("Show archived identities for a backdated report").check();
  await page
    .getByRole("button", { name: `Use ${owner.displayName} as reporter (archived)`, exact: true })
    .click();
  await expect(page.getByText(/Archived — backdated relationship/)).toBeVisible();
  await attribution.getByLabel("Historical selection confirmed", { exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Save issue reporter correction", exact: true }),
  ).toBeDisabled();
  await attribution
    .getByRole("textbox", { name: "Historical selection reason", exact: true })
    .fill("Former owner identified from retained history");
  await page
    .getByLabel("Reason (required)")
    .fill("Corrected attribution to the original owner report");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Correct issue reporter");
  const detail = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${current.id}`,
  );
  expect(detail.reporter).toMatchObject({
    role: "owner",
    partyId: ownerId,
    displayName: owner.displayName,
    currentPartyState: "archived",
  });
  expect(Date.parse(detail.reportedAtUtc)).toBe(Date.parse(reported));
  expect(
    (
      await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
        request,
        `/api/parties/${ownerId}`,
      )
    ).archivedAt,
  ).toBeTruthy();
});

test("Appointment completion does not resolve issue or establish completed work", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await openAction(page, "maintenance.appointment.create", f.issue.id);
  await page
    .getByLabel("Starts at utc (required)")
    .fill(new Date(Date.now() + 3600000).toISOString());
  await page
    .getByLabel("Ends at utc (required)")
    .fill(new Date(Date.now() + 7200000).toISOString());
  await page.getByLabel("Purpose (required)").fill("Inspect leak");
  await save(page, "Schedule appointment");
  const current = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  await openAction(page, "maintenance.appointment.finish", f.issue.id, current.appointments[0].id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Reason").fill("Attended inspection");
  await save(page, "Finish appointment");
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.status).toBe("open");
  expect(after.appointments[0].status).toBe("completed");
  expect(after.actualWorkCompleted).toBeNull();
});

test("operational cost replacement and paid Expense association never copy or create spending", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await openAction(page, "maintenance.cost.create", f.issue.id);
  await page.getByLabel("Context kind (required)").selectOption("operator_estimate");
  await page.getByLabel("Label (required)").fill("Rough repair estimate");
  await page.getByLabel("Amount (required)").fill("150.00");
  await page.getByLabel("Observed on (required)").fill(f.property.effectiveLocalDate);
  await save(page, "Record cost context");
  let current = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  const original = current.costContexts[0];
  expect(current.expenseLinks).toHaveLength(0);
  await openAction(page, "maintenance.cost.void", f.issue.id, original.id);
  await page.getByLabel("Reason (required)").fill("Revised estimate, not a payment");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Void cost context");
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Replace cost context", exact: true }).click();
  await expect(page.getByLabel("Context kind (required)")).toHaveValue("operator_estimate");
  await page.getByLabel("Amount (required)").fill("175.00");
  await save(page, "Record cost context");
  const categories = await get<
    Schemas["app__modules__finance__api__expense_router__CategoryResponse"][]
  >(request, "/api/expense-categories");
  const paid = await post<Schemas["ExpenseMutationResponse"]>(request, "/api/expenses", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    propertyId: f.property.id,
    categoryId: categories[0].id,
    payeeName: "Paid repair worker",
    paidByKind: "local_operator",
    paidOn: f.property.effectiveLocalDate,
    amount: "120.00",
    currencyCode: "USD",
    description: "Confirmed paid repair",
  });
  await openAction(page, "maintenance.expense.link", f.issue.id);
  await page.getByLabel("Expense id (required)").selectOption(paid.id);
  await save(page, "Link paid expense");
  current = await get<Schemas["IssueResponse"]>(request, `/api/maintenance-issues/${f.issue.id}`);
  expect(current.costContexts).toHaveLength(2);
  expect(
    current.costContexts.find((item) => item.replacesCostContextId === original.id)?.amountMinor,
  ).toBe(17500);
  expect(current.expenseLinks[0].expenseId).toBe(paid.id);
  await openAction(page, "maintenance.expense.archive", f.issue.id, current.expenseLinks[0].id);
  await page.getByLabel("Reason (required)").fill("Wrong issue association, retain paid spending");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Archive expense association");
  const unchanged = await get<Schemas["ExpenseResponse"]>(request, `/api/expenses/${paid.id}`);
  expect(unchanged.amount).toBe("120.00");
  expect(unchanged.voidedAt).toBeNull();
});

test("appointment rescheduling and follow-up filtering preserve independent issue state", async ({
  page,
  request,
}) => {
  const f = await issue(request),
    start = new Date(Date.now() + 3600000),
    end = new Date(Date.now() + 7200000);
  const appointment = await post<Schemas["AppointmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/appointments`,
    {
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      startsAtUtc: start.toISOString(),
      endsAtUtc: end.toISOString(),
      purpose: "Review leak",
    },
  );
  await openAction(page, "maintenance.appointment.update", f.issue.id, appointment.id);
  await page
    .getByLabel("Starts at utc (required)")
    .fill(new Date(start.getTime() + 86400000).toISOString());
  await page
    .getByLabel("Ends at utc (required)")
    .fill(new Date(end.getTime() + 86400000).toISOString());
  await page
    .getByRole("textbox", { name: "Reschedule reason", exact: true })
    .fill("Owner requested tomorrow");
  await save(page, "Reschedule appointment");
  await openAction(page, "maintenance.follow_up.create", f.issue.id);
  await page.getByLabel("Title (required)").fill("Review leak appointment");
  await save(page, "Create issue follow-up");
  const current = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(current.status).toBe("open");
  expect(current.tasks).toHaveLength(1);
  expect(current.appointments[0].scheduledTimezone).toBe("America/Los_Angeles");
  await page.goto(`/maintenance?propertyId=${f.property.id}`);
  await page
    .getByRole("combobox", { name: "Issue category", exact: true })
    .selectOption("plumbing");
  await page.getByRole("combobox", { name: "Issue priority", exact: true }).selectOption("urgent");
  await page.getByText("More filters", { exact: true }).click();
  await page
    .getByRole("combobox", { name: "Active follow-up Task", exact: true })
    .selectOption("true");
  await expect(page.getByRole("link", { name: new RegExp(f.issue.summary) }).first()).toBeVisible();
  await page
    .getByRole("combobox", { name: "Active follow-up Task", exact: true })
    .selectOption("false");
  await expect(page.getByRole("link", { name: new RegExp(f.issue.summary) })).toHaveCount(0);
  expect(
    (await get<Schemas["IssueResponse"]>(request, `/api/maintenance-issues/${f.issue.id}`)).status,
  ).toBe("open");
});

test("Reported partial work and operator verification remain distinct from resolution", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const provider = await post<Schemas["ProviderMutationResponse"]>(request, "/api/providers", {
    party: {
      partyKind: "organization",
      displayName: `Reported-work provider ${crypto.randomUUID()}`,
    },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const quote = await post<Schemas["QuoteCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/quotes`,
    {
      providerPartyId: provider.party.id,
      label: "Recorded work schedule",
      scopeSummary: "Repair leak",
      amount: "50.00",
      receivedOn: f.property.effectiveLocalDate,
      earliestWorkStartOn: f.property.effectiveLocalDate,
      estimatedWorkFinishOn: f.property.effectiveLocalDate,
      expectedRevision: f.issue.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  );
  const assignment = await post<Schemas["AssignmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/assignments`,
    {
      providerPartyId: provider.party.id,
      quoteId: quote.id,
      expectedRevision: quote.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  );
  await openAction(page, "maintenance.journal.record", f.issue.id);
  await page
    .getByRole("combobox", { name: "Assignment id", exact: true })
    .selectOption(assignment.id);
  await page.getByLabel("Entry kind (required)").selectOption("work_completed");
  await page.getByLabel("Source kind (required)").selectOption("provider_report");
  await page
    .getByLabel("Occurred at utc (required)")
    .fill(new Date(Date.now() - 1000).toISOString());
  await page.getByLabel("Summary (required)").fill("Seal replaced; pipe still leaks");
  await page
    .getByRole("combobox", { name: "Outcome status", exact: true })
    .selectOption("partially_completed");
  await page.getByLabel("Outcome summary", { exact: true }).fill("Return visit needed");
  await page.getByLabel("Follow up required", { exact: true }).check();
  await save(page, "Record work journal entry");
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.status).toBe("open");
  expect(after.workJournalPreview[0].operatorVerified).toBe(false);
  expect(after.assignments[0].endedAt).toBeNull();
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.getByRole("region", { name: "Work journal", exact: true })).toContainText(
    "partially completed",
  );
  await expect(page.getByRole("region", { name: "Work journal", exact: true })).toContainText(
    "Quoted earliest work start on",
  );
  await page.goto(`/providers/${provider.party.id}/details`);
  await expect(
    page.getByRole("region", { name: "Issue-backed Provider work", exact: true }),
  ).toContainText("Seal replaced; pipe still leaks");
  expect(
    (await get<Schemas["ProviderResponse"]>(request, `/api/providers/${provider.party.id}`))
      .workHistory,
  ).toHaveLength(0);
});

test("Journal correction retains evidence and reconciles a lost completion response", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const entry = await post<Schemas["WorkJournalEntryCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/work-journal`,
    {
      entryKind: "work_completed",
      sourceKind: "operator_observation",
      occurredAtUtc: new Date(Date.now() - 60000).toISOString(),
      summary: "Initial completion observation",
      outcomeStatus: "completed",
      outcomeSummary: "Dry at first check",
      operatorVerified: true,
      followUpRequired: false,
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
    },
  );
  const uploaded = await request.post("/api/files", {
    multipart: {
      entity_type: "maintenance_work_journal_entry",
      entity_id: entry.id,
      purpose: "completion_photo",
      idempotency_key: crypto.randomUUID(),
      file: {
        name: "completion.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("Initial observed condition"),
      },
    },
  });
  expect(uploaded.status(), await uploaded.text()).toBe(201);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Archive evidence association", exact: true }).click();
  await page
    .getByLabel("Reason (required)")
    .fill("Keep original evidence only in contextual history");
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(
    page
      .getByRole("region", { name: "Work journal", exact: true })
      .getByRole("link", { name: "Review evidence metadata: completion.txt" }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "Correct work entry: Initial completion observation", exact: true })
    .click();
  await expect(page.getByLabel("Summary (required)")).toHaveValue("Initial completion observation");
  await expect(
    page.getByRole("button", { name: "Record work journal entry", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Summary (required)").fill("Verified partial outcome on recheck");
  await page
    .getByRole("combobox", { name: "Outcome status", exact: true })
    .selectOption("partially_completed");
  await page
    .getByRole("textbox", { name: "Outcome summary", exact: true })
    .fill("Small leak persists");
  await page.getByRole("checkbox", { name: "Follow up required", exact: true }).check();
  await page
    .getByRole("textbox", { name: "Correction reason", exact: true })
    .fill("First check overstated the outcome");
  let calls = 0;
  await page.route(`**/api/maintenance-issues/${f.issue.id}/work-journal`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Record work journal entry", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  expect(calls).toBe(1);
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.status).toBe("open");
  expect(after.workJournalEntryCount).toBe(2);
  expect(after.actualWorkCompleted).toBeNull();
  expect(after.workJournalPreview.find((item) => item.isEffective)?.summary).toBe(
    "Verified partial outcome on recheck",
  );
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(
    page.getByText("Superseded factual entry; retained for context, not current completion.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "Correct work entry: Initial completion observation",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("Journal pages are bounded and terminal history requires explicit confirmation", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  let revision = 1;
  for (let index = 0; index < 21; index++) {
    const entry = await post<Schemas["WorkJournalEntryCommandResponse"]>(
      request,
      `/api/maintenance-issues/${f.issue.id}/work-journal`,
      {
        entryKind: ["work_started", "progress_update", "work_blocked", "general_note"][index % 4],
        sourceKind: "operator_observation",
        occurredAtUtc: new Date(Date.now() - 60000 + index).toISOString(),
        summary: `Bounded work fact ${index}`,
        expectedRevision: revision,
        idempotencyKey: crypto.randomUUID(),
      },
    );
    revision = entry.revision;
  }
  await post(request, `/api/maintenance-issues/${f.issue.id}/resolve`, {
    reason: "Verified separately",
    confirmed: true,
    expectedRevision: revision,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const journal = page.getByRole("region", { name: "Work journal", exact: true });
  await expect(journal.getByRole("article")).toHaveCount(20);
  await journal.getByRole("button", { name: "Older work entries", exact: true }).click();
  await expect(journal.getByRole("article")).toHaveCount(1);
  await expect(journal).toContainText("Bounded work fact 0");
  await journal.getByRole("button", { name: "First work page", exact: true }).click();
  await expect(journal.getByRole("article")).toHaveCount(20);
  await openAction(page, "maintenance.journal.record", f.issue.id);
  await page
    .getByLabel("Occurred at utc (required)")
    .fill(new Date(Date.now() - 1000).toISOString());
  await page.getByLabel("Summary (required)").fill("Historical note after resolution");
  await expect(
    page.getByRole("button", { name: "Record work journal entry", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Historical entry confirmed", { exact: true }).check();
  await save(page, "Record work journal entry");
  expect(
    (await get<Schemas["IssueResponse"]>(request, `/api/maintenance-issues/${f.issue.id}`)).status,
  ).toBe("resolved");
});

test("Conversation draft, optional follow-up and correction retain separate original records", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const ownerId = f.property.ownerships[0].partyId!;
  await page.goto(
    `/conversations?workflow=communication.create&entityType=maintenance_issue&entityId=${f.issue.id}`,
  );
  await page.getByLabel("Subject (required)").fill("Owner called about leak");
  await page.getByLabel("Body (required)").fill("Asked about repair timing");
  await page
    .getByLabel("Occurred at utc (required)")
    .fill(new Date(Date.now() - 60000).toISOString());
  await page.getByLabel("Occurred timezone (required)").fill("America/Los_Angeles");
  await page.getByRole("button", { name: "Add participants entry" }).click();
  await page.getByLabel("Existing identity (required)").fill(ownerId);
  await page.getByLabel("Role (required)").selectOption("reporter");
  await save(page, "Create conversation");
  const href = (await page
    .getByRole("link", { name: "Open current work record" })
    .getAttribute("href"))!;
  const id = new URL(href, "http://local").searchParams.get("id")!;
  const draft = await get<Schemas["CommunicationResponse"]>(request, `/api/communications/${id}`);
  expect(draft.status).toBe("draft");
  expect(draft.followUpTasks).toHaveLength(0);
  await page.goto(href);
  const detail = page.getByRole("region", { name: "Work record", exact: true });
  await expect(detail.getByRole("heading", { name: draft.subject, exact: true })).toBeVisible();
  await expect(detail.getByRole("region", { name: "Message", exact: true })).toContainText(
    draft.body,
  );
  await expect(detail).not.toContainText(id);
  await expect(
    detail.getByRole("link", { name: "← Back to Conversations", exact: true }),
  ).toHaveAttribute("href", "/conversations");
  await expect(detail.getByRole("list", { name: "Conversation participants" })).toContainText(
    draft.participants[0].partyDisplayName,
  );
  expect(await detail.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(
    "rgba(0, 0, 0, 0)",
  );
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await detail.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    );
  }
  await page.getByRole("button", { name: "Edit conversation draft", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Body", exact: true })
    .fill("Draft clarified repair timing");
  await save(page, "Edit conversation draft");
  await page.goto(href);
  await page.getByRole("button", { name: "Record conversation", exact: true }).click();
  await page.getByRole("button", { name: "Add follow up", exact: true }).click();
  await page.getByLabel("Title (required)").fill("Call plumber");
  await save(page, "Record conversation");
  const recorded = await get<Schemas["CommunicationResponse"]>(
    request,
    `/api/communications/${id}`,
  );
  expect(recorded.followUpTasks).toHaveLength(1);
  await page.goto(href);
  await expect(detail.getByRole("region", { name: "Follow-up tasks", exact: true })).toContainText(
    "Call plumber",
  );
  await page.getByRole("button", { name: "Correct recorded conversation", exact: true }).click();
  await page.getByLabel("Subject (required)").fill("Owner asked for tomorrow");
  await page.getByLabel("Correction reason (required)").fill("Correct timing");
  await save(page, "Correct recorded conversation");
  const prior = await get<Schemas["CommunicationResponse"]>(request, `/api/communications/${id}`);
  expect(prior.status).toBe("superseded");
  expect(prior.followUpTasks).toHaveLength(1);
  expect(prior.body).toBe("Draft clarified repair timing");
  await page.goto(`/conversations?record=communication&id=${id}`);
  await expect(page.getByRole("link", { name: "Conversation history" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Correct recorded conversation", exact: true }),
  ).toHaveCount(0);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.getByRole("link", { name: "All linked conversations" })).toBeVisible();
});

test("manual outbound contact selection and local-date timeline filters preserve snapshots", async ({
  page,
  request,
}) => {
  const f = await issue(request),
    ownerId = f.property.ownerships[0].partyId!;
  const owner = await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
    request,
    `/api/parties/${ownerId}`,
  );
  const contact = await post<Schemas["ContactMutationResponse"]>(
    request,
    `/api/parties/${ownerId}/contact-methods`,
    {
      expectedRevision: owner.revision,
      idempotencyKey: crypto.randomUUID(),
      methodKind: "email",
      value: "owner@example.test",
    },
  );
  const occurred = new Date(Date.now() - 60000);
  await page.goto(
    `/conversations?workflow=communication.create&entityType=property&entityId=${f.property.id}`,
  );
  await page.getByLabel("Direction (required)").selectOption("outbound");
  await page.getByLabel("Channel (required)").selectOption("email");
  await page.getByLabel("Subject (required)").fill("Already emailed owner");
  await page.getByLabel("Body (required)").fill("Manual history only; no delivery requested");
  await page.getByLabel("Occurred at utc (required)").fill(occurred.toISOString());
  await page.getByLabel("Occurred timezone (required)").fill("America/Los_Angeles");
  await page.getByLabel("Find participant by name").fill(owner.displayName);
  await page.getByRole("button", { name: "Search participants", exact: true }).click();
  await page
    .getByRole("button", { name: `Add ${owner.displayName} participant`, exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Contact snapshot for participant 1", exact: true })
    .selectOption(contact.id);
  await page.getByLabel("Record", { exact: true }).check();
  await save(page, "Create conversation");
  const href = (await page
    .getByRole("link", { name: "Open current work record" })
    .getAttribute("href"))!;
  const id = new URL(href, "http://local").searchParams.get("id")!;
  const stored = await get<Schemas["CommunicationResponse"]>(request, `/api/communications/${id}`);
  expect(stored.participants[0].contactDisplayValue).toBe("owner@example.test");
  expect(stored.links[0].propertyTimezoneSnapshot).toBe("America/Los_Angeles");
  await page.goto(href);
  const detail = page.getByRole("region", { name: "Work record", exact: true });
  await expect(detail.locator(".conversation-detail-time")).toContainText("America/Los_Angeles");
  await expect(detail.getByRole("list", { name: "Conversation participants" })).toContainText(
    "owner@example.test",
  );
  await expect(detail.getByRole("region", { name: "Related records", exact: true })).toContainText(
    "Related property",
  );
  await page.goto(`/conversations?partyId=${ownerId}&propertyId=${f.property.id}`);
  await page.getByRole("combobox", { name: "Direction", exact: true }).selectOption("outbound");
  await page.getByRole("combobox", { name: "Channel", exact: true }).selectOption("email");
  const localDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(occurred);
  await page.getByLabel("Occurred from (stored local date)").fill(localDate);
  await page.getByLabel("Occurred to (stored local date)").fill(localDate);
  await expect(page.getByRole("link", { name: /Already emailed owner/ })).toBeVisible();
  await page.getByRole("combobox", { name: "Direction", exact: true }).selectOption("inbound");
  await expect(page.getByRole("link", { name: /Already emailed owner/ })).toHaveCount(0);
});

test("lost manual recording response recovers one communication and one follow-up", async ({
  page,
  request,
}) => {
  const f = await issue(request),
    ownerId = f.property.ownerships[0].partyId!;
  await page.goto(
    `/conversations?workflow=communication.create&entityType=maintenance_issue&entityId=${f.issue.id}`,
  );
  await page.getByLabel("Subject (required)").fill("Manual follow-up receipt");
  await page.getByLabel("Body (required)").fill("Operator spoke with owner");
  await page
    .getByLabel("Occurred at utc (required)")
    .fill(new Date(Date.now() - 60000).toISOString());
  await page.getByLabel("Occurred timezone (required)").fill("America/Los_Angeles");
  await page.getByRole("button", { name: "Add participants entry" }).click();
  await page.getByLabel("Existing identity (required)").fill(ownerId);
  await page.getByLabel("Role (required)").selectOption("reporter");
  await page.getByLabel("Record", { exact: true }).check();
  await page.getByRole("button", { name: "Add follow up", exact: true }).click();
  await page.getByLabel("Title (required)").fill("Call owner tomorrow");
  let calls = 0;
  let original: Schemas["CommunicationReceiptResponse"] | undefined;
  await page.route("**/api/communications", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls++;
    original = (await (await route.fetch()).json()) as Schemas["CommunicationReceiptResponse"];
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Create conversation", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  expect(calls).toBe(1);
  expect(original?.followUpTasks).toHaveLength(1);
  const rows = await get<Schemas["CommunicationPage"]>(
    request,
    `/api/communications?entityType=maintenance_issue&entityId=${f.issue.id}`,
  );
  expect(rows.items).toHaveLength(1);
  expect(rows.items[0].id).toBe(original?.id);
});

test("Owner concern resolution preserves claim context and independent follow-up", async ({
  page,
  request,
}) => {
  const property = await home(request);
  const value = await post<Schemas["ConcernMutationResponse"]>(request, "/api/owner-concerns", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerPartyId: property.ownerships[0].partyId,
    propertyId: property.id,
    concernType: "general_rental",
    summary: "Owner asks about repairs",
    description: "Please explain timing",
    raisedAtUtc: property.asOf,
    priority: "high",
  });
  await openAction(page, "owner_concern.follow_up", value.id);
  await page.getByLabel("Title (required)").fill("Reply to Owner");
  await save(page, "Create concern follow-up");
  await openAction(page, "owner_concern.resolved", value.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Summary", { exact: true }).fill("Explained repair timing");
  await save(page, "Resolve owner concern");
  const current = await get<Schemas["ConcernResponse"]>(request, `/api/owner-concerns/${value.id}`);
  expect(current.status).toBe("resolved");
  expect(current.followUpTasks[0].status).toBe("open");
  await page.getByRole("link", { name: "Open current work record" }).click();
  await expect(page.getByRole("link", { name: "Owner context" })).toBeVisible();
});

test("Work directory failures remain unavailable while Task summary can succeed", async ({
  page,
}) => {
  await page.route("**/api/tasks?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "temporary", message: "Directory busy" } }),
    }),
  );
  await page.goto("/tasks");
  await expect(page.getByRole("alert")).toContainText("Directory busy");
  await expect(page.getByRole("region", { name: "Task deadlines and reminders" })).toContainText(
    "As of",
  );
  await expect(
    page.getByText("No matching recorded items on this page.", { exact: false }),
  ).not.toBeVisible();
});

test("Lost lifecycle response reconciles original receipt without another transition", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  let writes = 0;
  await page.route(`**/api/maintenance-issues/${f.issue.id}/resolve`, async (route) => {
    writes++;
    await route.fetch();
    await route.abort("failed");
  });
  await openAction(page, "maintenance.issue.resolve", f.issue.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Reason (required)").fill("Repair reviewed and accepted");
  await page.getByRole("button", { name: "Save resolve maintenance issue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  expect(
    (await get<Schemas["IssueResponse"]>(request, `/api/maintenance-issues/${f.issue.id}`))
      .revision,
  ).toBe(f.issue.revision + 1);
});

test("Child from another issue cannot be mutated through a forged context", async ({
  page,
  request,
}) => {
  const a = await issue(request),
    b = await issue(request);
  const appointment = await post<Schemas["AppointmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${a.issue.id}/appointments`,
    {
      expectedRevision: a.issue.revision,
      idempotencyKey: crypto.randomUUID(),
      startsAtUtc: new Date(Date.now() + 3600000).toISOString(),
      endsAtUtc: new Date(Date.now() + 7200000).toISOString(),
      purpose: "Inspect",
    },
  );
  await openAction(page, "maintenance.appointment.finish", b.issue.id, appointment.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save finish appointment", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("does not belong");
  expect(
    (await get<Schemas["IssueResponse"]>(request, `/api/maintenance-issues/${a.issue.id}`))
      .appointments[0].status,
  ).toBe("scheduled");
});

test("Provider quotes, assignment and ending remain independent of paid expenses", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const provider = await post<Schemas["ProviderMutationResponse"]>(request, "/api/providers", {
    party: { partyKind: "organization", displayName: `Slice53 plumber ${crypto.randomUUID()}` },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await openAction(page, "maintenance.quote.create", f.issue.id);
  await page.getByLabel("Provider party id (required)").selectOption(provider.party.id);
  await page.getByLabel("Label (required)").fill("Sink repair quote");
  await page.getByLabel("Scope summary (required)").fill("Repair leaking pipe");
  await page.getByLabel("Amount (required)").fill("100.00");
  await page.getByLabel("Received on (required)").fill(f.property.effectiveLocalDate);
  await page.getByLabel("Earliest work start on").first().fill(f.property.effectiveLocalDate);
  await expect(
    page.getByRole("button", { name: "Record provider quote", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Estimated work finish on").first().fill(f.property.effectiveLocalDate);
  await save(page, "Record provider quote");
  const quoted = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const comparison = page.getByRole("region", { name: "Quote comparison", exact: true });
  await page.getByText("Compare provider quotes", { exact: true }).click();
  await expect(comparison).toContainText("USD 100.00");
  await comparison
    .getByRole("link", { name: "Review assignment for Sink repair quote", exact: true })
    .click();
  await expect(page.getByLabel("Provider party id (required)")).toHaveValue(provider.party.id);
  await expect(page.getByRole("combobox", { name: "Quote id", exact: true })).toHaveValue(
    quoted.quotes[0].id,
  );
  await save(page, "Assign provider");
  const assigned = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(assigned.expenseLinks).toHaveLength(0);
  expect(assigned.status).toBe("open");
  await openAction(page, "maintenance.assignment.end", f.issue.id, assigned.assignments[0].id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Reason (required)").fill("Engagement ended");
  await save(page, "End provider assignment");
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.assignments[0].endedAt).not.toBeNull();
  expect(after.status).toBe("open");
  await openAction(page, "maintenance.quote.withdraw", f.issue.id, quoted.quotes[0].id);
  await page.getByLabel("Reason (required)").fill("Revised offer received");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Withdraw quote");
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Replace withdrawn quote", exact: true }).click();
  await expect(page.getByLabel("Provider party id (required)")).toHaveValue(provider.party.id);
  await page.getByLabel("Amount (required)").fill("110.00");
  await save(page, "Record provider quote");
  const replaced = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(replaced.quotes).toHaveLength(2);
  expect(
    replaced.quotes.find((item) => item.replacesQuoteId === quoted.quotes[0].id)
      ?.earliestWorkStartOn,
  ).toBe(f.property.effectiveLocalDate);
});

test("avoided Provider direct assignment and lost-response reassignment preserve one current engagement", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const avoided = await post<Schemas["ProviderMutationResponse"]>(request, "/api/providers", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    party: { partyKind: "organization", displayName: `Avoided worker ${crypto.randomUUID()}` },
    selectionStatus: "avoid",
    selectionReason: "Provider-owned confidential context",
  });
  const alternate = await post<Schemas["ProviderMutationResponse"]>(request, "/api/providers", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    party: { partyKind: "organization", displayName: `Alternate worker ${crypto.randomUUID()}` },
  });
  await openAction(page, "maintenance.assignment.create", f.issue.id);
  await page.getByLabel("Provider party id (required)").selectOption(avoided.party.id);
  await expect(
    page.getByRole("region", { name: "Quote and Provider selection review" }),
  ).toContainText("marked avoid");
  await page.getByLabel("Direct assignment confirmed", { exact: true }).check();
  await page
    .getByRole("textbox", { name: "Selection reason", exact: true })
    .fill("Emergency work with known Provider");
  await page.getByLabel("Avoid override confirmed", { exact: true }).check();
  await page
    .getByRole("textbox", { name: "Avoid override reason", exact: true })
    .fill("Explicit exception for this issue only");
  await save(page, "Assign provider");
  const assigned = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(assigned.assignments[0].providerSelectionStatusSnapshot).toBe("avoid");
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Review reassignment", exact: true }).click();
  await page.getByLabel("Provider party id (required)").selectOption(alternate.party.id);
  await page.getByLabel("Direct assignment confirmed", { exact: true }).check();
  await page
    .getByRole("textbox", { name: "Selection reason", exact: true })
    .fill("Confirmed alternate scope");
  await page.getByLabel("Replacement confirmed", { exact: true }).check();
  await page
    .getByRole("textbox", { name: "End reason", exact: true })
    .fill("Engaged alternate Provider");
  let calls = 0;
  await page.route(`**/api/maintenance-issues/${f.issue.id}/assignments`, async (route) => {
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Assign provider", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  const current = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(calls).toBe(1);
  expect(current.assignments).toHaveLength(2);
  expect(current.assignments.filter((item) => !item.endedAt)).toHaveLength(1);
  expect(current.assignments.find((item) => !item.endedAt)?.replacesAssignmentId).toBe(
    assigned.assignments[0].id,
  );
  expect(current.status).toBe("open");
  expect(current.expenseLinks).toHaveLength(0);
  expect(current.tasks).toHaveLength(0);
});

test("Owner concern create and edit use effective relationship validation", async ({
  page,
  request,
}) => {
  const property = await home(request);
  await page.goto("/maintenance?workflow=owner_concern.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page.getByLabel("Owner party id (required)").fill(property.ownerships[0].partyId!);
  await page.getByLabel("Concern type (required)").selectOption("general_rental");
  await page.getByLabel("Summary (required)").fill("Owner requests an update");
  await page.getByLabel("Description (required)").fill("Manual owner request");
  await page.getByLabel("Raised at utc (required)").fill(property.asOf);
  await save(page, "Record owner concern");
  const id = new URL(
    (await page.getByRole("link", { name: "Open current work record" }).getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  await openAction(page, "owner_concern.patch", id);
  await page.getByRole("textbox", { name: "Summary", exact: true }).fill("Updated owner request");
  await save(page, "Edit owner concern");
  expect(
    (await get<Schemas["ConcernResponse"]>(request, `/api/owner-concerns/${id}`)).summary,
  ).toBe("Updated owner request");
});

test("Owner concern duplicate review requires an independent reason and never merges", async ({
  page,
  request,
}) => {
  const property = await home(request);
  const original = await post<Schemas["ConcernMutationResponse"]>(request, "/api/owner-concerns", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerPartyId: property.ownerships[0].partyId,
    propertyId: property.id,
    concernType: "general_rental",
    summary: "Original rental concern",
    description: "Original claim",
    raisedAtUtc: property.asOf,
  });
  await page.goto("/maintenance?workflow=owner_concern.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page.getByLabel("Owner party id (required)").fill(property.ownerships[0].partyId!);
  await page.getByLabel("Concern type (required)").selectOption("general_rental");
  await page.getByLabel("Summary (required)").fill("Independent owner request");
  await page.getByLabel("Description (required)").fill("A distinct rental question");
  await page.getByLabel("Raised at utc (required)").fill(property.asOf);
  await page.getByRole("button", { name: "Record owner concern", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Possible duplicate concerns", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: `Review existing concern ${original.id}`, exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Start independent concern review", exact: true }).click();
  await page.getByRole("checkbox", { name: "Duplicate confirmed", exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Record owner concern", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Duplicate reason", exact: true })
    .fill("Separate question, not a correction of the original");
  await save(page, "Record owner concern");
  const current = await get<Schemas["ConcernPage"]>(
    request,
    `/api/owner-concerns?propertyId=${property.id}`,
  );
  expect(current.items).toHaveLength(2);
  expect(current.items.find((item) => item.id === original.id)?.summary).toBe(
    "Original rental concern",
  );
});

test("Archived Owner concern selection requires explicit backdated confirmation", async ({
  page,
  request,
}) => {
  const property = await post<Schemas["PropertyMutationResponse"]>(
    request,
    "/__test__/historical-owner",
    {},
  );
  const ownerId = property.ownerships[0].partyId!;
  const owner = await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
    request,
    `/api/parties/${ownerId}`,
  );
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const ended = await request.put(`/api/properties/${property.id}/ownerships`, {
    data: {
      expectedPropertyRevision: property.propertyRevision,
      idempotencyKey: crypto.randomUUID(),
      effectiveOn: today,
      ownerships: [{ ownerKind: "local_operator" }],
    },
  });
  expect(ended.ok(), await ended.text()).toBe(true);
  await post(request, `/api/parties/${ownerId}/archive`, {
    expectedRevision: owner.revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
  });
  await page.goto("/maintenance?workflow=owner_concern.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page.getByLabel("Owner party id (required)").fill(ownerId);
  await page.getByLabel("Concern type (required)").selectOption("general_rental");
  await page.getByLabel("Summary (required)").fill("Historical Owner question");
  await page.getByLabel("Description (required)").fill("Backdated client-owner context");
  await page
    .getByLabel("Raised at utc (required)")
    .fill(`${property.effectiveLocalDate}T20:00:00Z`);
  await expect(
    page.getByRole("region", { name: "Owner concern review", exact: true }),
  ).toContainText("Archived — historical selection required");
  await page.getByRole("checkbox", { name: "Historical selection confirmed", exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Record owner concern", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Historical selection reason", exact: true })
    .fill("Raised while this Owner managed the Property");
  await save(page, "Record owner concern");
  const concerns = await get<Schemas["ConcernPage"]>(
    request,
    `/api/owner-concerns?propertyId=${property.id}`,
  );
  expect(concerns.items).toHaveLength(1);
  expect(concerns.items[0].ownerPartyId).toBe(ownerId);
});

test("Vacancy concern requires a matching Space and retains observed status rather than changing it", async ({
  page,
  request,
}) => {
  const property = await home(request);
  const before = await get<Schemas["SpaceStatusResponse"]>(
    request,
    `/api/spaces/${property.spaces[0].id}/status`,
  );
  await page.goto("/maintenance?workflow=owner_concern.create");
  await page.getByLabel("Property id (required)").selectOption(property.id);
  await page.getByLabel("Owner party id (required)").fill(property.ownerships[0].partyId!);
  await page.getByLabel("Concern type (required)").selectOption("vacancy");
  await page.getByLabel("Summary (required)").fill("Owner asks about vacancy");
  await page.getByLabel("Description (required)").fill("Current vacancy context only");
  await page.getByLabel("Raised at utc (required)").fill(property.asOf);
  await expect(
    page.getByRole("button", { name: "Record owner concern", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("combobox", { name: "Space id", exact: true })
    .selectOption(property.spaces[0].id);
  await save(page, "Record owner concern");
  const after = await get<Schemas["SpaceStatusResponse"]>(
    request,
    `/api/spaces/${property.spaces[0].id}/status`,
  );
  expect(after.revision).toBe(before.revision);
  expect(after.currentOccupancy).toEqual(before.currentOccupancy);
  expect(after.availability).toEqual(before.availability);
});

test("Dismissed Owner concern target correction preserves its predecessor and original result", async ({
  page,
  request,
}) => {
  const property = await home(request),
    correctedProperty = await home(request);
  const original = await post<Schemas["ConcernMutationResponse"]>(request, "/api/owner-concerns", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerPartyId: property.ownerships[0].partyId,
    propertyId: property.id,
    concernType: "general_rental",
    summary: "Wrong property selected",
    description: "Rental context correction",
    raisedAtUtc: property.asOf,
  });
  await openAction(page, "owner_concern.dismissed", original.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page
    .getByRole("textbox", { name: "Summary", exact: true })
    .fill("Incorrect target; retained rather than erased");
  await save(page, "Dismiss owner concern");
  await page.goto(`/maintenance?record=concern&id=${original.id}`);
  await page.getByRole("link", { name: "Correct dismissed concern context", exact: true }).click();
  await expect(page.getByLabel("Summary (required)")).toHaveValue("Wrong property selected");
  await page.getByLabel("Property id (required)").selectOption(correctedProperty.id);
  await page.getByLabel("Owner party id (required)").fill(correctedProperty.ownerships[0].partyId!);
  await page.getByLabel("Raised at utc (required)").fill(correctedProperty.asOf);
  await page.getByLabel("Summary (required)").fill("Correct property selected");
  await save(page, "Record owner concern");
  const current = await get<Schemas["ConcernResponse"]>(
    request,
    `/api/owner-concerns/${original.id}`,
  );
  expect(current.status).toBe("dismissed");
  expect(current.successor?.summary).toBe("Correct property selected");
  await page.goto(`/maintenance?record=concern&id=${original.id}`);
  await expect(
    page.getByRole("link", { name: "Correct dismissed concern context", exact: true }),
  ).toHaveCount(0);
});

test("Lost concern follow-up recovers one Task while recorded conversation history remains independent", async ({
  page,
  request,
}) => {
  const property = await home(request);
  const concern = await post<Schemas["ConcernMutationResponse"]>(request, "/api/owner-concerns", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerPartyId: property.ownerships[0].partyId,
    propertyId: property.id,
    concernType: "general_rental",
    summary: "Owner discussion",
    description: "Follow up on context",
    raisedAtUtc: property.asOf,
  });
  await openAction(page, "owner_concern.follow_up", concern.id);
  await page.getByLabel("Title (required)").fill("Respond to concern");
  let calls = 0;
  await page.route(`**/api/owner-concerns/${concern.id}/follow-ups`, async (route) => {
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Create concern follow-up", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  expect(calls).toBe(1);
  const conversation = await post<Schemas["CommunicationReceiptResponse"]>(
    request,
    "/api/communications",
    {
      direction: "inbound",
      channel: "phone",
      subject: "Owner context call",
      body: "Recorded rental discussion",
      occurredAtUtc: property.asOf,
      occurredTimezone: "America/Los_Angeles",
      record: true,
      participants: [{ partyId: property.ownerships[0].partyId, role: "sender" }],
      links: [{ entityType: "owner_concern", entityId: concern.id }],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  );
  const current = await get<Schemas["ConcernResponse"]>(
    request,
    `/api/owner-concerns/${concern.id}`,
  );
  expect(current.status).toBe("open");
  expect(current.revision).toBe(2);
  expect(current.followUpTasks).toHaveLength(1);
  await page.goto(`/maintenance?record=concern&id=${concern.id}`);
  await page
    .getByRole("region", { name: "Recent concern conversations", exact: true })
    .getByRole("link", { name: "Owner context call", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(conversation.id));
});

test("Task start, cancellation, reopening and deletion require explicit independent commands", async ({
  page,
  request,
}) => {
  const original = await task(request);
  for (const action of ["start", "cancel", "reopen", "delete"]) {
    await openAction(page, `task.${action}`, original.id);
    if (action !== "start") await page.getByLabel("I confirm this lifecycle change").check();
    await save(page, `${action[0].toUpperCase()}${action.slice(1)} task`);
  }
  const deleted = await request.get(`/api/tasks/${original.id}`);
  expect(deleted.status()).toBe(404);
});

test("Evidence attachment is a separate command and unavailable data cannot be opened", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.goto(
    `/money?workflow=file.upload&entityType=maintenance_issue&entityId=${f.issue.id}`,
  );
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "leak.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Photographic observation described here"),
  });
  await save(page, "Attach supporting evidence");
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.files[0].available).toBe(true);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Review evidence metadata: leak.txt" }).click();
  await expect(page.getByRole("link", { name: "Download leak.txt" })).toBeVisible();
  await page.route(`**/api/files/${after.files[0].fileId}`, async (route) => {
    const response = await route.fetch();
    const metadata = (await response.json()) as Schemas["FileMetadataResponse"];
    await route.fulfill({ response, json: { ...metadata, storageState: "missing" } });
  });
  await page.reload();
  await expect(page.getByText("Content unavailable; opening disabled.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download leak.txt" })).not.toBeVisible();
  await page.unroute(`**/api/files/${after.files[0].fileId}`);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await page.getByRole("link", { name: "Archive evidence association", exact: true }).click();
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Unrelated attachment; retain original history");
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  const retained = await get<Schemas["FileMetadataResponse"]>(
    request,
    `/api/files/${after.files[0].fileId}`,
  );
  expect(retained.links[0].archivedAt).toBeTruthy();
  expect(retained.links[0].archiveReason).toBe("Unrelated attachment; retain original history");
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.getByRole("link", { name: "Review evidence metadata: leak.txt" })).toHaveCount(
    0,
  );
});

test("Work paging is bounded without per-row HTTP detail requests", async ({ page, request }) => {
  const original = await task(request);
  let details = 0;
  page.on("request", (req) => {
    if (/\/api\/tasks\/[0-9a-f-]{36}(?:\?|$)/.test(req.url())) details++;
  });
  await page.goto("/tasks");
  await expect(page.getByRole("region", { name: "Work directory" })).toContainText(original.title);
  expect(details).toBe(0);
});

test("Task pages preserve contextual membership without gaps or duplicate records", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const ids = new Set<string>();
  for (let index = 0; index < 26; index++) {
    const item = await post<Schemas["TaskCreationResponse"]>(request, "/api/tasks", {
      title: `Context task ${index}`,
      relatedEntityType: "maintenance_issue",
      relatedEntityId: f.issue.id,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    ids.add(item.id);
  }
  await page.goto(`/tasks?entityType=maintenance_issue&entityId=${f.issue.id}`);
  const directory = page.getByRole("region", { name: "Work directory" });
  await expect(directory.getByRole("link", { name: /^Context task / })).toHaveCount(25);
  const seen = new Set(
    await directory
      .getByRole("link", { name: /^Context task / })
      .evaluateAll((links) =>
        links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("id")!),
      ),
  );
  await directory.getByRole("button", { name: "Next work page" }).click();
  await expect(directory.getByRole("link", { name: /^Context task / })).toHaveCount(1);
  const last = new URL(
    (await directory.getByRole("link", { name: /^Context task / }).getAttribute("href"))!,
    "http://local",
  ).searchParams.get("id")!;
  expect(seen.has(last)).toBe(false);
  seen.add(last);
  expect(seen).toEqual(ids);
});

test("Appointment cancellation requires a reason and does not cancel its issue", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const appointment = await post<Schemas["AppointmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/appointments`,
    {
      expectedRevision: f.issue.revision,
      idempotencyKey: crypto.randomUUID(),
      startsAtUtc: new Date(Date.now() + 3600000).toISOString(),
      endsAtUtc: new Date(Date.now() + 7200000).toISOString(),
      purpose: "Inspect",
    },
  );
  await openAction(page, "maintenance.appointment.finish", f.issue.id, appointment.id);
  await page.getByLabel("Cancelled", { exact: true }).check();
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save finish appointment", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Cancellation requires a reason");
  await page.getByLabel("Reason", { exact: true }).fill("Access unavailable");
  await save(page, "Finish appointment");
  const after = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(after.status).toBe("open");
  expect(after.appointments[0].status).toBe("cancelled");
});

test("Narrow Task actions are keyboard accessible without hiding their deadline", async ({
  page,
  request,
}) => {
  const value = await task(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/tasks?record=task&id=${value.id}`);
  await expect(page.getByText(value.dueAtUtc!, { exact: true })).toBeVisible();
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Set waiting context", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Set waiting context" })).toBeVisible();
  await expect(page.getByLabel("Waiting for label")).toBeEnabled();
});

test("Lost Task deletion can resume and reconcile after its source is unavailable", async ({
  page,
  request,
}) => {
  const original = await task(request);
  let writes = 0;
  await page.route(`**/api/tasks/${original.id}`, async (route) => {
    if (route.request().method() !== "DELETE") return route.continue();
    writes++;
    await route.fetch();
    await route.abort("failed");
  });
  await openAction(page, "task.delete", original.id);
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save delete task", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  const recoveries = await get<Schemas["RecoveryPage"]>(
    request,
    "/api/operator/recovery?limit=100",
  );
  const saved = recoveries.items.find(
    (item) => item.formKey === "task.delete" && item.sourceId === original.id,
  )!;
  expect(saved).toBeDefined();
  await page.goto(`/tasks?workflow=task.delete&target=${original.id}&resume=${saved.id}`);
  await expect(page.getByRole("alert")).toContainText("Current source unavailable");
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
});
