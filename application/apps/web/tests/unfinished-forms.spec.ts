import { expect, test, type Page } from "@playwright/test";
import { type Schema } from "./helpers/workflow-contracts";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function propertyForm(page: Page, region = "OR") {
  await page.goto("/properties?workflow=portfolio.property.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Retained property input");
  await page.getByLabel("Address line1 (required)", { exact: true }).fill("1 Synthetic Street");
  await page
    .getByLabel("City (required)", { exact: true })
    .fill(region === "AK" ? "Cold City" : "Portland");
  await page.getByLabel("State", { exact: true }).selectOption(region);
  await page.getByLabel("Postal code", { exact: true }).fill(region === "AK" ? "99928" : "97205");
}

test("unsupported address stays editable before submission and accepts an explicit zone", async ({
  page,
}) => {
  await propertyForm(page, "AK");
  let dispatches = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/properties")) dispatches++;
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("choose a time zone manually");
  await expect(page.getByLabel("Display name (required)", { exact: true })).toBeEnabled();
  expect(dispatches).toBe(0);
  await page.getByLabel("Property time zone (optional override)").selectOption("America/Juneau");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.locator(".saved-item")).toContainText("America/Juneau");
  expect(dispatches).toBe(1);
});

test("incomplete forms can save and close, resume editing, and discard without creating a property", async ({
  page,
}) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Only a saved name");
  await page.getByRole("button", { name: "Save and close", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/recovery$/);
  const card = page.locator(".recovery-form-card").filter({ hasText: "Only a saved name" });
  await expect(card).toBeVisible();
  await card.getByRole("link", { name: /Continue editing/ }).click();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toHaveValue(
    "Only a saved name",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Discard…", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/recovery$/);
  await expect(card).toHaveCount(0);
});

test("a definitive command rejection returns to editable input", async ({ page }) => {
  await propertyForm(page);
  await page.route("**/api/properties", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 422,
          json: {
            detail: { code: "property_validation", message: "Review the property address." },
          },
        })
      : route.continue(),
  );
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Review the property address.");
  await expect(page.getByLabel("Display name (required)", { exact: true })).toBeEnabled();
  await expect(page.getByRole("region", { name: "Submission needs checking" })).toHaveCount(0);
});

test("discarding a never-delivered submission fences its original key", async ({
  page,
  request,
}) => {
  await propertyForm(page);
  let body: Record<string, unknown> = {};
  await page.route("**/api/properties", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    body = route.request().postDataJSON() as Record<string, unknown>;
    return route.abort();
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("region", { name: "Submission needs checking" })).toBeVisible();
  await expect(page.getByLabel("Display name (required)", { exact: true })).not.toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Discard…", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/recovery$/);
  const delayed = await request.post("/api/properties", { data: body });
  expect(delayed.status(), await delayed.text()).toBe(409);
  expect((await delayed.json()) as { detail: { code: string } }).toMatchObject({
    detail: { code: "submission_closed" },
  });
});

test("checking a lost successful response opens the original result", async ({ page }) => {
  await propertyForm(page);
  let created: Schema["PropertyMutationResponse"] | undefined;
  await page.route("**/api/properties", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    created = (await response.json()) as Schema["PropertyMutationResponse"];
    await route.abort();
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("region", { name: "Submission needs checking" })).toBeVisible();
  await page.getByRole("button", { name: "Check submission", exact: true }).click();
  await expect(page.locator(".saved-item")).toContainText("Retained property input");
  await expect(page.locator(".saved-item a")).toHaveAttribute(
    "href",
    `/properties/${created?.id}/overview`,
  );
});

test("missing required input never prepares or dispatches a submission", async ({ page }) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  let attempts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      (request.url().endsWith("/api/properties") || request.url().endsWith("/prepare"))
    )
      attempts++;
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toBeFocused();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toBeEnabled();
  expect(attempts).toBe(0);
});

test("fix and continue retains input and closes a never-delivered submission", async ({
  page,
  request,
}) => {
  await propertyForm(page);
  let original: Record<string, unknown> = {};
  await page.route("**/api/properties", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    original = route.request().postDataJSON() as Record<string, unknown>;
    return route.abort();
  });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.getByRole("region", { name: "Submission needs checking" })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Fix and continue", exact: true }).click();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toBeEnabled();
  await expect(page.getByLabel("Display name (required)", { exact: true })).toHaveValue(
    "Retained property input",
  );
  const delayed = await request.post("/api/properties", { data: original });
  expect(delayed.status(), await delayed.text()).toBe(409);
  await page.unroute("**/api/properties");
  await page.getByLabel("Display name (required)", { exact: true }).fill("Corrected property");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.locator(".saved-item")).toContainText("Corrected property");
});

test("save and close resumes the latest acknowledged input across repeated visits", async ({
  page,
}) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  const name = page.getByLabel("Display name (required)", { exact: true });
  const street = page.getByLabel("Address line1 (required)", { exact: true });
  await name.fill("First saved name");
  await page.getByRole("button", { name: "Save and close", exact: true }).click();
  await page
    .locator(".recovery-form-card")
    .filter({ hasText: "First saved name" })
    .getByRole("link", { name: /Continue editing/ })
    .click();
  await expect(name).toHaveValue("First saved name");
  await name.fill("Latest saved name");
  await street.fill("42 Retained Street");
  await page.getByRole("button", { name: "Save and close", exact: true }).click();
  await page
    .locator(".recovery-form-card")
    .filter({ hasText: "Latest saved name" })
    .getByRole("link", { name: /Continue editing/ })
    .click();
  await expect(name).toHaveValue("Latest saved name");
  await expect(street).toHaveValue("42 Retained Street");
});

test("property overrides can be cleared, including after draft recovery", async ({ page }) => {
  await propertyForm(page);
  await page.getByLabel("Display name (required)", { exact: true }).fill("Clearable override");
  const zone = page.getByLabel("Property time zone (optional override)");
  await zone.selectOption("America/Juneau");
  await zone.selectOption({ label: "Determine from address" });
  await expect(zone).toHaveValue("");
  await zone.selectOption("America/Juneau");
  await page.getByRole("button", { name: "Save and close", exact: true }).click();
  await page
    .locator(".recovery-form-card")
    .filter({ hasText: "Clearable override" })
    .getByRole("link", { name: /Continue editing/ })
    .click();
  await expect(zone).toHaveValue("America/Juneau");
  await zone.selectOption({ label: "Determine from address" });
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page.locator(".saved-item")).toContainText("America/Los_Angeles");
});

test("notes edits retain a saved zone for an unsupported property address", async ({ page }) => {
  await propertyForm(page, "AK");
  await page.getByLabel("Property time zone (optional override)").selectOption("America/Juneau");
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/properties",
  );
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  const property = (await (await created).json()) as { id: string };
  await page.goto(`/properties?workflow=portfolio.property.patch&target=${property.id}`);
  await page.getByLabel("Notes", { exact: true }).fill("Updated notes with the same address");
  await page.getByRole("button", { name: "Save property changes", exact: true }).click();
  await expect(page.locator(".saved-item")).toContainText("America/Juneau");
  await expect(page.locator(".saved-item")).toContainText("Updated notes with the same address");
});
