import { expect, test } from "@playwright/test";
import { issue, lease, property, post, type Schema } from "./helpers/workflow-contracts";

test.use({ timezoneId: "UTC", extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("new appointment and issue follow-up use the property zone instead of the browser zone", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  expect(f.property.timeZone).toBe("America/Los_Angeles");
  await page.goto(`/maintenance?workflow=maintenance.appointment.create&target=${f.issue.id}`);
  await expect(page.getByLabel("Time zone", { exact: true })).toHaveValue(f.property.timeZone);
  await expect(page.getByLabel("Starts at (required)")).toBeEnabled();
  await page.getByLabel("Starts at (required)").fill("2027-05-01T10:30");
  await page.getByLabel("Purpose (required)").fill("Property-local visit");
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/api/maintenance-issues/${f.issue.id}/appointments`),
  );
  await page.getByRole("button", { name: "Schedule appointment", exact: true }).click();
  const saved = (await (await response).json()) as Schema["AppointmentCommandResponse"];
  expect(saved.startsAtUtc).toBe("2027-05-01T17:30:00Z");
  expect(saved.scheduledTimezone).toBe(f.property.timeZone);
  await expect(page.locator(".saved-item")).toContainText(
    "May 1, 2027, 10:30 AM · America/Los_Angeles",
  );
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(page.locator(".maintenance-appointment time")).toHaveText(
    "May 1, 2027, 10:30 AM · America/Los_Angeles",
  );
  await page.goto(`/maintenance?workflow=maintenance.follow_up.create&target=${f.issue.id}`);
  await expect(page.getByLabel("Due time zone", { exact: true })).toHaveValue(f.property.timeZone);
  await page.getByLabel("Title (required)").fill("Check the visit");
  await page.getByLabel("Due at", { exact: true }).fill("2027-05-02T10:30");
  const followUp = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/api/maintenance-issues/${f.issue.id}/follow-ups`),
  );
  await page.getByRole("button", { name: "Create issue follow-up", exact: true }).click();
  expect((await followUp).request().postDataJSON()).toMatchObject({
    dueTimezone: f.property.timeZone,
    dueAtUtc: "2027-05-02T17:30:00Z",
  });
});

test("task property selection changes only the default and recovered overrides remain unchanged", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.goto("/tasks?workflow=task.create");
  await page.getByLabel("Title (required)", { exact: true }).fill("Property-local task");
  await page.getByLabel("No due date", { exact: true }).uncheck();
  await page.getByText("Optional Task details", { exact: true }).click();
  await expect(page.getByLabel("Due time zone", { exact: true })).toHaveValue("UTC");
  await page.getByLabel("Find a related record").fill(f.property.displayName);
  await page.getByRole("button", { name: `Use ${f.property.displayName}`, exact: true }).click();
  await expect(page.getByLabel("Due time zone", { exact: true })).toHaveValue(f.property.timeZone);
  await expect(page.getByLabel("Due at", { exact: true })).toBeEnabled();
  await page.getByLabel("Due time zone", { exact: true }).selectOption("Asia/Tokyo");
  await page.getByLabel("Due at", { exact: true }).fill("2027-05-01T10:30");
  const draft = page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().includes("/api/operator/recovery/"),
  );
  await page.getByLabel("Notes", { exact: true }).fill("Retain the chosen zone");
  const recovery = (await (await draft).json()) as Schema["RecoveryResponse"];
  await page.goto(`/tasks?workflow=task.create&resume=${recovery.id}`);
  await page.getByText("Optional Task details", { exact: true }).click();
  await expect(page.getByLabel("Due time zone", { exact: true })).toHaveValue("Asia/Tokyo");
  await expect(page.getByLabel("Due at", { exact: true })).toHaveValue("2027-05-01T10:30");
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/api/tasks"),
  );
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  const created = (await (await response).json()) as Schema["TaskCreationResponse"];
  expect(created.dueTimezone).toBe("Asia/Tokyo");
  await expect(page.locator(".saved-item")).toContainText("May 1, 2027, 10:30 AM · Asia/Tokyo");
  await page.goto(`/tasks?record=task&id=${created.id}`);
  await expect(page.locator(".task-deadline strong")).toHaveText(
    "May 1, 2027, 10:30 AM · Asia/Tokyo",
  );
  await page.goto(`/tasks?workflow=task.edit&target=${created.id}`);
  await expect(page.getByLabel("Due time zone", { exact: true })).toHaveValue("Asia/Tokyo");
});

