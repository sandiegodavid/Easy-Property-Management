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
  await test.step(title, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  if (["Create property", "Edit property"].includes(title)) {
    const tab = title === "Edit property" ? "setup" : "overview";
    await page.getByRole("link", { name: "Back to property", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/properties/[^/]+/${tab}$`));
    return;
  }
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
}

test("ownership changes use named owner search and property-local date help", async ({
  page,
  request,
}, testInfo) => {
  const property = await create(request, "Ownership form office", "office_suites");
  const response = await request.post("/api/parties", {
    data: {
      partyKind: "individual",
      displayName: "Ownership search Morgan",
      contacts: [
        { methodKind: "email", value: "morgan@example.test" },
        { methodKind: "phone", value: "503-555-0199", label: "Mobile" },
        { methodKind: "mailing_address", value: "10 Oak St\nPortland OR 97201\nUS" },
      ],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const party = (await response.json()) as Schemas["PartyMutationResponse"];
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await expect(
    page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
  ).toHaveAttribute("href", `/properties/${property.id}/overview`);
  await expect(page.getByLabel("Effective date", { exact: true })).toHaveValue(
    property.effectiveLocalDate,
  );
  await page
    .getByRole("button", { name: "How the ownership effective date works", exact: true })
    .focus();
  await expect(page.getByRole("tooltip")).toContainText("America/Los_Angeles");
  await expect(page.getByText("Inventory uses", { exact: false })).toHaveCount(0);
  await expect(page.getByLabel("Existing identity ID", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to property", exact: true })).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    const contrast = await page
      .getByRole("button", { name: "Save ownership change", exact: true })
      .evaluate((button) => {
        const style = getComputedStyle(button);
        const luminance = (color: string) => {
          const channels = color
            .match(/\d+/g)!
            .slice(0, 3)
            .map((channel) => {
              const value = Number(channel) / 255;
              return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
            });
          return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
        };
        const values = [luminance(style.color), luminance(style.backgroundColor)];
        return (Math.max(...values) + 0.05) / (Math.min(...values) + 0.05);
      });
    expect(contrast).toBeGreaterThanOrEqual(4.5);
  }
  await expect(
    page.getByRole("button", { name: "Check latest property record", exact: true }),
  ).toBeHidden();
  await expect(page.locator(".command-form-actions button")).toHaveText([
    "Save ownership change",
    "Save unfinished form",
  ]);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save ownership change", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Find an owner by name", { exact: true }).fill(party.displayName);
  await expect(page.getByRole("button", { name: "Search", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: `Add ${party.displayName}`, exact: true }).click();
  await expect(page.locator(".ownership-selected")).toContainText(party.displayName);
  await expect(page.locator(".owner-contact-details")).toContainText("morgan@example.test");
  await expect(page.locator(".owner-contact-details")).toContainText("503-555-0199");
  await expect(page.locator(".owner-contact-details")).toContainText("10 Oak St");
  await expect(page.getByRole("region", { name: "Add an owner", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await page.getByRole("button", { name: "Create a new owner", exact: true }).click();
  await page.getByLabel("New owner name", { exact: true }).fill("Unsaved new owner");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page
        .getByRole("region", { name: "Add an owner", exact: true })
        .screenshot({ path: testInfo.outputPath(`add-owner-${theme}-${width}.png`) });
    }
  }
  await page.getByRole("button", { name: "Add to owners", exact: true }).click();
  await expect(page.locator(".ownership-selected")).toContainText("Unsaved new owner");
  await page.getByRole("button", { name: "Remove Unsaved new owner", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save ownership change", exact: true }),
  ).toBeEnabled();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ownership updated", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Ownership updated", exact: true })).toBeVisible();
  await expect(page.locator(".ownership-command form")).toHaveCount(0);
  const confirmation = page.getByRole("region", { name: "Ownership updated", exact: true });
  await expect(
    confirmation
      .getByRole("region", { name: "Owners", exact: true })
      .locator(":scope > .saved-item-entry"),
  ).toHaveCount(2);
  await expect(confirmation).toContainText("You");
  await expect(confirmation).toContainText(party.displayName);
  await expect(
    confirmation.getByRole("link", { name: "Back to property", exact: true }),
  ).toHaveAttribute("href", `/properties/${property.id}/overview`);
  await expect(confirmation.locator("input, select, textarea, button")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Save ownership change", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add owner", exact: true })).toHaveCount(0);
  await expect(page.getByText("Form status and recovery details", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Changing ownership", { exact: true })).toBeHidden();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toHaveCount(0);
  await expect(page.getByText(/^Operation /)).toHaveCount(0);
  await expect(page.getByText(/^Result record /)).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("region", { name: "Ownership updated", exact: true })
    .screenshot({ path: testInfo.outputPath("ownership-confirmation.png") });
  const updated = await request.get(`/api/properties/${property.id}`);
  expect(updated.ok()).toBe(true);
  const result = (await updated.json()) as Schemas["PropertyMutationResponse"];
  expect(result.ownerships.some((item) => item.partyId === party.id && item.endsOn === null)).toBe(
    true,
  );
});

test("ownership confirmation waits for a known result after an interrupted save", async ({
  page,
  request,
}) => {
  const property = await create(request, "Recoverable ownership confirmation");
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await page.getByRole("button", { name: "Create a new owner", exact: true }).click();
  await page.getByLabel("New owner name", { exact: true }).fill("Confirmation owner");
  await page.getByRole("button", { name: "Add to owners", exact: true }).click();
  await page.getByLabel("Effective date", { exact: true }).fill(property.effectiveLocalDate);
  let writes = 0;
  await page.route(`**/api/properties/${property.id}/ownerships`, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    writes++;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".ownership-command form")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Ownership updated", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Ownership updated", exact: true })).toBeVisible();
  await expect(page.locator(".ownership-command form")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Ownership updated", exact: true })).toContainText(
    "Confirmation owner",
  );
  await expect(
    page
      .getByRole("region", { name: "Ownership updated", exact: true })
      .getByRole("region", { name: "Owners", exact: true })
      .locator(":scope > .saved-item-entry"),
  ).toHaveCount(2);
  expect(writes).toBe(1);
});

test("new owner contacts save with ownership and remain visible after reopening", async ({
  page,
  request,
}, testInfo) => {
  const property = await create(request, "Owner contact office", "office_suites");
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await page.getByRole("button", { name: "Create a new owner", exact: true }).click();
  await page.getByLabel("New owner name", { exact: true }).fill("Morgan with contacts");
  await page.getByRole("button", { name: "Add email", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill("owner-ui@example.test");
  await page.getByRole("button", { name: "Add phone number", exact: true }).click();
  await page.getByLabel("Phone number", { exact: true }).fill("503-555-0199");
  await page.getByRole("button", { name: "Add phone number", exact: true }).click();
  await page.getByLabel("Phone number", { exact: true }).nth(1).fill("503-555-0188");
  await page
    .getByLabel("Mailing address", { exact: true })
    .fill("10 Oak St\nPortland OR 97201\nUS");
  await page.getByRole("button", { name: "Add to owners", exact: true }).click();
  await expect(page.getByLabel("Email", { exact: true })).toHaveValue("owner-ui@example.test");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ownership updated", exact: true })).toBeVisible();
  const confirmation = page.getByRole("region", { name: "Ownership updated", exact: true });
  await expect(
    confirmation
      .getByRole("region", { name: "Owners", exact: true })
      .locator(":scope > .saved-item-entry"),
  ).toHaveCount(2);
  await expect(confirmation).toContainText("Morgan with contacts");
  await expect(
    confirmation.getByRole("link", { name: "Back to property", exact: true }),
  ).toHaveAttribute("href", `/properties/${property.id}/overview`);
  await expect(confirmation.locator("input, select, textarea, button")).toHaveCount(0);
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await expect(page.locator(".owner-contact-details")).toContainText("owner-ui@example.test");
  await expect(page.locator(".owner-contact-details")).toContainText("503-555-0199");
  await expect(page.locator(".owner-contact-details")).toContainText("503-555-0188");
  await expect(page.locator(".owner-contact-details")).toContainText("10 Oak St");
  await expect(
    page.getByRole("link", { name: "Manage contact details", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".ownership-selected > li")).toHaveCount(2);
  await page.getByRole("link", { name: "Manage contact details", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Morgan with contacts", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Shared identities and tenants", exact: true }),
  ).toHaveCount(0);
  const contacts = page.getByRole("region", { name: "Contact details", exact: true });
  await expect(contacts).toContainText("owner-ui@example.test");
  await expect(contacts).toContainText("503-555-0199");
  await expect(contacts).toContainText("10 Oak St");
  await expect(page.getByText("Record details", { exact: true })).toBeVisible();
  await expect(page.getByText("Revision", { exact: true })).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Add contact details", exact: true }),
  ).toBeVisible();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`owner-details-${theme}-${width}.png`),
        fullPage: true,
      });
    }
  }
  await page.evaluate(axe.source);
  expect(
    await page.evaluate(async () =>
      (
        await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    ),
  ).toEqual([]);
  await page.getByRole("link", { name: "← Back to change ownership", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`portfolio.ownerships.replace&target=${property.id}`));
});

test("owner browsing is opt-in and paginates ten results at a time", async ({ page, request }) => {
  const property = await create(request, "Paged ownership search");
  const people = Array.from({ length: 12 }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    displayName: `Paged Owner ${index + 1}`,
    partyKind: "individual",
    revision: 1,
    archivedAt: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  }));
  const calls: URL[] = [];
  let releaseNextPage: () => void = () => undefined;
  const nextPageReady = new Promise<void>((resolve) => {
    releaseNextPage = resolve;
  });
  await page.route("**/api/parties/selection?*", async (route) => {
    const url = new URL(route.request().url());
    calls.push(url);
    const search = url.searchParams.get("search");
    const offset = url.searchParams.get("cursor") ? 10 : 0;
    if (offset) await nextPageReady;
    const matches = search
      ? people.filter((person) => person.displayName.includes(search))
      : people;
    await route.fulfill({
      json: {
        items: matches.slice(offset, offset + 10),
        nextCursor: matches.length > offset + 10 ? people[9].id : null,
      },
    });
  });
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await expect(page.locator(".ownership-search-results")).toHaveCount(0);
  expect(calls).toHaveLength(0);
  await page.getByRole("button", { name: "Browse owners", exact: true }).click();
  await expect(page.locator(".ownership-search-results li")).toHaveCount(10);
  const pages = page.getByRole("navigation", { name: "Owner search pages", exact: true });
  await expect(pages.getByRole("button", { name: "Previous", exact: true })).toBeDisabled();
  await pages.scrollIntoViewIfNeeded();
  const position = await pages.evaluate((nav) => ({
    top: nav.getBoundingClientRect().top,
    scroll: window.scrollY,
  }));
  const results = page.getByRole("region", { name: "Matching owners", exact: true });
  const originalHeight = await results.evaluate(
    (element) => element.getBoundingClientRect().height,
  );
  await pages.getByRole("button", { name: "Next", exact: true }).click();
  await expect(results).toHaveAttribute("aria-busy", "true");
  expect(await results.evaluate((element) => element.getBoundingClientRect().height)).toBe(
    originalHeight,
  );
  expect(await pages.evaluate((nav) => nav.getBoundingClientRect().top)).toBeCloseTo(
    position.top,
    0,
  );
  expect(await page.evaluate(() => window.scrollY)).toBe(position.scroll);
  releaseNextPage();
  await expect(page.locator(".ownership-search-results li")).toHaveCount(2);
  await expect(pages).toContainText("11–12");
  expect(await results.evaluate((element) => element.getBoundingClientRect().height)).toBe(
    originalHeight,
  );
  expect(await pages.evaluate((nav) => nav.getBoundingClientRect().top)).toBeCloseTo(
    position.top,
    0,
  );
  expect(await page.evaluate(() => window.scrollY)).toBe(position.scroll);
  await expect(pages.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  await pages.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.locator(".ownership-search-results li")).toHaveCount(10);
  await page.getByLabel("Find an owner by name", { exact: true }).fill("Paged Owner 12");
  await expect(page.locator(".ownership-search-results li")).toHaveCount(1);
  await expect(pages).toContainText("1–1");
  expect(calls.every((url) => url.searchParams.get("limit") === "10")).toBe(true);
  await expect(page.getByRole("button", { name: "Hide results", exact: true })).toHaveCount(0);
  await page.getByLabel("Find an owner by name", { exact: true }).fill("");
  await expect(page.locator(".ownership-search-results")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save ownership change", exact: true }),
  ).toBeEnabled();
});

test("owner live search debounces typing and never shows stale matches", async ({
  page,
  request,
}) => {
  const property = await create(request, "Live ownership search");
  let releaseOld: () => void = () => undefined;
  const oldReady = new Promise<void>((resolve) => {
    releaseOld = resolve;
  });
  const calls: string[] = [];
  await page.route("**/api/parties/selection?*", async (route) => {
    const search = new URL(route.request().url()).searchParams.get("search") ?? "";
    calls.push(search);
    if (search === "Old") await oldReady;
    await route.fulfill({
      json: {
        items: [
          {
            id: "00000000-0000-4000-8000-000000000099",
            partyKind: "individual",
            displayName: `${search} owner`,
            revision: 1,
            archivedAt: null,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
          },
        ],
        nextCursor: null,
      },
    });
  });
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  const input = page.getByLabel("Find an owner by name", { exact: true });
  await input.fill("Old");
  await expect.poll(() => calls).toEqual(["Old"]);
  await input.fill("");
  await input.pressSequentially("New", { delay: 20 });
  await expect(page.getByRole("button", { name: "Add New owner", exact: true })).toBeVisible();
  releaseOld();
  await expect(page.getByRole("button", { name: "Add Old owner", exact: true })).toHaveCount(0);
  expect(calls).toEqual(["Old", "New"]);
  await input.fill("");
  await expect(page.getByRole("region", { name: "Matching owners", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save ownership change", exact: true }),
  ).toBeEnabled();
});

test("property tabs show one address below the name in the shared header", async ({
  page,
  request,
}) => {
  const property = await create(request, "Property address tabs", "office_suites");
  const address = [
    property.addressLine1,
    property.addressLine2,
    property.city,
    property.region,
    property.postalCode,
  ]
    .filter(Boolean)
    .join(", ");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ["overview", "units", "setup", "money", "maintenance", "conversations"]) {
      await page.goto(`/properties/${property.id}/${tab}`);
      await expect(page.getByLabel("Property address", { exact: true })).toHaveText(address);
      await expect(page.getByText(address, { exact: true })).toHaveCount(1);
      await expect(
        page.locator(".property-workspace-header").getByLabel("Property address", { exact: true }),
      ).toBeVisible();
      expect(
        (await page
          .getByRole("heading", { name: property.displayName, exact: true })
          .boundingBox())!.y,
      ).toBeLessThan((await page.getByLabel("Property address", { exact: true }).boundingBox())!.y);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    }
  }
});

test("property setup puts all actions on the top row without a repeated heading", async ({
  page,
  request,
}) => {
  const property = await create(request, "Setup action row", "office_suites");
  const setupUrl = `/properties/${property.id}/setup`;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(setupUrl);
  const setup = page.getByRole("region", { name: "Property setup", exact: true });
  const actions = setup.getByRole("navigation", { name: "Property actions", exact: true });
  await expect(setup.getByRole("heading", { name: "Property setup", exact: true })).toHaveCount(0);
  await expect(actions.getByRole("button")).toHaveText([
    "Edit Property",
    "Add Suite",
    "Archive property",
  ]);
  const tops = await actions
    .getByRole("button")
    .evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().top));
  expect(new Set(tops).size).toBe(1);
  expect(
    await actions
      .getByRole("button", { name: "Archive property", exact: true })
      .evaluate((button) => getComputedStyle(button).backgroundColor),
  ).toBe("rgba(0, 0, 0, 0)");
  for (const [name, command] of [
    ["Edit Property", "portfolio.property.patch"],
    ["Add Suite", "portfolio.space.create"],
    ["Archive property", "portfolio.property.archive"],
  ]) {
    await actions.getByRole("button", { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`workflow=${command}&target=${property.id}`));
    await page.goto(setupUrl);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await expect(actions.getByRole("button")).toHaveCount(3);
  await expect(setup.getByRole("button", { name: "Change ownership", exact: true })).toHaveCount(0);
  await page.goto(`/properties/${property.id}/overview`);
  const owners = page.getByRole("region", { name: "Owners", exact: true });
  const change = owners.getByRole("button", { name: "Change ownership", exact: true });
  await expect(change).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  expect(
    Math.abs(
      (await owners.getByRole("heading", { name: "Owners", exact: true }).boundingBox())!.y -
        (await change.boundingBox())!.y,
    ),
  ).toBeLessThan(20);
  await change.click();
  await expect(page).toHaveURL(
    new RegExp(`workflow=portfolio.ownerships.replace&target=${property.id}`),
  );
});

test("property edit groups and prefills details without changing ownership or rental status", async ({
  page,
  request,
}, testInfo) => {
  const property = await create(request, "Property edit context", "office_suites");
  const response = await request.patch(`/api/properties/${property.id}`, {
    data: {
      expectedPropertyRevision: property.propertyRevision,
      idempotencyKey: crypto.randomUUID(),
      addressLine2: "North building",
      notes: "Use the courtyard entrance.",
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const prior = (await response.json()) as Schemas["PropertyMutationResponse"];
  for (const theme of ["light", "dark"] as const) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await action(page, "portfolio.property.patch", property.id);
    const context = page.getByRole("region", { name: "Selected property", exact: true });
    await expect(
      context.getByRole("heading", { name: property.displayName, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `← Back to ${property.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/properties/${property.id}/setup`);
    const editor = page.getByRole("region", { name: "Edit property", exact: true });
    for (const name of ["Property name", "Address", "Notes"])
      await expect(editor.getByRole("group", { name, exact: true })).toBeVisible();
    for (const [name, value] of [
      ["Display name", property.displayName],
      ["Address line1", "10 Maple Street"],
      ["Address line2", "North building"],
      ["City", "Portland"],
      ["State", "OR"],
      ["Postal code", "97201"],
      ["Notes", "Use the courtyard entrance."],
    ]) {
      await expect(editor.getByRole("textbox", { name, exact: true })).toHaveValue(value);
    }
    await expect(page.getByText(/Displayed source revision:/)).not.toBeVisible();
    await expect(editor.getByLabel("Region", { exact: true })).toHaveCount(0);
    await expect(editor.getByLabel(/Country code/)).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Return to current record", exact: true }),
    ).toHaveCount(0);
    await expect(editor.locator(".command-form-actions").getByRole("button")).toHaveText([
      "Save property changes",
      "Save unfinished form",
    ]);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`property-edit-${theme}-${width}.png`),
        fullPage: true,
      });
    }
  }
  await page
    .getByRole("textbox", { name: "Display name", exact: true })
    .fill("Updated property name");
  await page.getByRole("textbox", { name: "Notes", exact: true }).fill("New entrance note.");
  await save(page, "Edit property");
  await expect(page).toHaveURL(`/properties/${property.id}/setup`);
  const updatedResponse = await request.get(`/api/properties/${property.id}`);
  const updated = (await updatedResponse.json()) as Schemas["PropertyMutationResponse"];
  expect(updated.displayName).toBe("Updated property name");
  expect(updated.notes).toBe("New entrance note.");
  expect(updated.addressLine2).toBe(prior.addressLine2);
  expect(updated.region).toBe(prior.region);
  expect(updated.postalCode).toBe(prior.postalCode);
  expect(updated.countryCode).toBe("US");
  expect(updated.ownerships).toEqual(prior.ownerships);
  const rentalFacts = (item: Schemas["PropertyMutationResponse"]) =>
    item.spaces.map((space) => ({
      id: space.id,
      revision: space.revision,
      displayName: space.displayName,
      status: space.status,
      occupancy: space.currentOccupancy,
      availability: space.availability,
    }));
  expect(rentalFacts(updated)).toEqual(rentalFacts(prior));
  await action(page, "portfolio.property.patch", property.id);
  await page.getByRole("textbox", { name: "Notes", exact: true }).fill("");
  await page.getByRole("textbox", { name: "Address line2", exact: true }).fill("");
  await save(page, "Edit property");
  const clearedResponse = await request.get(`/api/properties/${property.id}`);
  const cleared = (await clearedResponse.json()) as Schemas["PropertyMutationResponse"];
  expect(cleared.notes).toBeNull();
  expect(cleared.addressLine2).toBeNull();
  expect(cleared.region).toBe("OR");
  expect(cleared.postalCode).toBe("97201");
});

test("interrupted property edit returns to setup only after reconciliation", async ({
  page,
  request,
}) => {
  const property = await create(request, "Interrupted property edit");
  await action(page, "portfolio.property.patch", property.id);
  await page
    .getByRole("textbox", { name: "Display name", exact: true })
    .fill("Saved property edit");
  let writes = 0;
  await page.route(`**/api/properties/${property.id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    writes += 1;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save property changes", exact: true }).click();
  await expect(
    page.getByText("The outcome is unresolved. Check the original receipt before continuing."),
  ).toBeVisible();
  await expect(page).toHaveURL(/workflow=portfolio.property.patch/);
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await page.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(`/properties/${property.id}/setup`);
  expect(writes).toBe(1);
  const response = await request.get(`/api/properties/${property.id}`);
  const updated = (await response.json()) as Schemas["PropertyMutationResponse"];
  expect(updated.displayName).toBe("Saved property edit");
});

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
  await page.goto(`/properties/${property.id}/units`);
  const card = page.getByRole("article", { name: updated.displayName, exact: true });
  await card.getByText("History", { exact: true }).click();
  const change = card.getByRole("article").filter({
    hasText: `Display name changed from ${rental.displayName} to ${updated.displayName}.`,
  });
  await expect(change).toBeVisible();
  await expect(change.getByText("You", { exact: true })).toBeVisible();
  await expect(change.locator("time")).toBeVisible();
  const before = change
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: "Before change" }) });
  const after = change
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: "After change" }) });
  await expect(before).not.toHaveAttribute("open", "");
  await expect(after).not.toHaveAttribute("open", "");
  await before.locator("summary").click();
  await after.locator("summary").click();
  await expect(before.getByText(rental.displayName, { exact: true })).toBeVisible();
  await expect(after.getByText(updated.displayName, { exact: true })).toBeVisible();
  expect(await change.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(
    "rgba(0, 0, 0, 0)",
  );
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
    await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
    expect((await status(request, rental.id)).status).toBe("archived");
    expect((await status(request, property.spaces[1].id)).status).toBe("active");
  }
});

