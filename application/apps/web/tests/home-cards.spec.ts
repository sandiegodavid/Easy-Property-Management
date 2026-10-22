import { expect, test } from "@playwright/test";

test("Home tabs retain details, filters are optional, and desktop cards show all captured rows with scrolling", async ({
  page,
  request,
}) => {
  for (let index = 0; index < 12; index += 1) {
    const response = await request.post("/api/tasks", {
      headers: { Origin: "http://127.0.0.1:18744" },
      data: {
        title: `Scrollable task ${index}`,
        dueAtUtc: new Date(Date.now() - 86400000).toISOString(),
        dueTimezone: "UTC",
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
  }
  const pages: URL[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/operator/home/items") pages.push(url);
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/home");
  const disclosureHint = page
    .locator(".home-queue-header")
    .getByText("Click anywhere on an item’s summary bar to expand or collapse its details.", {
      exact: true,
    });
  await expect(disclosureHint).toHaveCount(1);
  await expect(disclosureHint).toBeHidden();
  const help = page
    .locator(".home-queue-header")
    .getByRole("button", { name: "How to expand items", exact: true });
  const header = page.locator(".home-queue-header");
  const headerHeight = (await header.boundingBox())!.height;
  await help.hover();
  await expect(disclosureHint).toBeVisible();
  await help.focus();
  await page.mouse.move(0, 0);
  await expect(disclosureHint).toBeVisible();
  await expect(help).toHaveAccessibleDescription(
    "Click anywhere on an item’s summary bar to expand or collapse its details.",
  );
  expect((await header.boundingBox())!.height).toBe(headerHeight);
  await page.keyboard.press("Escape");
  await expect(disclosureHint).toBeHidden();
  const grid = page.locator(".home-grid");
  await expect(
    grid
      .locator(".home-section")
      .getByText("Click anywhere on an item’s summary bar to expand or collapse its details.", {
        exact: true,
      }),
  ).toHaveCount(2);
  for (const title of ["Calendar and appointments", "Information review"]) {
    const card = page.getByRole("region", { name: title, exact: true });
    const cardHelp = card.getByRole("button", { name: "How to expand items", exact: true });
    const tooltip = card.getByRole("tooltip");
    const before = (await card.locator(".ui-region-heading").boundingBox())!.height;
    await expect(tooltip).toBeHidden();
    await cardHelp.hover();
    await expect(tooltip).toBeVisible();
    await cardHelp.focus();
    await page.mouse.move(0, 0);
    await expect(tooltip).toBeVisible();
    await expect(cardHelp).toHaveAccessibleDescription(
      "Click anywhere on an item’s summary bar to expand or collapse its details.",
    );
    expect((await card.locator(".ui-region-heading").boundingBox())!.height).toBe(before);
    await page.keyboard.press("Escape");
    await expect(tooltip).toBeHidden();
  }
  const descriptions = await page
    .getByRole("button", { name: "How to expand items", exact: true })
    .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-describedby")));
  expect(new Set(descriptions).size).toBe(3);
  await expect(grid).toHaveCount(1);
  await expect(page.locator(".home-supporting")).toHaveCount(0);
  await expect(grid.locator(":scope > *")).toHaveCount(4);
  expect(
    await grid.evaluate((element) => getComputedStyle(element).gridTemplateRows.split(" ").length),
  ).toBe(2);
  await expect(grid.locator(":scope > .home-section")).toHaveCount(2);
  const summary = page.getByRole("region", { name: "Home summary", exact: true });
  await expect(summary).not.toContainText("Home summary captured at");
  await expect(summary.locator("time")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Recorded money", exact: true }).locator(".home-capture time"),
  ).toBeVisible();
  await expect(summary).toHaveCSS("align-self", "start");
  await expect(summary).toHaveCSS("text-align", "left");
  await expect(summary).toHaveCSS("justify-self", "end");
  const fortyCharacters = await summary.evaluate((element) => {
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;display:block;width:40ch";
    element.appendChild(probe);
    const width = probe.getBoundingClientRect().width;
    probe.remove();
    return width;
  });
  const summaryBox = await summary.boundingBox();
  const headerBox = await page.locator(".home-heading-bar").boundingBox();
  expect(summaryBox!.x + summaryBox!.width).toBeCloseTo(headerBox!.x + headerBox!.width, 0);
  expect(summaryBox!.width).toBeCloseTo(fortyCharacters, 0);
  await expect(summary.locator("p").last()).toHaveClass("home-scope");
  await expect(summary.locator(".home-scope")).toContainText("Scope: All properties.");
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action.locator(".ui-region-footer .home-capture time")).toBeVisible();
  const information = page.getByRole("region", { name: "Information review", exact: true });
  const actionBox = await action.boundingBox();
  const informationBox = await information.boundingBox();
  expect(informationBox!.y + informationBox!.height).toBeCloseTo(
    actionBox!.y + actionBox!.height,
    0,
  );
  const moneyBox = await page
    .getByRole("region", { name: "Recorded money", exact: true })
    .boundingBox();
  const inventoryBox = await page
    .getByRole("region", { name: "Inventory", exact: true })
    .boundingBox();
  expect(moneyBox!.y).toBeCloseTo(inventoryBox!.y, 0);
  expect(moneyBox!.y + moneyBox!.height).toBeCloseTo(inventoryBox!.y + inventoryBox!.height, 0);
  expect(moneyBox!.y - (actionBox!.y + actionBox!.height)).toBeCloseTo(16, 0);
  await expect(action.locator(":scope > :last-child")).toHaveClass("ui-region-footer");
  await expect(action).not.toContainText("Checked at");
  await expect(page.getByRole("region", { name: "Home", exact: true })).not.toContainText(
    "Checked at",
  );
  await expect(action.locator(".ui-disclosure")).toHaveCount(12);
  expect(pages.length).toBeGreaterThan(0);
  expect(
    pages.every((url) => url.searchParams.get("limit") === "100" && url.searchParams.has("cursor")),
  ).toBe(true);
  const scroller = action.locator("div[aria-busy]");
  expect(await scroller.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
    true,
  );
  const row = action.getByRole("button", { name: /Scrollable task 0/ });
  await row.click();
  await page.getByRole("tab", { name: "Waiting", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Upcoming", exact: true })).toBeFocused();
  await expect(disclosureHint).toHaveCount(1);
  await expect(action).toBeHidden();
  const upcomingBox = await page
    .getByRole("region", { name: "Upcoming", exact: true })
    .boundingBox();
  expect(upcomingBox!.y + upcomingBox!.height).toBeCloseTo(
    informationBox!.y + informationBox!.height,
    0,
  );
  await page.keyboard.press("Home");
  await expect(row).toHaveAttribute("aria-expanded", "true");
  const filters = page.getByRole("button", { name: "Filters", exact: true });
  await expect(filters).toHaveAccessibleDescription("Property, upcoming horizon, and money period");
  await expect(page.locator("#home-filter-hint")).toBeVisible();
  await expect(page.getByRole("form", { name: "Home filters", exact: true })).toBeHidden();
  await filters.click();
  await expect(page.locator("#home-money-filter-hint")).toBeVisible();
  await expect(page.getByLabel("Money from", { exact: true })).toHaveAccessibleDescription(
    "Money dates apply only to Recorded money. They do not hide overdue or unresolved work.",
  );
  await page.getByLabel("Money from", { exact: true }).fill("2026-09-01");
  await filters.click();
  await filters.click();
  await expect(page.getByLabel("Money from", { exact: true })).toHaveValue("2026-09-01");
  await expect(page.getByRole("region", { name: "Recorded money", exact: true })).toContainText(
    "Recorded money period:",
  );
  await expect(page.locator(".home-heading-bar")).not.toContainText("Recorded money period:");
  const money = page.getByRole("region", { name: "Recorded money", exact: true });
  const moneyBody = money.locator("div[aria-busy]");
  await expect(moneyBody.locator(":scope > :first-child")).toHaveJSProperty("tagName", "DL");
  const period = await money.getByText(/^Recorded money period:/).innerText();
  const dateRange = period.match(/^Recorded money period: (.+? through .+?)\./)?.[1];
  expect(period).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  if (!dateRange) throw new Error(`Missing readable money period: ${period}`);
  expect((await money.innerText()).split(dateRange)).toHaveLength(2);
  await expect(moneyBody.locator(":scope > p")).toHaveCount(1);
  await expect(moneyBody.locator(":scope > p")).toContainText(
    "These totals do not establish profit or owner entitlement.",
  );
  await expect(money).toContainText(
    "Recorded activity includes archived-property history and may include future-dated entries.",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await scroller.evaluate((element) => getComputedStyle(element).overflowY)).not.toBe(
    "auto",
  );
});

test("failed continuation preserves the captured preview and stops automatic reads", async ({
  page,
}) => {
  let reads = 0;
  await page.route("**/api/operator/home/items?*", (route) => {
    reads += 1;
    return route.fulfill({ status: 409, json: { detail: "Capture changed" } });
  });
  await page.goto("/home");
  const action = page.getByRole("region", { name: "Needs action", exact: true });
  await expect(action.getByRole("alert")).toContainText("Remaining items could not be loaded");
  await expect(action.locator(".ui-disclosure")).toHaveCount(5);
  expect(reads).toBe(1);
  await page.getByRole("tab", { name: "Waiting", exact: true }).click();
  await page.getByRole("tab", { name: "Needs action", exact: true }).click();
  await expect(action.getByRole("alert")).toBeVisible();
  expect(reads).toBe(1);
});
