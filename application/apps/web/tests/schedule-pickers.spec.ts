import { expect, test } from "@playwright/test";
import { issue, post, type Schema } from "./helpers/workflow-contracts";
import { zonedInstant } from "../src/shared/zoned-date-time";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("appointment pickers save a start-only visit, retain its zone and reschedule with an optional end", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(`/maintenance?workflow=maintenance.appointment.create&target=${f.issue.id}`);
  const start = page.getByLabel("Starts at (required)", { exact: true });
  const end = page.getByLabel("Ends at", { exact: true });
  await expect(start).toHaveAttribute("type", "datetime-local");
  await expect(start).toHaveAttribute("step", "60");
  await expect(end).toHaveAttribute("step", "60");
  await expect(start).toHaveAttribute("required", "");
  await expect(end).not.toHaveAttribute("required", "");
  await page.getByLabel("Time zone", { exact: true }).selectOption("America/New_York");
  await expect(page.getByLabel("Time zone", { exact: true }).locator("option:checked")).toHaveText(
    "America/New_York",
  );
  await start.fill("2027-05-01T10:30");
  await page.getByLabel("Purpose (required)").fill("Inspect the window");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const schedule = page.getByRole("region", { name: "Appointment schedule", exact: true });
    expect(await schedule.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    );
  }
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/api/maintenance-issues/${f.issue.id}/appointments`),
  );
  await page.getByRole("button", { name: "Schedule appointment", exact: true }).click();
  const submitted = await response;
  const created = (await submitted.json()) as Schema["AppointmentCommandResponse"];
  expect(created.startsAtUtc).toBe("2027-05-01T14:30:00Z");
  expect(created.endsAtUtc).toBeNull();
  expect(created.scheduledTimezone).toBe("America/New_York");
  const payload: unknown = submitted.request().postDataJSON();
  expect(
    await post(request, `/api/maintenance-issues/${f.issue.id}/appointments`, payload),
  ).toEqual(created);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const appointment = page.locator(`#appointment-${created.id}`);
  await expect(appointment.getByRole("heading", { name: "Inspect the window" })).toBeVisible();
  await expect(appointment.locator(".maintenance-appointment-times")).toContainText(
    "EndsNot specified",
  );
  await expect(appointment.locator("time")).toHaveCount(1);
  await expect(appointment.locator("time")).toHaveAttribute("datetime", created.startsAtUtc);
  expect(pageErrors).toEqual([]);
  await page.goto(
    `/maintenance?workflow=maintenance.appointment.update&target=${f.issue.id}&child=${created.id}`,
  );
  await expect(start).toHaveValue("2027-05-01T10:30");
  await expect(end).toHaveValue("");
  await expect(page.getByLabel("Time zone", { exact: true })).toHaveValue("America/New_York");
  expect((await start.boundingBox())!.y).toBeLessThanOrEqual((await end.boundingBox())!.y);
  await page.getByLabel("Time zone", { exact: true }).selectOption("America/Chicago");
  await expect(start).toHaveValue("2027-05-01T09:30");
  await start.fill("2027-05-02T11:00");
  await end.fill("2027-05-02T12:15");
  await page.getByLabel("Reschedule reason", { exact: true }).fill("Owner requested tomorrow");
  const update = page.waitForResponse(
    (r) =>
      r.request().method() === "PATCH" &&
      r.url().endsWith(`/api/maintenance-appointments/${created.id}`),
  );
  await page.getByRole("button", { name: "Save reschedule appointment", exact: true }).click();
  const changed = (await (await update).json()) as Schema["AppointmentCommandResponse"];
  expect(changed.startsAtUtc).toBe("2027-05-02T16:00:00Z");
  expect(changed.endsAtUtc).toBe("2027-05-02T17:15:00Z");
  expect(changed.scheduledTimezone).toBe("America/Chicago");
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(appointment.locator("time")).toHaveCount(2);
  await expect(appointment.locator("time").nth(1)).toHaveAttribute("datetime", changed.endsAtUtc!);
  await page.goto(
    `/maintenance?workflow=maintenance.appointment.update&target=${f.issue.id}&child=${created.id}`,
  );
  await end.fill("");
  await page.getByLabel("Reschedule reason", { exact: true }).fill("End no longer known");
  const clear = page.waitForResponse(
    (r) =>
      r.request().method() === "PATCH" &&
      r.url().endsWith(`/api/maintenance-appointments/${created.id}`),
  );
  await page.getByRole("button", { name: "Save reschedule appointment", exact: true }).click();
  expect(
    ((await (await clear).json()) as Schema["AppointmentCommandResponse"]).endsAtUtc,
  ).toBeNull();
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  await expect(appointment.locator(".maintenance-appointment-times")).toContainText(
    "EndsNot specified",
  );
  await expect(appointment.locator("time")).toHaveCount(1);
  expect(pageErrors).toEqual([]);
});

