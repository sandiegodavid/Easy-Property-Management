import { expect, test } from "@playwright/test";
import { property, post, type Schema } from "./helpers/workflow-contracts";

test.use({
  timezoneId: "UTC",
  locale: "en-US",
  extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" },
});

test("follow-up entry uses the property zone and rescheduling preserves instants when selecting another zone", async ({
  page,
  request,
}) => {
  const home = await property(request);
  const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
    title: "Property-local follow-up",
    relatedEntityType: "property",
    relatedEntityId: home.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/tasks?workflow=task.waiting.set&target=${task.id}`);
  const zone = page.getByLabel("Follow up timezone", { exact: true });
  const time = page.getByLabel("Follow up at", { exact: true });
  await expect(zone).toHaveValue("America/Los_Angeles");
  await expect(time).toHaveAttribute("type", "datetime-local");
  await page.getByLabel("Waiting for kind").selectOption("organization");
  await page.getByLabel("Waiting for label").fill("Contractor reply");
  await time.fill("2027-05-01T10:30");
  await zone.selectOption("America/New_York");
  await expect(time).toHaveValue("2027-05-01T13:30");
  await zone.selectOption("America/Los_Angeles");
  const creation = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith(`/api/tasks/${task.id}/waiting`),
  );
  await page.getByRole("button", { name: "Save set waiting context", exact: true }).click();
  const created = await creation;
  expect(created.ok(), await created.text()).toBe(true);
  const submitted = created.request().postDataJSON() as {
    followUpAt: string;
    followUpTimezone: string;
  };
  expect(Date.parse(submitted.followUpAt)).toBe(Date.parse("2027-05-01T17:30:00Z"));
  expect(submitted.followUpTimezone).toBe("America/Los_Angeles");
  await page.goto(`/tasks?workflow=task.waiting.reschedule&target=${task.id}`);
  await expect(time).toHaveValue("2027-05-01T10:30");
  await expect(zone).toHaveValue("America/Los_Angeles");
  await zone.selectOption("America/New_York");
  await expect(time).toHaveValue("2027-05-01T13:30");
  await time.fill("2027-05-01T14:00");
  const reschedule = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/api/tasks/${task.id}/waiting/follow-up`),
  );
  await page.getByRole("button", { name: "Save reschedule follow-up", exact: true }).click();
  const saved = await reschedule;
  expect(saved.ok(), await saved.text()).toBe(true);
  const current = (await (
    await request.get(`/api/tasks/${task.id}`)
  ).json()) as Schema["TaskResponse"];
  expect(Date.parse(current.followUpAt!)).toBe(Date.parse("2027-05-01T18:00:00Z"));
  expect(current.followUpTimezone).toBe("America/New_York");
});

test("a follow-up in a daylight-saving gap stays on screen and is not submitted", async ({
  page,
  request,
}) => {
  const home = await property(request);
  const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
    title: "Invalid follow-up clock",
    relatedEntityType: "property",
    relatedEntityId: home.id,
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/tasks?workflow=task.waiting.set&target=${task.id}`);
  await expect(page.getByLabel("Follow up timezone", { exact: true })).toHaveValue(
    "America/Los_Angeles",
  );
  await page.getByLabel("Waiting for label").fill("Plumber reply");
  await page.getByLabel("Waiting for kind").selectOption("organization");
  const time = page.getByLabel("Follow up at", { exact: true });
  await time.fill("2027-03-14T02:30");
  await expect(
    page.getByRole("alert").filter({ hasText: "This time does not exist" }),
  ).toBeVisible();
  let writes = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith(`/api/tasks/${task.id}/waiting`)) writes++;
  });
  await page.getByRole("button", { name: "Save set waiting context", exact: true }).click();
  await expect(time).toHaveValue("2027-03-14T02:30");
  await expect(time).toHaveAttribute("aria-invalid", "true");
  expect(writes).toBe(0);
});

test.describe("property-local saved reminder", () => {
  test.use({ timezoneId: "America/Los_Angeles" });
  test("lost reminder response and recovered confirmation agree with Task detail despite a deadline-zone override", async ({
    page,
    request,
  }) => {
    const home = await post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
      displayName: "Eastern reminder property",
      addressLine1: "11 Broadway",
      city: "New York",
      region: "NY",
      postalCode: "10005",
      countryCode: "US",
      propertyType: "townhome",
      ownerships: [{ ownerKind: "local_operator" }],
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    const task = await post<Schema["TaskCreationResponse"]>(request, "/api/tasks", {
      title: "Eastern reminder with Tokyo deadline",
      relatedEntityType: "property",
      relatedEntityId: home.id,
      dueAtUtc: "2027-05-01T01:30:00Z",
      dueTimezone: "Asia/Tokyo",
      isAllDay: false,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    await page.goto(`/tasks?workflow=task.reminder.add&target=${task.id}`);
    await expect(page.getByLabel("Reminder time zone", { exact: true })).toHaveValue(
      "America/New_York",
    );
    const draftResponse = page.waitForResponse(
      (r) => r.request().method() === "PUT" && r.url().includes("/api/operator/recovery/"),
    );
    await page.getByLabel("Remind at (required)", { exact: true }).fill("2027-05-01T13:30");
    const draft = (await (await draftResponse).json()) as Schema["RecoveryResponse"];
    let writes = 0;
    await page.route(`**/api/tasks/${task.id}/reminders`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      writes++;
      const response = await route.fetch();
      expect(response.ok(), await response.text()).toBe(true);
      await route.abort();
    });
    await page.getByRole("button", { name: "Add task reminder", exact: true }).click();
    await page.getByRole("button", { name: "Check original result", exact: true }).click();
    const confirmation = page.locator(".saved-item");
    const expectedTime = "May 1, 2027, 1:30 PM · America/New_York";
    await expect(confirmation).toContainText(expectedTime);
    await expect(confirmation).not.toContainText("10:30 AM · America/Los_Angeles");
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(`**/api/properties/${home.id}`, async (route) => {
      const response = await route.fetch();
      await gate;
      await route.fulfill({ response });
    });
    await page.goto(`/tasks?workflow=task.reminder.add&target=${task.id}&resume=${draft.id}`);
    try {
      await expect(
        confirmation.getByRole("status").filter({ hasText: "Loading scheduling time zone" }),
      ).toBeVisible();
      await expect(confirmation).not.toContainText("10:30 AM · America/Los_Angeles");
    } finally {
      release();
    }
    await expect(confirmation).toContainText(expectedTime);
    await page.unroute(`**/api/properties/${home.id}`);
    expect(writes).toBe(1);
    await page.goto(`/tasks?record=task&id=${task.id}`);
    await expect(page.locator(".task-reminder-card h4")).toHaveText(`Reminder · ${expectedTime}`);
    await expect(page.locator(".task-deadline strong")).toContainText("Asia/Tokyo");
  });
});
