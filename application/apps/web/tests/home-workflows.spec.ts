import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
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
async function property(request: APIRequestContext) {
  return post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Home workflow ${crypto.randomUUID()}`,
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
          displayName: `Home Owner ${crypto.randomUUID()}`,
        },
      },
    ],
  });
}
async function issue(request: APIRequestContext) {
  const home = await property(request);
  const issue = await post<Schema["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
    propertyId: home.id,
    summary: `Home leak ${crypto.randomUUID()}`,
    description: "Inspect water leak",
    category: "plumbing",
    priority: "urgent",
    reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
    reporter: { role: "manager", subjectKind: "local_operator" },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  return { home, issue };
}
async function expanded(
  page: Page,
  propertyId: string,
  title: string,
  collection = "needs_action",
) {
  await page.goto(`/home/collections/${collection}?propertyId=${propertyId}`);
  const row = page.getByRole("button", { name: new RegExp(title) });
  await row.click();
  return page.getByRole("region", { name: "Source workflow and grouped actions", exact: true });
}
async function action(page: Page, title: string, group = "Actions") {
  await page.getByText(group, { exact: true }).click();
  await page.getByRole("link", { name: title, exact: true }).click();
}
async function save(page: Page, title: string) {
  await test.step(title, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
}

test("Home Task actions reload current state, retain input on conflict, reconcile one lost result and keep return context", async ({
  page,
  request,
}) => {
  const home = await property(request);
  const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
    title: `Home Task ${crypto.randomUUID()}`,
    relatedEntityType: "property",
    relatedEntityId: home.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const panel = await expanded(page, home.id, task.title);
  const homeUrl = page.url();
  await panel.getByRole("link", { name: "View", exact: true }).click();
  await action(page, "Complete task");
  await page.getByLabel("Outcome note", { exact: true }).fill("Confirmed by telephone");
  await page.getByLabel("I confirm this lifecycle change").check();
  await post(request, `/api/tasks/${task.id}/start`, {
    expectedRevision: task.revision,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.getByRole("button", { name: "Save complete task", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Outcome note", exact: true })).toHaveValue(
    "Confirmed by telephone",
  );
  await expect(
    page.getByRole("button", { name: "Review current source", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page
    .getByRole("button", { name: "Keep my edits with this reviewed revision", exact: true })
    .click();
  let calls = 0;
  await page.route(`**/api/tasks/${task.id}/complete`, async (route) => {
    calls += 1;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save complete task", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  expect(calls).toBe(1);
  const current = await get<Schema["TaskResponse"]>(request, `/api/tasks/${task.id}`);
  expect(current.status).toBe("completed");
  expect(current.outcomeNote).toBe("Confirmed by telephone");
  expect(current.revision).toBe(task.revision + 2);
  await page.getByRole("link", { name: "Return to current record", exact: true }).click();
  await expect(page.getByRole("heading", { name: task.title, exact: true })).toBeVisible();
  await page
    .getByRole("link", { name: "Return to Home collection or preview", exact: true })
    .click();
  await expect(page).toHaveURL(homeUrl);
});

test("grouped previews expose nested reminders and every linked Task through bounded source pages", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const tasks: Schema["TaskResponse"][] = [];
  for (let index = 0; index < 26; index += 1) {
    const linked = await post<Schema["TaskSummaryCommandResponse"]>(
      request,
      `/api/maintenance-issues/${f.issue.id}/follow-ups`,
      {
        title: `Home grouped ${String(index).padStart(2, "0")}`,
        expectedRevision: f.issue.revision + index,
        idempotencyKey: crypto.randomUUID(),
      },
    );
    tasks.push(await get<Schema["TaskResponse"]>(request, `/api/tasks/${linked.id}`));
  }
  // Every Task has a due reminder, so any bounded child preview exercises nesting.
  for (const task of tasks)
    await post(request, `/api/tasks/${task.id}/reminders`, {
      remindAtUtc: new Date(Date.now() - 60000).toISOString(),
      expectedRevision: task.revision,
      idempotencyKey: crypto.randomUUID(),
    });
  let detailReads = 0;
  page.on("request", (entry) => {
    if (new URL(entry.url()).pathname === `/api/maintenance-issues/${f.issue.id}`) detailReads += 1;
  });
  const panel = await expanded(page, f.home.id, f.issue.summary);
  await expect(
    panel.getByRole("link", { name: "Review linked Task and actions", exact: true }),
  ).toHaveCount(3);
  await expect(
    panel.getByRole("link", { name: "Review reminder and actions", exact: true }).first(),
  ).toBeVisible();
  expect(detailReads).toBe(0); // Disclosure does not fetch sensitive owning detail.
  await panel
    .getByRole("link", { name: "Review all linked Tasks and their reminders", exact: true })
    .click();
  const directory = page.getByRole("region", { name: "Work directory", exact: true });
  await expect(directory.locator("ul > li > a")).toHaveCount(25);
  const first = await directory.locator("ul > li > a").allTextContents();
  await page.getByRole("button", { name: "Next work page", exact: true }).click();
  await expect(directory.locator("ul > li > a")).toHaveCount(1);
  const last = await directory.locator("ul > li > a").allTextContents();
  expect(new Set([...first, ...last]).size).toBe(26);
  await directory.locator("ul > li > a").click();
  const reminders = page.getByRole("region", { name: "Task reminders", exact: true });
  await reminders.getByText(/^Reminder actions/).click();
  await reminders.getByRole("link", { name: "Acknowledge reminder", exact: true }).click();
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Acknowledge reminder");
  await expect(
    page.getByRole("link", { name: "Return to Home collection or preview", exact: true }),
  ).toBeVisible();
  const current = await get<Schema["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(current.status).toBe("open");
  expect(current.actualWorkCompleted).toBeNull();
});

test("Home appointment opens its owning issue and records attendance without resolving repair work", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const appointment = await post<Schema["AppointmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/appointments`,
    {
      expectedRevision: f.issue.revision,
      idempotencyKey: crypto.randomUUID(),
      startsAtUtc: new Date(Date.now() + 3600000).toISOString(),
      endsAtUtc: new Date(Date.now() + 7200000).toISOString(),
      purpose: "Home appointment inspection",
    },
  );
  const panel = await expanded(page, f.home.id, f.issue.summary, "appointments");
  await expect(panel.getByRole("link", { name: "View", exact: true })).toHaveAttribute(
    "href",
    new RegExp(`#appointment-${appointment.id}$`),
  );
  await panel.getByRole("link", { name: "View", exact: true }).click();
  await page.getByText("Actions for Home appointment inspection", { exact: true }).click();
  await page.getByRole("link", { name: "Finish appointment", exact: true }).click();
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByLabel("Reason", { exact: true }).fill("Attended; repair remains outstanding");
  await save(page, "Finish appointment");
  const current = await get<Schema["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  expect(current.appointments[0].status).toBe("completed");
  expect(current.status).toBe("open");
  expect(current.actualWorkCompleted).toBeNull();
});