test("reminder detail uses the related property zone even when the task has no deadline", async ({
  page,
  request,
}) => {
  const home = await property(request);
  const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
    title: "Undated property reminder",
    relatedEntityType: "property",
    relatedEntityId: home.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await post(request, `/api/tasks/${task.id}/reminders`, {
    expectedRevision: task.revision,
    idempotencyKey: crypto.randomUUID(),
    remindAtUtc: "2027-05-01T17:30:00Z",
  });
  await page.goto(`/tasks?record=task&id=${task.id}`);
  await expect(page.locator(".task-reminder-card h4")).toHaveText(
    "Reminder · May 1, 2027, 10:30 AM · America/Los_Angeles",
  );
});

for (const kind of ["space", "lease", "maintenance_issue", "owner_concern"] as const) {
  test(`task reminders and follow-ups resolve the property through ${kind}`, async ({
    page,
    request,
  }) => {
    const f = ["maintenance_issue", "owner_concern"].includes(kind)
      ? await issue(request)
      : await lease(request);
    let relatedId =
      "issue" in f ? f.issue.id : kind === "lease" ? f.lease.id : f.property.spaces[0].id;
    if (kind === "owner_concern") {
      const concern = await post<Schema["ConcernMutationResponse"]>(
        request,
        "/api/owner-concerns",
        {
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          ownerPartyId: f.property.ownerships[0].partyId,
          propertyId: f.property.id,
          concernType: "general_rental",
          summary: "Scheduling concern",
          description: "Arrange a follow-up",
        },
      );
      relatedId = concern.id;
    }
    const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
      title: `Related ${kind} task`,
      priority: "normal",
      relatedEntityType: kind,
      relatedEntityId: relatedId,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    await page.goto(`/tasks?workflow=task.reminder.add&target=${task.id}`);
    await expect(page.getByLabel("Reminder time zone", { exact: true })).toHaveValue(
      f.property.timeZone,
    );
    await page.goto(`/tasks?workflow=task.waiting.set&target=${task.id}`);
    await expect(page.getByLabel("Follow up timezone", { exact: true })).toHaveValue(
      f.property.timeZone,
    );
  });
}

test("an unavailable property zone blocks scheduling rather than silently using the browser zone", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.route(`**/api/properties/${f.property.id}`, (route) =>
    route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
  );
  await page.goto(`/maintenance?workflow=maintenance.appointment.create&target=${f.issue.id}`);
  await expect(
    page.getByRole("alert").filter({ hasText: "Could not load the property's time zone" }),
  ).toBeVisible();
  await expect(page.getByLabel("Starts at (required)")).toBeDisabled();
});

for (const multiple of [false, true]) {
  test(`conversation-linked task uses ${multiple ? "browser zone for multiple properties" : "its property's zone"}`, async ({
    page,
    request,
  }) => {
    const home = await property(request);
    const homes = multiple ? [home, await property(request)] : [home];
    const conversation = await post<Schema["CommunicationResponse"]>(
      request,
      "/api/communications",
      {
        direction: "internal",
        channel: "other",
        subject: "Scheduling context",
        body: "Check the property",
        record: false,
        participants: [{ partyId: home.ownerships[0].partyId, role: "sender" }],
        links: homes.map((item) => ({ entityType: "property", entityId: item.id })),
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    );
    const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
      title: "Conversation follow-up",
      priority: "normal",
      relatedEntityType: "communication",
      relatedEntityId: conversation.id,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    await page.goto(`/tasks?workflow=task.reminder.add&target=${task.id}`);
    await expect(page.getByLabel("Reminder time zone", { exact: true })).toHaveValue(
      multiple ? "UTC" : home.timeZone,
    );
    await expect(page.getByLabel("Remind at (required)", { exact: true })).toBeEnabled();
  });
}
