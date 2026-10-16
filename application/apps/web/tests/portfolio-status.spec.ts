import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function create(
  request: APIRequestContext,
  name: string,
  layout?: "whole_office" | "office_suites",
) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: name,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: layout ? "office" : "single_family_home",
      ...(layout ? { inventoryLayout: layout } : {}),
      ...(layout === "office_suites"
        ? { spaces: [{ displayName: "Suite 201" }, { displayName: "Suite 202" }] }
        : {}),
      ownerships: [{ ownerKind: "local_operator" }],
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schemas["PropertyMutationResponse"];
}
async function status(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/spaces/${id}/status`);
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schemas["SpaceStatusResponse"];
}
function later(date: string, days: number) {
  const next = new Date(`${date}T12:00:00Z`);
  next.setUTCDate(next.getUTCDate() + days);
  return next.toISOString().slice(0, 10);
}
async function classify(
  request: APIRequestContext,
  property: Schemas["PropertyMutationResponse"],
  occupancy: "vacant" | "occupied",
  availability: "available_now" | "available_on" | "not_available",
) {
  const response = await request.put(`/api/spaces/${property.spaces[0].id}/classification`, {
    data: {
      expectedRevision: property.spaces[0].revision,
      idempotencyKey: crypto.randomUUID(),
      occupancy: { occupancyStatus: occupancy, effectiveOn: property.effectiveLocalDate },
      availability: {
        availabilityStatus: availability,
        ...(availability === "available_on"
          ? { availableOn: later(property.effectiveLocalDate, 3) }
          : {}),
      },
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
}
async function action(page: Page, key: string, space: string, child?: string) {
  await page.goto(`/properties?workflow=${key}&target=${space}${child ? `&child=${child}` : ""}`);
  await expect(page.getByRole("group", { name: "Requested change", exact: true })).toBeVisible();
}
async function save(page: Page, title: string) {
  await page.getByRole("button", { name: `Save ${title.toLowerCase()}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
}

test("rental edit shows property context, current values and a responsive form", async ({
  page,
  request,
}) => {
  const property = await create(request, "Rental edit context", "office_suites");
  const rental = property.spaces[0];
  await action(page, "portfolio.space.patch", property.id, rental.id);
  const context = page.getByRole("region", { name: "Selected property and rental" });
  await expect(context).toContainText(property.displayName);
  await expect(context.getByRole("heading", { name: rental.displayName })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /^Display name/ })).toHaveValue(
    rental.displayName,
  );
  await expect(
    page.getByRole("link", { name: `← Back to ${property.displayName}` }),
  ).toHaveAttribute("href", `/properties/${property.id}/units`);
  await expect(page.getByText(/Displayed source revision:/)).not.toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("textbox", { name: /^Display name/ }).fill("Suite 201 — East");
  await save(page, "Edit suite");
  const updated = await status(request, rental.id);
  expect(updated.displayName).toBe("Suite 201 — East");
  expect(updated.currentOccupancy.occupancyStatus).toBe(rental.currentOccupancy.occupancyStatus);
  expect(updated.availability.effectiveStatus).toBe(rental.availability.effectiveStatus);
});