test("Home coverage action uses the source review receipt and preserves return context", async ({
  page,
  request,
}) => {
  const home = await property(request);
  await page.goto(`/home/collections/information_review?propertyId=${home.id}`);
  await page.getByRole("button", { name: /maintenance/i }).click();
  await page.getByRole("link", { name: "Review information", exact: true }).click();
  await page.getByRole("button", { name: "Review maintenance information", exact: true }).click();
  await page.getByLabel("Review reason").fill("Reviewed recorded maintenance responsibilities");
  await page.getByRole("button", { name: "Record review", exact: true }).click();
  await expect(page.getByText(/Original review .*recorded/)).toBeVisible();
  const current = await get<Schema["CoverageResult"]>(
    request,
    `/api/operator/coverage/property/${home.id}/maintenance`,
  );
  expect(current.state).toBe("recorded");
  await page
    .getByRole("link", { name: "Return to Home collection or preview", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/home/collections/information_review\\?propertyId=${home.id}`),
  );
});

async function leaseFixture(request: APIRequestContext, fixedTerm = false) {
  const home = await property(request),
    today = home.effectiveLocalDate;
  const end = new Date(`${today}T12:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 10);
  const endsOn = end.toISOString().slice(0, 10);
  const tenant = await post<Schema["TenantMutationResponse"]>(request, "/api/tenants", {
    partyKind: "individual",
    displayName: `Home tenant ${crypto.randomUUID()}`,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const lease = await post<Schema["LeaseMutationResponse"]>(request, "/api/leases", {
    expectedLeaseRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    spaceId: home.spaces[0].id,
    leaseKind: "residential",
    contractStartsOn: `${today.slice(0, 7)}-01`,
    ...(fixedTerm ? { contractEndsOn: endsOn } : {}),
    occupancyStartsOn: today,
    initialTerm: {
      baseRentMinor: 100000,
      currencyCode: "USD",
      paymentFrequency: "monthly",
      paymentDueDay: 1,
      agreedSecurityDepositMinor: 100000,
    },
    participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
  });
  await post(request, `/api/leases/${lease.id}/execute`, {
    expectedLeaseRevision: lease.leaseRevision,
    expectedRevision: home.spaces[0].revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    executedOn: today,
  });
  return { home, lease, today, endsOn };
}

async function rentFixture(request: APIRequestContext) {
  const { home, lease, today } = await leaseFixture(request);
  const schedule = await post<Schema["SynchronizeResponse"]>(
    request,
    `/api/leases/${lease.id}/rent-expectations/synchronize`,
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseTermId: lease.terms[0].id,
      throughOn: new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) + 1, 0))
        .toISOString()
        .slice(0, 10),
      scheduleAnchorOn: `${today.slice(0, 7)}-01`,
    },
  );
  return { home, lease, today, expectation: schedule.items[0] };
}