test("guided property creation supports suites, co-owners and shared owner search", async ({
  page,
  request,
}, testInfo) => {
  for (const theme of ["light", "dark"] as const) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto("/properties?workflow=portfolio.property.create");
    const ownership = page.locator("fieldset.ownership-owners");
    await expect(ownership.getByText("You", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Effective date", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel(/Country code/)).toHaveCount(0);
    await expect(page.getByLabel("Region", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Form status and recovery details", { exact: true })).toHaveCount(
      0,
    );
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`property-create-${theme}-${width}.png`),
        fullPage: true,
      });
    }
  }
  await page.getByLabel("Display name (required)", { exact: true }).fill("Guided office create");
  await page.getByLabel("Address line1 (required)", { exact: true }).fill("22 Oak Street");
  await page.getByLabel("City (required)", { exact: true }).fill("Portland");
  await page.getByLabel("State", { exact: true }).fill("OR");
  await page.getByLabel("Postal code", { exact: true }).fill("97201");
  await page
    .getByRole("combobox", { name: "Property type (required)", exact: true })
    .selectOption("office");
  await page
    .getByRole("combobox", { name: "Rental layout", exact: true })
    .selectOption("office_suites");
  await page
    .getByRole("group", { name: "Suite 1", exact: true })
    .getByLabel("Display name (required)", { exact: true })
    .fill("Suite A");
  await page.getByRole("button", { name: "Add suite", exact: true }).click();
  await page
    .getByRole("group", { name: "Suite 2", exact: true })
    .getByLabel("Display name (required)", { exact: true })
    .fill("Suite B");
  const partyResponse = await request.post("/api/parties", {
    data: {
      partyKind: "individual",
      displayName: "Guided office co-owner",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(partyResponse.ok(), await partyResponse.text()).toBe(true);
  const party = (await partyResponse.json()) as Schemas["PartyMutationResponse"];
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await expect(page.getByRole("button", { name: "Create property", exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Save unfinished form", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("region", { name: "Add an owner", exact: true })
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "Create property", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  let writes = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/properties")
      writes++;
  });
  await page.getByLabel("Find an owner by name", { exact: true }).fill(party.displayName);
  await page.getByRole("button", { name: `Add ${party.displayName}`, exact: true }).click();
  expect(writes).toBe(0);
  await expect(page.locator("form form")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create property", exact: true })).toBeEnabled();
  await save(page, "Create property");
  expect(writes).toBe(1);
  const response = await request.get("/api/properties");
  const rows =
    (await response.json()) as Schemas["app__modules__portfolio__api__router__PropertyPageResponse"];
  const created = rows.items.find((item) => item.displayName === "Guided office create")!;
  expect(created.countryCode).toBe("US");
  expect(created.region).toBe("OR");
  expect(created.inventoryLayout).toBe("office_suites");
  expect(created.spaces.map((item) => item.displayName).sort()).toEqual(["Suite A", "Suite B"]);
  expect(created.ownerships.map((owner) => owner.ownerKind).sort()).toEqual([
    "client_owner",
    "local_operator",
  ]);
  expect(created.ownerships.some((owner) => owner.partyId === party.id)).toBe(true);
});

test("US property drafts retain the shared owner form through recovery", async ({
  page,
  request,
}) => {
  let propertyWrites = 0;
  page.on("request", (outgoing) => {
    if (outgoing.method() === "POST" && new URL(outgoing.url()).pathname === "/api/properties")
      propertyWrites++;
  });
  await page.goto("/properties?workflow=portfolio.property.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Recovered US property");
  await page.getByLabel("Address line1 (required)", { exact: true }).fill("45 Cedar Street");
  await page.getByLabel("City (required)", { exact: true }).fill("Portland");
  await page.getByLabel("State", { exact: true }).fill("OR");
  await page.getByLabel("Postal code", { exact: true }).fill("97201");
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await page.getByRole("button", { name: "Create a new owner", exact: true }).click();
  await page.getByLabel("New owner name", { exact: true }).fill("Recovered new owner");
  await page.getByRole("button", { name: "Add to owners", exact: true }).click();
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        /\/api\/operator\/recovery\/[^/]+$/.test(new URL(response.url()).pathname) &&
        response.ok(),
    ),
    page.getByRole("button", { name: "Save unfinished form", exact: true }).click(),
  ]);
  const recovery = await request.get("/api/operator/recovery?limit=100");
  const records = (await recovery.json()) as Schemas["RecoveryPage"];
  const candidates = records.items.filter(
    (item) => item.formKey === "portfolio.property.create" && item.status === "active",
  );
  let recoveryId: string | undefined;
  for (const candidate of candidates) {
    const response = await request.get(`/api/operator/recovery/${candidate.id}`);
    const saved = (await response.json()) as {
      id: string;
      payload: { countryCode?: string; displayName?: string };
    };
    if (saved.payload.displayName === "Recovered US property") {
      expect(saved.payload.countryCode).toBe("US");
      recoveryId = saved.id;
    }
  }
  expect(recoveryId).toBeTruthy();
  expect(propertyWrites).toBe(0);
  await page.goto(`/properties?workflow=portfolio.property.create&resume=${recoveryId}`);
  await expect(page.getByLabel("State", { exact: true })).toHaveValue("OR");
  await expect(page.getByLabel("New owner name", { exact: true })).toHaveValue(
    "Recovered new owner",
  );
  await expect(page.getByLabel(/Country code/)).toHaveCount(0);
  await expect(page.getByText("Form status and recovery details", { exact: true })).toHaveCount(0);
  await save(page, "Create property");
  expect(propertyWrites).toBe(1);
});

