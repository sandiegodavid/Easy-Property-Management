import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("tenant IDs are optional on profiles, masked, editable and preserved by recovery", async ({
  page,
  request,
}, testInfo) => {
  const created = await request.post("/api/tenants", {
    data: {
      partyKind: "individual",
      displayName: `Official ID tenant ${crypto.randomUUID()}`,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const tenant = (await created.json()) as Schema["TenantMutationResponse"];
  const detail = `/tenants?identity=${tenant.id}`;
  await page.goto(detail);
  const identification = page.getByRole("region", { name: "Official identification", exact: true });
  await expect(identification).toContainText("No official ID recorded");
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await page.getByRole("button", { name: "Add official ID", exact: true }).click();
  await page
    .getByRole("combobox", { name: "ID type (required)", exact: true })
    .selectOption("drivers_license");
  await page
    .getByRole("textbox", { name: "Issuing country (two-letter code) (required)", exact: true })
    .fill("US");
  await page
    .getByRole("textbox", { name: "Issuing state or region (optional)", exact: true })
    .fill("OR");
  const suffix = page.getByRole("textbox", {
    name: "Last four letters or digits only (required)",
    exact: true,
  });
  await suffix.fill("A123");
  await expect(suffix).toHaveAttribute("maxlength", "4");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page
        .locator("#workspace-content")
        .screenshot({ path: testInfo.outputPath(`tenant-id-${theme}-${width}.png`) });
    }
  }
  await page.evaluate(axe.source);
  expect(
    await page.evaluate(async () =>
      (
        await window.axe.run("#workspace-content", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
        })
      ).violations.map((item) => item.id),
    ),
  ).toEqual([]);
  const write = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/tenants/${tenant.id}`) &&
      response.request().method() === "PATCH",
  );
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  const response = await write;
  expect(response.ok(), await response.text()).toBe(true);
  const result = (await response.json()) as Schema["TenantMutationResponse"];
  const recovered = await request.get(`/api/tenants/operations/${result.operationId}`);
  expect(await recovered.json()).toEqual(result);
  await page.goto(detail);
  await expect(identification).toContainText("Driver’s license");
  await expect(identification).toContainText("Ending in A123");
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await expect(suffix).toHaveValue("A123");
  await suffix.fill("B456");
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  await page.goto(detail);
  await expect(identification).toContainText("Ending in B456");
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await page.getByRole("button", { name: "Remove official ID 1", exact: true }).click();
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  const final = await request.get(`/api/tenants/${tenant.id}`);
  expect(((await final.json()) as Schema["TenantResponse"]).profile.officialIds).toEqual([]);
});
