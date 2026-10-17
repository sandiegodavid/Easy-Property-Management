import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("property overview shares review cards, puts them first and identifies suites", async ({
  page,
  request,
}) => {
  const created = await request.post("/api/properties", {
    data: {
      displayName: "Review cards office",
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "office",
      inventoryLayout: "office_suites",
      spaces: [{ displayName: "Suite 201" }, { displayName: "Suite 202" }],
      ownerships: [{ ownerKind: "local_operator" }],
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const item = (await created.json()) as Schema["PropertyMutationResponse"];
  await page.goto(`/properties/${item.id}/overview`);
  const section = page.getByRole("region", { name: "Information review section", exact: true });
  await expect(
    section.getByRole("heading", { name: "Information review", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".context-section").first()).toHaveAttribute("id", "coverage");
  const cards = section.getByRole("listitem");
  await expect(cards).toHaveCount(9);
  await expect(cards.first()).toContainText("Missing required information");
  await expect(section).toContainText("3 items need review");
  for (const suite of ["Suite 201", "Suite 202"]) {
    await expect(cards.filter({ hasText: suite })).toHaveCount(4);
  }
  const inactive = cards.filter({ hasText: "Not applicable" });
  expect(await inactive.count()).toBeGreaterThan(0);
  await expect(inactive.locator("a")).toHaveCount(0);
  await expect(section).not.toContainText(/coverage/i);
  for (const hidden of ["Suites", "Leases", "Money", "Maintenance", "Communications"]) {
    await expect(page.getByRole("region", { name: hidden, exact: true })).toHaveCount(0);
  }
  await expect(page.getByRole("region", { name: "Relationships", exact: true })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Property status summary", exact: true }),
  ).toContainText("2 active suites");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await section.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    );
    const rowGaps = await section.locator(".directory-coverage-card").evaluateAll((elements) => {
      const rows = new Map<number, number>();
      for (const element of elements) {
        const { top, bottom } = element.getBoundingClientRect();
        rows.set(top, Math.max(rows.get(top) ?? bottom, bottom));
      }
      const ordered = [...rows].sort(([a], [b]) => a - b);
      return ordered.slice(1).map(([top], index) => top - ordered[index][1]);
    });
    expect(rowGaps.length).toBeGreaterThan(0);
    for (const gap of rowGaps) expect(gap).toBeGreaterThanOrEqual(15);
  }
  for (const unit of item.spaces) {
    const current = await request.get(`/api/spaces/${unit.id}/status`);
    expect(current.ok(), await current.text()).toBeTruthy();
    const status = (await current.json()) as Schema["SpaceStatusResponse"];
    const classified = await request.put(`/api/spaces/${unit.id}/classification`, {
      data: {
        expectedRevision: status.revision,
        idempotencyKey: crypto.randomUUID(),
        occupancy: { occupancyStatus: "vacant", effectiveOn: status.effectiveLocalDate },
        availability: { availabilityStatus: "not_available" },
      },
    });
    expect(classified.ok(), await classified.text()).toBeTruthy();
  }
  await page.reload();
  await expect(section).toContainText("1 item needs review");
  await cards
    .filter({ hasText: "Suite 202" })
    .getByRole("link", { name: /Review occupancy/ })
    .click();
  await expect(page).toHaveURL(`/coverage/space/${item.spaces[1].id}/occupancy`);
});

test("relationship cards link to the other record by name without self-links or IDs", async ({
  page,
  request,
}) => {
  const client = await property(request, "Relationship client");
  const ownerId = client.ownerships[0].partyId!;
  const mixed = await property(request, "Relationship mixed property", [null, ownerId]);
  for (const suffix of ["", "?relationshipScope=all"]) {
    await page.goto(`/properties/${mixed.id}/overview${suffix}`);
    const relationships = page.getByRole("region", { name: "Relationships", exact: true });
    await expect(
      relationships.getByRole("link", { name: "Relationship client owner", exact: true }),
    ).toHaveAttribute("href", `/owners/${ownerId}/overview`);
    await expect(relationships.getByText("You", { exact: true })).toBeVisible();
    await expect(relationships.getByRole("link", { name: "You", exact: true })).toHaveCount(0);
    await expect(relationships.locator(`a[href="/properties/${mixed.id}/overview"]`)).toHaveCount(
      0,
    );
    await expect(relationships).not.toContainText(mixed.id);
    await expect(relationships).not.toContainText("View source property");
  }
  await page
    .getByRole("region", { name: "Relationships", exact: true })
    .getByRole("link", { name: "Relationship client owner", exact: true })
    .click();
  await expect(page).toHaveURL(`/owners/${ownerId}/overview`);
  const relationships = page.getByRole("region", { name: "Relationships", exact: true });
  await expect(
    relationships.getByRole("link", { name: mixed.displayName, exact: true }),
  ).toHaveAttribute("href", `/properties/${mixed.id}/overview`);
  await expect(relationships).not.toContainText("View source property");
  await relationships.getByRole("link", { name: mixed.displayName, exact: true }).click();
  await expect(page).toHaveURL(`/properties/${mixed.id}/overview`);
});

test("property content scrolls without moving the top area", async ({ page, request }) => {
  const item = await property(request, "Fixed property header");
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`/properties/${item.id}/overview`);
  const content = page.getByRole("region", { name: "Property content", exact: true });
  await expect(content.getByRole("group", { name: "Include relationships" })).toBeVisible();
  const header = page.locator(".property-workspace-header");
  const brand = page.locator(".ui-brand");
  const toolbar = page.locator(".workspace-toolbar");
  const before = await Promise.all([
    header.boundingBox(),
    brand.boundingBox(),
    toolbar.boundingBox(),
  ]);
  await content.hover();
  await page.mouse.wheel(0, 600);
  await expect.poll(() => content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await Promise.all([
    header.boundingBox(),
    brand.boundingBox(),
    toolbar.boundingBox(),
  ]);
  expect(after).toEqual(before);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test("applying a money period preserves the property scroll position while loading", async ({
  page,
  request,
}) => {
  const item = await property(request, "Money scroll position");
  await page.setViewportSize({ width: 1280, height: 500 });
  await page.goto(`/properties/${item.id}/money?fromOn=2026-01-01&throughOn=2026-01-31`);
  const money = page.getByRole("region", { name: "Money", exact: true });
  await expect(money).toContainText("2026-01-01 through 2026-01-31");
  await money.getByLabel("Money from").fill("2026-02-01");
  await money.getByLabel("Money through").fill("2026-02-28");
  const apply = money.getByRole("button", { name: "Apply money period" });
  await apply.scrollIntoViewIfNeeded();
  const content = page.getByRole("region", { name: "Property content", exact: true });
  const before = await content.evaluate((element) => element.scrollTop);
  expect(before).toBeGreaterThan(0);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/operator/properties/${item.id}/overview?*`, async (route) => {
    await pending;
    await route.continue();
  });
  await apply.click();
  await expect(page).toHaveURL(/fromOn=2026-02-01&throughOn=2026-02-28/);
  await expect(money).toContainText("2026-01-01 through 2026-01-31");
  expect(
    Math.abs((await content.evaluate((element) => element.scrollTop)) - before),
  ).toBeLessThanOrEqual(2);
  release();
  await expect(money).toContainText("2026-02-01 through 2026-02-28");
  expect(
    Math.abs((await content.evaluate((element) => element.scrollTop)) - before),
  ).toBeLessThanOrEqual(2);
  await expect(apply).toBeInViewport();
});

test.describe("page capture time", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("directories and overviews show one local capture in the top right", async ({
    page,
    request,
  }) => {
    const item = await property(request, "Local capture property");
    const owner = item.ownerships[0].partyId;
    for (const path of [
      "/properties",
      "/owners",
      "/leasing",
      `/properties/${item.id}/overview`,
      `/owners/${owner}/overview`,
    ]) {
      await page.goto(path);
      const capture = page.locator("#workspace-content .page-as-of");
      await expect(capture).toHaveCount(1);
      await expect(capture).toContainText("America/Los_Angeles");
      const time = capture.locator("time");
      const instant = await time.getAttribute("datetime");
      expect(instant).toBeTruthy();
      const expected = await page.evaluate((value) => {
        return new Intl.DateTimeFormat(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(value!));
      }, instant);
      await expect(time).toContainText(expected);
      await expect(page.locator("#workspace-content p").filter({ hasText: /^As of / })).toHaveCount(
        1,
      );
      const position = await capture.boundingBox();
      const content = await page.locator("#workspace-content").boundingBox();
      expect(position!.y - content!.y).toBeLessThan(30);
      expect(Math.abs(position!.x + position!.width - content!.x - content!.width)).toBeLessThan(2);
    }
  });
});
async function property(request: APIRequestContext, name: string, owners?: (string | null)[]) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: name,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "single_family_home",
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      ownerships: owners
        ? owners.map((partyId) =>
            partyId === null
              ? { ownerKind: "local_operator" }
              : { ownerKind: "client_owner", partyId },
          )
        : [
            {
              ownerKind: "client_owner",
              inlineParty: { partyKind: "individual", displayName: `${name} owner` },
            },
          ],
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Schema["PropertyMutationResponse"];
}

test("property conversations use local timestamps without displaying communication IDs", async ({
  page,
  request,
}) => {
  const item = await property(request, "Conversation timestamps");
  const instant = "2026-10-01T18:30:00Z";
  const response = await request.post("/api/communications", {
    data: {
      direction: "inbound",
      channel: "phone",
      subject: "Property update call",
      body: "Recorded property discussion\nPlease confirm the next visit.",
      occurredAtUtc: instant,
      occurredTimezone: "America/Los_Angeles",
      record: true,
      participants: [{ partyId: item.ownerships[0].partyId, role: "sender" }],
      links: [{ entityType: "property", entityId: item.id }],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const communication = (await response.json()) as Schema["CommunicationReceiptResponse"];
  await page.goto(`/properties/${item.id}/conversations?fromOn=2026-09-30&throughOn=2026-12-31`);
  const localTime = await page.evaluate((at) => {
    const formatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const zone = formatter.resolvedOptions().timeZone;
    return `${formatter.format(new Date(at))} · ${zone}${zone === "America/Los_Angeles" ? "" : " · Source time zone: America/Los_Angeles"}`;
  }, instant);
  const row = page.locator(".context-item-cards > li").filter({ hasText: "Property update call" });
  await expect(row.locator("time")).toHaveText(localTime);
  await expect(row).not.toContainText(communication.id);
  await row.getByRole("link", { name: "View conversation", exact: true }).click();
  const detail = page.getByRole("region", { name: "Source detail", exact: true });
  await expect(
    detail.getByRole("heading", { name: "Property update call", exact: true }),
  ).toBeVisible();
  await expect(detail).toContainText(localTime);
  await expect(detail).not.toContainText(communication.id);
  await expect(detail.getByRole("list", { name: "Conversation participants" })).toContainText(
    `${item.displayName} owner`,
  );
  await expect(detail.getByRole("region", { name: "Message", exact: true })).toContainText(
    "Please confirm the next visit.",
  );
  await expect(
    detail.getByRole("link", { name: "View full conversation", exact: true }),
  ).toHaveAttribute("href", `/conversations?record=communication&id=${communication.id}`);
  expect(await detail.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(
    "rgba(0, 0, 0, 0)",
  );
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await detail.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    );
  }
  await detail.getByRole("link", { name: "Close conversation", exact: true }).click();
  await expect(detail).toHaveCount(0);
  await expect(page).toHaveURL(
    `/properties/${item.id}/conversations?fromOn=2026-09-30&throughOn=2026-12-31`,
  );
});

test("property cards show the scheduled leasing date", async ({ page, request }) => {
  const item = await property(request, "Scheduled leasing date");
  const directory = await request.get("/api/operator/properties?q=Scheduled%20leasing%20date");
  expect(directory.ok()).toBeTruthy();
  const result = (await directory.json()) as Schema["PropertyDirectoryPage"];
  const space = result.items.find((entry) => entry.id === item.id)!.spaces[0];
  const changed = await request.put(`/api/spaces/${space.id}/availability`, {
    data: {
      availabilityStatus: "available_on",
      availableOn: "2099-05-01",
      expectedRevision: space.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  await page.goto("/properties?state=active&availability=available_on");
  const card = page.getByRole("listitem").filter({
    has: page.getByRole("heading", { name: "Scheduled leasing date", exact: true }),
  });
  await expect(card).toContainText("Open for leasing later · 2099-05-01");
});

test("property setup keeps configuration and actions without duplicating overview", async ({
  page,
  request,
}) => {
  const item = await property(request, "Details panels home", [null]);
  await page.goto(`/properties/${item.id}/setup`);
  const details = page.getByRole("region", { name: "Property setup", exact: true });
  const setupTab = page
    .getByRole("navigation", { name: "property sections", exact: true })
    .getByRole("link", { name: "Property setup", exact: true });
  await expect(setupTab).toHaveAttribute("aria-current", "page");
  await expect(setupTab).toHaveAttribute("href", /\/setup\??$/);
  await expect(page.getByText(/^10 Maple Street, Portland, US ·/)).toHaveCount(0);
  await expect(
    details.getByRole("region", { name: "Property information", exact: true }),
  ).toContainText("single family home");
  await expect(details.getByText("10 Maple Street", { exact: true })).toHaveCount(0);
  await expect(details.getByRole("region", { name: "Ownership history", exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("region", { name: "relationships section", exact: true }),
  ).toHaveCount(0);
  await expect(details.locator("summary").filter({ hasText: "Property actions" })).toHaveCount(0);
  const edit = details.getByRole("button", { name: "Edit property", exact: true });
  await expect(edit).toBeVisible();
  await expect(
    details
      .locator(".property-setup-heading")
      .getByRole("button", { name: "Edit property", exact: true }),
  ).toBeVisible();
  await expect(
    details.getByRole("button", { name: "Archive property", exact: true }),
  ).toBeVisible();
  await expect(
    details.getByRole("navigation", { name: "Property actions", exact: true }),
  ).toBeVisible();
  await expect(
    details.getByRole("region", { name: "Property space details", exact: true }),
  ).toHaveCount(0);
  await expect(details.getByText("History", { exact: true }).last()).toBeVisible();
  await details.getByText("History", { exact: true }).last().click();
  const history = details.locator(".property-history");
  const created = history
    .locator(":scope > article")
    .filter({ has: page.getByText("Created", { exact: true }) });
  await expect(created).toHaveCount(1);
  const occurredAt = await created.locator("time").getAttribute("datetime");
  expect(occurredAt).toBeTruthy();
  const localTime = await page.evaluate((value) => {
    const formatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    return `${formatter.format(new Date(value!))} · ${formatter.resolvedOptions().timeZone}`;
  }, occurredAt);
  await expect(created.locator("time")).toHaveText(localTime);
  await expect(created.getByText("You", { exact: true })).toBeVisible();
  await created.getByText("After change", { exact: true }).click();
  await expect(created.getByText("Details panels home", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await edit.click();
  await expect(page).toHaveURL(new RegExp(`workflow=portfolio.property.patch&target=${item.id}`));
});

test("property owner counts include You and co-owners", async ({ page, request }) => {
  const clients = [];
  for (let index = 0; index < 10; index += 1) {
    const item = await property(request, `Owner identity ${index}`);
    clients.push(item.ownerships[0].partyId!);
  }
  const sole = await property(request, "Ownership counts Sole", [null]);
  await property(request, "Ownership counts Mixed", [null, ...clients.slice(0, 2)]);
  await property(request, "Ownership counts Four", clients.slice(0, 4));
  const ten = await property(request, "Ownership counts Ten", clients);
  await page.goto("/properties?q=Ownership%20counts");
  await expect(page.getByText("1 owner · You · 1 rental unit", { exact: true })).toBeVisible();
  await expect(page.getByText("3 owners · 1 rental unit", { exact: true })).toBeVisible();
  await expect(page.getByText("4 owners · 1 rental unit", { exact: true })).toBeVisible();
  const soleCard = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: "Ownership counts Sole", exact: true }) });
  await expect(
    soleCard.getByRole("region", { name: "Owners", exact: true }).getByText("You", { exact: true }),
  ).toBeVisible();
  const mixedCard = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: "Ownership counts Mixed", exact: true }) });
  await expect(
    mixedCard
      .getByRole("region", { name: "Owners", exact: true })
      .getByText("You", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("10 owners · 1 rental unit", { exact: true })).toBeVisible();
  const remaining = page.getByRole("link", { name: "+5 more owners", exact: true });
  await expect(remaining).toHaveAttribute("href", `/properties/${ten.id}/overview#relationships`);
  const tenCard = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: "Ownership counts Ten", exact: true }) });
  await expect(tenCard.getByRole("link", { name: /Owner identity \d owner/ })).toHaveCount(5);
  await expect(tenCard.locator(".property-card-recognition > section")).toHaveCount(2);
  const ownerSection = tenCard.getByRole("region", { name: "Owners", exact: true });
  const spaceSection = tenCard.getByRole("region", { name: "Rental units", exact: true });
  await expect(ownerSection.getByRole("heading", { name: "Owners", exact: true })).toBeVisible();
  await expect(
    spaceSection.getByRole("heading", { name: "Rental units", exact: true }),
  ).toBeVisible();
  await expect(spaceSection.getByText(/Whole home/)).toBeVisible();
  await expect(ownerSection.getByText(/Whole home/)).toHaveCount(0);
  const coverage = tenCard.getByRole("list", { name: "Information review areas" });
  await expect(
    tenCard.getByRole("heading", { name: "Information review", exact: true }),
  ).toHaveCount(0);
  await expect(tenCard).not.toContainText("Local date:");
  await expect(tenCard).not.toContainText("No status attention");
  await expect(
    tenCard.getByText("Occupancy or leasing status needs review", { exact: true }),
  ).toBeVisible();
  const statusReview = tenCard.locator("p").filter({
    hasText: "Occupancy or leasing status needs review",
  });
  await expect(
    statusReview.getByRole("link", { name: "Review status for Ownership counts Ten", exact: true }),
  ).toHaveAttribute("href", `/properties/${ten.id}/units`);
  await expect(
    tenCard.getByRole("link", { name: "View information review", exact: true }),
  ).toHaveCount(0);
  const maintenance = coverage.getByRole("listitem").filter({ hasText: "Maintenance" });
  const notApplicable = coverage.getByRole("listitem").filter({
    has: page.getByText("Not applicable", { exact: true }),
  });
  expect(await notApplicable.count()).toBeGreaterThan(0);
  await expect(notApplicable.getByRole("link")).toHaveCount(0);
  const inactiveCard = notApplicable.first().locator(".directory-coverage-card");
  await expect(inactiveCard).toBeVisible();
  await inactiveCard.click();
  await expect(page).toHaveURL(/\/properties\?q=Ownership/);
  await expect(maintenance.locator(".directory-coverage-area")).toHaveText("Review maintenance");
  await expect(maintenance.locator(".directory-coverage-state")).toHaveText("Needs review");
  await expect(
    maintenance.getByRole("link", { name: "Review maintenance Needs review", exact: true }),
  ).toHaveAttribute("href", `/coverage/property/${ten.id}/maintenance`);
  await expect(maintenance.locator("a .directory-coverage-state")).toHaveCount(1);
  await maintenance.locator(".directory-coverage-state").click();
  await expect(page).toHaveURL(`/coverage/property/${ten.id}/maintenance`);
  await expect(
    page.getByRole("heading", { name: "Maintenance information review", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await remaining.click();
  const allOwners = page.getByRole("region", { name: "relationships section", exact: true });
  await expect(allOwners.getByText("10 owners", { exact: true })).toBeVisible();
  for (let index = 0; index < 10; index += 1) {
    await expect(allOwners.getByText(new RegExp(`Owner identity ${index} owner`))).toBeVisible();
  }
  await page.goto(`/properties/${sole.id}/overview`);
  const relationships = page.getByRole("region", { name: "relationships section", exact: true });
  await expect(relationships.getByText("1 owner · You", { exact: true })).toBeVisible();
  await expect(relationships.getByText("You", { exact: true })).toBeVisible();
});

test("real directories recognize properties and owners, preserve filters and switch records", async ({
  page,
  request,
}) => {
  const first = await property(request, "Éclair Slice49 A");
  const owner = first.ownerships[0]?.partyId;
  expect(owner).toBeTruthy();
  await property(request, "Éclair Slice49 B", [owner!]);
  await property(request, "Second owner Slice49");
  const reads: string[] = [];
  page.on("request", (item) => {
    if (item.url().includes("/api/operator/properties?")) reads.push(item.url());
  });
  await page.goto("/properties?q=Éclair%20Slice49&ownershipContext=managed_for_owner");
  await expect(page.getByText("2 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Éclair Slice49 A", exact: true })).toBeVisible();
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
  await page.getByRole("link", { name: "Éclair Slice49 A", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Éclair Slice49 A", exact: true })).toBeVisible();
  const relationships = page.getByRole("group", { name: "Include relationships", exact: true });
  const current = relationships.getByRole("checkbox", { name: "Current", exact: true });
  const former = relationships.getByRole("checkbox", { name: "Former", exact: true });
  await expect(current).toBeChecked();
  await expect(current).toBeDisabled();
  await former.click();
  await expect(page).toHaveURL(/relationshipScope=all/);
  await expect(former).toBeChecked();
  await current.click();
  await expect(page).toHaveURL(/relationshipScope=former/);
  await expect(current).not.toBeChecked();
  await expect(former).toBeDisabled();
  await current.click();
  await former.click();
  await expect(page).toHaveURL(/relationshipScope=current/);
  await page.getByRole("link", { name: "Property setup", exact: true }).click();
  await expect(page).toHaveURL(/\/setup\?relationshipScope=current/);
  await expect(page.getByRole("region", { name: "Relationships", exact: true })).toHaveCount(0);
  await expect(page.getByText("Switch property", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "← Back to Properties", exact: true }).click();
  await expect(page).toHaveURL(/q=.*Slice49.*ownershipContext=managed_for_owner/);
  await page.goto(`/owners/${owner}/overview`);
  await expect(
    page.getByRole("heading", { level: 2, name: "Éclair Slice49 A owner", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(owner!, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Owner workspace", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Properties", exact: true })).toContainText(
    "2 matching records",
  );
  await expect(page.getByText("Switch owner", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "All owners", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "← Back to Owners", exact: true }).click();
  await expect(page).toHaveURL(/\/owners$/);
  await page.goto("/owners?q=Slice49");
  await expect(page.getByText("2 matching owners", { exact: true })).toBeVisible();
  await page.goto("/owners?q=Éclair%20Slice49&relationshipScope=former");
  await expect(page.getByText("0 matching owners", { exact: true })).toBeVisible();
});

test("independent task continuations and explicit whole-property money use composed reads", async ({
  page,
  request,
}) => {
  const item = await property(request, "Section Slice49");
  for (let index = 0; index < 11; index++) {
    const created = await request.post("/api/tasks", {
      data: {
        title: `Section task ${index}`,
        relatedEntityType: "property",
        relatedEntityId: item.id,
        status: "open",
        priority: "normal",
        isAllDay: false,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
  }
  const reads: string[] = [];
  page.on("request", (entry) => {
    if (entry.url().includes(`/api/operator/properties/${item.id}/overview`))
      reads.push(entry.url());
  });
  await page.goto(`/properties/${item.id}/overview`);
  const tasks = page.getByRole("region", { name: "Tasks", exact: true });
  await expect(tasks).toContainText("11 matching records");
  await expect(tasks.getByRole("link", { name: /View source task/ })).toHaveCount(10);
  await tasks
    .getByRole("link", { name: /View source task/ })
    .first()
    .click();
  await expect(page.getByRole("region", { name: "Source detail", exact: true })).toContainText(
    "Section task",
  );
  await page.getByRole("link", { name: "Close source detail" }).click();
  await page.getByRole("button", { name: "Next tasks", exact: true }).click();
  await expect(tasks.getByRole("link", { name: /View source task/ })).toHaveCount(1);
  expect(reads).toHaveLength(2);
  expect(reads[1]).toContain("section=tasks");
  expect(reads[1]).toContain("cursor=");
  await page
    .getByRole("navigation", { name: "property sections", exact: true })
    .getByRole("link", { name: "money", exact: true })
    .click();
  await expect(page.getByText("Choose an explicit period to read money activity.")).toBeVisible();
  const money = page.getByRole("region", { name: "Money", exact: true });
  await expect(money.getByRole("button", { name: "Retry section", exact: true })).toHaveCount(0);
  await money.getByLabel("Money from").fill("2026-01-01");
  await money.getByLabel("Money through").fill("2026-01-31");
  await money.getByRole("button", { name: "Apply money period" }).click();
  await expect(page.getByText(/Whole-property activity, not owner entitlement/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Money", exact: true })).toContainText(
    "2026-01-01 through 2026-01-31",
  );
  await expect(page.getByRole("region", { name: "Money", exact: true })).toContainText("USD");
  await expect(page).toHaveURL(/fromOn=2026-01-01&throughOn=2026-01-31/);
});

test("expired cursor retains filters; sparse pages keep totals and continuation", async ({
  page,
  request,
}) => {
  await property(request, "Sparse Slice49");
  let calls = 0;
  await page.route("**/api/operator/properties?*", async (route) => {
    calls++;
    const url = new URL(route.request().url());
    if (url.searchParams.get("cursor") === "expired") {
      await route.fulfill({
        status: 409,
        json: { detail: { code: "operator_view_changed", message: "Expired view" } },
      });
      return;
    }
    const response = await route.fetch();
    const data = (await response.json()) as Schema["PropertyDirectoryPage"];
    await route.fulfill({ json: { ...data, items: [], nextCursor: "expired" } });
  });
  await page.goto("/properties?q=Sparse%20Slice49");
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching records on this page.")).toBeVisible();
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByText(/This view changed or its continuation expired/)).toBeVisible();
  await page.getByRole("button", { name: "Refresh results" }).click();
  await expect(page.getByLabel("Property name or address", { exact: true })).toHaveValue(
    "Sparse Slice49",
  );
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  expect(calls).toBeLessThanOrEqual(4);
});

test("section failure never becomes an empty result and date errors retain input", async ({
  page,
  request,
}) => {
  const item = await property(request, "Partial Slice49");
  await page.route(`**/api/operator/properties/${item.id}/overview*`, async (route) => {
    const response = await route.fetch();
    if (!response.ok()) {
      await route.fulfill({ response });
      return;
    }
    const data = (await response.json()) as Schema["OverviewResponse"];
    const section = data.sections.maintenance;
    if (section && section.kind === "maintenance")
      data.sections.maintenance = {
        ...section,
        availability: "unavailable",
        reasonCode: "source_read_unavailable",
        sourceRevision: null,
        items: null,
        matchingTotal: null,
        nextCursor: null,
      };
    await route.fulfill({ json: data });
  });
  await page.goto(`/properties/${item.id}/overview`);
  await expect(page.getByRole("region", { name: "Maintenance", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Relationships", exact: true })).toContainText(
    "1 owner",
  );
  await page
    .getByRole("navigation", { name: "property sections", exact: true })
    .getByRole("link", { name: "maintenance", exact: true })
    .click();
  const maintenance = page.getByRole("region", { name: "Maintenance", exact: true });
  await expect(maintenance).toContainText("This source is unavailable");
  await expect(
    maintenance.getByRole("button", { name: "Retry section", exact: true }),
  ).toBeVisible();
  await expect(maintenance).not.toContainText("0 matching records");
  await page
    .getByRole("navigation", { name: "property sections", exact: true })
    .getByRole("link", { name: "money", exact: true })
    .click();
  await page.getByLabel("Money from").fill("2026-02-01");
  await page.getByLabel("Money through").fill("2026-01-01");
  await page.getByRole("button", { name: "Apply money period" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Money from")).toHaveValue("2026-02-01");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
