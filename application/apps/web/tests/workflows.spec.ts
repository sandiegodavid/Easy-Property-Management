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
  await test.step(title, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  if (title === "Create property") {
    await page.getByRole("link", { name: "Back to property", exact: true }).click();
    await expect(page).toHaveURL(/\/properties\/[^/]+\/overview$/);
    return;
  }
  await expect(page.locator(".saved-item")).toBeVisible();
  await expect(page.getByText(/^Operation /)).toHaveCount(0);
  await expect(page.getByText(/^Result record /)).toHaveCount(0);
}

test("progressive property creation opens the new property overview", async ({ page, request }) => {
  const savedCountries: unknown[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "PUT" &&
      /^\/api\/operator\/recovery\/[^/]+$/.test(new URL(request.url()).pathname)
    )
      savedCountries.push(record(record(request.postDataJSON()).payload).countryCode);
  });
  await page.goto("/properties");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await page
    .getByLabel("Display name (required)", { exact: true })
    .fill("Slice50 progressive home");
  await page.getByLabel("Address line1 (required)").fill("20 Maple Street");
  await page.getByLabel("City (required)").fill("Portland");
  await expect(page.getByLabel(/Country code/)).toHaveCount(0);
  await page.getByLabel("State", { exact: true }).selectOption("OR");
  await page.getByLabel("Postal code", { exact: true }).fill("97201");
  await expect(page.getByText("Form status and recovery details", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await page.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(/\/properties\/[^/]+\/overview$/);
  expect(savedCountries.length).toBeGreaterThan(0);
  expect(savedCountries.every((country) => country === "US")).toBe(true);
  const rows = await request.get("/api/properties");
  const result =
    (await rows.json()) as Schema["app__modules__portfolio__api__router__PropertyPageResponse"];
  const created = result.items.find((item) => item.displayName === "Slice50 progressive home")!;
  expect(created.countryCode).toBe("US");
  expect(created.propertyRevision).toBe(1);
  expect(created.spaces).toHaveLength(1);
  await expect(page).toHaveURL(`/properties/${created.id}/overview`);
  await expect(page.getByRole("region", { name: "Unfinished form", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Property setup", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Property information", exact: true }),
  ).toContainText("single family home");
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
  await expect(page.getByRole("button", { name: /Save space changes/ })).toHaveCount(0);
});

