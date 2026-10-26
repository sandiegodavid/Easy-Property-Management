import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function property(request: APIRequestContext, name: string) {
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
      ownerships: [{ ownerKind: "local_operator" }],
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as Schema["PropertyMutationResponse"];
}
async function issue(request: APIRequestContext, propertyId: string) {
  const response = await request.post("/api/maintenance-issues", {
    data: {
      propertyId,
      summary: "Coverage source change",
      description: "Inspect plumbing",
      category: "plumbing",
      priority: "normal",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test("bounded search groups preserve continuations and open typed targets", async ({
  page,
  request,
}) => {
  const name = `Search54 ${crypto.randomUUID()}`;
  for (let i = 0; i < 11; i++) {
    const response = await request.post("/api/tasks", {
      data: {
        title: `${name} ${String(i).padStart(2, "0")}`,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  const calls: string[] = [];
  page.on("request", (entry) => {
    if (entry.url().includes("/api/operator/search")) calls.push(entry.url());
  });
  await page.goto(`/search?q=${name}`);
  await expect(page.getByLabel("Search records", { exact: true })).toHaveValue(name);
  await expect(
    page.getByText(
      "Searches names and record details. Message text and file contents are not searched.",
    ),
  ).toBeVisible();
  for (const heading of [
    "Properties",
    "Rental units",
    "Owners",
    "Tenants",
    "Leases",
    "Conversations",
    "Maintenance issues",
    "Tasks",
  ]) {
    await expect(
      page
        .getByRole("region", { name: `${heading} search results`, exact: true })
        .getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
  }
  const group = page.getByRole("region", { name: "Tasks search results" });
  await expect(group).toContainText("11 matches");
  await expect(group.getByRole("link")).toHaveCount(10);
  await expect(group.locator(".search-result-card .child-record-heading")).toHaveCount(10);
  const first = await group.getByRole("link").allTextContents();
  await group.getByRole("button", { name: "Next tasks results" }).click();
  await expect(group.getByRole("link")).toHaveCount(1);
  expect(first).not.toContain(await group.getByRole("link").innerText());
  expect(calls).toHaveLength(2);
  expect(calls[1]).toContain("group=tasks");
  await group.getByRole("link").click();
  await expect(page.getByRole("heading", { name: /Search54/ })).toBeVisible();
  await page.goBack();
  await expect(group.getByRole("link")).toHaveCount(1);
  await expect(page).toHaveURL(/tasksCursor=/);
});

test("record details hide internal IDs and revisions and format statuses and deadlines", async ({
  page,
  request,
}) => {
  const item = await property(request, "Readable rental unit");
  await page.goto(`/search?sourceType=space&sourceId=${item.spaces[0].id}`);
  const panel = page.getByRole("region", { name: "Record details", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Rental unit details", exact: true }),
  ).toBeVisible();
  await expect(panel.getByText("Active", { exact: true })).toBeVisible();
  await expect(panel.locator("dl")).toHaveCSS("display", "grid");
  await expect(panel).not.toContainText(item.id);
  await expect(panel).not.toContainText(item.spaces[0].id);
  await expect(panel.getByText("Revision", { exact: true })).toHaveCount(0);
  const deadline = "2026-01-02T12:00:00Z";
  const created = await request.post("/api/tasks", {
    data: {
      title: "Readable deadline",
      priority: "normal",
      isAllDay: false,
      dueAtUtc: deadline,
      dueTimezone: "America/Los_Angeles",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const task = (await created.json()) as Schema["TaskResponse"];
  await page.goto(`/search?sourceType=task&sourceId=${task.id}`);
  await expect(panel.getByRole("heading", { name: "Task details", exact: true })).toBeVisible();
  await expect(panel.getByText("Open", { exact: true })).toBeVisible();
  await expect(panel).not.toContainText(task.id);
  await expect(panel).not.toContainText(deadline);
  await expect(panel).not.toContainText(/no_deadline|not_due|follow_up|Revision/);
  const localDeadline = await page.evaluate(
    (value) =>
      new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      ),
    deadline,
  );
  await expect(panel).toContainText(localDeadline);
  await expect(panel.getByRole("link", { name: "View task", exact: true })).toHaveAttribute(
    "href",
    `/tasks?record=task&id=${task.id}`,
  );
  await panel.getByRole("link", { name: "Close details", exact: true }).click();
  await expect(panel).toHaveCount(0);
});

test("search failure is independent and stale continuations restart with filters", async ({
  page,
  request,
}) => {
  const item = await property(request, "Search54 independent");
  await page.route("**/api/operator/search?*", async (route) => {
    if (new URL(route.request().url()).searchParams.has("cursor")) {
      await route.fulfill({ status: 409, json: { detail: "Search view changed" } });
      return;
    }
    const response = await route.fetch();
    const data = (await response.json()) as Schema["SearchResponse"];
    if (data.groups.tasks)
      data.groups.tasks = {
        ...data.groups.tasks,
        availability: "unavailable",
        reasonCode: "source_read_unavailable",
        matchingTotal: null,
        items: null,
        sourceRevision: null,
        nextCursor: null,
      };
    if (data.groups.properties) data.groups.properties.nextCursor = "expired";
    await route.fulfill({ json: data });
  });
  await page.goto("/search?q=Search54%20independent&includeArchived=true");
  await expect(page.getByRole("region", { name: "Tasks search results" })).toContainText(
    "unavailable",
  );
  const retry = page.waitForRequest(
    (entry) =>
      entry.url().includes("/api/operator/search") &&
      new URL(entry.url()).searchParams.get("group") === "tasks",
  );
  await page.getByRole("button", { name: "Retry tasks search" }).click();
  await retry;
  const group = page.getByRole("region", { name: "Properties search results" });
  await expect(group.getByRole("link")).toHaveAttribute("href", `/properties/${item.id}/overview`);
  await group.getByRole("button", { name: "Next properties results" }).click();
  await expect(group.getByRole("alert")).toBeVisible();
  const restarted = page.waitForRequest((entry) => {
    const url = new URL(entry.url());
    return (
      url.pathname === "/api/operator/search" &&
      url.searchParams.get("group") === "properties" &&
      !url.searchParams.has("cursor")
    );
  });
  const restartedResponse = page.waitForResponse((entry) => {
    const url = new URL(entry.url());
    return (
      url.pathname === "/api/operator/search" &&
      url.searchParams.get("group") === "properties" &&
      !url.searchParams.has("cursor")
    );
  });
  await group.getByRole("button", { name: "Restart group" }).click();
  const fresh = new URL((await restarted).url());
  await restartedResponse;
  expect(fresh.searchParams.get("q")).toBe("Search54 independent");
  expect(fresh.searchParams.get("includeArchived")).toBe("true");
  await expect(page.getByLabel("Search records")).toHaveValue("Search54 independent");
  await expect(page.getByLabel("Include archived records")).toBeChecked();
});

test("archived metadata remains opt-in and opens the retained contextual record", async ({
  page,
  request,
}) => {
  const item = await property(request, "Archived OPS acceptance property");
  const archived = await request.post(`/api/properties/${item.id}/archive`, {
    data: {
      confirmed: true,
      expectedPropertyRevision: item.propertyRevision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(archived.ok(), await archived.text()).toBe(true);
  await page.goto("/search?q=Archived%20OPS%20acceptance%20property");
  const group = page.getByRole("region", { name: "Properties search results" });
  await expect(group).toContainText("0 matches");
  await page.getByLabel("Include archived records").click();
  await expect(page.getByLabel("Include archived records")).toBeChecked();
  await expect(group).toContainText("1 matches");
  await expect(group).toContainText("Archived");
  await expect(group.locator(".search-result-card .record-pill")).toHaveText("Archived");
  await group.getByRole("link", { name: "Archived OPS acceptance property", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Archived OPS acceptance property", exact: true }),
  ).toBeVisible();
});

test("maintenance review commits a source-bound receipt and dirty forms resume", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 resume");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await expect(
    page.getByRole("heading", { name: "Maintenance information review", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Maintenance information review", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/This is not insurance or service coverage/)).toBeVisible();
  await expect(page.getByRole("region", { name: "maintenance information review" })).toContainText(
    "needs review",
  );
  await page.getByRole("button", { name: "Review maintenance information" }).click();
  await expect(
    page
      .getByRole("region", { name: "Information review form", exact: true })
      .getByRole("heading", { name: "Review maintenance", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Review reason").fill("Checked maintenance records");
  const saving = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  const saved = (await (await saving).json()) as Schema["RecoveryResponse"];
  await expect(page.getByRole("status").filter({ hasText: "Unfinished form saved" })).toBeVisible();
  await page.goto(`/coverage/reviews/${saved.id}`);
  await expect(page.getByLabel("Review reason")).toHaveValue("Checked maintenance records");
  await page.getByRole("button", { name: "Record review" }).click();
  const confirmation = page.getByText(/^Recorded review: recorded/);
  await expect(confirmation).toBeVisible();
  await expect(confirmation).not.toContainText(/[0-9a-f]{8}-[0-9a-f]{4}-/);
  const captured = confirmation.locator("time");
  await expect(captured).toHaveAttribute("datetime", /^\d{4}-\d{2}-\d{2}T/);
  await expect(captured).not.toContainText(/^\d{4}-\d{2}-\d{2}T/);
  const information = page.getByRole("region", { name: "Current information", exact: true });
  await expect(information.locator(".information-review-badge")).toHaveText("recorded");
  await expect(information.getByText("applicable", { exact: true })).toHaveCount(0);
});

test("information review cards fit all areas in both themes and narrow screens", async ({
  page,
  request,
}, testInfo) => {
  const item = await property(request, "Information review layout");
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    for (const area of ["maintenance", "occupancy", "lease", "rent", "deposit"]) {
      await page.setViewportSize({ width: 1280, height: 900 });
      const path = area === "maintenance" ? `property/${item.id}` : `space/${item.spaces[0].id}`;
      await page.goto(`/coverage/${path}/${area}`);
      const information = page.getByRole("region", { name: "Current information", exact: true });
      const details = page.getByRole("region", { name: "Review details", exact: true });
      await expect(information).toBeVisible();
      await expect(details).toBeVisible();
      await expect(information.getByText("applicable", { exact: true })).toHaveCount(0);
      if (area === "lease" || area === "rent" || area === "deposit") {
        await expect(information.getByText("not applicable", { exact: true })).toHaveCount(1);
        await expect(information).toContainText("No setup is needed for the current records.");
        await expect(information.getByRole("link")).toHaveCount(0);
      }
      const explanation = page.locator(".information-review-page > footer");
      await expect(explanation).toContainText(
        "Check whether the app has enough recorded information",
      );
      await expect(
        page.getByRole("heading", { name: "Information review", exact: true }),
      ).toHaveCount(0);
      expect(
        await explanation.evaluate((footer) =>
          footer.previousElementSibling?.classList.contains("information-review-panel"),
        ),
      ).toBe(true);
      const back = page.getByRole("link", { name: `← Back to ${item.displayName}`, exact: true });
      await expect(back).toHaveAttribute("href", `/properties/${item.id}/overview`);
      await expect(
        page.locator(".information-review-panel > .information-review-property"),
      ).toHaveText(item.displayName);
      expect(
        await page
          .locator(".information-review-property")
          .evaluate((name) =>
            name.nextElementSibling?.classList.contains("information-review-grid"),
          ),
      ).toBe(true);
      if (theme === "light") {
        await back.click();
        await expect(page).toHaveURL(new RegExp(`/properties/${item.id}/overview$`));
        await page.goBack();
        await expect(information).toBeVisible();
      }
      const left = await information.boundingBox();
      const right = await details.boundingBox();
      expect(right!.x).toBeGreaterThan(left!.x);
      if (area === "maintenance") {
        await page.screenshot({
          path: testInfo.outputPath(`information-review-${theme}.png`),
          fullPage: true,
        });
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await expect
        .poll(async () => (await details.boundingBox())!.y)
        .toBeGreaterThan((await information.boundingBox())!.y);
      await page
        .getByRole("button", {
          name: area === "occupancy" ? "Add review note" : `Review ${area} information`,
          exact: true,
        })
        .click();
      const editor = page.getByRole("region", { name: "Information review form", exact: true });
      await expect(editor.getByLabel("Review reason")).toBeVisible();
      await expect(editor.getByText("Evidence revision:", { exact: false })).not.toBeVisible();
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
        .toBe(true);
    }
  }
});

test("unclassified leasing status offers one clear next step", async ({ page, request }) => {
  const item = await property(request, "Leasing status guidance");
  const space = item.spaces[0];
  const occupancy = await request.put(`/api/spaces/${space.id}/classification`, {
    data: {
      occupancy: { occupancyStatus: "vacant", effectiveOn: item.effectiveLocalDate },
      expectedRevision: space.revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(occupancy.ok(), await occupancy.text()).toBe(true);
  await page.goto(`/coverage/space/${space.id}/occupancy`);
  const information = page.getByRole("region", { name: "Current information", exact: true });
  await expect(
    information.getByText("Leasing status hasn’t been classified.", { exact: true }),
  ).toBeVisible();
  await expect(information.getByRole("heading", { name: "Next step", exact: true })).toBeVisible();
  await expect(
    information.getByText(/Choose whether this home is not open for leasing/),
  ).toBeVisible();
  const action = information.getByRole("link", { name: "Set leasing status", exact: true });
  await expect(action).toHaveAttribute(
    "href",
    `/properties?workflow=portfolio.space.classify&target=${space.id}`,
  );
  await expect(information).toContainText(
    "Save the classification form, then return here and refresh.",
  );
  const history = page.getByRole("region", { name: "Review details", exact: true });
  await expect(history.getByRole("heading", { name: "Review history", exact: true })).toBeVisible();
  await expect(history).toContainText("A review note does not change occupancy or leasing status");
  await expect(history.getByRole("button", { name: "Add review note", exact: true })).toBeVisible();
  await action.click();
  await expect(page).toHaveURL(`/properties?workflow=portfolio.space.classify&target=${space.id}`);
  await expect(page.getByRole("heading", { name: "Classify home", exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: "Requested change", exact: true })).toBeVisible();
});

test("required gaps survive acknowledgment and non-applicability comes from sources", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 gaps");
  const space = item.spaces[0];
  await page.goto(`/coverage/space/${space.id}/occupancy`);
  await expect(page.getByRole("region", { name: "occupancy information review" })).toContainText(
    "missing required information",
  );
  await expect(
    page.getByText("Leasing status hasn’t been classified.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Save the classification form/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Set occupancy and leasing status", exact: true }),
  ).toHaveAttribute("href", `/properties?workflow=portfolio.space.classify&target=${space.id}`);
  await page.getByRole("button", { name: "Add review note" }).click();
  await expect(page.getByRole("option", { name: "Not applicable", exact: true })).toHaveCount(0);
  await page.getByLabel("Review reason").fill("Reviewed the unknown facts");
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByText(/Recorded review: missing required information/)).toBeVisible();
  await page.goto(`/coverage/space/${space.id}/lease`);
  await expect(page.getByRole("region", { name: "lease information review" })).toContainText(
    "not applicable",
  );
  await page.getByRole("button", { name: "Review lease information" }).click();
  await expect(page.getByRole("option", { name: "Not applicable", exact: true })).toHaveCount(1);
});

test("conflicting occupancy routes to record review rather than classification", async ({
  page,
  request,
}) => {
  const item = await property(request, "Conflicting occupancy guidance");
  const space = item.spaces[0];
  await page.route(`**/api/spaces/${space.id}/status`, async (route) => {
    const response = await route.fetch();
    const status = (await response.json()) as Schema["SpaceStatusResponse"];
    await route.fulfill({
      response,
      json: { ...status, attentionReasons: [{ code: "source_conflict" }] },
    });
  });
  await page.goto(`/coverage/space/${space.id}/occupancy`);
  const information = page.getByRole("region", { name: "Current information", exact: true });
  await expect(
    information.getByRole("link", { name: "Review occupancy and leasing status", exact: true }),
  ).toHaveAttribute("href", `/properties/${item.id}/units`);
  await expect(information).toContainText("conflicting records need review before changes");
  await expect(information.locator('a[href*="workflow=portfolio.space.classify"]')).toHaveCount(0);
});

test("missing lease context opens property leases without assuming a new agreement", async ({
  page,
  request,
}) => {
  const item = await property(request, "Missing lease context guidance");
  const unit = item.spaces[0];
  await page.route(`**/api/operator/coverage/space/${unit.id}/lease`, async (route) => {
    const response = await route.fetch();
    const result = (await response.json()) as Schema["CoverageResult"];
    await route.fulfill({
      response,
      json: {
        ...result,
        applicability: "applicable",
        state: "missing_required_information",
        causes: ["lease_context_missing"],
      },
    });
  });
  await page.goto(`/coverage/space/${unit.id}/lease`);
  const information = page.getByRole("region", { name: "Current information", exact: true });
  const action = information.getByRole("link", { name: "Review property leases", exact: true });
  await expect(action).toHaveAttribute("href", `/properties/${item.id}/leases`);
  await expect(information.locator('a[href*="workflow=lease.create"]')).toHaveCount(0);
  await action.click();
  await expect(page.getByRole("region", { name: "Leases section", exact: true })).toBeVisible();
});

test("missing rent and deposit tracking opens the matching setup form for its lease", async ({
  page,
  request,
}) => {
  const item = await property(request, "Money setup guidance");
  const tenantResponse = await request.post("/api/tenants", {
    data: {
      partyKind: "individual",
      displayName: "Review setup tenant",
      officialIds: [{ documentType: "passport", issuingCountry: "US", lastFour: "TEST" }],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(tenantResponse.ok(), await tenantResponse.text()).toBeTruthy();
  const tenant = (await tenantResponse.json()) as Schema["TenantMutationResponse"];
  const created = await request.post("/api/leases", {
    data: {
      expectedLeaseRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      spaceId: item.spaces[0].id,
      leaseKind: "residential",
      contractStartsOn: item.effectiveLocalDate,
      occupancyStartsOn: item.effectiveLocalDate,
      initialTerm: {
        baseRentMinor: 100000,
        currencyCode: "USD",
        paymentFrequency: "monthly",
        paymentDueDay: 1,
        agreedSecurityDepositMinor: 100000,
      },
      participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const lease = (await created.json()) as Schema["LeaseMutationResponse"];
  const executed = await request.post(`/api/leases/${lease.id}/execute`, {
    data: {
      expectedLeaseRevision: lease.leaseRevision,
      expectedRevision: item.spaces[0].revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
      executedOn: item.effectiveLocalDate,
    },
  });
  expect(executed.ok(), await executed.text()).toBeTruthy();
  for (const scenario of [
    {
      area: "rent",
      label: "Set up rent schedule",
      url: `/money?workflow=finance.rent_expectation.synchronize&target=${lease.id}`,
      heading: "Synchronize rent schedule",
    },
    {
      area: "deposit",
      label: "Set up deposit tracking",
      url: `/money?workflow=finance.deposit_account.create&leaseId=${lease.id}`,
      heading: "Create deposit account",
    },
  ]) {
    await page.goto(`/coverage/space/${item.spaces[0].id}/${scenario.area}`);
    const information = page.getByRole("region", { name: "Current information", exact: true });
    const action = information.getByRole("link", { name: scenario.label, exact: true });
    await expect(action).toHaveAttribute("href", scenario.url);
    await expect(
      information.getByRole("link", { name: "Review lease and terms", exact: true }),
    ).toHaveCount(1);
    await action.click();
    await expect(page).toHaveURL(scenario.url);
    await expect(page.getByRole("heading", { name: scenario.heading, exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: "Requested change", exact: true })).toBeVisible();
  }
  for (const scenario of [
    {
      area: "rent",
      cause: "rent_synchronization_required",
      label: "Update rent schedule",
      url: `/money?workflow=finance.rent_expectation.synchronize&target=${lease.id}`,
    },
    {
      area: "deposit",
      cause: "deposit_terms_changed",
      label: "Review deposit records",
      url: `/money?tab=deposits&leaseId=${lease.id}`,
    },
    {
      area: "lease",
      cause: "lease_context_ambiguous_or_missing_term",
      label: "Review lease and terms",
      url: `/leases/${lease.id}/details`,
    },
  ]) {
    await page.route(
      `**/api/operator/coverage/space/${item.spaces[0].id}/${scenario.area}`,
      async (route) => {
        const response = await route.fetch();
        const result = (await response.json()) as Schema["CoverageResult"];
        await route.fulfill({
          response,
          json: {
            ...result,
            applicability: "applicable",
            state: "needs_review",
            causes: [scenario.cause],
          },
        });
      },
    );
    await page.goto(`/coverage/space/${item.spaces[0].id}/${scenario.area}`);
    const information = page.getByRole("region", { name: "Current information", exact: true });
    await expect(
      information.getByRole("link", { name: scenario.label, exact: true }),
    ).toHaveAttribute("href", scenario.url);
    if (scenario.area === "deposit")
      await expect(
        information.locator('a[href*="workflow=finance.deposit_account.create"]'),
      ).toHaveCount(0);
  }
});

test("source changes retain review text and require explicit revision review", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 stale");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance information" }).click();
  await page.getByLabel("Review reason").fill("Keep my review text");
  await issue(request, item.id);
  await page.getByRole("button", { name: "Refresh maintenance information" }).click();
  await expect(page.getByText(/Source information changed/)).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue("Keep my review text");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
  await page.getByRole("button", { name: "Use displayed evidence revision" }).click();
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByText(/Recorded review: recorded/)).toBeVisible();
});

test("lost review response reconciles the original attempt after reload", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 interruption");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance information" }).click();
  await page.getByLabel("Review reason").fill("Original interrupted review");
  let recoveryId = "";
  page.on("response", async (response) => {
    if (response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"))
      recoveryId = ((await response.json()) as Schema["RecoveryResponse"]).id;
  });
  await page.route("**/coverage/property/*/maintenance/reviews", async (route) => {
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(page.getByRole("button", { name: "Check submission" })).toBeVisible();
  expect(recoveryId).toBeTruthy();
  await page.goto("/settings/recovery");
  await page
    .locator(".recovery-form-card")
    .filter({ hasText: "Information review" })
    .getByRole("button", { name: "Check submission" })
    .click();
  await expect(page).toHaveURL(
    `/coverage/property/${item.id}/maintenance?reviewResume=${recoveryId}`,
  );
  await expect(page.getByText(/Recorded review: recorded/)).toBeVisible();
  const events = await request.get(
    `/api/audit/events/operator_coverage_review/${((await (await request.get(`/api/operator/recovery/${recoveryId}`)).json()) as Schema["RecoveryResponse"]).receipt?.receiptId}`,
  );
  expect(events.ok()).toBeTruthy();
});

test("coverage absence, membership failure and hidden destinations remain truthful", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 availability");
  const unsupported = await page.goto(`/coverage/property/${item.id}/lease`);
  expect(unsupported?.status()).toBe(404);
  await page.goto(`/coverage/property/${crypto.randomUUID()}/maintenance`);
  await expect(page.getByRole("alert")).toBeVisible();
  await page.route(`**/api/operator/coverage/property/${item.id}/maintenance`, (route) =>
    route.fulfill({
      json: {
        subjectKind: "property",
        subjectId: item.id,
        area: "maintenance",
        availability: "unavailable",
        state: null,
        causes: [],
        asOf: new Date().toISOString(),
      },
    }),
  );
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await expect(page.getByText(/Information review source unavailable/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Review maintenance information" })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as Schema["BootstrapResponse"];
    if (data.preferences) data.preferences.hiddenDestinationIds = ["properties"];
    await route.fulfill({ json: data });
  });
  await page.goto("/search?q=Coverage54%20availability");
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Properties" }),
  ).toHaveCount(0);
  await page
    .getByRole("region", { name: "Properties search results" })
    .getByRole("link", { name: "Coverage54 availability" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Coverage54 availability", exact: true }),
  ).toBeVisible();
});

test("stale review admission preserves edits and blocks a new attempt", async ({
  page,
  request,
}) => {
  const item = await property(request, "Coverage54 race");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance information" }).click();
  await page.getByLabel("Review reason").fill("Retain my stale review");
  await page.route("**/coverage/property/*/maintenance/reviews", async (route) => {
    await issue(request, item.id);
    await route.fulfill({ response: await route.fetch() });
  });
  await page.getByRole("button", { name: "Record review" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Coverage evidence has changed" }),
  ).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue("Retain my stale review");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
  const current = await request.get(`/api/operator/coverage/property/${item.id}/maintenance`);
  expect(((await current.json()) as Schema["CoverageResult"]).lastManualReviewAt).toBeNull();
});

test("a coverage outage preserves an open review form", async ({ page, request }) => {
  const item = await property(request, "Coverage54 dirty outage");
  await page.goto(`/coverage/property/${item.id}/maintenance`);
  await page.getByRole("button", { name: "Review maintenance information" }).click();
  await page.getByLabel("Review reason").fill("Retain this during an outage");
  await page.route(`**/api/operator/coverage/property/${item.id}/maintenance`, (route) =>
    route.fulfill({
      json: {
        subjectKind: "property",
        subjectId: item.id,
        area: "maintenance",
        availability: "unavailable",
        state: null,
        causes: [],
        asOf: new Date().toISOString(),
      },
    }),
  );
  await page.getByRole("button", { name: "Refresh maintenance information" }).click();
  await expect(page.getByText(/Information review source unavailable/)).toBeVisible();
  await expect(page.getByLabel("Review reason")).toHaveValue("Retain this during an outage");
  await expect(page.getByRole("button", { name: "Record review" })).toBeDisabled();
});
