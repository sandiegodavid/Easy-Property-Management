import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";
import { record } from "@epm/contracts/workflows";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function fixture(request: APIRequestContext) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: `Ownership portions ${crypto.randomUUID()}`,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      countryCode: "US",
      propertyType: "single_family_home",
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      ownerships: [
        { ownerKind: "local_operator", sharePercent: "60.00" },
        {
          ownerKind: "client_owner",
          sharePercent: "40.00",
          inlineParty: { partyKind: "individual", displayName: "Morgan Share Owner" },
        },
      ],
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schema["PropertyMutationResponse"];
}

test("property creation records an explicit sole-owner share", async ({ page }) => {
  await page.goto("/properties?workflow=portfolio.property.create");
  await page
    .getByLabel("Display name (required)", { exact: true })
    .fill(`Whole ownership ${crypto.randomUUID()}`);
  await page.getByLabel("Address line1 (required)").fill("20 Maple Street");
  await page.getByLabel("City (required)").fill("Portland");
  await page.getByLabel("State", { exact: true }).fill("OR");
  const share = page.getByRole("spinbutton", { name: "Ownership share for You (%)", exact: true });
  await expect(share).toHaveValue("");
  await share.fill("100");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await page.getByRole("link", { name: "Back to property", exact: true }).click();
  await expect(page).toHaveURL(/\/properties\/[^/]+\/overview$/);
  await expect(page.getByText("Ownership share: 100%", { exact: true })).toBeVisible();
});

test("share edits validate totals, survive draft recovery and reconcile one committed write", async ({
  page,
  request,
}, testInfo) => {
  const property = await fixture(request);
  const url = `/properties?workflow=portfolio.ownerships.replace&target=${property.id}`;
  await page.goto(url);
  const you = page.getByRole("spinbutton", { name: "Ownership share for You (%)", exact: true });
  const owner = page.getByRole("spinbutton", {
    name: "Ownership share for Morgan Share Owner (%)",
    exact: true,
  });
  await expect(you).toHaveValue("60.00");
  await expect(owner).toHaveValue("40.00");
  let writes = 0;
  await page.route(`**/api/properties/${property.id}/ownerships`, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    writes++;
    const response = await route.fetch();
    expect(response.ok(), await response.text()).toBe(true);
    await route.abort("failed");
  });
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await you.fill("55");
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await expect(
    page
      .getByText("Ownership shares must total 100% when every share is recorded.", { exact: true })
      .first(),
  ).toBeVisible();
  expect(writes).toBe(0);
  await you.fill("50");
  await owner.fill("50");
  await expect(
    page.getByText("Ownership shares must total 100% when every share is recorded.", {
      exact: true,
    }),
  ).toHaveCount(0);
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
        .locator(".ownership-command")
        .screenshot({ path: testInfo.outputPath(`shares-${theme}-${width}.png`) });
    }
    await page.evaluate(axe.source);
    expect(
      await page.evaluate(async () =>
        (
          await window.axe.run(".ownership-command", {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
          })
        ).violations.map((item) => item.id),
      ),
    ).toEqual([]);
  }
  await page.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  const draft = (await (await saved).json()) as Schema["RecoveryResponse"];
  await expect
    .poll(async () => {
      const response = await request.get(`/api/operator/recovery/${draft.id}`);
      const current = (await response.json()) as Schema["RecoveryResponse"];
      const ownerships = record(current.payload).ownerships;
      return Array.isArray(ownerships)
        ? ownerships.map(record).map((item) => item.sharePercent)
        : [];
    })
    .toEqual(["50", "50"]);
  await page.goto(`${url}&resume=${draft.id}`);
  await expect(you).toHaveValue("50");
  await expect(owner).toHaveValue("50");
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Ownership updated", exact: true })).toContainText(
    "50%",
  );
  expect(writes).toBe(1);
  const current = await request.get(`/api/properties/${property.id}`);
  const result =
    (await current.json()) as Schema["app__modules__portfolio__api__router__PropertyResponse"];
  expect(result.propertyRevision).toBe(property.propertyRevision + 1);
  expect(result.ownerships.map((item) => item.sharePercent)).toEqual(["50.00", "50.00"]);
  const ownerId = property.ownerships.find((item) => item.partyId)!.partyId!;
  for (const path of [`/properties/${property.id}/overview`, `/owners/${ownerId}/overview`]) {
    await page.goto(path);
    await expect(page.getByText("Ownership share: 50%", { exact: true }).first()).toBeVisible();
  }
  await page.goto(`/properties?q=${encodeURIComponent(property.displayName)}`);
  await expect(page.getByRole("region", { name: "Owners", exact: true })).toContainText("50%");
});

test("unknown ownership shares stay explicit rather than inferred", async ({ page, request }) => {
  const property = await fixture(request);
  await page.goto(`/properties?workflow=portfolio.ownerships.replace&target=${property.id}`);
  await page.getByRole("spinbutton", { name: "Ownership share for You (%)", exact: true }).fill("");
  await page
    .getByRole("spinbutton", { name: "Ownership share for Morgan Share Owner (%)", exact: true })
    .fill("");
  await page.getByRole("button", { name: "Save ownership change", exact: true }).click();
  const confirmation = page.getByRole("region", { name: "Ownership updated", exact: true });
  await expect(confirmation.getByText("Not recorded", { exact: true })).toHaveCount(2);
  const current = await request.get(`/api/properties/${property.id}`);
  const result =
    (await current.json()) as Schema["app__modules__portfolio__api__router__PropertyResponse"];
  expect(result.ownerships.every((item) => item.sharePercent === null)).toBe(true);
});