test("identity contacts and Tenant preferences use their displayed source revisions", async ({
  page,
  request,
}, testInfo) => {
  const identity = await party(request, "Slice50 tenant identity");
  await page.goto(`/parties?workflow=party.contact.add&target=${identity.id}`);
  const back = page.getByRole("link", { name: `← Back to ${identity.displayName}`, exact: true });
  await expect(back).toHaveAttribute("href", `/parties?identity=${identity.id}`);
  await back.click();
  await expect(
    page.getByRole("heading", { name: identity.displayName, exact: true }),
  ).toBeVisible();
  await page.goto(`/parties?workflow=party.contact.add&target=${identity.id}`);
  const editor = page.getByRole("region", { name: "Add contact details", exact: true });
  await expect(editor.getByRole("heading", { name: "Add contact details" })).toBeVisible();
  await expect(page.locator(".command-form-actions button")).toHaveText([
    "Add contact details",
    "Save unfinished form",
  ]);
  await expect(page.getByRole("link", { name: "Return to current record" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Check latest contact record" })).toBeHidden();
  await expect(page.getByText("Identity and contact changes use", { exact: false })).toHaveCount(0);
  await expect(page.getByLabel("Contact type (required)")).toHaveValue("email");
  await expect(editor.getByRole("checkbox")).toHaveCount(1);
  await expect(editor.getByLabel("Make primary for this contact type")).not.toBeChecked();
  await expect(editor.locator(".workflow-field > label")).toHaveText([
    /Contact type \(required\)/,
    "Email (required)",
    "Label",
    "Make primary for this contact type",
  ]);
  await page.getByLabel("Contact type (required)").selectOption("phone");
  await expect(page.getByLabel("Phone number (required)")).toBeVisible();
  await expect(page.getByLabel("Extension", { exact: true })).toBeVisible();
  await page.getByLabel("Contact type (required)").selectOption("mailing_address");
  await expect(page.getByLabel("Mailing address (required)")).toHaveJSProperty(
    "tagName",
    "TEXTAREA",
  );
  await expect(page.getByLabel("Extension", { exact: true })).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await editor.screenshot({ path: testInfo.outputPath(`contact-form-${theme}-${width}.png`) });
    }
  }
  await page.getByLabel("Contact type (required)").selectOption("email");
  await page.getByLabel("Email (required)").fill("tenant50@example.com");
  await saved(page, "Add contact");
  await page.goto(`/tenants?workflow=tenant.designate&target=${identity.id}`);
  await saved(page, "Use identity as tenant");
  await page.goto(`/tenants?identity=${identity.id}`);
  await expect(page.getByRole("heading", { name: "Tenant preferences" })).toBeVisible();
  const contacts = page.getByRole("region", { name: "Contact details", exact: true });
  const preferences = page.getByRole("region", { name: "Tenant preferences", exact: true });
  await expect(
    contacts.getByRole("button", { name: "Add contact details", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("More actions", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Archive person or organization", exact: true }),
  ).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const [panel, title, action] of [
        [contacts, "Contact details", "Add contact details"],
        [preferences, "Tenant preferences", "Edit tenant preferences"],
      ] as const) {
        const heading = await panel
          .getByRole("heading", { name: title, exact: true })
          .boundingBox();
        const button = await panel.getByRole("button", { name: action, exact: true }).boundingBox();
        if (width === 1280)
          expect(
            Math.abs(heading!.y + heading!.height / 2 - button!.y - button!.height / 2),
          ).toBeLessThan(2);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page
        .locator(".person-detail")
        .screenshot({ path: testInfo.outputPath(`tenant-details-${theme}-${width}.png`) });
    }
    await page.evaluate(axe.source);
    expect(
      await page.evaluate(async () =>
        (
          await window.axe.run(".person-detail", {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
          })
        ).violations.map((item) => item.id),
      ),
    ).toEqual([]);
  }
  const archive = page.getByRole("button", { name: "Archive tenant", exact: true });
  expect((await archive.boundingBox())!.y).toBeGreaterThan(
    (await preferences.boundingBox())!.y + (await preferences.boundingBox())!.height,
  );
  await preferences.getByRole("button", { name: "Edit tenant preferences", exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(`/tenants\\?workflow=tenant.profile.patch&target=${identity.id}`),
  );
  await expect(
    page.getByText("Name and contact changes are saved separately from tenant preferences.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.getByText(/Party revision|owning role|separate Tenant revision/)).toHaveCount(
    0,
  );
  await page.getByLabel("Do not contact", { exact: true }).check();
  await saved(page, "Edit tenant preferences");
  const tenant = await request.get(`/api/tenants/${identity.id}`);
  const result = (await tenant.json()) as Schema["TenantResponse"];
  expect(result.profile.doNotContact).toBe(true);
  expect(result.profile.revision).toBe(2);
  expect(result.partyRevision).toBe(2);
});

test("shared contacts allow multiple values per type, switch primary and retain removed history", async ({
  page,
  request,
}) => {
  const identity = await party(request, "Shared primary contacts");
  const addUrl = `/parties?workflow=party.contact.add&target=${identity.id}`;
  const values = [
    { type: "email", field: "Email", entries: ["first@example.com", "second@example.com"] },
    { type: "phone", field: "Phone number", entries: ["+15035550101", "+15035550102"] },
    {
      type: "mailing_address",
      field: "Mailing address",
      entries: ["1 Maple Street\nPortland, OR 97201", "2 Maple Street\nPortland, OR 97201"],
    },
  ];
  for (const { type, field, entries } of values) {
    for (const [index, value] of entries.entries()) {
      await page.goto(addUrl);
      await page.getByLabel("Contact type (required)").selectOption(type);
      await page.getByLabel(`${field} (required)`, { exact: true }).fill(value);
      await page.getByLabel("Label", { exact: true }).fill(`${type} ${index + 1}`);
      await saved(page, "Add contact");
      const row = page.locator(".saved-item");
      await expect(row).toContainText(value);
      await expect(
        row
          .getByText("Primary contact", { exact: true })
          .locator("..")
          .getByText(index === 0 ? "Yes" : "No", { exact: true }),
      ).toBeVisible();
    }
  }
  for (const { type } of values) {
    await page.goto(addUrl);
    const first = page.locator(".person-contact-row").filter({ hasText: `${type} 1` });
    const second = page.locator(".person-contact-row").filter({ hasText: `${type} 2` });
    // Primary removal must use the archive command and fail until another is selected.
    await first.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(
      page.getByRole("link", { name: `← Back to ${identity.displayName}`, exact: true }),
    ).toHaveAttribute("href", `/parties?identity=${identity.id}`);
    await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
    await page.getByRole("button", { name: "Remove contact details", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.goto(addUrl);
    await second.getByRole("link", { name: "Make primary", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Edit contact details", exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Make primary for this contact type")).toBeChecked();
    await page.getByRole("button", { name: "Save contact details", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Contact details updated", exact: true }),
    ).toBeVisible();
    await page.goto(addUrl);
    await expect(second.getByText("Primary", { exact: true })).toBeVisible();
    await expect(first.getByText("Primary", { exact: true })).toHaveCount(0);
    await first.getByRole("button", { name: "Edit", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Edit contact details", exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Label", { exact: true })).toHaveValue(`${type} 1`);
    await page.getByLabel("Label", { exact: true }).fill(`${type} edited`);
    await expect(page.getByLabel("Label", { exact: true })).toHaveValue(`${type} edited`);
    await page.getByRole("button", { name: "Save contact details", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Contact details updated", exact: true }),
    ).toBeVisible();
    await page.goto(addUrl);
    await page
      .locator(".person-contact-row")
      .filter({ hasText: `${type} edited` })
      .getByRole("button", { name: "Remove", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Add resolve contact references entry" }),
    ).toBeVisible();
    await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
    await page.getByRole("button", { name: "Remove contact details", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Archive contact — complete", exact: true }),
    ).toBeVisible();
    await page.goto(addUrl);
    const list = page.getByRole("region", { name: "Contact details", exact: true });
    await expect(
      list.locator(":scope > ul > li").filter({ hasText: `${type} edited` }),
    ).toHaveCount(0);
    await list.getByText(/^Archived contacts/).click();
    await expect(
      list
        .locator("details li")
        .filter({ hasText: `${type} edited` })
        .getByRole("button", { name: "Restore", exact: true }),
    ).toBeVisible();
    // The final active contact of a type can be removed even though it is primary.
    await second.getByRole("button", { name: "Remove", exact: true }).click();
    await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
    await page.getByRole("button", { name: "Remove contact details", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Archive contact — complete", exact: true }),
    ).toBeVisible();
  }
});

test("shared contact primary edits recover interrupted results and preserve stale input", async ({
  page,
  request,
}) => {
  const identity = await party(request, "Recoverable primary contacts");
  const addUrl = `/parties?workflow=party.contact.add&target=${identity.id}`;
  for (const value of ["original@example.com", "replacement@example.com"]) {
    await page.goto(addUrl);
    await page.getByLabel("Email (required)").fill(value);
    await saved(page, "Add contact");
  }
  await page.goto(addUrl);
  await page
    .locator(".person-contact-row")
    .filter({ hasText: "replacement@example.com" })
    .getByRole("link", { name: "Make primary", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Edit contact details", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Make primary for this contact type")).toBeChecked();
  await page.getByLabel("Label", { exact: true }).fill("Retained primary edit");
  await expect(page.getByLabel("Label", { exact: true })).toHaveValue("Retained primary edit");
  await page.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  const changed = await request.patch(`/api/parties/${identity.id}`, {
    data: {
      displayName: "Newer shared name",
      expectedRevision: 3,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(changed.ok(), await changed.text()).toBe(true);
  let writes = 0;
  await page.route(`**/api/parties/${identity.id}/contact-methods/*`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    writes++;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body.isPrimary).toBe(true);
    expect(body.value).toBe("replacement@example.com");
    expect(body.methodKind).toBe("email");
    expect(body.label).toBe("Retained primary edit");
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save contact details", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(writes).toBe(0);
  await expect(page.getByLabel("Label", { exact: true })).toHaveValue("Retained primary edit");
  await expect(page.getByLabel("Make primary for this contact type")).toBeChecked();
  await page.getByRole("button", { name: "Check latest contact record", exact: true }).click();
  await expect(page.getByRole("region", { name: "Current source review" })).toContainText(
    "Newer shared name",
  );
  await page
    .getByRole("button", { name: "Keep my edits with this reviewed revision", exact: true })
    .click();
  await page.getByRole("button", { name: "Save contact details", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Contact details updated", exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  await page.goto(addUrl);
  const active = page
    .getByRole("region", { name: "Contact details", exact: true })
    .locator(":scope > ul > li");
  await expect(active).toHaveCount(2);
  await expect(
    active.filter({ hasText: "Retained primary edit" }).getByText("Primary", { exact: true }),
  ).toBeVisible();
  await expect(
    active.filter({ hasText: "original@example.com" }).getByText("Primary", { exact: true }),
  ).toHaveCount(0);
});

test("provider directory presents services and preferences without identity or catalog clutter", async ({
  page,
  request,
}, testInfo) => {
  const term = `Directory ${crypto.randomUUID().slice(0, 8)}`;
  const created = await provider(request, `Harbor Services ${term}`);
  const other = await provider(request, `Cedar Repairs ${term}`);
  const service = await request.post(`/api/providers/${created.party.id}/services`, {
    data: {
      displayName: "Plumbing repair",
      expectedRevision: created.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(service.ok(), await service.text()).toBe(true);
  const current = (await service.json()) as Schema["ServiceMutationResponse"];
  const preferred = await request.patch(`/api/providers/${created.party.id}`, {
    data: {
      selectionStatus: "preferred",
      expectedRevision: current.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(preferred.ok(), await preferred.text()).toBe(true);
  const avoided = await request.patch(`/api/providers/${other.party.id}`, {
    data: {
      selectionStatus: "avoid",
      selectionReason: "Review previous missed appointment before booking",
      expectedRevision: other.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(avoided.ok(), await avoided.text()).toBe(true);
  const reads: string[] = [];
  const extraReads: string[] = [];
  page.on("request", (entry) => {
    const path = new URL(entry.url()).pathname;
    if (path === "/api/providers") reads.push(entry.url());
    if (path.startsWith("/api/providers/") || path.startsWith("/api/audit/")) extraReads.push(path);
  });
  await page.goto(`/providers?q=${encodeURIComponent(term)}`);
  const directory = page.getByRole("region", { name: "Providers", exact: true });
  await expect(
    directory.getByRole("button", { name: "Create provider", exact: true }),
  ).toBeVisible();
  await expect(directory.getByText("2 providers on this page", { exact: true })).toBeVisible();
  const card = directory.getByRole("link", { name: created.party.displayName, exact: true });
  await expect(card).toContainText("Plumbing repair");
  await expect(card).toContainText("Preferred");
  await expect(
    directory.getByRole("link", { name: other.party.displayName, exact: true }),
  ).toContainText("Review previous missed appointment before booking");
  await expect(
    directory.locator("p").filter({
      hasText:
        /Legal \/ Attorney|Shared identities|Use an existing identity|Category administration|manual work records/,
    }),
  ).toHaveCount(0);
  expect(reads).toHaveLength(1);
  expect(new URL(reads[0]).searchParams.get("limit")).toBe("50");
  expect(extraReads).toHaveLength(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await directory.screenshot({ path: testInfo.outputPath(`providers-${theme}-${width}.png`) });
    }
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(".provider-directory-page", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
  }
  await directory.getByRole("combobox", { name: "Preference", exact: true }).selectOption("avoid");
  await expect(directory.locator(".provider-directory-card")).toHaveCount(1);
  await directory
    .getByRole("combobox", { name: "Preference", exact: true })
    .selectOption("neutral");
  await expect(
    directory.getByRole("heading", { name: "No providers found", exact: true }),
  ).toBeVisible();
  await directory.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(
    directory.getByRole("searchbox", { name: "Search providers", exact: true }),
  ).toHaveValue("");
  await expect(directory.getByRole("combobox", { name: "Preference", exact: true })).toHaveValue(
    "",
  );
  await directory.getByRole("link", { name: "Manage provider categories", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/provider-categories$/);
  await expect(
    page.getByRole("heading", { name: "Provider categories", exact: true }),
  ).toBeVisible();
});

test("provider directory distinguishes unavailable results from an empty search", async ({
  page,
}) => {
  let attempts = 0;
  await page.route("**/api/providers?*", async (route) => {
    attempts += 1;
    if (attempts === 1)
      await route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
    else await route.fulfill({ json: { items: [], nextCursor: null } });
  });
  await page.goto("/providers?q=MissingProvider");
  const directory = page.getByRole("region", { name: "Provider directory", exact: true });
  await expect(directory.getByRole("alert")).toBeVisible();
  await expect(
    directory.getByRole("heading", { name: "No providers found", exact: true }),
  ).toHaveCount(0);
  await directory.getByRole("button", { name: "Retry loading providers", exact: true }).click();
  await expect(
    directory.getByRole("heading", { name: "No providers found", exact: true }),
  ).toBeVisible();
  expect(attempts).toBe(2);
  await expect(
    directory.getByRole("searchbox", { name: "Search providers", exact: true }),
  ).toHaveValue("MissingProvider");
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

test("identity return links name actual destinations instead of People", async ({
  page,
  request,
}) => {
  const identity = await party(request, `Return label ${crypto.randomUUID()}`);
  for (const [href, name] of [
    ["/owners", "Owners"],
    ["/providers", "Providers"],
    ["/tenants", "Tenants"],
  ]) {
    await page.goto(`/parties?identity=${identity.id}`);
    await page.evaluate(
      (returnTo) => history.replaceState({ ...history.state, usr: { returnTo } }, ""),
      href,
    );
    await page.reload();
    await expect(
      page.getByRole("link", { name: `← Back to ${name}`, exact: true }),
    ).toHaveAttribute("href", href);
    await expect(page.getByRole("link", { name: "← Back to people", exact: true })).toHaveCount(0);
  }
});

test("provider record dates use local time without revision counters", async ({
  page,
  request,
}) => {
  const created = await provider(request, `Readable dates ${crypto.randomUUID()}`);
  const archived = await request.post(`/api/providers/${created.party.id}/archive`, {
    data: {
      confirmed: true,
      expectedRevision: created.profile.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(archived.ok(), await archived.text()).toBeTruthy();
  const current = (await (
    await request.get(`/api/providers/${created.party.id}`)
  ).json()) as Schema["ProviderResponse"];
  await page.goto(`/providers/${created.party.id}/details`);
  const summary = page.getByText("Record details and history", { exact: true });
  await summary.click();
  const details = page.locator("details.record-detail-section").filter({ has: summary });
  await expect(details.getByText("Revision", { exact: true })).toHaveCount(0);
  for (const value of [current.profile.updatedAt, current.profile.archivedAt!]) {
    const local = await page.evaluate(
      (instant) =>
        new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
          new Date(instant),
        ),
      value,
    );
    await expect(details).toContainText(local);
    await expect(details).not.toContainText(value);
  }
  const history = details.locator("details.property-history");
  await history.locator("summary").first().click();
  await expect(history).toContainText("Recorded changes, newest first.");
  await expect(history.locator(".property-history-event-heading time").first()).toBeVisible();
  await expect(history.locator(".property-history-changes").first()).toBeVisible();
});

test("existing shared identity becomes a Provider without duplicating identity and keeps lifecycle history", async ({
  page,
  request,
}) => {
  const identity = await party(request, `Reusable Provider ${crypto.randomUUID()}`);
  await page.goto(`/parties?identity=${identity.id}`);
  await page.getByText("More actions", { exact: true }).click();
  await page.getByRole("link", { name: "Add provider role", exact: true }).click();
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
  await expect(page.getByRole("link", { name: "Edit provider profile", exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Restore provider", exact: true }).click();
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
}, testInfo) => {
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
  await page.getByLabel("Search providers", { exact: true }).fill(created.party.displayName);
  await page.getByText("More filters", { exact: true }).click();
  await page.getByLabel("Service", { exact: true }).fill("Electrical repair");
  await page.getByLabel("Service area", { exact: true }).fill("Portland metro");
  await page.getByLabel("Has references", { exact: true }).check();
  await page.getByRole("combobox", { name: "Preference", exact: true }).selectOption("avoid");
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
    await expect(page.getByRole("button", { name: "Edit provider", exact: true })).toBeVisible();
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page
        .locator(".provider-detail")
        .screenshot({ path: testInfo.outputPath(`provider-${theme}-${width}.png`) });
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
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
  const link = page.getByRole("link", { name: "View contact details", exact: true });
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
  await page.getByRole("button", { name: "Add service", exact: true }).click();
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
  await page.getByLabel("Show archived records").check();
  await expect(page.getByText("Electrical repair", { exact: true })).toBeVisible();
  await page.goto(`/providers?workflow=provider.service.restore&target=${id}&child=${service.id}`);
  await saved(page, "Restore service");
});

test("saved forms resume after reload with the original fields", async ({ page, request }) => {
  const identity = await party(request, "Slice50 resumable identity");
  await page.goto(`/parties?workflow=party.patch&target=${identity.id}`);
  await expect(
    page.getByRole("link", { name: `← Back to ${identity.displayName}`, exact: true }),
  ).toHaveAttribute("href", `/parties?identity=${identity.id}`);
  await expect(
    page.getByRole("heading", { name: "Edit name and identity", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".command-form-actions button")).toHaveText([
    "Save name and identity",
    "Save unfinished form",
  ]);
  await expect(
    page.getByRole("button", { name: "Check latest contact record", exact: true }),
  ).toBeHidden();
  await expect(page.getByText("Identity and contact changes use", { exact: false })).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((appearance) => {
      document.documentElement.dataset.theme = appearance;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    }
  }
  await page.getByLabel("Display name (required)").fill("Slice50 recovered identity");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume: Edit identity", exact: true }).click();
  await expect(page.getByLabel("Display name (required)")).toHaveValue(
    "Slice50 recovered identity",
  );
  await saved(page, "Name");
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
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume: Correct occupancy", exact: true }).click();
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
  await page.goto(`/tenants?workflow=tenant.designate&target=${identity.id}`);
  await saved(page, "Use identity as tenant");
  await page.goto(`/tenants?workflow=tenant.archive&target=${identity.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await saved(page, "Archive tenant");
  await page.goto(`/tenants?identity=${identity.id}`);
  await page.getByRole("button", { name: "Restore tenant", exact: true }).click();
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
  await page.getByRole("button", { name: "Add service", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
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
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
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
  await page.getByRole("button", { name: "Save name and identity", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Display name (required)")).toHaveValue("My retained edits");
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "Check latest contact record" }).click();
  await expect(page.getByRole("region", { name: "Current source review" })).toContainText(
    "Newer operator name",
  );
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  await expect(page.getByLabel("Display name (required)")).toHaveValue("My retained edits");
  await saved(page, "Name");
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
  await page.getByRole("link", { name: "Manage provider categories", exact: true }).click();
  const section = page.getByRole("article", { name: "Slice50 specialist", exact: true });
  const providerCount = section.getByRole("link", {
    name: "1 provider in Slice50 specialist",
    exact: true,
  });
  await expect(providerCount).toBeVisible();
  await expect(providerCount).toHaveAttribute("href", `/providers?categoryId=${category.id}`);
  await page.goto(`/providers?workflow=provider.category.archive&target=${category.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Replaced by a more precise category");
  await saved(page, "Archive provider category");
  const completion = page.locator(".saved-item");
  await expect(
    completion.getByRole("heading", { name: "Archive provider category — complete", exact: true }),
  ).toBeVisible();
  await expect(completion).toContainText("Replaced by a more precise category");
  await expect(completion).not.toContainText(category.id);
  await expect(completion).not.toContainText("Operation");
  await expect(completion).not.toContainText("Revision");
  await expect(completion).not.toContainText(/\d{4}-\d{2}-\d{2}T\d{2}:/);
  await expect(completion).toContainText("America/Los_Angeles");
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
  await page.getByLabel("Effective date", { exact: true }).fill(created.effectiveLocalDate);
  await page.getByRole("button", { name: "Add owner", exact: true }).click();
  await page.getByRole("button", { name: "Create a new owner", exact: true }).click();
  await page.getByLabel("New owner name", { exact: true }).fill("Slice50 inline owner");
  await page.getByRole("button", { name: "Add to owners", exact: true }).click();
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ownership updated", exact: true })).toBeVisible();
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
  await page.getByLabel("Show archived records", { exact: true }).check();
  const historyRow = section
    .locator(":scope > article")
    .filter({ hasText: "https://reputation.example/google_updated" });
  await expect(historyRow).toContainText("Revised private context");
  await historyRow.getByText("History", { exact: true }).click();
  await expect(
    historyRow.locator(".property-history-event-heading strong").filter({ hasText: /^Archived$/ }),
  ).toBeVisible();
  await historyRow
    .locator(".property-history > article")
    .filter({ has: page.getByText("Created", { exact: true }) })
    .getByText("After change", { exact: true })
    .click();
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
  await page.getByRole("button", { name: "Save reputation link changes", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
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
  await page.goto(`/providers/${id}/details`);
  for (const name of ["Portland metro", "Fixture work history", "Prior client", "Directory"]) {
    const child = page
      .locator(".child-record-card")
      .filter({ has: page.getByRole("heading", { name, exact: true }) });
    await expect(child).toBeVisible();
    await expect(child.locator(".record-pill")).toHaveText("Active");
  }
});
