import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Maintenance workspace served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts
// or:
//   npm run test:demo
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md).

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

const ISSUE_SUMMARIES = [
  "Seasonal furnace service scheduled",
  "Annual plumbing inspection",
  "Urgent under-sink leak",
  "Urgent loss of heating",
];

function workspace(page: Page) {
  return page.getByRole("region", { name: "Work workspace", exact: true });
}

function directory(page: Page) {
  return page.getByRole("region", { name: "Work directory", exact: true });
}

function issueCard(page: Page, summary: string) {
  return page.locator("a.maintenance-issue-card", {
    has: page.getByRole("heading", { name: summary, exact: true }),
  });
}

test("maintenance directory lists the seeded demo issues", async ({ page }) => {
  await page.goto("/maintenance");
  const ws = workspace(page);
  await expect(ws.getByRole("heading", { name: "Maintenance", exact: true })).toBeVisible();
  await expect(
    ws.getByRole("button", { name: "Report maintenance issue", exact: true }),
  ).toBeVisible();
  const views = ws.getByRole("navigation", { name: "Maintenance views", exact: true });
  await expect(views.getByRole("link", { name: "Issues", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(views.getByRole("link", { name: "Owner concerns", exact: true })).toBeVisible();

  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(4);
  for (const summary of ISSUE_SUMMARIES) {
    await expect(page.getByRole("heading", { name: summary, exact: true })).toBeVisible();
  }
});

test("issue cards show status, priority, category and property", async ({ page }) => {
  await page.goto("/maintenance");

  const leak = issueCard(page, "Urgent under-sink leak");
  await expect(leak.locator(".maintenance-issue-status")).toHaveText("Open");
  await expect(leak).toContainText("Urgent priority");
  await expect(leak).toContainText("Plumbing");
  await expect(leak).toContainText("Riverbend Condo 102");

  const furnace = issueCard(page, "Seasonal furnace service scheduled");
  await expect(furnace.locator(".maintenance-issue-status")).toHaveText("Open");
  await expect(furnace).toContainText("Normal priority");
  await expect(furnace).toContainText("Heating cooling");
  await expect(furnace).toContainText("Maple House");

  const heating = issueCard(page, "Urgent loss of heating");
  await expect(heating).toContainText("Urgent priority");
  await expect(heating).toContainText("Spruce House");

  const inspection = issueCard(page, "Annual plumbing inspection");
  await expect(inspection.locator(".maintenance-issue-status")).toHaveText("Open");
  await expect(inspection).toContainText("Low priority");
  await expect(inspection).toContainText("Plumbing");
  await expect(inspection).toContainText("Willow House — Prepaid");
});

test("category and priority filters narrow the issue list", async ({ page }) => {
  await page.goto("/maintenance");
  const dir = directory(page);

  await dir.getByRole("combobox", { name: "Issue category", exact: true }).selectOption("plumbing");
  await expect(page).toHaveURL(/category=plumbing/);
  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(2);
  for (const summary of ["Urgent under-sink leak", "Annual plumbing inspection"]) {
    await expect(
      page.getByRole("heading", { name: summary, exact: true }),
    ).toBeVisible();
  }

  await dir.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(4);

  await dir.getByRole("combobox", { name: "Issue priority", exact: true }).selectOption("urgent");
  await expect(page).toHaveURL(/priority=urgent/);
  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(2);
  await expect(
    page.getByRole("heading", { name: "Urgent under-sink leak", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Urgent loss of heating", exact: true }),
  ).toBeVisible();
});

test("status filter shows the empty state when nothing matches", async ({ page }) => {
  await page.goto("/maintenance");
  const dir = directory(page);
  await dir.getByRole("combobox", { name: "Status", exact: true }).selectOption("resolved");
  await expect(page).toHaveURL(/status=resolved/);
  await expect(
    dir.getByText("No maintenance issues match these filters.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(0);
});

test("opening an issue shows its quotes and returns to maintenance", async ({ page }) => {
  await page.goto("/maintenance");
  await issueCard(page, "Urgent under-sink leak").click();
  await expect(page).toHaveURL(/\/maintenance\?record=issue&id=[^&]+$/);

  const detail = page.getByRole("region", { name: "Work record", exact: true });
  await expect(
    detail.getByRole("heading", { name: "Urgent under-sink leak", exact: true }),
  ).toBeVisible();
  // The appointment card must not repeat the issue title as a heading.
  await expect(
    detail
      .getByRole("region", { name: "Appointments", exact: true })
      .getByRole("heading", { name: "Urgent under-sink leak", exact: true }),
  ).toHaveCount(0);
  const quotes = detail.getByRole("region", {
    name: "Provider quote comparison table",
    exact: true,
  });
  await expect(
    quotes.getByRole("link", { name: "Clearwater Plumbing (Demo)", exact: true }),
  ).toBeVisible();
  await expect(
    quotes.getByRole("link", { name: "North Star Pipeworks (Demo)", exact: true }),
  ).toBeVisible();
  await expect(
    quotes.getByRole("link", { name: "Cedar Flow Services (Demo)", exact: true }),
  ).toBeVisible();

  const back = detail.getByRole("link", { name: "← Back to Maintenance", exact: true });
  await expect(back).toHaveAttribute("href", "/maintenance");
  await back.click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(page.locator("a.maintenance-issue-card")).toHaveCount(4);
});

test("owner concerns tab shows the empty state", async ({ page }) => {
  await page.goto("/maintenance");
  const ws = workspace(page);
  await ws
    .getByRole("navigation", { name: "Maintenance views", exact: true })
    .getByRole("link", { name: "Owner concerns", exact: true })
    .click();
  await expect(page).toHaveURL(/tab=concerns/);
  await expect(ws.getByRole("heading", { name: "Owner concerns", exact: true })).toBeVisible();
  await expect(ws.getByRole("link", { name: "Record concern", exact: true })).toBeVisible();
  await expect(
    directory(page).getByText(
      "No matching recorded items on this page. This does not establish that no problems exist.",
      { exact: true },
    ),
  ).toBeVisible();
});

test("report issue opens the maintenance create workflow", async ({ page }) => {
  await page.goto("/maintenance");
  await workspace(page)
    .getByRole("button", { name: "Report maintenance issue", exact: true })
    .click();
  await expect(page).toHaveURL(/\/maintenance\?workflow=maintenance\.issue\.create$/);
  await expect(
    page.getByText(
      "Describe the issue, choose the property, and record who reported it. You can add appointments, quotes and evidence after saving.",
      { exact: true },
    ),
  ).toBeVisible();
});
