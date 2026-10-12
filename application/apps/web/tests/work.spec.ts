import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

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
  await page.getByRole("button", { name: `Save ${title.toLowerCase()}`, exact: true }).click();
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

test("Task creation uses original recovery identity and saved forms survive reload", async ({
  page,
  request,
}) => {
  await page.goto("/tasks?workflow=task.create");
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
  await page.getByRole("button", { name: "Save edit task", exact: true }).click();
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
  await page.getByLabel("Summary (required)").fill("Browser sink leak");
  await page.getByLabel("Description (required)").fill("Water visible");
  await page.getByLabel("Category (required)").selectOption("plumbing");
  await page
    .getByLabel("Reported at utc (required)")
    .fill(new Date(Date.now() - 60000).toISOString());
  await save(page, "Report maintenance issue");
  await page.getByRole("link", { name: "Open current work record" }).click();
  await expect(page.getByRole("heading", { name: "Browser sink leak" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Property context" })).toBeVisible();
  await expect(page.getByText("local operator", { exact: true })).toBeVisible();
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
  const assignment = await post<Schemas["AssignmentCommandResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}/assignments`,
    {
      providerPartyId: provider.party.id,
      directAssignmentConfirmed: true,
      selectionReason: "Existing trusted provider for this repair",
      expectedRevision: f.issue.revision,
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
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.getByRole("region", { name: "Work journal", exact: true })).toContainText(
    "partially completed",
  );
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
  await openAction(page, "communication.draft.record", id);
  await page.getByRole("button", { name: "Add follow up", exact: true }).click();
  await page.getByLabel("Title (required)").fill("Call plumber");
  await save(page, "Record conversation");
  const recorded = await get<Schemas["CommunicationResponse"]>(
    request,
    `/api/communications/${id}`,
  );
  expect(recorded.followUpTasks).toHaveLength(1);
  await openAction(page, "communication.correct", id);
  await page.getByLabel("Subject (required)").fill("Owner asked for tomorrow");
  await page.getByLabel("Correction reason (required)").fill("Correct timing");
  await save(page, "Correct recorded conversation");
  const prior = await get<Schemas["CommunicationResponse"]>(request, `/api/communications/${id}`);
  expect(prior.status).toBe("superseded");
  expect(prior.followUpTasks).toHaveLength(1);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.getByRole("link", { name: "All linked conversations" })).toBeVisible();
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
  await save(page, "Record provider quote");
  const quoted = await get<Schemas["IssueResponse"]>(
    request,
    `/api/maintenance-issues/${f.issue.id}`,
  );
  await openAction(page, "maintenance.assignment.create", f.issue.id);
  await page.getByLabel("Provider party id (required)").selectOption(provider.party.id);
  await page
    .getByRole("combobox", { name: "Quote id", exact: true })
    .selectOption(quoted.quotes[0].id);
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
