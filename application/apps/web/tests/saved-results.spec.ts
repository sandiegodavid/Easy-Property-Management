import { expect, test, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";
import {
  property as makeProperty,
  lease as makeLease,
  rent as makeRent,
} from "./helpers/workflow-contracts";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function submit(page: Page) {
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
}

async function savedContract(
  page: Page,
  heading: string,
  text: string,
  label: string,
  target: RegExp,
) {
  const result = page.locator(".saved-item");
  await expect(result.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  await expect(result).toContainText(text);
  await expect(page.locator(".command-editor form")).toHaveCount(0);
  await expect(result).not.toContainText(
    /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|Operation|Revision|\d{4}-\d\d-\d\dT\d\d:/,
  );
  const back = result.getByRole("link", { name: label, exact: true });
  await expect(back).toHaveAttribute("href", target);
  const destination = await back.getAttribute("href");
  await back.click();
  await expect(page).toHaveURL(destination!);
}

for (const entry of [
  {
    workflow: "task.create",
    path: "/tasks",
    field: "Title (required)",
    title: "Task",
    back: "task",
    target: /\/tasks\?record=task&id=/,
  },
  {
    workflow: "provider.create",
    path: "/providers",
    field: "Display name (required)",
    title: "Provider",
    back: "provider",
    target: /\/providers\/[^/]+\/details$/,
  },
  {
    workflow: "tenant.create",
    path: "/tenants",
    field: "Display name (required)",
    title: "Tenant",
    back: "tenant",
    target: /\/tenants\?identity=/,
  },
]) {
  test(`standalone ${entry.title.toLowerCase()} creation confirms saved data and returns to its record`, async ({
    page,
  }) => {
    const name = `${entry.title} saved contract ${crypto.randomUUID().slice(0, 8)}`;
    if (entry.workflow === "tenant.create") {
      await page.goto("/tenants");
      await page.getByRole("button", { name: "Create tenant", exact: true }).click();
    } else await page.goto(`${entry.path}?workflow=${entry.workflow}`);
    await page.getByLabel(entry.field, { exact: true }).fill(name);
    await submit(page);
    await savedContract(page, `${entry.title} saved`, name, `Back to ${entry.back}`, entry.target);
  });
}

test("standalone maintenance issue and owner concern creation retain their saved evidence", async ({
  page,
  request,
}) => {
  const home = await makeProperty(request);
  for (const concern of [false, true]) {
    await page.goto(
      `/maintenance?workflow=${concern ? "owner_concern.create" : "maintenance.issue.create"}`,
    );
    await page
      .getByRole("combobox", { name: "Property (required)", exact: true })
      .selectOption(home.id);
    if (concern) {
      await page
        .getByRole("combobox", { name: "Owner (required)", exact: true })
        .selectOption(home.ownerships[0].partyId);
      await page
        .getByRole("combobox", { name: "Concern type (required)", exact: true })
        .selectOption("general_rental");
      await expect(
        page.getByLabel("Raised at (include time-zone offset) (required)", { exact: true }),
      ).toHaveCount(0);
    } else {
      await page
        .getByRole("combobox", { name: "Category (required)", exact: true })
        .selectOption("plumbing");
      await expect(
        page.getByLabel("Reported at (include time-zone offset) (required)", { exact: true }),
      ).toHaveCount(0);
    }
    const text = concern ? "Owner asks about inspection" : "Kitchen tap needs repair";
    await page.getByRole("textbox", { name: "Summary (required)", exact: true }).fill(text);
    await page
      .getByRole("textbox", { name: "Description (required)", exact: true })
      .fill("Reported by the operator for review");
    const endpoint = concern ? "/api/owner-concerns" : "/api/maintenance-issues";
    const response = page.waitForResponse(
      (item) => new URL(item.url()).pathname === endpoint && item.request().method() === "POST",
    );
    await submit(page);
    const posted = await response;
    const payload: unknown = posted.request().postDataJSON();
    const field = concern ? "raisedAtUtc" : "reportedAtUtc";
    expect(payload).not.toHaveProperty(field);
    const created = (await posted.json()) as Record<string, unknown>;
    expect(created[field]).toBe(concern ? created.recordedAtUtc : created.createdAt);
    const replay = await request.post(endpoint, { data: payload });
    expect(replay.ok(), await replay.text()).toBe(true);
    expect(await replay.json()).toEqual(created);
    await expect(page.locator(".saved-item dt", { hasText: /^Recorded$/ })).not.toHaveCount(0);
    await expect(page.locator(".saved-item")).not.toContainText(
      /Reported at utc|Raised at utc|Occurred at utc/,
    );
    await savedContract(
      page,
      `${concern ? "Owner concern" : "Maintenance issue"} saved`,
      text,
      `Back to ${concern ? "owner concern" : "maintenance issue"}`,
      concern ? /\/maintenance\?record=concern&id=/ : /\/maintenance\?record=issue&id=/,
    );
  }
});

test("lease draft saved screen contains the agreed rent and returns to the new draft", async ({
  page,
  request,
}) => {
  const f = await makeLease(request);
  await page.goto(`/leasing?workflow=lease.create&spaceId=${f.property.spaces[0].id}`);
  await page.getByLabel("Contract starts on (required)").fill(f.today);
  await page.getByLabel("Occupancy starts on (required)").fill(f.today);
  await page.getByLabel("Base rent minor (required)").fill("123456");
  await page.getByLabel("Payment due day", { exact: true }).fill("1");
  await page.getByLabel("Tenant party id (required)").fill(f.tenant.id);
  await page.getByLabel("Participant role (required)").selectOption("primary_tenant");
  await submit(page);
  await savedContract(
    page,
    "Lease draft saved",
    "USD 1,234.56",
    "Back to lease",
    /\/leases\/[^/]+\/details$/,
  );
});

test("rent receipt saved screen confirms the payment once before returning to its receipt", async ({
  page,
  request,
}) => {
  const f = await makeRent(request);
  let writes = 0;
  page.on("request", (entry) => {
    if (entry.method() === "POST" && new URL(entry.url()).pathname === "/api/rent-receipts")
      writes++;
  });
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${f.expectation.id}`,
  );
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Amount (USD cents) (required)").nth(0).fill("195000");
  await page.getByLabel("Amount (USD cents) (required)").nth(1).fill("195000");
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await submit(page);
  await savedContract(
    page,
    "Rent receipt saved",
    "USD 1,950.00",
    "Back to rent receipt",
    /\/money\?record=receipt&id=/,
  );
  expect(writes).toBe(1);
});

test("standalone property creation and editing show saved data before returning to the item", async ({
  page,
  request,
}, info) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Confirmation house");
  await page.getByLabel("Address line1 (required)").fill("20 Maple Street");
  await page.getByLabel("City (required)").fill("Portland");
  await page.getByLabel("State", { exact: true }).fill("OR");
  const write = page.waitForResponse(
    (r) => r.url().endsWith("/api/properties") && r.request().method() === "POST",
  );
  await submit(page);
  const property = (await (await write).json()) as Schema["PropertyMutationResponse"];
  const result = page.locator(".saved-item");
  await expect(result).toContainText("Confirmation house");
  await expect(page).toHaveURL(/workflow=portfolio.property.create/);
  await expect(page.locator("form")).toHaveCount(0);
  await expect(result).not.toContainText(property.id);
  await expect(result).not.toContainText("Operation");
  await expect(result).not.toContainText("Revision");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await result.screenshot({ path: info.outputPath(`saved-property-${theme}-${width}.png`) });
    }
  }
  await page.evaluate(axe.source);
  expect(
    await page.evaluate(async () =>
      (
        await window.axe.run(".saved-item", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
        })
      ).violations.map((v) => v.id),
    ),
  ).toEqual([]);
  await result.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(`/properties/${property.id}/overview`);
  await expect(
    page.getByRole("link", { name: "← Back to Properties", exact: true }),
  ).toHaveAttribute("href", "/properties");
  await page.goto(`/properties?workflow=portfolio.property.patch&target=${property.id}`);
  await page
    .getByRole("textbox", { name: "Display name", exact: true })
    .fill("Updated confirmation house");
  await submit(page);
  await expect(result).toContainText("Updated confirmation house");
  await expect(
    result.getByRole("heading", { name: "Property updated", exact: true }),
  ).toBeVisible();
  await result.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(`/properties/${property.id}/setup`);
  expect((await request.get(`/api/properties/${property.id}`)).ok()).toBe(true);
});

test("embedded Task creation replaces only its editor and retains the directory viewport", async ({
  page,
}) => {
  await page.goto("/tasks");
  await page.getByRole("button", { name: "Quick add task", exact: true }).click();
  const enclosing = page.getByRole("region", { name: "Quick add task", exact: true });
  await enclosing
    .getByRole("textbox", { name: "Title (required)", exact: true })
    .fill("Inline confirmation task");
  await enclosing
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  const result = enclosing.locator(".saved-item");
  await expect(result).toContainText("Inline confirmation task");
  await expect(result).toHaveAttribute("data-embedded", "true");
  await expect(enclosing.locator("form")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Work directory", exact: true })).toBeVisible();
  await expect(page).toHaveURL("/tasks");
  await result.getByRole("link", { name: "View task", exact: true }).click();
  await expect(page).toHaveURL(/tasks\?record=task&id=/);
});

test("interrupted edits do not confirm until recovery and retain the immutable saved result", async ({
  page,
  request,
}) => {
  const response = await request.post("/api/parties", {
    data: {
      partyKind: "individual",
      displayName: "Before confirmation",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  const party = (await response.json()) as Schema["PartyMutationResponse"];
  let writes = 0;
  await page.goto(`/parties?workflow=party.patch&target=${party.id}`);
  await page.getByLabel("Display name (required)", { exact: true }).fill("Original saved name");
  await page.route(`**/api/parties/${party.id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    writes += 1;
    const result = await route.fetch();
    expect(result.ok()).toBe(true);
    await route.abort("failed");
  });
  await submit(page);
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".saved-item")).toHaveCount(0);
  const later = await request.patch(`/api/parties/${party.id}`, {
    data: { displayName: "Later name", expectedRevision: 2, idempotencyKey: crypto.randomUUID() },
  });
  expect(later.ok(), await later.text()).toBe(true);
  let unavailable = true;
  await page.route("**/api/parties/operations/*", (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unavailable" }),
        })
      : route.continue(),
  );
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  const result = page.locator(".saved-item");
  await expect(result).toContainText("was saved, but its details could not be loaded");
  await expect(page.locator("form")).toHaveCount(0);
  unavailable = false;
  await result.getByRole("button", { name: /^Retry saved/ }).click();
  await expect(result).toContainText("Original saved name");
  await expect(result).not.toContainText("Later name");
  expect(writes).toBe(1);
  await result.getByRole("link", { name: "Back to contact details", exact: true }).click();
  await expect(page).toHaveURL(`/parties?identity=${party.id}`);
});