test("property autosave keeps inputs stationary and focused", async ({ page }) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  const name = page.getByLabel("Display name (required)", { exact: true });
  await expect(name).toBeVisible();
  let releaseSave!: () => void;
  const saveGate = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  let saving!: () => void;
  const saveStarted = new Promise<void>((resolve) => {
    saving = resolve;
  });
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      /\/api\/operator\/recovery\/[^/]+$/.test(new URL(response.url()).pathname) &&
      response.ok(),
  );
  await page.route("**/api/operator/recovery/*", async (route) => {
    if (route.request().method() === "PUT") {
      saving();
      await saveGate;
    }
    await route.continue();
  });
  await name.fill("Stationary property form");
  const beforeSave = await name.boundingBox();
  await saveStarted;
  try {
    await expect(name).toBeFocused();
    expect((await name.boundingBox())?.y).toBe(beforeSave?.y);
    await expect(page.getByText(/^(Saving unfinished form…|Unfinished form saved\.)$/)).toHaveCount(
      0,
    );
  } finally {
    releaseSave();
  }
  await saved;
  await expect(name).toBeFocused();
  await expect(name).toHaveValue("Stationary property form");
  expect((await name.boundingBox())?.y).toBe(beforeSave?.y);
});

test("interrupted property creation opens its original property only after reconciliation", async ({
  page,
}) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Interrupted create");
  await page.getByLabel("Address line1 (required)").fill("55 Oak Street");
  await page.getByLabel("City (required)").fill("Portland");
  await page.getByLabel("State", { exact: true }).fill("OR");
  await page.getByLabel("Postal code", { exact: true }).fill("97201");
  let writes = 0;
  let createdId = "";
  await page.route("**/api/properties", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    writes++;
    const response = await route.fetch();
    expect(response.ok(), await response.text()).toBe(true);
    createdId = ((await response.json()) as { id: string }).id;
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/workflow=portfolio.property.create/);
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await page.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(`/properties/${createdId}/overview`);
  expect(writes).toBe(1);
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
    const unitTitle = `${item.unit[0].toUpperCase()}${item.unit.slice(1)}`;
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
    ).toHaveCount(0);
    await expect(card.getByRole("link", { name: "Start lease draft", exact: true })).toHaveCount(0);
    await expect(card.getByText("More actions", { exact: true })).toHaveCount(0);
    const archiveAction = card.getByRole("button", {
      name: `Archive ${unitTitle}`,
      exact: true,
    });
    await expect(archiveAction).toHaveCount(item.label === "Suites" ? 1 : 0);
    if (item.label === "Suites") {
      const titleRow = card.locator(".property-space-title-row");
      await expect(titleRow.getByRole("button", { name: "Start lease draft" })).toHaveCount(0);
      await expect(archiveAction).toBeVisible();
      const titleActions = await titleRow.locator("button").allTextContents();
      expect(titleActions).toEqual([`Edit ${unitTitle}`, "Archive Suite"]);
      await expect(archiveAction).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    }
    await expect(
      card.getByRole("button", { name: `Restore ${item.unit}`, exact: true }),
    ).toHaveCount(0);
    await expect(
      card
        .locator(".property-space-title-row")
        .getByRole("button", { name: `Edit ${unitTitle}`, exact: true }),
    ).toBeVisible();
    await card.getByRole("button", { name: `Edit ${unitTitle}`, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: `Edit ${item.unit}`, exact: true }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: `← Back to ${property.displayName}`, exact: true })
      .click();
    await expect(
      card.getByRole("button", { name: `Edit ${unitTitle}`, exact: true }),
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
    await page.goto(`/properties/${property.id}/leases`);
    const leaseGroup = page.getByRole("region", {
      name: `Leases for ${property.spaces[0].displayName}`,
      exact: true,
    });
    await expect(leaseGroup).toContainText("No matching leases on this page.");
    await leaseGroup.getByRole("button", { name: "Start lease draft", exact: true }).click();
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
  await expect(card.getByRole("button", { name: "Edit Home", exact: true })).toBeVisible();
  await expect(card.getByText("Home settings", { exact: true })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Archive home", exact: true })).toHaveCount(0);
  await expect(card.locator("summary")).toHaveText(["History"]);
  await expect(card.getByRole("region", { name: "Scheduled occupancy", exact: true })).toHaveCount(
    0,
  );
  await expect(card.getByText("Details and sources", { exact: true })).toHaveCount(0);
  await expect(card.getByText("Recorded leasing intention:", { exact: false })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Correct an error", exact: true })).toBeVisible();
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
    .getByRole("combobox", { name: "Ownership context", exact: true })
    .selectOption("self_owned");
  await page.getByRole("combobox", { name: "Occupancy", exact: true }).selectOption("vacant");
  await page
    .getByRole("combobox", { name: "Leasing status", exact: true })
    .selectOption("available_now");
  await page.getByRole("combobox", { name: "Needs attention", exact: true }).selectOption("false");
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
  await page.getByText("Form status and recovery details", { exact: true }).click();
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
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
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
