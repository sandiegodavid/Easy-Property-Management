import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import { record } from "@epm/contracts/workflows";
import axe from "axe-core";

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
  await page.getByRole("button", { name: "Create property", exact: true }).click();
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
  await page.getByRole("link", { name: "Property setup", exact: true }).click();
  await expect(page.getByRole("region", { name: "Property setup" })).toContainText("Configuration");
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

test("new Provider identity is created through the saved form and remains separate from Maintenance work", async ({
  page,
  request,
}) => {
  const name = `New Provider ${crypto.randomUUID()}`;
  await page.goto("/providers?workflow=provider.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill(name);
  await page
    .getByRole("combobox", { name: "Selection status", exact: true })
    .selectOption("preferred");
  await saved(page, "Create provider");
  const response = await request.get("/api/providers", { params: { search: name } });
  expect(response.ok(), await response.text()).toBe(true);
  const result = (await response.json()) as Schema["ProviderPageResponse"];
  expect(result.items).toHaveLength(1);
  const item = result.items[0];
  expect(item.party.displayName).toBe(name);
  expect(item.profile.selectionStatus).toBe("preferred");
  await page.goto(`/providers/${item.party.id}/details`);
  await expect(page.getByRole("region", { name: "Provider record", exact: true })).toContainText(
    "Manually recorded prior work",
  );
});

test("existing shared identity becomes a Provider without duplicating identity and keeps lifecycle history", async ({
  page,
  request,
}) => {
  const identity = await party(request, `Reusable Provider ${crypto.randomUUID()}`);
  await page.goto("/providers");
  await page.getByText("Use an existing identity", { exact: true }).click();
  await page.getByLabel("Existing identity ID", { exact: true }).fill(identity.id);
  await page.getByRole("button", { name: "Find identity", exact: true }).click();
  await page.getByRole("button", { name: `Use ${identity.displayName}`, exact: true }).click();
  await saved(page, "Use identity as provider");
  const current = (await (
    await request.get(`/api/providers/${identity.id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(current.party.id).toBe(identity.id);
  const invalid = await request.patch(`/api/providers/${identity.id}`, {
    data: {
      expectedRevision: current.profile.revision,
      idempotencyKey: crypto.randomUUID(),
      selectionStatus: "avoid",
    },
  });
  expect(invalid.status()).toBe(400);
  await page.goto(`/providers?workflow=provider.profile.patch&target=${identity.id}`);
  await page.getByRole("combobox", { name: "Selection status", exact: true }).selectOption("avoid");
  await page.getByLabel("Clear selection reason", { exact: true }).uncheck();
  await page.getByLabel("Selection reason", { exact: true }).fill("Operator recorded concern");
  await saved(page, "Edit provider profile");
  await page.goto(`/providers?workflow=provider.archive&target=${identity.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await saved(page, "Archive provider");
  const retained = (await (
    await request.get(`/api/parties/${identity.id}`)
  ).json()) as Schema["app__modules__parties__api__router__PartyResponse"];
  expect(retained.archivedAt).toBeNull();
  expect(retained.id).toBe(identity.id);
  expect(retained.revision).toBe(identity.revision);
  await page.goto(`/providers/${identity.id}/details`);
  await expect(page.getByRole("region", { name: "Provider record", exact: true })).toContainText(
    "Operator recorded concern",
  );
  await page.getByText("Provider actions", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Edit provider profile", exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("link", { name: "Restore provider", exact: true }).click();
  await saved(page, "Restore provider");
  const restored = (await (
    await request.get(`/api/providers/${identity.id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(restored.profile.archivedAt).toBeNull();
  expect(restored.profile.selectionStatus).toBe("avoid");
  expect(restored.party.id).toBe(identity.id);
});

test("Provider search combines service area references and avoid state with accessible contextual review", async ({
  page,
  request,
}) => {
  const created = await provider(request, `Éclair Provider ${crypto.randomUUID()}`);
  const id = created.profile.partyId;
  let revision = created.profile.revision;
  for (const [path, payload] of [
    ["services", { displayName: "Electrical repair" }],
    ["service-areas", { displayName: "Portland metro", countryCode: "US" }],
    ["references", { referenceName: "Prior client", email: "prior@example.com" }],
    ["work-history", { performedOn: "2026-01-01", summary: "Manual rewiring history" }],
  ] as const) {
    const response = await request.post(`/api/providers/${id}/${path}`, {
      data: { ...payload, expectedRevision: revision, idempotencyKey: crypto.randomUUID() },
    });
    expect(response.status(), await response.text()).toBe(201);
    revision = (
      (await response.json()) as
        | Schema["ServiceMutationResponse"]
        | Schema["AreaMutationResponse"]
        | Schema["ReferenceMutationResponse"]
        | Schema["WorkMutationResponse"]
    ).revision;
  }
  const patched = await request.patch(`/api/providers/${id}`, {
    data: {
      expectedRevision: revision,
      idempotencyKey: crypto.randomUUID(),
      selectionStatus: "avoid",
      selectionReason: "Review before assignment",
    },
  });
  expect(patched.ok(), await patched.text()).toBe(true);
  await page.goto("/providers");
  await page.getByLabel("Search Providers", { exact: true }).fill(created.party.displayName);
  await page.getByLabel("Service", { exact: true }).fill("Electrical repair");
  await page.getByLabel("Service area", { exact: true }).fill("Portland metro");
  await page.getByLabel("Has reference", { exact: true }).check();
  await page.getByRole("combobox", { name: "Selection status", exact: true }).selectOption("avoid");
  await page.getByRole("button", { name: "Apply Provider filters", exact: true }).click();
  await page
    .getByRole("region", { name: "Provider directory", exact: true })
    .getByRole("link", { name: created.party.displayName, exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 900 });
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto(`/providers/${id}/details`);
    await expect(page.getByRole("region", { name: "Provider record", exact: true })).toContainText(
      "Manually recorded prior work",
    );
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
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
  const link = page.getByRole("link", { name: "Shared identity and contacts", exact: true });
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/parties\\?identity=${id}`));
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

test("manual reputation sources retain safe external pointers and contextual lifecycle history", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Manual reputation Provider");
  const id = created.profile.partyId;
  let externalRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).hostname === "reputation.example") externalRequests++;
  });
  for (const kind of ["google", "yelp", "angi", "other"]) {
    await page.goto(`/providers?workflow=provider.reputation_link.add&target=${id}`);
    await page
      .getByRole("combobox", { name: "Source kind (required)", exact: true })
      .selectOption(kind);
    await page
      .getByLabel("Url (required)", { exact: true })
      .fill(`https://REPUTATION.example:443/${kind}_reviews`);
    if (kind === "other")
      await page.getByLabel("Source name", { exact: true }).fill("Local directory");
    await page.getByLabel("Notes", { exact: true }).fill("Private reputation context");
    await page.getByLabel("Last checked on", { exact: true }).fill("2025-01-02");
    await saved(page, "Add reputation link");
  }
  const detail = (await (
    await request.get(`/api/providers/${id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(detail.reputationLinks).toHaveLength(4);
  const google = detail.reputationLinks.find((item) => item.sourceKind === "google")!;
  expect(google.url).toBe("https://reputation.example/google_reviews");
  let historyReads = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/audit/events/provider_reputation_link/")) historyReads++;
  });
  await page.goto(`/providers/${id}/details`);
  const section = page.getByRole("region", { name: "Reputation links", exact: true });
  await expect(section).toContainText("not verified ratings or endorsements");
  const external = section.getByRole("link", {
    name: "Review google externally (new tab)",
    exact: true,
  });
  await expect(external).toHaveAttribute("href", google.url);
  await expect(external).toHaveAttribute("rel", "noopener noreferrer");
  await expect(external).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(historyReads).toBe(0);
  expect(externalRequests).toBe(0);
  await page.goto(
    `/providers?workflow=provider.reputation_link.update&target=${id}&child=${google.id}`,
  );
  await page
    .getByRole("textbox", { name: "Url", exact: true })
    .fill("https://reputation.example/google_updated");
  await page.getByRole("textbox", { name: "Notes", exact: true }).fill("Revised private context");
  await saved(page, "Edit reputation link");
  await page.goto(
    `/providers?workflow=provider.reputation_link.archive&target=${id}&child=${google.id}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await saved(page, "Archive reputation link");
  await page.goto(`/providers/${id}/details`);
  await expect(
    section.getByRole("link", { name: "Review google externally (new tab)", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Include archived contextual history", { exact: true }).check();
  const historyRow = section
    .locator(":scope > article")
    .filter({ hasText: "https://reputation.example/google_updated" });
  await expect(historyRow).toContainText("Revised private context");
  await historyRow.getByText("History", { exact: true }).click();
  await expect(historyRow.getByText("archived", { exact: true })).toBeVisible();
  await historyRow.getByText("Resulting facts", { exact: true }).last().click();
  await expect(historyRow).toContainText("https://reputation.example/google_reviews");
  expect(externalRequests).toBe(0);
  await page.goto(
    `/providers?workflow=provider.reputation_link.restore&target=${id}&child=${google.id}`,
  );
  await saved(page, "Restore reputation link");
  const restored = (await (
    await request.get(`/api/providers/${id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(restored.reputationLinks.find((item) => item.id === google.id)?.archivedAt).toBeNull();
  expect(restored.profile.selectionStatus).toBe(created.profile.selectionStatus);
  const summary = (await (
    await request.get("/api/providers", { params: { search: created.party.displayName } })
  ).json()) as Schema["ProviderPageResponse"];
  expect(summary.items[0].reputationLinkCount).toBe(4);
  expect(JSON.stringify(summary)).not.toContain("reputation.example");
  expect(JSON.stringify(summary)).not.toContain("Private reputation context");
});

test("reputation edits reconcile a lost response and reject unsafe or duplicate pointers", async ({
  page,
  request,
}) => {
  const created = await provider(request, "Reputation retry Provider");
  const id = created.profile.partyId;
  const response = await request.post(`/api/providers/${id}/reputation-links`, {
    data: {
      sourceKind: "google",
      url: "https://reputation.example/retry",
      notes: "Original note",
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const first = (await response.json()) as Schema["ReputationMutationResponse"];
  for (const [payload, status] of [
    [{ sourceKind: "google", url: "https://reputation.example/duplicate" }, 409],
    [{ sourceKind: "yelp", url: "https://reputation.example/retry" }, 409],
    [{ sourceKind: "other", url: "https://reputation.example/other" }, 422],
    [{ sourceKind: "angi", url: "javascript:alert(1)" }, 422],
  ] as const) {
    const rejected = await request.post(`/api/providers/${id}/reputation-links`, {
      data: {
        ...payload,
        expectedRevision: first.revision,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(rejected.status(), await rejected.text()).toBe(status);
  }
  let writes = 0;
  await page.route(`**/api/providers/${id}/reputation-links/${first.item.id}`, async (route) => {
    if (route.request().method() === "PATCH") {
      writes++;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto(
    `/providers?workflow=provider.reputation_link.update&target=${id}&child=${first.item.id}`,
  );
  await page.getByRole("textbox", { name: "Notes", exact: true }).fill("Updated note after review");
  await page.getByRole("button", { name: "Save edit reputation link", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result", exact: true })).toBeVisible();
  expect(writes).toBe(1);
  const current = (await (
    await request.get(`/api/providers/${id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(current.reputationLinks).toHaveLength(1);
  expect(current.reputationLinks[0].id).toBe(first.item.id);
  expect(current.reputationLinks[0].notes).toBe("Updated note after review");
  expect(current.profile.revision).toBe(3);
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