test("appointment pickers reject nonexistent local times without submitting", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      r.url().endsWith(`/api/maintenance-issues/${f.issue.id}/appointments`)
    )
      writes.push(r.url());
  });
  await page.goto(`/maintenance?workflow=maintenance.appointment.create&target=${f.issue.id}`);
  await page.getByLabel("Time zone", { exact: true }).selectOption("America/Los_Angeles");
  await page.getByLabel("Starts at (required)").fill("2027-03-14T01:30");
  await page.getByLabel("Starts at (required)").fill("2027-03-14T02:30");
  await expect(page.getByRole("alert")).toContainText("does not exist");
  await expect(page.getByLabel("Starts at (required)")).toHaveAttribute("aria-invalid", "true");
  const draftSave = page.waitForResponse(
    (r) =>
      r.request().method() === "PUT" &&
      /\/api\/operator\/recovery\//.test(r.url()) &&
      (r.request().postDataJSON() as { payload?: { purpose?: string } })?.payload?.purpose ===
        "Review the repair",
  );
  await page.getByLabel("Purpose (required)").fill("Review the repair");
  const saved = await draftSave;
  expect(saved.ok(), await saved.text()).toBe(true);
  expect(
    (saved.request().postDataJSON() as { payload: { startsAtUtc?: string } }).payload.startsAtUtc,
  ).toBe("2027-03-14T09:30:00.000Z");
  await expect(page.getByLabel("Starts at (required)")).toHaveValue("2027-03-14T02:30");
  await page.getByRole("button", { name: "Schedule appointment", exact: true }).click();
  await expect(page.getByLabel("Starts at (required)")).toBeFocused();
  expect(
    await page
      .getByLabel("Starts at (required)")
      .evaluate((input: HTMLInputElement) => input.validity.customError),
  ).toBe(true);
  expect(writes).toHaveLength(0);
  await page.getByLabel("Starts at (required)").fill("2027-03-14T03:30");
  await expect(page.getByLabel("Starts at (required)")).toHaveAttribute("aria-invalid", "false");
});

test("Task due time accepts typed picker input and saves the selected zone", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.goto("/tasks?workflow=task.create");
  await page.getByLabel("Title (required)", { exact: true }).fill("Call after lunch");
  await page.getByLabel("No due date", { exact: true }).uncheck();
  await page.getByText("Optional Task details", { exact: true }).click();
  await expect(page.getByLabel("Related entity id", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Related entity type", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Choices are bounded/)).toHaveCount(0);
  await page.getByLabel("Find a related record").fill(f.property.displayName);
  await page.getByRole("button", { name: `Use ${f.property.displayName}`, exact: true }).click();
  await page.getByLabel("Due time zone", { exact: true }).selectOption("America/New_York");
  const due = page.getByLabel("Due at", { exact: true });
  await expect(due).toHaveAttribute("type", "datetime-local");
  await due.fill("2027-05-01T13:45");
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/api/tasks"),
  );
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  const created = (await (await response).json()) as Schema["TaskResponse"];
  expect(created.dueAtUtc).toBe("2027-05-01T17:45:00Z");
  expect(created.dueTimezone).toBe("America/New_York");
  expect(created.isAllDay).toBe(false);
  expect(created.relatedEntityId).toBe(f.property.id);
  expect(created.relatedEntityType).toBe("property");
  expect(created.relatedLabel).toBe(f.property.displayName);
  await page.goto(`/tasks?workflow=task.edit&target=${created.id}`);
  await expect(page.getByLabel("Due at", { exact: true })).toHaveAttribute(
    "type",
    "datetime-local",
  );
  await expect(page.getByLabel("Due at", { exact: true })).toHaveValue("2027-05-01T13:45");
  await page.getByLabel("Due time zone", { exact: true }).selectOption("America/Chicago");
  await expect(page.getByLabel("Due at", { exact: true })).toHaveValue("2027-05-01T12:45");
  await page.getByLabel("Due at", { exact: true }).fill("2027-05-02T10:15");
  const edit = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.url().endsWith(`/api/tasks/${created.id}`),
  );
  await page.getByRole("button", { name: "Save task changes", exact: true }).click();
  const changed = ((await (await edit).json()) as Schema["TaskMutationResponse"]).task;
  expect(changed.dueAtUtc).toBe("2027-05-02T15:15:00Z");
  expect(changed.dueTimezone).toBe("America/Chicago");
});

test("zoned picker conversion preserves repeated-hour instants and rejects daylight-saving gaps", () => {
  expect(zonedInstant("2026-11-01T01:30", "America/Los_Angeles", "2026-11-01T09:30:00Z")).toBe(
    "2026-11-01T09:30:00Z",
  );
  expect(zonedInstant("2026-11-01T01:30", "America/Los_Angeles")).toBe("2026-11-01T08:30:00.000Z");
  expect(() => zonedInstant("2027-03-14T02:30", "America/Los_Angeles")).toThrow(/does not exist/);
  expect(zonedInstant("2027-05-01T13:45", "Asia/Kolkata")).toBe("2027-05-01T08:15:00.000Z");
});