test("Home lease review opens the source and records a renewal without implying executed continuation", async ({
  page,
  request,
}) => {
  const f = await leaseFixture(request, true);
  const panel = await expanded(page, f.home.id, `Lease ending ${f.endsOn}`);
  await panel.getByRole("link", { name: "Review lease", exact: true }).click();
  const lastCoveredDay = new Date(`${f.endsOn}T12:00:00Z`);
  lastCoveredDay.setUTCDate(lastCoveredDay.getUTCDate() - 1);
  await expect(page.getByRole("region", { name: "Lease milestones", exact: true })).toContainText(
    new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
      lastCoveredDay,
    ),
  );
  await page
    .getByRole("navigation", { name: "Lease actions", exact: true })
    .getByRole("link", { name: "Add renewal option", exact: true })
    .click();
  await page.getByLabel("Proposed starts on (required)").fill(f.endsOn);
  await save(page, "Add renewal option");
  const current = await get<Schema["LeaseResponse"]>(request, `/api/leases/${f.lease.id}`);
  expect(current.status).toBe("executed");
  expect(current.renewalOptions).toHaveLength(1);
  expect(current.renewalOptions[0].status).toBe("open");
  await expect(
    page.getByRole("link", { name: "Return to Home collection or preview", exact: true }),
  ).toBeVisible();
});

test("a failed current-source read offers no lifecycle commands and keeps Home return navigation", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const panel = await expanded(page, f.home.id, f.issue.summary);
  await page.route(`**/api/maintenance-issues/${f.issue.id}`, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: { code: "maintenance_unavailable", message: "Current issue unavailable" } },
    }),
  );
  await panel.getByRole("link", { name: "Review issue", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Current issue unavailable");
  await expect(page.getByText("Actions", { exact: true })).toHaveCount(0);
  await page
    .getByRole("link", { name: "Return to Home collection or preview", exact: true })
    .click();
  await expect(page.getByRole("button", { name: new RegExp(f.issue.summary) })).toBeVisible();
});

