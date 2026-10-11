import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import { record } from "@epm/contracts/workflows";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function property(request: APIRequestContext, name: string) {
  const result = await request.post("/api/properties", {
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
  expect(result.status(), await result.text()).toBe(201);
  return (await result.json()) as Schema["PropertyMutationResponse"];
}
async function party(request: APIRequestContext, name: string) {
  const result = await request.post("/api/parties", {
    data: {
      partyKind: "individual",
      displayName: name,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(result.status(), await result.text()).toBe(201);
  return (await result.json()) as Schema["PartyMutationResponse"];
}
async function provider(request: APIRequestContext, name: string) {
  const result = await request.post("/api/providers", {
    data: {
      party: { partyKind: "organization", displayName: name },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(result.status(), await result.text()).toBe(201);
  return (await result.json()) as Schema["ProviderMutationResponse"];
}
async function saved(page: Page, title: string) {
  await page.getByRole("button", { name: `Save ${title.toLowerCase()}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  await expect(page.getByText("Draft saved · Command committed", { exact: true })).toBeVisible();
}

test("progressive property creation commits through a registered form and links to setup", async ({
  page,
  request,
}) => {
  await page.goto("/properties");
  await page.getByText("Set up property", { exact: true }).click();
  await page.getByRole("link", { name: "Create property", exact: true }).click();
  await page
    .getByLabel("Display name (required)", { exact: true })
    .fill("Slice50 progressive home");
  await page.getByLabel("Address line1 (required)").fill("20 Maple Street");
  await page.getByLabel("City (required)").fill("Portland");
  await page.getByLabel("Country code (required)").fill("US");
  await page.getByLabel("Region", { exact: true }).fill("OR");
  await page.getByLabel("Postal code", { exact: true }).fill("97201");
  await saved(page, "Create property");
  const rows = await request.get("/api/properties");
  const result =
    (await rows.json()) as Schema["app__modules__portfolio__api__router__PropertyPageResponse"];
  const created = result.items.find((item) => item.displayName === "Slice50 progressive home")!;
  expect(created.propertyRevision).toBe(1);
  expect(created.spaces).toHaveLength(1);
  await page.getByRole("link", { name: "Return to current record" }).click();
  await page.getByRole("link", { name: "Slice50 progressive home", exact: true }).click();
  await page.getByRole("link", { name: "details", exact: true }).click();
  await expect(page.getByRole("region", { name: "Property setup" })).toContainText(
    "Local operator",
  );
});

test("manual occupancy uses the independent Space revision and rejects foreign children", async ({
  page,
  request,
}) => {
  const item = await property(request, "Slice50 status home");
  const space = item.spaces[0];
  await page.goto(`/properties?workflow=portfolio.space.patch&target=${item.id}&child=${space.id}`);
  await page.getByLabel("Display name", { exact: true }).fill("Updated whole-property space");
  await saved(page, "Edit space");
  const inventory = await request.get(`/api/properties/${item.id}`);
  const updated =
    (await inventory.json()) as Schema["app__modules__portfolio__api__router__PropertyResponse"];
  expect(updated.spaces[0].displayName).toBe("Updated whole-property space");
  expect(updated.propertyRevision).toBe(2);
  await page.goto(`/properties?workflow=portfolio.occupancy.change&target=${space.id}`);
  await page.getByLabel("Occupancy status (required)").selectOption("vacant");
  const tomorrow = new Date(`${item.effectiveLocalDate}T12:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  await page.getByLabel("Effective date (required)").fill(tomorrow.toISOString().slice(0, 10));
  await saved(page, "Change occupancy");
  const latest = await request.get(`/api/spaces/${space.id}/status`);
  const status = (await latest.json()) as Schema["SpaceStatusResponse"];
  expect(status.revision).toBe(space.revision + 1);
  expect(status.scheduledOccupancy?.occupancyStatus).toBe("vacant");
  const other = await property(request, "Slice50 other home");
  await page.goto(
    `/properties?workflow=portfolio.space.patch&target=${item.id}&child=${other.spaces[0].id}`,
  );
  await expect(page.getByRole("alert")).toContainText("does not belong");
  await expect(page.getByRole("button", { name: /Save edit space/ })).toHaveCount(0);
});

test("identity contacts and Tenant preferences use their displayed source revisions", async ({
  page,
  request,
}) => {
  const identity = await party(request, "Slice50 tenant identity");
  await page.goto(`/parties?workflow=party.contact.add&target=${identity.id}`);
  await page.getByLabel("Method kind (required)").selectOption("email");
  await page.getByLabel("Value (required)").fill("tenant50@example.com");
  await saved(page, "Add contact");
  await page.goto(`/parties?workflow=tenant.designate&target=${identity.id}`);
  await saved(page, "Use identity as tenant");
  await page.goto(`/parties?identity=${identity.id}`);
  await expect(page.getByRole("heading", { name: "Tenant preferences" })).toBeVisible();
  await page.getByText("Tenant actions", { exact: true }).click();
  await page.getByRole("link", { name: "Edit tenant preferences" }).click();
  await page.getByLabel("Do not contact", { exact: true }).check();
  await saved(page, "Edit tenant preferences");
  const tenant = await request.get(`/api/tenants/${identity.id}`);
  const result = (await tenant.json()) as Schema["TenantResponse"];
  expect(result.profile.doNotContact).toBe(true);
  expect(result.profile.revision).toBe(2);
  expect(result.partyRevision).toBe(2);
});

test("provider profile and service history commit through their registered OPS forms", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Slice50 services provider");
  const id = created.profile.partyId;
  await page.goto(`/providers/${id}/details`);
  await page.getByText("Add services", { exact: true }).click();
  await page.getByRole("link", { name: "Add service", exact: true }).click();
  await page.getByLabel("Display name (required)").fill("Electrical repair");
  await saved(page, "Add service");
  const response = await request.get(`/api/providers/${id}`);
  const current = (await response.json()) as Schema["ProviderResponse"];
  const service = current.services[0];
  await page.goto(`/providers?workflow=provider.service.archive&target=${id}&child=${service.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await saved(page, "Archive service");
  await page.goto(`/providers/${id}/details`);
  await expect(page.getByText("Electrical repair", { exact: true })).toHaveCount(0);
  await page.getByLabel("Include archived contextual history").check();
  await expect(page.getByText("Electrical repair", { exact: true })).toBeVisible();
  await page.goto(`/providers?workflow=provider.service.restore&target=${id}&child=${service.id}`);
  await saved(page, "Restore service");
});

test("saved forms resume after reload with the original fields", async ({ page, request }) => {
  const identity = await party(request, "Slice50 resumable identity");
  await page.goto(`/parties?workflow=party.patch&target=${identity.id}`);
  await page.getByLabel("Display name (required)").fill("Slice50 recovered identity");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume party.patch", exact: true }).click();
  await expect(page.getByLabel("Display name (required)")).toHaveValue(
    "Slice50 recovered identity",
  );
  await saved(page, "Edit identity");
});

test("saved occupancy corrections recover their child context before timeline validation", async ({
  page,
  request,
}) => {
  const created = await property(request, "Slice50 resumable occupancy");
  const space = created.spaces[0];
  await page.goto(
    `/properties?workflow=portfolio.occupancy.correct&target=${space.id}&child=${space.currentOccupancy.id}`,
  );
  await page.getByLabel("Reason (required)").fill("Clarify the original observation");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume portfolio.occupancy.correct", exact: true }).click();
  await expect(page.getByLabel("Reason (required)")).toHaveValue(
    "Clarify the original observation",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("archived Tenant profiles remain reachable for explicit restoration", async ({
  page,
  request,
}) => {
  const identity = await party(request, "Slice50 archived Tenant");
  await page.goto(`/parties?workflow=tenant.designate&target=${identity.id}`);
  await saved(page, "Use identity as tenant");
  await page.goto(`/parties?workflow=tenant.archive&target=${identity.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await saved(page, "Archive tenant");
  await page.goto(`/parties?identity=${identity.id}`);
  await page.getByText("Tenant actions", { exact: true }).click();
  await page.getByRole("link", { name: "Restore tenant", exact: true }).click();
  await saved(page, "Restore tenant");
  const response = await request.get(`/api/tenants/${identity.id}`);
  const current = (await response.json()) as Schema["TenantResponse"];
  expect(current.profile.archivedAt).toBeNull();
  expect(current.profile.revision).toBe(3);
});

test("an interrupted committed response reconciles without duplicating the Provider service", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Slice50 interrupted provider");
  const id = created.profile.partyId;
  let writes = 0;
  await page.route(`**/api/providers/${id}/services`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    writes++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort("failed");
  });
  await page.goto(`/providers?workflow=provider.service.add&target=${id}`);
  await page.getByLabel("Display name (required)").fill("One retained service");
  await page.getByRole("button", { name: "Save add service", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  expect(writes).toBe(1);
  const response = await request.get(`/api/providers/${id}`);
  const current = (await response.json()) as Schema["ProviderResponse"];
  expect(
    current.services.filter((item) => item.displayName === "One retained service"),
  ).toHaveLength(1);
});

test("stale identity changes retain input without dispatching an official write", async ({
  page,
  request,
}) => {
  const identity = await party(request, "Slice50 stale identity");
  await page.goto(`/parties?workflow=party.patch&target=${identity.id}`);
  await page.getByLabel("Display name (required)").fill("My retained edits");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  const changed = await request.patch(`/api/parties/${identity.id}`, {
    data: {
      displayName: "Newer operator name",
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  let writes = 0;
  page.on("request", (entry) => {
    if (entry.method() === "PATCH" && entry.url().endsWith(`/api/parties/${identity.id}`)) writes++;
  });
  await page.getByRole("button", { name: "Save edit identity", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Display name (required)")).toHaveValue("My retained edits");
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "Review current source" }).click();
  await expect(page.getByRole("region", { name: "Current source review" })).toContainText(
    "Newer operator name",
  );
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Display name (required)")).toHaveValue("My retained edits");
  await saved(page, "Edit identity");
  const response = await request.get(`/api/parties/${identity.id}`);
  const current =
    (await response.json()) as Schema["app__modules__parties__api__router__PartyResponse"];
  expect(current.displayName).toBe("My retained edits");
  expect(current.revision).toBe(3);
});

test("category assignment and archive preserve effective counts and contextual reasons", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Slice50 category provider");
  const id = created.profile.partyId;
  await page.goto("/providers?workflow=provider.category.create");
  await page.getByLabel("Display name (required)").fill("Slice50 specialist");
  await saved(page, "Create provider category");
  const rows = await request.get("/api/provider-categories");
  const categories =
    (await rows.json()) as Schema["app__modules__vendors__api__router__CategoryResponse"][];
  const category = categories.find((item) => item.displayName === "Slice50 specialist")!;
  await page.goto(`/providers?workflow=provider.category_assignment.assign&target=${id}`);
  await page.getByLabel("Category id (required)").selectOption(category.id);
  await saved(page, "Assign category");
  await page.goto("/providers");
  await page.getByText("Category administration", { exact: true }).click();
  const section = page
    .getByRole("heading", { name: "Slice50 specialist", exact: true })
    .locator("..");
  await expect(section).toContainText("Effective provider count");
  await expect(section.locator("dd").filter({ hasText: /^1$/ })).toHaveCount(2); // Revision and source-owned count.
  await page.goto(`/providers?workflow=provider.category.archive&target=${category.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Replaced by a more precise category");
  await saved(page, "Archive provider category");
  await page.goto(`/providers/${id}/details?history=true`);
  await expect(
    page.getByText("Replaced by a more precise category", { exact: true }),
  ).toBeVisible();
});

test("ownership replacement can create an inline owner without erasing interval history", async ({
  page,
  request,
}) => {
  const created = await property(request, "Slice50 ownership home");
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${created.id}`);
  await page.getByLabel("Effective date (required)").fill(created.effectiveLocalDate);
  await page.getByRole("button", { name: "Add ownerships entry" }).click();
  const owner = page.getByRole("group", { name: "Ownerships 1", exact: true });
  await owner.getByLabel("Ownership kind (required)").selectOption("client_owner");
  await owner.getByRole("button", { name: "Add create owner identity here" }).click();
  await owner.getByLabel("Identity kind (required)").selectOption("individual");
  await owner.getByLabel("Display name (required)").fill("Slice50 inline owner");
  await saved(page, "Change ownership");
  const response = await request.get(`/api/properties/${created.id}`);
  const current =
    (await response.json()) as Schema["app__modules__portfolio__api__router__PropertyResponse"];
  expect(
    current.ownerships.some((item) => item.party?.displayName === "Slice50 inline owner"),
  ).toBe(true);
  const history = await request.get(`/api/audit/events/property/${created.id}`);
  const events = record(await history.json()).events as unknown[];
  const change = events.map(record).find((event) => event.action === "ownership_changed")!;
  const prior = record(change.before).ownerships as unknown[];
  expect(prior.map(record).some((item) => item.ownerKind === "local_operator")).toBe(true);
  expect(current.propertyRevision).toBe(2);
});

test("Provider area, work, reference and reputation forms record independently owned children", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Slice50 full Provider");
  const id = created.profile.partyId;
  const jobs: {
    key: string;
    title: string;
    values: [string, string][];
    selects?: [string, string][];
  }[] = [
    {
      key: "area",
      title: "service area",
      values: [
        ["Display name (required)", "Portland metro"],
        ["Country code", "US"],
      ],
    },
    {
      key: "work_history",
      title: "work history",
      values: [
        ["Performed on (required)", "2026-01-01"],
        ["Summary (required)", "Fixture work history"],
      ],
    },
    {
      key: "reference",
      title: "reference",
      values: [
        ["Reference name", "Prior client"],
        ["Email", "prior@example.com"],
      ],
    },
    {
      key: "reputation_link",
      title: "reputation link",
      values: [
        ["Url (required)", "https://example.com/profile"],
        ["Source name", "Directory"],
      ],
      selects: [["Source kind (required)", "other"]],
    },
  ];
  for (const job of jobs) {
    await page.goto(`/providers?workflow=provider.${job.key}.add&target=${id}`);
    for (const [label, value] of job.values)
      await page.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of job.selects ?? [])
      await page.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    await saved(page, `Add ${job.title}`);
  }
  const response = await request.get(`/api/providers/${id}`);
  const current = (await response.json()) as Schema["ProviderResponse"];
  expect(current.profile.revision).toBe(5);
  expect(current.serviceAreas[0].displayName).toBe("Portland metro");
  expect(current.workHistory[0].summary).toBe("Fixture work history");
  expect(current.references[0].referenceName).toBe("Prior client");
  expect(current.reputationLinks[0].url).toBe("https://example.com/profile");
});