test("archive suite explains its scope and confirms the change in both themes", async ({
  page,
  request,
}, testInfo) => {
  for (const theme of ["light", "dark"] as const) {
    const property = await create(request, `Archive context ${theme}`, "office_suites");
    const rental = property.spaces[0];
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await action(page, "portfolio.space.archive", property.id, rental.id);
    const context = page.getByRole("region", { name: "Selected property and rental" });
    await expect(context).toContainText(property.displayName);
    await expect(context.getByRole("heading", { name: rental.displayName })).toBeVisible();
    await expect(context).toContainText("The property and its other suites remain active.");
    await expect(page.getByText(/Displayed source revision:/)).not.toBeVisible();
    await expect(
      page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/properties/${property.id}/units`);
    expect((await status(request, rental.id)).status).toBe("active");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({
      path: testInfo.outputPath(`archive-suite-${theme}-desktop.png`),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`archive-suite-${theme}-mobile.png`),
      fullPage: true,
    });
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
    await page
      .getByRole("checkbox", { name: "I confirm this lifecycle change", exact: true })
      .check();
    await page.getByRole("button", { name: "Archive suite", exact: true }).click();
    await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
    expect((await status(request, rental.id)).status).toBe("archived");
    expect((await status(request, property.spaces[1].id)).status).toBe("active");
  }
});

test("Back to Properties leaves an untouched create form and protects edits", async ({ page }) => {
  let propertyWrites = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/properties")
      propertyWrites++;
  });
  await page.goto("/properties");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("group", { name: "Requested change", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "← Back to Properties", exact: true }).click();
  await expect(page).toHaveURL(/\/properties$/);
  await expect(page.getByRole("heading", { name: "Properties", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await page.getByLabel("Display name (required)", { exact: true }).fill("Unfinished property");
  await page.getByRole("link", { name: "← Back to Properties", exact: true }).click();
  await expect(page.getByRole("region", { name: "Unfinished form" })).toBeVisible();
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toHaveValue(
    "Unfinished property",
  );
  expect(propertyWrites).toBe(0);
});

test("property layout uses Home, Office, or Suites labels without developer wording", async ({
  page,
  request,
}) => {
  const cases = [
    { label: "Home", layout: undefined, unit: "home" },
    { label: "Office", layout: "whole_office" as const, unit: "office" },
    { label: "Suites", layout: "office_suites" as const, unit: "suite" },
  ];
  for (const item of cases) {
    const property = await create(request, `Layout ${item.label}`, item.layout);
    await page.goto(`/properties/${property.id}/overview`);
    await expect(page.getByRole("region", { name: item.label, exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: `Manage ${item.label.toLowerCase()}`, exact: true }),
    ).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Property status summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Spaces", exact: true })).toHaveCount(0);
    await page.goto(`/properties/${property.id}/units`);
    await expect(
      page
        .getByRole("navigation", { name: "property sections", exact: true })
        .getByRole("link", { name: item.label, exact: true }),
    ).toHaveAttribute("aria-current", "page");
    const rentals = page.getByRole("region", {
      name: `Property ${item.label.toLowerCase()}`,
      exact: true,
    });
    await expect(rentals).toBeVisible();
    await expect(rentals).not.toContainText(/\bspaces?\b/i);
    const card = rentals.getByRole("article", {
      name: property.spaces[0].displayName,
      exact: true,
    });
    await expect(
      card
        .locator(".property-space-title-row")
        .getByRole("button", { name: "Start lease draft", exact: true }),
    ).toBeVisible();
    await expect(card.getByRole("link", { name: "Start lease draft", exact: true })).toHaveCount(0);
    await expect(card.getByText("More actions", { exact: true })).toHaveCount(0);
    await expect(
      card.getByRole("button", { name: `Archive ${item.unit}`, exact: true }),
    ).toHaveCount(item.label === "Suites" ? 1 : 0);
    await expect(
      card.getByRole("button", { name: `Restore ${item.unit}`, exact: true }),
    ).toHaveCount(0);
    await expect(
      card
        .locator(".property-space-title-row")
        .getByRole("button", { name: `Edit ${item.unit}`, exact: true }),
    ).toBeVisible();
    await card.getByRole("button", { name: `Edit ${item.unit}`, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: `Edit ${item.unit}`, exact: true }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: `← Back to ${property.displayName}`, exact: true })
      .click();
    await expect(
      card.getByRole("button", { name: `Edit ${item.unit}`, exact: true }),
    ).toBeVisible();
    if (item.label === "Suites") {
      await rentals
        .locator("summary")
        .filter({ hasText: /^Add suite$/ })
        .click();
      await expect(rentals.getByRole("link", { name: "Add suite", exact: true })).toBeVisible();
    }
    await card
      .getByRole("button", {
        name: `Review status for ${property.spaces[0].displayName}`,
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", { name: `Classify ${item.unit}`, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/properties/${property.id}/units`);
    await page.goto(`/properties/${property.id}/units`);
    await card.getByRole("button", { name: "Start lease draft", exact: true }).click();
    await expect(page).toHaveURL(`/leasing?workflow=lease.create&spaceId=${property.spaces[0].id}`);
  }
});

