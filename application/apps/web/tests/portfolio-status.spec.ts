import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function create(request: APIRequestContext, name: string) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: name,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "single_family_home",
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

test("unknown Space review classifies independent occupancy and future availability", async ({
  page,
  request,
}) => {
  const property = await create(request, "PORT003 classification");
  const space = property.spaces[0];
  await page.goto(`/properties/${property.id}/units`);
  await expect(
    page.getByRole("region", { name: "Property occupancy and leasing status" }),
  ).toContainText("Unknown occupancy count");
  await page
    .getByRole("link", { name: `Review status for ${space.displayName}`, exact: true })
    .click();
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
  await page.getByRole("button", { name: "Save classify space", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect((await status(request, space.id)).revision).toBe(space.revision);
  const date = later(property.effectiveLocalDate, 3);
  await page.getByLabel("Open for leasing on", { exact: true }).fill(date);
  await save(page, "Classify space");
  const current = await status(request, space.id);
  expect(current.currentOccupancy.occupancyStatus).toBe("vacant");
  expect(current.availability.effectiveStatus).toBe("available_on");
  await page.goto(`/properties/${property.id}/units`);
  const setup = page.getByRole("region", { name: "Property setup", exact: true });
  await expect(setup).toContainText("Current leasing status: Open for leasing later");
  await expect(setup).toContainText("Recorded intention: Open for leasing later");
  await expect(setup).toContainText(date);
  await expect(
    setup.getByRole("link", { name: `Review status for ${space.displayName}`, exact: true }),
  ).toHaveCount(0);
  await action(page, "portfolio.availability.change", space.id);
  await page
    .getByRole("combobox", { name: "Leasing status (required)", exact: true })
    .selectOption("not_available");
  await save(page, "Change availability");
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
  await page.getByText("Scheduled occupancy and corrections", { exact: true }).click();
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
    `${totals.activePropertyCount} active properties · ${totals.activeSpaceCount} active spaces. Counts describe spaces; filtered property results include any matching active space.`,
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
  await page.getByRole("button", { name: "Save change availability", exact: true }).click();
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
  await page.getByRole("button", { name: "Save change availability", exact: true }).click();
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
    const review = page.getByRole("link", {
      name: `Review status for ${property.spaces[0].displayName}`,
      exact: true,
    });
    await review.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Classify space", exact: true })).toBeVisible();
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
