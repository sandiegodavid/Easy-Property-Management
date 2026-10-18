import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("provider IDs retain optional full numbers with explicit reveal and original recovery", async ({
  page,
  request,
}, testInfo) => {
  const created = await request.post("/api/providers", {
    data: {
      party: { partyKind: "organization", displayName: `ID provider ${crypto.randomUUID()}` },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const provider = (await created.json()) as Schema["ProviderMutationResponse"];
  const detail = `/providers/${provider.party.id}/details`;
  await page.goto(detail);
  const identification = page.getByRole("region", { name: "Official identification", exact: true });
  await expect(identification).toContainText("No official ID recorded");
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await page.getByRole("button", { name: "Add official ID", exact: true }).click();
  await page
    .getByRole("combobox", { name: "ID type (required)", exact: true })
    .selectOption("license");
  await page
    .getByRole("textbox", { name: "Issuing country (two-letter code) (required)", exact: true })
    .fill("US");
  const number = page.getByLabel("Full ID number (optional)", { exact: false });
  await number.fill("OR-123456");
  await expect(number).toHaveAttribute("type", "password");
  await expect(
    page.getByRole("textbox", { name: "Last four letters or digits only (required)", exact: true }),
  ).toHaveValue("3456");
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
        .screenshot({ path: testInfo.outputPath(`provider-id-${theme}-${width}.png`) });
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
      response.url().endsWith(`/api/providers/${provider.party.id}`) &&
      response.request().method() === "PATCH",
  );
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  const response = await write;
  expect(response.ok(), await response.text()).toBe(true);
  const original = (await response.json()) as Schema["ProviderMutationResponse"];
  expect(
    await (await request.get(`/api/providers/operations/${original.operationId}`)).json(),
  ).toEqual(original);
  await page.goto(detail);
  await expect(identification).toContainText("Ending in 3456");
  await expect(identification).not.toContainText("OR-123456");
  await identification.getByRole("button", { name: "Show ID number", exact: true }).click();
  await expect(identification).toContainText("OR-123456");
  await identification.getByRole("button", { name: "Hide ID number", exact: true }).click();
  await expect(identification).not.toContainText("OR-123456");
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await page
    .getByRole("combobox", { name: "ID type (required)", exact: true })
    .selectOption("passport");
  await number.fill("P-987654");
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  await page.goto(detail);
  await expect(identification).toContainText("Passport");
  await expect(identification).not.toContainText("P-987654");
  await identification.getByRole("button", { name: "Show ID number", exact: true }).click();
  await expect(identification).toContainText("P-987654");
  expect(
    await (await request.get(`/api/providers/operations/${original.operationId}`)).json(),
  ).toEqual(original);
  await identification.getByRole("button", { name: "Manage official IDs", exact: true }).click();
  await page.getByRole("button", { name: "Remove official ID 1", exact: true }).click();
  await page
    .getByRole("group", { name: "Form actions", exact: true })
    .locator('button[type="submit"]')
    .click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  const result = (await (
    await request.get(`/api/providers/${provider.party.id}`)
  ).json()) as Schema["ProviderResponse"];
  expect(result.profile.officialIds).toEqual([]);
});
