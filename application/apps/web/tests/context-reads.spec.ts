import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test.describe("page capture time", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("directories and overviews show one local capture in the top right", async ({
    page,
    request,
  }) => {
    const item = await property(request, "Local capture property");
    const owner = item.ownerships[0].partyId;
    for (const path of [
      "/properties",
      "/owners",
      "/leasing",
      `/properties/${item.id}/overview`,
      `/owners/${owner}/overview`,
    ]) {
      await page.goto(path);
      const capture = page.locator("#workspace-content .page-as-of");
      await expect(capture).toHaveCount(1);
      await expect(capture).toContainText("America/Los_Angeles");
      const time = capture.locator("time");
      const instant = await time.getAttribute("datetime");
      expect(instant).toBeTruthy();
      const expected = await page.evaluate((value) => {
        return new Intl.DateTimeFormat(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(value!));
      }, instant);
      await expect(time).toContainText(expected);
      await expect(page.locator("#workspace-content p").filter({ hasText: /^As of / })).toHaveCount(
        1,
      );
      const position = await capture.boundingBox();
      const content = await page.locator("#workspace-content").boundingBox();
      expect(position!.y - content!.y).toBeLessThan(30);
      expect(Math.abs(position!.x + position!.width - content!.x - content!.width)).toBeLessThan(2);
    }
  });
});
async function property(request: APIRequestContext, name: string, owners?: string[]) {
  const response = await request.post("/api/properties", {
    data: {
      displayName: name,
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "single_family_home",
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      ownerships: owners
        ? owners.map((partyId) => ({ ownerKind: "client_owner", partyId }))
        : [
            {
              ownerKind: "client_owner",
              inlineParty: { partyKind: "individual", displayName: `${name} owner` },
            },
          ],
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Schema["PropertyMutationResponse"];
}

test("real directories recognize properties and owners, preserve filters and switch records", async ({
  page,
  request,
}) => {
  const first = await property(request, "Éclair Slice49 A");
  const owner = first.ownerships[0]?.partyId;
  expect(owner).toBeTruthy();
  await property(request, "Éclair Slice49 B", [owner!]);
  await property(request, "Second owner Slice49");
  const reads: string[] = [];
  page.on("request", (item) => {
    if (item.url().includes("/api/operator/properties?")) reads.push(item.url());
  });
  await page.goto("/properties?q=Éclair%20Slice49&ownershipContext=managed_for_owner");
  await expect(page.getByText("2 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Éclair Slice49 A", exact: true })).toBeVisible();
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
  await page.getByRole("link", { name: "Éclair Slice49 A", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Éclair Slice49 A", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "details", exact: true }).click();
  await expect(page.getByRole("region", { name: "relationships", exact: true })).toContainText(
    "current",
  );
  await expect(page.getByText("Switch property", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "← Back to Properties", exact: true }).click();
  await expect(page).toHaveURL(/q=.*Slice49.*ownershipContext=managed_for_owner/);
  await page.goto(`/owners/${owner}/overview`);
  await expect(page.getByRole("region", { name: "properties", exact: true })).toContainText(
    "2 matching records",
  );
  await page.getByText("Switch owner", { exact: true }).click();
  await page.getByLabel("Find owner", { exact: true }).fill("Éclair Slice49");
  await page.getByRole("button", { name: "Find records" }).click();
  await expect(page.getByText("1 matches; showing up to 50.", { exact: false })).toBeVisible();
  await page.goto("/owners?q=Slice49");
  await expect(page.getByText("2 matching owners", { exact: true })).toBeVisible();
  await page.goto("/owners?q=Éclair%20Slice49&relationshipScope=former");
  await expect(page.getByText("0 matching owners", { exact: true })).toBeVisible();
});

test("independent task continuations and explicit whole-property money use composed reads", async ({
  page,
  request,
}) => {
  const item = await property(request, "Section Slice49");
  for (let index = 0; index < 11; index++) {
    const created = await request.post("/api/tasks", {
      data: {
        title: `Section task ${index}`,
        relatedEntityType: "property",
        relatedEntityId: item.id,
        status: "open",
        priority: "normal",
        isAllDay: false,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
  }
  const reads: string[] = [];
  page.on("request", (entry) => {
    if (entry.url().includes(`/api/operator/properties/${item.id}/overview`))
      reads.push(entry.url());
  });
  await page.goto(`/properties/${item.id}/overview`);
  const tasks = page.getByRole("region", { name: "tasks", exact: true });
  await expect(tasks).toContainText("11 matching records");
  await expect(tasks.getByRole("link", { name: /View source task/ })).toHaveCount(10);
  await tasks
    .getByRole("link", { name: /View source task/ })
    .first()
    .click();
  await expect(page.getByRole("region", { name: "Source detail", exact: true })).toContainText(
    "Section task",
  );
  await page.getByRole("link", { name: "Close source detail" }).click();
  await page.getByRole("button", { name: "Next tasks", exact: true }).click();
  await expect(tasks.getByRole("link", { name: /View source task/ })).toHaveCount(1);
  expect(reads).toHaveLength(2);
  expect(reads[1]).toContain("section=tasks");
  expect(reads[1]).toContain("cursor=");
  await expect(page.getByText("Choose an explicit period to read money activity.")).toBeVisible();
  await page.getByLabel("Money from").fill("2026-01-01");
  await page.getByLabel("Money through").fill("2026-01-31");
  await page.getByRole("button", { name: "Apply context" }).click();
  await expect(page.getByText(/Whole-property activity, not owner entitlement/)).toBeVisible();
  await expect(page.getByRole("region", { name: "money", exact: true })).toContainText(
    "2026-01-01 through 2026-01-31",
  );
  await expect(page.getByRole("region", { name: "money", exact: true })).toContainText("USD");
  await page.getByRole("link", { name: "money", exact: true }).click();
  await expect(page).toHaveURL(/fromOn=2026-01-01&throughOn=2026-01-31/);
});

test("expired cursor retains filters; sparse pages keep totals and continuation", async ({
  page,
  request,
}) => {
  await property(request, "Sparse Slice49");
  let calls = 0;
  await page.route("**/api/operator/properties?*", async (route) => {
    calls++;
    const url = new URL(route.request().url());
    if (url.searchParams.get("cursor") === "expired") {
      await route.fulfill({
        status: 409,
        json: { detail: { code: "operator_view_changed", message: "Expired view" } },
      });
      return;
    }
    const response = await route.fetch();
    const data = (await response.json()) as Schema["PropertyDirectoryPage"];
    await route.fulfill({ json: { ...data, items: [], nextCursor: "expired" } });
  });
  await page.goto("/properties?q=Sparse%20Slice49");
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching records on this page.")).toBeVisible();
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByText(/This view changed or its continuation expired/)).toBeVisible();
  await page.getByRole("button", { name: "Refresh results" }).click();
  await expect(page.getByLabel("Property name or address", { exact: true })).toHaveValue(
    "Sparse Slice49",
  );
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  expect(calls).toBeLessThanOrEqual(4);
});

test("section failure never becomes an empty result and date errors retain input", async ({
  page,
  request,
}) => {
  const item = await property(request, "Partial Slice49");
  await page.route(`**/api/operator/properties/${item.id}/overview*`, async (route) => {
    const response = await route.fetch();
    if (!response.ok()) {
      await route.fulfill({ response });
      return;
    }
    const data = (await response.json()) as Schema["OverviewResponse"];
    const section = data.sections.maintenance;
    if (section && section.kind === "maintenance")
      data.sections.maintenance = {
        ...section,
        availability: "unavailable",
        reasonCode: "source_read_unavailable",
        sourceRevision: null,
        items: null,
        matchingTotal: null,
        nextCursor: null,
      };
    await route.fulfill({ json: data });
  });
  await page.goto(`/properties/${item.id}/overview`);
  const maintenance = page.getByRole("region", { name: "maintenance", exact: true });
  await expect(maintenance).toContainText("This source is unavailable");
  await expect(maintenance).not.toContainText("0 matching records");
  await expect(page.getByRole("region", { name: "spaces", exact: true })).toContainText(
    "1 matching records",
  );
  await page.getByLabel("Money from").fill("2026-02-01");
  await page.getByLabel("Money through").fill("2026-01-01");
  await page.getByRole("button", { name: "Apply context" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Money from")).toHaveValue("2026-02-01");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
