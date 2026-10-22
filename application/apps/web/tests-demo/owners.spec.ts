import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Owners directory served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts owners
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md).

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

// Seeded demo client owners in directory sort order (casefolded display name).
const OWNER_NAMES = [
  "Daniel Kim (Demo)",
  "Elena Torres (Demo)",
  "Grace Liu (Demo)",
  "Isabel Santos (Demo)",
  "Morgan Chen (Demo)",
  "Noah Williams (Demo)",
  "Oliver Grant (Demo)",
  "Priya Shah (Demo)",
  "Sam Rivera (Demo)",
  "Sofia Ahmed (Demo)",
];

function cardFor(page: Page, name: string) {
  return page.locator("ul.context-cards > li", {
    has: page.getByRole("link", { name, exact: true }),
  });
}

test("owners directory lists the seeded client owners", async ({ page }) => {
  await page.goto("/owners");
  await expect(page.getByRole("heading", { name: "Owners", exact: true })).toBeVisible();
  await expect(page.getByText("10 matching owners", { exact: true })).toBeVisible();
  const headings = await page.locator("ul.context-cards > li > h3").allInnerTexts();
  expect(headings.map((heading) => heading.trim())).toEqual(OWNER_NAMES);
});

test("owner search filters by name", async ({ page }) => {
  await page.goto("/owners");
  const search = page.getByRole("textbox", { name: "Search", exact: true });

  await search.fill("Morgan");
  await expect(page.getByText("1 matching owners", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Morgan Chen (Demo)", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sam Rivera (Demo)", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/q=Morgan/);
});

test("owner cards show related property counts and bounded previews", async ({ page }) => {
  await page.goto("/owners");

  const morgan = cardFor(page, "Morgan Chen (Demo)");
  await expect(
    morgan.getByText("Person · Active · 5 related properties (Current)", { exact: true }),
  ).toBeVisible();
  await expect(morgan.getByText("Showing a bounded property preview.")).toBeVisible();
  await expect(morgan.getByRole("link", { name: "View related properties" })).toBeVisible();
  for (const name of [
    "Alder House — Co-owned",
    "Birch Townhome — Rent Follow-up",
    "Magnolia House — Four Owners",
  ]) {
    await expect(morgan.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(
    morgan.getByRole("link", { name: "Sequoia House — Ten Owners", exact: true }),
  ).toHaveCount(0);

  const daniel = cardFor(page, "Daniel Kim (Demo)");
  await expect(
    daniel.getByText("Person · Active · 1 related properties (Current)", { exact: true }),
  ).toBeVisible();
  await expect(
    daniel.getByRole("link", { name: "Sequoia House — Ten Owners", exact: true }),
  ).toBeVisible();
  await expect(daniel.getByText("Showing a bounded property preview.")).toHaveCount(0);
});

test("archived filter shows the empty directory state", async ({ page }) => {
  await page.goto("/owners");
  await page.getByLabel("State", { exact: true }).selectOption("archived");
  await expect(page).toHaveURL(/state=archived/);
  await expect(page.getByText("0 matching owners", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching records on this page.", { exact: true })).toBeVisible();
});

test("relationship scope filter keeps current owners", async ({ page }) => {
  await page.goto("/owners");
  await page.getByLabel("Show relationships", { exact: true }).selectOption("all");
  await expect(page).toHaveURL(/relationshipScope=all/);
  await expect(page.getByText("10 matching owners", { exact: true })).toBeVisible();
});

test("opening an owner and returning to the directory", async ({ page }) => {
  await page.goto("/owners");
  await page.getByRole("link", { name: "Priya Shah (Demo)", exact: true }).click();
  await expect(page).toHaveURL(/\/owners\/[^/]+\/overview/);
  // The owner workspace has no titled header class (unlike properties), so
  // assert the first matching heading instead of scoping to a class.
  await expect(
    page.getByRole("heading", { name: "Priya Shah (Demo)", exact: true }).first(),
  ).toBeVisible();

  await page.getByRole("link", { name: "← Back to Owners", exact: true }).click();
  await expect(page).toHaveURL(/\/owners$/);
  await expect(page.getByText("10 matching owners", { exact: true })).toBeVisible();
});
