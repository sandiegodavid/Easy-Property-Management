import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}
async function fixture(request: APIRequestContext) {
  const property = await post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Parent navigation ${crypto.randomUUID()}`,
    addressLine1: "10 Maple Street",
    city: "Portland",
    region: "OR",
    countryCode: "US",
    propertyType: "single_family_home",
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerships: [{ ownerKind: "local_operator" }],
  });
  const issue = await post<Schema["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
    propertyId: property.id,
    summary: "Navigation repair",
    description: "Check the kitchen tap",
    category: "plumbing",
    priority: "urgent",
    reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
    reporter: { role: "manager", subjectKind: "local_operator" },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  return { property, issue };
}

test("sidebar destinations have no parent link; secondary pages have a single top link", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  for (const path of [
    "/home",
    "/properties",
    "/owners",
    "/tenants",
    "/leasing",
    "/money",
    "/maintenance",
    "/providers",
    "/settings",
  ]) {
    await page.goto(path);
    await expect(page.locator("#workspace-content")).toBeVisible();
    await expect(page.locator(".parent-back-link")).toHaveCount(0);
  }
  for (const [path, href, label] of [
    [`/properties/${f.property.id}/overview`, "/properties", "← Back to Properties"],
    [`/maintenance?record=issue&id=${f.issue.id}`, "/maintenance", "← Back to Maintenance"],
    ["/settings/navigation", "/settings", "← Back to Settings"],
    ["/settings/provider-categories", "/settings", "← Back to Settings"],
    ["/tasks?workflow=task.create", "/tasks", "← Back to Tasks"],
    ["/conversations?intake=true", "/conversations", "← Back to Conversations"],
    ["/leasing?templates=true", "/leasing", "← Back to Leasing"],
  ]) {
    await page.goto(path);
    const back = page.locator(".parent-back-link");
    await expect(back).toHaveCount(1);
    await expect(back).toHaveAttribute("href", href);
    await expect(back).toHaveText(label);
    const heading = page.locator("#workspace-content h2").first();
    await expect(heading).toBeVisible();
    expect((await back.boundingBox())!.y).toBeLessThan((await heading.boundingBox())!.y);
    await expect(
      page.getByRole("link", { name: "Return to current record", exact: true }),
    ).toHaveCount(0);
  }
});

test("filtered directory returns preserve filters and click-time scroll through detail and form", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  for (let index = 0; index < 12; index++) {
    await post(request, "/api/maintenance-issues", {
      propertyId: f.property.id,
      summary: `Navigation repair ${index}`,
      description: "Check the kitchen tap",
      category: "plumbing",
      priority: "urgent",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
  }
  const directory = `/maintenance?propertyId=${f.property.id}&category=plumbing&priority=urgent`;
  await page.goto(directory);
  const cards = page.locator(".maintenance-issue-card");
  await expect(cards).toHaveCount(13);
  const selected = cards.last();
  await selected.scrollIntoViewIfNeeded();
  const scroll = await page.evaluate(() => window.scrollY);
  expect(scroll).toBeGreaterThan(100);
  const detail = await selected.getAttribute("href");
  await selected.click();
  await expect(page.locator(".parent-back-link")).toHaveAttribute("href", directory);
  await page.getByRole("link", { name: "Edit issue", exact: true }).click();
  await expect(page.locator(".parent-back-link")).toHaveAttribute("href", detail!);
  await expect(page.locator(".parent-back-link")).toHaveText("← Back to maintenance issue");
  await page
    .getByRole("textbox", { name: "Description", exact: true })
    .fill("Unfinished repair clarification");
  await page.locator(".parent-back-link").click();
  const unfinished = page.getByRole("region", { name: "Unfinished form", exact: true });
  await expect(unfinished).toBeVisible();
  await unfinished.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Description", exact: true })).toHaveValue(
    "Unfinished repair clarification",
  );
  await page.locator(".parent-back-link").click();
  await unfinished.getByRole("button", { name: "Save and leave", exact: true }).click();
  await expect(page.locator(".issue-detail-description")).toBeVisible();
  await page.locator(".parent-back-link").click();
  await expect(page).toHaveURL(directory);
  await expect(cards).toHaveCount(13);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(scroll, 0);
  await expect(page.locator(".parent-back-link")).toHaveCount(0);
});

test("record tabs keep the parent and unsafe or stale state falls back to the owning directory", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/properties?q=${encodeURIComponent(f.property.displayName)}&state=active`);
  const directory = new URL(page.url()).pathname + new URL(page.url()).search;
  await page.getByRole("link", { name: f.property.displayName, exact: true }).click();
  await page
    .getByRole("navigation", { name: "property sections", exact: true })
    .getByRole("link", { name: "Property setup", exact: true })
    .click();
  await expect(page.locator(".parent-back-link")).toHaveAttribute("href", directory);
  await page.reload();
  await expect(page.locator(".parent-back-link")).toHaveAttribute("href", directory);
  for (const returnTo of [
    "https://example.com/",
    "//example.com/",
    "javascript:alert(1)",
    `/properties/${f.property.id}/setup`,
  ]) {
    await page.evaluate((value) => {
      history.replaceState(
        {
          ...history.state,
          usr: {
            returnTo: value,
            parentRuntime: "another-workspace",
            parentTrail: [{ href: "https://example.com/", label: "Unsafe", scroll: -1 }],
          },
        },
        "",
      );
    }, returnTo);
    await page.reload();
    await expect(page.locator(".parent-back-link")).toHaveAttribute("href", "/properties");
  }
});