test("unknown Space review classifies independent occupancy and future availability", async ({
  page,
  request,
}, testInfo) => {
  const property = await create(request, "PORT003 classification");
  const space = property.spaces[0];
  await page.goto(`/properties/${property.id}/units`);
  await expect(page.getByRole("region", { name: "Property home", exact: true })).toContainText(
    "Needs classification",
  );
  const initialCard = page.getByRole("article", { name: space.displayName, exact: true });
  await expect(initialCard.locator(".property-space-attention")).toContainText(
    "Leasing status hasn’t been classified.",
  );
  await expect(initialCard.locator(".property-space-attention").getByRole("button")).toBeVisible();
  await page
    .getByRole("button", { name: `Review status for ${space.displayName}`, exact: true })
    .click();
  await expect(page).toHaveURL(`/properties?workflow=portfolio.space.classify&target=${space.id}`);
  const selectedSpace = page.getByRole("region", {
    name: "Selected property and rental",
    exact: true,
  });
  await expect(selectedSpace).toContainText(property.displayName);
  await expect(
    selectedSpace.getByRole("heading", { name: space.displayName, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
  ).toHaveAttribute("href", `/properties/${property.id}/units`);
  await expect(page.getByText(/Displayed source revision:/)).not.toBeVisible();
  await page.getByRole("button", { name: "Add occupancy", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Occupancy status (required)", exact: true })
    .selectOption("vacant");
  await page
    .getByLabel("Effective date (required)", { exact: true })
    .fill(property.effectiveLocalDate);
  await page.getByRole("button", { name: "Add leasing status", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Leasing status (required)", exact: true })
    .selectOption("available_on");
  await page.setViewportSize({ width: 1280, height: 900 });
  const formPanels = page.locator(".space-status-command form > fieldset > fieldset");
  await expect(formPanels).toHaveCount(2);
  expect((await formPanels.nth(1).boundingBox())!.x).toBeGreaterThan(
    (await formPanels.first().boundingBox())!.x,
  );
  await page.screenshot({
    path: testInfo.outputPath("classification-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await formPanels.nth(1).boundingBox())!.y).toBeGreaterThan(
    (await formPanels.first().boundingBox())!.y,
  );
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.screenshot({ path: testInfo.outputPath("classification-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "Save classify home", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect((await status(request, space.id)).revision).toBe(space.revision);
  const date = later(property.effectiveLocalDate, 3);
  await page.getByLabel("Open for leasing on", { exact: true }).fill(date);
  await save(page, "Classify home");
  const current = await status(request, space.id);
  expect(current.currentOccupancy.occupancyStatus).toBe("vacant");
  expect(current.availability.effectiveStatus).toBe("available_on");
  await page.goto(`/properties/${property.id}/units`);
  const setup = page.getByRole("region", { name: "Property home", exact: true });
  const card = setup.getByRole("article", { name: space.displayName, exact: true });
  await expect(card.locator(".property-space-status")).toContainText("Open for leasing later");
  await expect(card.locator(".property-space-status time")).toHaveText(date);
  await expect(card.locator(".property-space-attention")).toHaveCount(0);
  await expect(
    card.locator("dt").getByRole("button", { name: "Change leasing status", exact: true }),
  ).toBeVisible();
  await expect(card.getByRole("button", { name: "Edit home", exact: true })).toBeVisible();
  await expect(card.getByText("Home settings", { exact: true })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Archive home", exact: true })).toHaveCount(0);
  await expect(card.locator("summary")).toHaveText(["History"]);
  await expect(card.getByRole("region", { name: "Scheduled occupancy", exact: true })).toHaveCount(
    0,
  );
  await expect(card.getByText("Details and sources", { exact: true })).toHaveCount(0);
  await expect(card.getByText("Recorded leasing intention:", { exact: false })).toHaveCount(0);
  await expect(card.getByText("Correct recorded occupancy", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("space-card-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await expect(
    card.getByRole("button", { name: "Change leasing status", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("space-card-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(setup.getByRole("article")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "spaces", exact: true })).toHaveCount(0);
  await expect(setup).toContainText(date);
  await expect(
    setup.getByRole("button", { name: `Review status for ${space.displayName}`, exact: true }),
  ).toHaveCount(0);
  await action(page, "portfolio.availability.change", space.id);
  await page
    .getByRole("combobox", { name: "Leasing status (required)", exact: true })
    .selectOption("not_available");
  await save(page, "Change leasing status");
  expect((await status(request, space.id)).currentOccupancy.occupancyStatus).toBe("vacant");
});

test("scheduled occupancy reschedules and cancels without changing current status early", async ({
  page,
  request,
}) => {
  const property = await create(request, "PORT003 timeline");
  const space = property.spaces[0];
  await classify(request, property, "vacant", "not_available");
  await action(page, "portfolio.occupancy.change", space.id);
  await page
    .getByRole("combobox", { name: "Occupancy status (required)", exact: true })
    .selectOption("occupied");
  await page
    .getByLabel("Effective date (required)", { exact: true })
    .fill(later(property.effectiveLocalDate, 1));
  await save(page, "Change occupancy");
  const scheduled = await status(request, space.id);
  expect(scheduled.currentOccupancy.occupancyStatus).toBe("vacant");
  await page.goto(`/properties/${property.id}/units`);
  await expect(
    page.getByRole("region", { name: "Scheduled occupancy", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reschedule occupancy", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(later(property.effectiveLocalDate, 1), { exact: true }).first(),
  ).toBeVisible();
  await action(page, "portfolio.occupancy.reschedule", space.id, scheduled.scheduledOccupancy!.id);
  await page
    .getByRole("combobox", { name: "Occupancy status (required)", exact: true })
    .selectOption("occupied");
  await page
    .getByLabel("Effective date (required)", { exact: true })
    .fill(later(property.effectiveLocalDate, 2));
  await save(page, "Reschedule occupancy");
  const moved = await status(request, space.id);
  expect(moved.revision).toBe(scheduled.revision + 1);
  expect(moved.scheduledOccupancy!.startsOn).toBe(later(property.effectiveLocalDate, 2));
  await action(page, "portfolio.occupancy.cancel", space.id, moved.scheduledOccupancy!.id);
  await save(page, "Cancel scheduled occupancy");
  const cancelled = await status(request, space.id);
  expect(cancelled.scheduledOccupancyTimeline).toEqual([]);
  expect(cancelled.currentOccupancy.occupancyStatus).toBe("vacant");
  await action(page, "portfolio.occupancy.correct", space.id, cancelled.currentOccupancy.id);
  await page
    .getByRole("combobox", { name: "Occupancy status (required)", exact: true })
    .selectOption("occupied");
  await page.getByLabel("Reason (required)").fill("Correct the recorded observation");
  await save(page, "Correct occupancy");
  expect((await status(request, space.id)).currentOccupancy.occupancyStatus).toBe("occupied");
});

test("Portfolio summary drill-down and combined status filters use source facts", async ({
  page,
  request,
}) => {
  const vacant = await create(request, "PORT003 filter vacant");
  const occupied = await create(request, "PORT003 filter occupied");
  await create(request, "PORT003 filter unknown");
  await classify(request, vacant, "vacant", "available_now");
  await classify(request, occupied, "occupied", "available_on");
  await page.goto("/properties?q=PORT003%20filter");
  const vacantCard = page.getByRole("listitem").filter({
    has: page.getByRole("heading", { name: vacant.displayName, exact: true }),
  });
  await expect(vacantCard).toBeVisible();
  await expect(vacantCard).not.toContainText("No status attention");
  await expect(vacantCard).not.toContainText("Occupancy or leasing status needs review");
  await expect(
    page.locator(".directory-heading").getByRole("button", { name: "Create property" }),
  ).toBeVisible();
  await expect(page.getByLabel("Property name or address", { exact: true })).toHaveValue(
    "PORT003 filter",
  );
  await expect(page.getByText("Create a minimal property", { exact: false })).toHaveCount(0);
  const tabs = page.getByRole("navigation", { name: "Property status filters" });
  await expect(tabs.getByRole("link")).toHaveCount(6);
  const summary = page.getByRole("region", { name: "Portfolio occupancy and leasing status" });
  await page.getByRole("button", { name: "About leasing status" }).focus();
  await expect(page.getByRole("tooltip")).toContainText("independent of current occupancy");
  const response = await request.get("/api/portfolio/status-summary");
  const totals = (await response.json()) as Schemas["PortfolioStatusSummaryResponse"];
  await expect(summary.locator("p").filter({ hasText: "active properties" })).toHaveText(
    `${totals.activePropertyCount} active properties · ${totals.activeSpaceCount} active rental units.`,
  );
  await expect(
    summary.getByRole("link", {
      name: `Open for leasing now: ${totals.availableNowCount}`,
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "ownership Context", exact: true })
    .selectOption("self_owned");
  await page.getByRole("combobox", { name: "occupancy", exact: true }).selectOption("vacant");
  await page
    .getByRole("combobox", { name: "Leasing status", exact: true })
    .selectOption("available_now");
  await page.getByRole("combobox", { name: "needs Attention", exact: true }).selectOption("false");
  await expect(page.getByRole("button", { name: "Apply filters", exact: true })).toHaveCount(0);
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: vacant.displayName, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: occupied.displayName, exact: true })).toHaveCount(0);
  await summary
    .getByRole("link", {
      name: `Open for leasing later: ${totals.availableLaterCount}`,
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(/availability=available_on/);
  await expect(page).toHaveURL(/q=PORT003\+filter/);
  await expect(tabs.getByRole("link", { name: /^Open for leasing later:/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("link", { name: occupied.displayName, exact: true })).toBeVisible();
  const search = page.getByRole("textbox", { name: "Property name or address", exact: true });
  await search.fill(occupied.displayName);
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(occupied.displayName);
  await expect(search).toBeFocused();
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page).toHaveURL(/\/properties$/);
  await expect(search).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Leasing status", exact: true })).toHaveValue("");
  await page.route("**/api/portfolio/status-summary", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: { code: "unavailable", message: "Status source unavailable" } },
    }),
  );
  await page.reload();
  await expect(summary.getByRole("alert")).toContainText("unavailable");
  await expect(page.getByRole("link", { name: occupied.displayName, exact: true })).toBeVisible();
});

test("leasing status form shows property context and fits both themes", async ({
  page,
  request,
}, testInfo) => {
  const property = await create(request, "Leasing form layout");
  const space = property.spaces[0];
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "light" ? "Light" : "Dark", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await action(page, "portfolio.availability.change", space.id);
    await expect(
      page.getByRole("region", { name: "Selected property and rental", exact: true }),
    ).toContainText(property.displayName);
    await expect(
      page.getByRole("heading", { name: "Change leasing status", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/Changing it does not change occupancy or an existing lease/),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/properties/${property.id}/units`);
    const form = page.locator(".space-leasing-command form");
    await expect(form.locator(".workflow-field").first()).toContainText(
      "Leasing status (required)",
    );
    await form
      .getByRole("combobox", { name: "Leasing status (required)", exact: true })
      .selectOption("available_on");
    await page
      .getByLabel("Open for leasing on", { exact: true })
      .fill(later(property.effectiveLocalDate, theme === "light" ? 5 : 6));
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({
      path: testInfo.outputPath(`leasing-form-${theme}.png`),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true);
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
    await save(page, "Change leasing status");
    expect((await status(request, space.id)).currentOccupancy.occupancyStatus).toBe("unknown");
  }
});

test("occupancy form shows property context and schedules changes in both themes", async ({
  page,
  request,
}, testInfo) => {
  for (const theme of ["light", "dark"]) {
    const property = await create(request, `Occupancy form ${theme}`);
    const space = property.spaces[0];
    await classify(request, property, "vacant", "not_available");
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "light" ? "Light" : "Dark", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await action(page, "portfolio.occupancy.change", space.id);
    const context = page.getByRole("region", { name: "Selected property and rental", exact: true });
    await expect(context).toContainText(property.displayName);
    await expect(
      context.getByRole("heading", { name: space.displayName, exact: true }),
    ).toBeVisible();
    await expect(context).toContainText(
      "Changing it does not change leasing status or an existing lease",
    );
    await expect(
      page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/properties/${property.id}/units`);
    await expect(page.getByText(/A future date schedules the change/)).toBeVisible();
    await expect(page.getByText(/Displayed source revision:/)).not.toBeVisible();
    const form = page.locator(".space-occupancy-command form");
    await expect(form.locator(".workflow-field").first()).toContainText(
      "Occupancy status (required)",
    );
    await form
      .getByRole("combobox", { name: "Occupancy status (required)", exact: true })
      .selectOption("occupied");
    const effectiveOn = later(property.effectiveLocalDate, 7);
    await form.getByLabel("Effective date (required)", { exact: true }).fill(effectiveOn);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({
      path: testInfo.outputPath(`occupancy-form-${theme}.png`),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true);
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
    await save(page, "Change occupancy");
    const current = await status(request, space.id);
    expect(current.currentOccupancy.occupancyStatus).toBe("vacant");
    expect(current.scheduledOccupancy?.startsOn).toBe(effectiveOn);
    expect(current.scheduledOccupancy?.occupancyStatus).toBe("occupied");
    expect(current.availability.effectiveStatus).toBe("not_available");
  }
});

test("stale availability retains edits and an interrupted write reconciles its original result", async ({
  page,
  request,
}) => {
  const property = await create(request, "PORT003 recovery");
  const space = property.spaces[0];
  await action(page, "portfolio.availability.change", space.id);
  await page
    .getByRole("combobox", { name: "Leasing status (required)", exact: true })
    .selectOption("available_now");
  const concurrent = await request.put(`/api/spaces/${space.id}/availability`, {
    data: {
      availabilityStatus: "not_available",
      expectedRevision: space.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(concurrent.ok(), await concurrent.text()).toBe(true);
  await page.getByRole("button", { name: "Save change leasing status", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Leasing status (required)", exact: true }),
  ).toHaveValue("available_now");
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  let writes = 0;
  await page.route(`**/api/spaces/${space.id}/availability`, async (route) => {
    if (route.request().method() === "PUT") {
      writes++;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Save change leasing status", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  const committed = await status(request, space.id);
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  expect((await status(request, space.id)).revision).toBe(committed.revision);
  expect(writes).toBe(1);
});

test("status review supports keyboard access and both themes at narrow width", async ({
  page,
  request,
}) => {
  const property = await create(request, "PORT003 accessible review");
  await page.setViewportSize({ width: 390, height: 900 });
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto(`/properties/${property.id}/units`);
    const review = page.getByRole("button", {
      name: `Review status for ${property.spaces[0].displayName}`,
      exact: true,
    });
    await review.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Classify home", exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
});
