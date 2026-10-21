import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Money workspace served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts money
// or:
//   npm run test:demo
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md). The demo seeds
// two rent expectations per leased property (current and next month), 40 paid
// expenses, nine funded security deposits and no scheduled checks. Settlement
// counts are stable over time; timeliness states are not asserted.

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

const MONEY_TABS = [
  "Rent",
  "Received rent",
  "Expenses",
  "Deposits",
  "Scheduled checks",
  "Owner reports",
  "Expense categories",
  "Reporting",
];

function moneyViews(page: Page) {
  return page.getByRole("navigation", { name: "Money views", exact: true });
}

test("money workspace shows its views and rent filters", async ({ page }) => {
  await page.goto("/money");
  const workspace = page.getByRole("region", { name: "Money workspace", exact: true });
  await expect(workspace.getByRole("heading", { name: "Money", exact: true })).toBeVisible();
  await expect(
    workspace.getByText(
      "Recorded payments, paid expenses and held deposits are separate records. Scheduled checks and pending owner reports are not received income.",
      { exact: true },
    ),
  ).toBeVisible();
  const views = moneyViews(page);
  for (const name of MONEY_TABS) {
    await expect(views.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(views.getByRole("link", { name: "Rent", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  const records = page.getByRole("region", { name: "Rent records", exact: true });
  await expect(records.getByRole("combobox", { name: "Settlement", exact: true })).toBeVisible();
  await expect(records.getByRole("combobox", { name: "Timeliness", exact: true })).toBeVisible();
  await expect(records.getByLabel("Due from", { exact: true })).toBeVisible();
  await expect(records.getByLabel("Due to", { exact: true })).toBeVisible();
});

test("rent tab lists the seeded expectations", async ({ page }) => {
  await page.goto("/money");
  const records = page.getByRole("region", { name: "Rent records", exact: true });
  await expect(records.getByRole("article")).toHaveCount(18);
  const first = records.getByRole("article").first();
  await expect(first.getByRole("heading", { name: "Rent due", exact: true })).toBeVisible();
  await expect(first.getByText("Expected", { exact: true })).toBeVisible();
  await expect(
    first.getByRole("link", { name: "Review amounts and receipt allocations", exact: true }),
  ).toBeVisible();
});

test("settlement filter separates paid and unpaid rent", async ({ page }) => {
  await page.goto("/money");
  const records = page.getByRole("region", { name: "Rent records", exact: true });
  const settlement = records.getByRole("combobox", { name: "Settlement", exact: true });
  await settlement.selectOption("paid");
  await expect(page).toHaveURL(/status=paid/);
  await expect(records.getByRole("article")).toHaveCount(9);
  await settlement.selectOption("unpaid");
  await expect(page).toHaveURL(/status=unpaid/);
  await expect(records.getByRole("article")).toHaveCount(9);
});

test("birch townhome shows its unpaid rent expectations", async ({ page }) => {
  await page.goto("/properties");
  await page.getByRole("link", { name: "Birch Townhome — Rent Follow-up", exact: true }).click();
  await page.getByRole("button", { name: "View in Money", exact: true }).click();
  await expect(page).toHaveURL(/\/money\?propertyId=[^&]+$/);
  await expect(page.getByText(/Showing this property.s records./)).toBeVisible(); // regex, non-exact: the notice shares its paragraph with a Remove-filter button, and the source uses a curly apostrophe.
  const context = page.getByRole("region", { name: "Property context", exact: true });
  await expect(
    context.getByRole("link", { name: "Birch Townhome — Rent Follow-up", exact: true }),
  ).toBeVisible();
  const records = page.getByRole("region", { name: "Rent records", exact: true });
  const cards = records.getByRole("article");
  await expect(cards).toHaveCount(2);
  const first = cards.first();
  await expect(first.getByRole("heading", { name: "Rent due", exact: true })).toBeVisible();
  await expect(first.getByText("unpaid", { exact: true }).first()).toBeVisible();
  await expect(first.getByText("USD 1950.00", { exact: true }).first()).toBeVisible();
});

test("willow house prepayment is a paid future expectation", async ({ page }) => {
  await page.goto("/leasing");
  const card = page.locator("ul.lease-directory-grid > li", {
    has: page.getByRole("heading", { name: "Willow House — Prepaid", exact: true }),
  });
  await card.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/leases\/[^/]+\/details$/);
  await page.getByRole("link", { name: "View rent and deposits →", exact: true }).click();
  await expect(page).toHaveURL(/\/money\?leaseId=[^&]+$/);
  await expect(page.getByText(/Showing this lease.s records./)).toBeVisible();
  const rent = page.getByRole("region", { name: "Rent records", exact: true });
  await expect(rent.getByRole("article")).toHaveCount(2);
  await rent.getByRole("combobox", { name: "Settlement", exact: true }).selectOption("paid");
  await expect(rent.getByRole("article")).toHaveCount(2);
  await expect(rent.getByText("USD 2350.00", { exact: true }).first()).toBeVisible();

  await moneyViews(page).getByRole("link", { name: "Received rent", exact: true }).click();
  await expect(page).toHaveURL(/tab=receipts/);
  const receipts = page.getByRole("region", { name: "Received rent records", exact: true });
  await expect(receipts.getByRole("article")).toHaveCount(2);
  await expect(receipts.getByRole("heading", { name: "Rent received", exact: true })).toHaveCount(
    2,
  );
});

test("expenses tab lists the seeded paid expenses", async ({ page }) => {
  await page.goto("/money?tab=expenses");
  const records = page.getByRole("region", { name: "Expenses records", exact: true });
  await expect(records.getByRole("article")).toHaveCount(25);
  await expect(records.getByRole("combobox", { name: "Paid by", exact: true })).toBeVisible();
  const first = records.getByRole("article").first();
  await expect(first.getByText("Local operator")).toBeVisible();
  await expect(first.getByText(/USD \d+\.\d{2}/).first()).toBeVisible();

  await records.getByRole("combobox", { name: "Paid by", exact: true }).selectOption("party");
  await expect(page).toHaveURL(/paidByKind=party/);
  await expect(page.getByText("No records match these filters.", { exact: true })).toBeVisible();
});

test("deposits tab lists the funded security deposits", async ({ page }) => {
  await page.goto("/money?tab=deposits");
  const records = page.getByRole("region", { name: "Deposits records", exact: true });
  await expect(records.getByRole("heading", { name: "Security deposit", exact: true })).toHaveCount(
    9,
  );
  await expect(records.getByText("USD 2150.00", { exact: true }).first()).toBeVisible();
});

test("scheduled checks tab is empty in the demo", async ({ page }) => {
  await page.goto("/money?tab=checks");
  const records = page.getByRole("region", { name: "Scheduled checks records", exact: true });
  await expect(records.getByText("No records match these filters.", { exact: true })).toBeVisible();
});
