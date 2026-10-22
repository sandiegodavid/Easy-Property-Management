import { expect, test, type Locator, type Page } from "@playwright/test";
import { issue, lease, rent, post, type Schema } from "./helpers/workflow-contracts";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function independentlyToggle(page: Page, first: Locator, second: Locator) {
  const left = first.locator(":scope > summary");
  const right = second.locator(":scope > summary");
  for (const entry of [first, second]) {
    if (await entry.evaluate((node: HTMLDetailsElement) => node.open))
      await entry.locator(":scope > summary").click();
  }
  await left.focus();
  await page.keyboard.press("Enter");
  await expect(first).toHaveJSProperty("open", true);
  await page.keyboard.press("Space");
  await expect(first).toHaveJSProperty("open", false);
  const box = await left.boundingBox();
  await left.click({ position: { x: box!.width - 8, y: box!.height / 2 } });
  await expect(first).toHaveJSProperty("open", true);
  await right.focus();
  await page.keyboard.press("Enter");
  await expect(second).toHaveJSProperty("open", true);
  await expect(first).toHaveJSProperty("open", true);
  await left.focus();
  await page.keyboard.press("Space");
  await expect(first).toHaveJSProperty("open", false);
  await expect(second).toHaveJSProperty("open", true);
  await expect(left).toBeFocused();
}

test("issue section bars support full-width clicks and independent keyboard disclosure", async ({
  page,
  request,
}) => {
  const f = await issue(request);
  await page.goto(`/maintenance?record=issue&id=${f.issue.id}`);
  const before: string[] = [];
  page.on("request", (entry) => {
    if (entry.method() !== "GET") before.push(entry.method());
  });
  await independentlyToggle(
    page,
    page.getByRole("region", { name: "Provider assignments", exact: true }).locator("details"),
    page.getByRole("region", { name: "Estimates and cost notes", exact: true }).locator("details"),
  );
  expect(before).toEqual([]);
});

test("lease section bars independently disclose renewals and termination requests", async ({
  page,
  request,
}) => {
  const f = await lease(request);
  await page.goto(`/leases/${f.lease.id}/details`);
  await independentlyToggle(
    page,
    page
      .locator("summary")
      .filter({ hasText: /^Renewal options/ })
      .locator(".."),
    page
      .getByRole("region", { name: "Termination requests", exact: true })
      .locator("details")
      .first(),
  );
});

test("Money details and history disclose independently without submitting commands", async ({
  page,
}) => {
  await page.goto("/money?record=category&id=00000000-0000-4000-8000-000000000201");
  await independentlyToggle(
    page,
    page
      .locator("summary")
      .filter({ hasText: /^Record details$/ })
      .locator(".."),
    page
      .locator("summary")
      .filter({ hasText: /^History$/ })
      .locator(".."),
  );
});

test("Task history rows keep independent disclosure states and keyboard focus", async ({
  page,
  request,
}) => {
  const task = await post<Schema["TaskResponse"]>(request, "/api/tasks", {
    title: "Independent Task history",
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await post(request, `/api/tasks/${task.id}/start`, {
    expectedRevision: task.revision,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/tasks?record=task&id=${task.id}`);
  const bar = page.locator("summary").filter({ hasText: /^History$/ });
  await bar.focus();
  await page.keyboard.press("Enter");
  const history = bar.locator("..");
  await expect(history.locator("article")).toHaveCount(2);
  const rows = history.locator("article");
  await independentlyToggle(
    page,
    rows
      .nth(0)
      .locator("summary")
      .filter({ hasText: /^After change$/ })
      .locator(".."),
    rows
      .nth(1)
      .locator("summary")
      .filter({ hasText: /^After change$/ })
      .locator(".."),
  );
  await bar.focus();
  await page.keyboard.press("Space");
  await expect(history).toHaveJSProperty("open", false);
  await page.keyboard.press("Enter");
  await expect(
    rows
      .nth(1)
      .locator("summary")
      .filter({ hasText: /^After change$/ })
      .locator(".."),
  ).toHaveJSProperty("open", true);
});

test("money, work, leasing, category and Intake forms share contextual action-row order", async ({
  page,
  request,
}) => {
  const f = await rent(request);
  const draft = await lease(request);
  const repair = await issue(request);
  for (const [url, label] of [
    [
      `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${f.expectation.id}`,
      "Record rent receipt",
    ],
    ["/maintenance?workflow=maintenance.issue.create", "Report maintenance issue"],
    [
      `/maintenance?workflow=maintenance.issue.patch&target=${repair.issue.id}`,
      "Save issue changes",
    ],
    [`/leasing?workflow=lease.create&spaceId=${draft.property.spaces[0].id}`, "Create lease draft"],
    [`/leasing?workflow=lease.patch&target=${draft.lease.id}`, "Save lease draft changes"],
    ["/money?workflow=finance.expense_category.create", "Create expense category"],
    [
      "/money?workflow=finance.expense_category.patch&target=00000000-0000-4000-8000-000000000201",
      "Save expense category changes",
    ],
    ["/providers?workflow=provider.category.create", "Create provider category"],
    ["/conversations?workflow=intake.source.admit", "Retain source"],
  ]) {
    await test.step(label, async () => {
      await page.goto(url);
      const actions = page.getByRole("group", { name: "Form actions", exact: true });
      const buttons = actions.getByRole("button");
      await expect(buttons).toHaveCount(2);
      await expect(buttons.nth(0)).toHaveText(label);
      await expect(buttons.nth(0)).toHaveAttribute("type", "submit");
      await expect(buttons.nth(1)).toHaveText(
        /^(Save unfinished form|Saved|Saving unfinished form…)$/,
      );
      await expect(buttons.nth(1)).toHaveAttribute("type", "button");
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 900 });
        const primary = (await buttons.nth(0).boundingBox())!;
        const secondary = (await buttons.nth(1).boundingBox())!;
        if (Math.abs(primary.y - secondary.y) < 2) expect(primary.x).toBeLessThan(secondary.x);
        else expect(primary.y).toBeLessThan(secondary.y);
      }
    });
  }
});