test("Home payment uses current allocations and an interrupted response reconciles exactly one receipt", async ({
  page,
  request,
}) => {
  const f = await rentFixture(request);
  await page.goto(`/home/collections/needs_action?propertyId=${f.home.id}`);
  const response = await get<Schema["CollectionResponse"]>(
    request,
    `/api/operator/home/items?collection=needs_action&propertyId=${f.home.id}`,
  );
  if (response.result.status !== "available") throw new Error("Unavailable source fixture");
  const row = response.result.items.find((item) => item.source.kind === "rent_expectation")!;
  expect(row).toBeTruthy();
  await page.getByRole("button", { name: new RegExp(row.title) }).click();
  await page.getByRole("link", { name: "Record payment", exact: true }).click();
  await action(page, "Record rent receipt", "Rent ledger actions");
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  let calls = 0;
  await page.route("**/api/rent-receipts", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls += 1;
    const result = await route.fetch();
    expect(result.ok(), await result.text()).toBe(true);
    await route.abort();
  });
  await page.getByRole("button", { name: "Record rent receipt", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  const receipts = await get<Schema["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(receipts.items).toHaveLength(1);
  expect(receipts.items[0].allocations[0].expectationId).toBe(f.expectation.id);
  expect(calls).toBe(1);
  await expect(
    page.getByRole("link", { name: "Return to Home collection or preview", exact: true }),
  ).toBeVisible();
});

test("Home Owner review actions persist independently of Finance and linked follow-up Tasks", async ({
  page,
  request,
}) => {
  const f = await rentFixture(request);
  const report = await post<Schema["OwnerRentReportMutationResponse"]>(
    request,
    "/api/owner-rent-reports",
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseId: f.lease.id,
      ownerPartyId: f.home.ownerships[0].partyId,
      receivedOn: f.today,
      amountMinor: 12345,
      paymentMethodKind: "cash",
      reportedAtUtc: new Date().toISOString(),
    },
  );
  const concern = await post<Schema["ConcernMutationResponse"]>(request, "/api/owner-concerns", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerPartyId: f.home.ownerships[0].partyId,
    propertyId: f.home.id,
    concernType: "general_rental",
    summary: `Home concern ${crypto.randomUUID()}`,
    description: "Review the Owner claim",
    raisedAtUtc: f.home.asOf,
  });
  let panel = await expanded(page, f.home.id, concern.summary);
  await panel.getByRole("link", { name: "Review concern", exact: true }).click();
  await action(page, "Create concern follow-up");
  await page.getByLabel("Title (required)").fill("Review Owner request");
  await save(page, "Create concern follow-up");
  const current = await get<Schema["ConcernResponse"]>(
    request,
    `/api/owner-concerns/${concern.id}`,
  );
  expect(current.status).toBe("open");
  expect(current.followUpTasks).toHaveLength(1);
  await page
    .getByRole("link", { name: "Return to Home collection or preview", exact: true })
    .click();
  const rows = await get<Schema["CollectionResponse"]>(
    request,
    `/api/operator/home/items?collection=needs_action&propertyId=${f.home.id}`,
  );
  if (rows.result.status !== "available") throw new Error("Unavailable source fixture");
  const row = rows.result.items.find((item) => item.source.id === report.id)!;
  panel = await expanded(page, f.home.id, row.title);
  await panel.getByRole("link", { name: "Review report", exact: true }).click();
  await action(page, "Reject owner rent report");
  await page.getByLabel("Reason (required)").fill("Owner withdrew this claim");
  await page.getByLabel("I confirm this lifecycle change").check();
  await save(page, "Reject owner rent report");
  const rejected = await get<Schema["OwnerRentReportResponse"]>(
    request,
    `/api/owner-rent-reports/${report.id}`,
  );
  expect(rejected.status).toBe("rejected");
  expect(
    (await get<Schema["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
});
