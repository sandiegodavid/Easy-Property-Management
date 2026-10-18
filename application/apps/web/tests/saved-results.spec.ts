import { expect, test, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function submit(page: Page) {
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
}

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
