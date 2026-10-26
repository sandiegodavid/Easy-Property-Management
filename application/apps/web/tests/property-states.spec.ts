import { expect, test } from "@playwright/test";
import { post, type Schema } from "./helpers/workflow-contracts";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("returning to a browser tab retains property input throughout readiness revalidation", async ({
  page,
}) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  const name = page.getByLabel("Display name (required)", { exact: true });
  await name.fill("Keep my property input");
  await page.getByLabel("City (required)", { exact: true }).fill("New York");
  await page.getByRole("combobox", { name: "State", exact: true }).selectOption("NY");
  const original = await name.elementHandle();
  let release!: () => void;
  const pending = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/operator/bootstrap", async (route) => {
    await pending;
    await route.continue();
  });
  // Headless tabs remain visible; deliver the same lifecycle events explicitly.
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  });
  const checking = page.waitForRequest("**/api/operator/bootstrap");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  });
  await checking;
  const checked = page.waitForResponse("**/api/operator/bootstrap");
  try {
    await expect(name).toHaveValue("Keep my property input");
    expect(await original.evaluate((node) => node.isConnected)).toBe(true);
  } finally {
    release();
  }
  await checked;
  await expect(name).toHaveValue("Keep my property input");
  await expect(page.getByLabel("City (required)", { exact: true })).toHaveValue("New York");
  await expect(page.getByRole("combobox", { name: "State", exact: true })).toHaveValue("NY");
  expect(await original.evaluate((node) => node.isConnected)).toBe(true);
  await page.unroute("**/api/operator/bootstrap");
  await page.route("**/api/operator/bootstrap", (route) =>
    route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
  );
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true })),
  );
  await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
  await expect(name).toHaveCount(0);
});

test("property creation offers all states, recovers the selection and submits its abbreviation", async ({
  page,
}) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  const state = page.getByRole("combobox", { name: "State", exact: true });
  await expect(state.getByRole("option")).toHaveCount(52);
  await expect(page.getByRole("textbox", { name: "State", exact: true })).toHaveCount(0);
  for (const [name, code] of [
    ["New York", "NY"],
    ["New Jersey", "NJ"],
    ["Texas", "TX"],
    ["Oregon", "OR"],
    ["District of Columbia", "DC"],
  ])
    await expect(state.getByRole("option", { name, exact: true })).toHaveAttribute("value", code);
  await expect(state).toHaveAttribute("autocomplete", "address-level1");
  await expect(page.getByLabel("State", { exact: true })).toHaveAttribute(
    "id",
    (await state.getAttribute("id")) ?? "",
  );
  await state.focus();
  await expect(state).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Postal code", { exact: true })).toBeFocused();
  await page.getByLabel("Display name (required)", { exact: true }).fill("State dropdown property");
  await page
    .getByLabel("Address line1 (required)", { exact: true })
    .fill("2345 Time Square Street");
  await page.getByLabel("City (required)", { exact: true }).fill("New York");
  await page.getByLabel("Postal code", { exact: true }).fill("10005");
  const draftResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "PUT" &&
      r.url().includes("/api/operator/recovery/") &&
      (r.request().postDataJSON() as { payload: { region?: string } }).payload.region === "NY",
  );
  await state.selectOption({ label: "New York" });
  const draft = (await (await draftResponse).json()) as Schema["RecoveryResponse"];
  await page.goto(`/properties?workflow=portfolio.property.create&resume=${draft.id}`);
  await expect(state).toHaveValue("NY");
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/api/properties"),
  );
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  const saved = await response;
  expect(saved.ok(), await saved.text()).toBe(true);
  expect((saved.request().postDataJSON() as { region: string }).region).toBe("NY");
  expect(((await saved.json()) as Schema["PropertyMutationResponse"]).timeZone).toBe(
    "America/New_York",
  );
  await expect(page.locator(".saved-item")).toContainText("State dropdown property");
});

test("editing a full state name displays its existing selection and saves a new state code", async ({
  page,
  request,
}) => {
  const property = await post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: "Full state name property",
    addressLine1: "2345 Time Square Street",
    city: "New York",
    region: "New York",
    postalCode: "10005",
    countryCode: "US",
    propertyType: "townhome",
    ownerships: [{ ownerKind: "local_operator" }],
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/properties?workflow=portfolio.property.patch&target=${property.id}`);
  const state = page.getByRole("combobox", { name: "State", exact: true });
  await expect(state).toHaveValue("NY");
  await expect(state.getByRole("option")).toHaveCount(52);
  await page.getByLabel("City", { exact: true }).fill("Princeton");
  await page.getByLabel("Postal code", { exact: true }).fill("08540");
  await state.selectOption({ label: "New Jersey" });
  const response = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.url().endsWith(`/api/properties/${property.id}`),
  );
  await page.getByRole("button", { name: "Save property changes", exact: true }).click();
  const saved = await response;
  expect(saved.ok(), await saved.text()).toBe(true);
  expect((saved.request().postDataJSON() as { region: string }).region).toBe("NJ");
  await expect(page.locator(".saved-item")).toContainText("Princeton");
});
