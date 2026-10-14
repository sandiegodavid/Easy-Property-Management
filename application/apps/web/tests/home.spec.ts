import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("Home explains aggregate availability and shared Task rows reach real source actions", async ({
  page,
  request,
}) => {
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const bootstrap = (await response.json()) as components["schemas"]["BootstrapResponse"];
    await route.fulfill({
      json: {
        ...bootstrap,
        capabilities: bootstrap.capabilities.filter((item) => item !== "operator.home"),
      },
    });
  });
  const title = `Slice56 deadline ${crypto.randomUUID()}`;
  const response = await request.post("/api/tasks", {
    data: {
      title,
      priority: "urgent",
      dueAtUtc: new Date(Date.now() - 86400000).toISOString(),
      dueTimezone: "America/Los_Angeles",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const task = (await response.json()) as components["schemas"]["TaskCreationResponse"];
  await page.goto("/home");
  await expect(
    page.getByText("The combined Home work queue and calendar are not available yet.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Task deadlines and reminders" }).click();
  const summary = page.getByRole("button", { name: new RegExp(title) });
  await summary.focus();
  await page.keyboard.press("Enter");
  const panel = page.getByRole("region", { name: new RegExp(title) });
  await panel.getByRole("link", { name: "Review Task and actions" }).click();
  await expect(page).toHaveURL(new RegExp(task.id));
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Start task", exact: true }).click();
  await page.getByRole("button", { name: "Save start task", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  const current = await request.get(`/api/tasks/${task.id}`);
  const started = (await current.json()) as components["schemas"]["TaskResponse"];
  expect(started.status).toBe("in_progress");
  const waiting = await request.post(`/api/tasks/${task.id}/waiting`, {
    data: {
      expectedRevision: started.revision,
      idempotencyKey: crypto.randomUUID(),
      waitingForKind: "person",
      waitingForLabel: "Contractor",
    },
  });
  expect(waiting.ok(), await waiting.text()).toBe(true);
  await page.goto("/home");
  await page.getByRole("link", { name: "Waiting and follow-ups" }).click();
  const waitingSection = page.getByRole("region", { name: "Waiting", exact: true });
  const waitingSummary = waitingSection.getByRole("button", { name: new RegExp(title) });
  await expect(waitingSummary).toContainText("unscheduled");
  await expect(waitingSummary).toContainText("overdue");
  await waitingSummary.click();
  await expect(
    waitingSection.getByRole("link", { name: "Review Task and follow-up" }),
  ).toBeVisible();
});
