import { expect, test, type APIRequestContext, type Page, type Response } from "@playwright/test";

const BASE_URL = (process.env.EPM_SMOKE_BASE_URL ?? "http://localhost:18802").replace(/\/$/, "");
const IS_LOCAL_CONTAINER =
  BASE_URL.startsWith("http://localhost:") || BASE_URL.startsWith("http://127.0.0.1:");
const RUN_TAG = `[SMOKE-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${crypto.randomUUID().slice(0, 6)}]`;
const EXPECTED_SUPPORT_CONTACT = process.env.EPM_SMOKE_SUPPORT_CONTACT ?? "dctech92130@gmail.com";

interface ObservabilityTracker {
  setAllowExpected404: (allow: boolean) => void;
  assertClean: () => void;
}

function attachObservabilityGuard(page: Page): ObservabilityTracker {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  let allowExpected404 = false;

  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      const text = message.text();
      const url = message.location().url;
      if (
        text.includes("the server responded with a status of 404 (Not Found)") &&
        (allowExpected404 ||
          url.endsWith("/favicon.ico") ||
          (IS_LOCAL_CONTAINER && url.endsWith("/api/hosted/recovery/status")))
      ) {
        return;
      }
      consoleErrors.push(url ? `${text} (${url})` : text);
    }
  });
  page.on("response", (response: Response) => {
    if (response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  return {
    setAllowExpected404(allow: boolean) {
      allowExpected404 = allow;
    },
    assertClean() {
      expect(pageErrors, "Unexpected uncaught page errors").toEqual([]);
      expect(consoleErrors, "Unexpected browser console errors").toEqual([]);
      expect(serverErrors, "Unexpected HTTP 5xx responses").toEqual([]);
    },
  };
}

async function ensureSignedIn(page: Page): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/home(\?|$)/, { timeout: 15_000 });
  expect(
    page.url(),
    "Expected authenticated redirect to /home. For live canary runs, pass EPM_SMOKE_STORAGE_STATE.",
  ).toMatch(/\/home(\?|$)/);
  const settings = await page.request.get("/api/hosted/settings", { timeout: 10_000 });
  expect(
    settings.status(),
    "Home can render a sign-in screen at the same URL. Provide a valid Demo A session.",
  ).toBe(200);
}

async function readCsrfToken(page: Page): Promise<string> {
  const response = await page.request.get(`${BASE_URL}/api/hosted/session`);
  if (response.ok()) {
    const payload = (await response.json()) as { csrfToken?: string; csrf_token?: string };
    if (payload.csrfToken) return payload.csrfToken;
    if (payload.csrf_token) return payload.csrf_token;
  }
  const authStatus = await page.request.get(`${BASE_URL}/auth/status`);
  if (authStatus.ok()) {
    const payload = (await authStatus.json()) as { csrfToken?: string; csrf_token?: string };
    if (payload.csrfToken) return payload.csrfToken;
    if (payload.csrf_token) return payload.csrf_token;
  }
  return "";
}

async function hostedApiHeaders(page: Page): Promise<Record<string, string>> {
  const csrf = await readCsrfToken(page);
  const headers: Record<string, string> = { Origin: BASE_URL };
  if (csrf) {
    headers["x-epm-csrf"] = csrf;
  }
  return headers;
}

async function fetchJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`${BASE_URL}${path}`);
  expect(response.ok(), `GET ${path} failed (${response.status()}): ${await response.text()}`).toBe(
    true,
  );
  return (await response.json()) as T;
}

interface PropertyListResponse {
  items: Array<{
    id: string;
    displayName: string;
    spaces?: Array<{ id: string; displayName: string }>;
  }>;
}

interface PropertyDetailResponse {
  id: string;
  displayName: string;
  spaces: Array<{ id: string; displayName: string; revision: number }>;
  ownerships: Array<{ partyId: string | null }>;
}

interface ExpenseCategoryItem {
  id: string;
  name?: string;
  displayName?: string;
}

interface HostedSettingsResponse {
  surface: string;
  usage: {
    state: string;
    data: { plan: string; usable_bytes: number; used_bytes: number } | null;
  };
  protection: {
    state: string;
    data: { status: string; state?: string | null } | null;
  };
  support_contact: string;
}

interface FinancialReportingResponse {
  summary: { operating: { available: boolean; expensesPaid: string } };
}

function extractExpensesPaidMinor(report: FinancialReportingResponse): number {
  const operating = report.summary.operating;
  expect(operating.available).toBe(true);
  expect(operating.expensesPaid).toMatch(/^-?\d+\.\d{2}$/);
  return Number(operating.expensesPaid.replace(".", ""));
}

function isoDateOffset(daysOffset: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + daysOffset);
  return date.toISOString().slice(0, 10);
}

test.describe.serial("Hosted Operator post-deployment workflow smoke suite", () => {
  test("SMOKE-01: Hosted boundary, session, settings and SPA fallback", async ({
    page,
    browser,
  }) => {
    const guard = attachObservabilityGuard(page);

    if (BASE_URL.startsWith("http://localhost:") || BASE_URL.startsWith("http://127.0.0.1:")) {
      const live = await page.request.get(`${BASE_URL}/health/live`);
      expect(live.status()).toBe(200);
      const ready = await page.request.get(`${BASE_URL}/health/ready`);
      expect(ready.status()).toBe(200);
    }

    await ensureSignedIn(page);

    const homeResponse = await page.goto("/home", { waitUntil: "networkidle" });
    expect(homeResponse?.status()).toBe(200);
    const headers = homeResponse?.headers() ?? {};
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("no-referrer");
    expect(headers["content-security-policy"]).toBeTruthy();

    await expect(page.locator('meta[name="epm-deployment"]')).toHaveAttribute(
      "content",
      "hosted_managed",
    );
    await expect(page.locator('meta[name="epm-administrator-contact"]')).toHaveAttribute(
      "content",
      EXPECTED_SUPPORT_CONTACT,
    );

    const settingsPayload = await fetchJson<HostedSettingsResponse>(
      page.request,
      "/api/hosted/settings",
    );
    expect(settingsPayload.surface).toBe("operator_settings");
    expect(settingsPayload.support_contact).toBe(EXPECTED_SUPPORT_CONTACT);
    expect(settingsPayload.usage.state).toBe("ready");
    expect(settingsPayload.usage.data?.plan).toBe("free");
    expect(settingsPayload.usage.data?.usable_bytes).toBe(50_000_000);
    expect(settingsPayload.usage.data?.used_bytes ?? -1).toBeGreaterThanOrEqual(0);
    expect(settingsPayload.protection.state).toBe("ready");

    await page.goto("/settings", { waitUntil: "networkidle" });
    await expect(page.getByText(EXPECTED_SUPPORT_CONTACT).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /upgrade|billing|subscribe/i })).toHaveCount(0);

    // Regression guard for G-06: invalid HTML routes must render SPA 404 fallback, never raw 503.
    guard.setAllowExpected404(true);
    try {
      const invalidResponse = await page.goto("/nonexistent-route", {
        waitUntil: "domcontentloaded",
      });
      expect(invalidResponse?.status()).toBe(404);
      await expect(page.getByRole("heading", { name: "Page unavailable" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Return Home" })).toBeVisible();
      await expect(page.locator("body")).not.toContainText("Workspace access is unavailable");

      const badUuidResponse = await page.goto("/properties/not-a-uuid/overview", {
        waitUntil: "domcontentloaded",
      });
      expect(badUuidResponse?.status()).toBe(404);
      await expect(page.getByRole("heading", { name: "Page unavailable" })).toBeVisible();
    } finally {
      guard.setAllowExpected404(false);
    }

    // Unauthenticated API request must fail closed with 401.
    const anonContext = await browser.newContext();
    try {
      const unauth = await anonContext.request.get(`${BASE_URL}/api/properties`);
      expect(unauth.status()).toBe(401);
    } finally {
      await anonContext.close();
    }

    guard.assertClean();
  });

  test("SMOKE-02: Home dashboard, search and multi-source overview read parity", async ({
    page,
  }) => {
    const guard = attachObservabilityGuard(page);
    await ensureSignedIn(page);

    await page.goto("/home", { waitUntil: "networkidle" });
    await expect(page.getByText("This source is unavailable")).toHaveCount(0);

    // Switch Home work queue sub-tabs.
    for (const tabName of ["Needs action", "Waiting", "Upcoming"]) {
      const tab = page.getByRole("tab", { name: new RegExp(`^${tabName}`) });
      if ((await tab.count()) > 0) {
        await tab.first().click();
      }
    }

    // Regression guard for H-04: "View all Calendar and appointments" must navigate cleanly.
    const viewAllCalendar = page.getByRole("link", {
      name: /View all Calendar and appointments/i,
    });
    if ((await viewAllCalendar.count()) > 0) {
      await viewAllCalendar.first().click();
      await expect(page).toHaveURL(/\/home\/collections\/appointments/);
      await expect(page.getByText("This source is unavailable")).toHaveCount(0);
    }

    // Regression guard for G-02: Ctrl/Meta+K opens /search.
    await page.goto("/home", { waitUntil: "networkidle" });
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${modifier}+k`);
    await expect(page).toHaveURL(/\/search/);

    const properties = await fetchJson<PropertyListResponse>(page.request, "/api/properties");
    expect(properties.items.length).toBeGreaterThan(0);
    const targetProperty = properties.items[0];
    const searchTerm = targetProperty.displayName.split(/\s+/)[0] || "Alder";

    const searchInput = page.getByLabel("Search records", { exact: true });
    await searchInput.fill(searchTerm.slice(0, 1));
    await expect(page.getByText(/at least two characters/i).first()).toBeVisible();
    await searchInput.fill(searchTerm);
    await expect(
      page.getByRole("link", { name: targetProperty.displayName }).first(),
    ).toBeVisible();

    // Regression guard for P-03 / O-02: Property & Owner Overview Tasks section must load cleanly.
    await page.goto(`/properties/${targetProperty.id}/overview`, { waitUntil: "networkidle" });
    await expect(page.getByText("This source is unavailable")).toHaveCount(0);

    const propertyDetail = await fetchJson<PropertyDetailResponse>(
      page.request,
      `/api/properties/${targetProperty.id}`,
    );
    const ownerId = propertyDetail.ownerships.find((entry) => entry.partyId)?.partyId;
    if (ownerId) {
      await page.goto(`/owners/${ownerId}/overview`, { waitUntil: "networkidle" });
      await expect(page.getByText("This source is unavailable")).toHaveCount(0);
    }

    // Verify Leasing and Providers directories render cleanly.
    await page.goto("/leasing", { waitUntil: "networkidle" });
    await expect(
      page.getByRole("button", { name: "Create lease draft", exact: true }),
    ).toBeVisible();
    await page.goto("/providers", { waitUntil: "networkidle" });
    await expect(page.getByRole("button", { name: "Create provider", exact: true })).toBeVisible();

    guard.assertClean();
  });

  test("SMOKE-03: Tenant draft recovery lease, CRUD, draft lease create/void and cleanup", async ({
    page,
  }) => {
    const guard = attachObservabilityGuard(page);
    await ensureSignedIn(page);

    const tenantName = `${RUN_TAG} Jordan Avery`;
    const updatedName = `${RUN_TAG} Jordan Avery Updated`;
    let createdTenantId: string | null = null;
    let createdLeaseId: string | null = null;

    try {
      // 3.1 Start creating a tenant, leave partial draft, navigate to /settings/recovery.
      await page.goto("/tenants", { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Create tenant", exact: true }).click();
      await expect(page).toHaveURL(/workflow=tenant\.create/);

      const displayNameInput = page.getByLabel(/Display name/i).first();
      await displayNameInput.fill(tenantName);
      // Allow draft autosave to flush before navigating away.
      await page.waitForTimeout(700);

      await page.goto("/settings/recovery", { waitUntil: "networkidle" });
      const draftItem = page.getByRole("listitem").filter({ hasText: tenantName }).first();
      const continueLink = draftItem.getByRole("link", { name: /Continue editing/i });
      await expect(continueLink).toBeVisible();

      // 3.2 Same-tab resume must reuse the active lease without 409 / "Take over editing".
      await continueLink.click();
      await expect(page).toHaveURL(/workflow=tenant\.create/);
      await expect(page.getByRole("button", { name: /Take over editing/i })).toHaveCount(0);
      await expect(page.getByLabel(/Display name/i).first()).toHaveValue(tenantName);

      // 3.3 Submit valid tenant and verify persistence across reload.
      const createResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes("/api/tenants") && resp.request().method() === "POST",
        { timeout: 15_000 },
      );
      await page.locator('form button[type="submit"]').first().click();
      const createResponse = await createResponsePromise;
      expect(
        createResponse.ok(),
        `Create tenant failed (${createResponse.status()}): ${await createResponse.text()}`,
      ).toBe(true);
      const created = (await createResponse.json()) as {
        id: string;
        profile: { revision: number };
      };
      createdTenantId = created.id;

      await page.reload({ waitUntil: "networkidle" });
      await expect(page.getByText(tenantName).first()).toBeVisible();

      // 3.4 Edit display name and confirm persistence.
      const headers = await hostedApiHeaders(page);
      const patchResp = await page.request.patch(`${BASE_URL}/api/parties/${createdTenantId}`, {
        headers,
        data: {
          displayName: updatedName,
          expectedRevision: created.profile.revision,
          idempotencyKey: crypto.randomUUID(),
        },
      });
      expect(patchResp.ok(), `Patch tenant failed: ${await patchResp.text()}`).toBe(true);

      await page.goto(`/tenants?identity=${createdTenantId}`, { waitUntil: "networkidle" });
      await expect(page.getByText(updatedName).first()).toBeVisible();

      // 3.5 Create a Draft lease for this tenant and immediately Void it (safe, reversible Leasing check).
      const properties = await fetchJson<PropertyListResponse>(page.request, "/api/properties");
      const firstProp = await fetchJson<PropertyDetailResponse>(
        page.request,
        `/api/properties/${properties.items[0].id}`,
      );
      const spaceId = firstProp.spaces[0].id;
      const spaceRevision = firstProp.spaces[0].revision;
      const start = isoDateOffset(30);

      const leaseResp = await page.request.post(`${BASE_URL}/api/leases`, {
        headers,
        data: {
          expectedLeaseRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          spaceId,
          leaseKind: "residential",
          contractStartsOn: start,
          occupancyStartsOn: start,
          initialTerm: {
            baseRentMinor: 125_000,
            currencyCode: "USD",
            paymentFrequency: "monthly",
            paymentDueDay: 1,
            agreedSecurityDepositMinor: 125_000,
          },
          participants: [{ tenantPartyId: createdTenantId, participantRole: "primary_tenant" }],
        },
      });
      expect(leaseResp.ok(), `Create draft lease failed: ${await leaseResp.text()}`).toBe(true);
      const draftLease = (await leaseResp.json()) as { id: string; leaseRevision: number };
      createdLeaseId = draftLease.id;

      await page.goto(`/leases/${createdLeaseId}/details`, { waitUntil: "networkidle" });
      await expect(page.getByText("Draft").first()).toBeVisible();

      const voidLeaseResp = await page.request.post(
        `${BASE_URL}/api/leases/${createdLeaseId}/void`,
        {
          headers,
          data: {
            expectedRevision: spaceRevision,
            expectedLeaseRevision: draftLease.leaseRevision,
            idempotencyKey: crypto.randomUUID(),
            confirmed: true,
          },
        },
      );
      expect(voidLeaseResp.ok(), `Void draft lease failed: ${await voidLeaseResp.text()}`).toBe(
        true,
      );
      createdLeaseId = null;
    } finally {
      const headers = await hostedApiHeaders(page);
      if (createdLeaseId) {
        const current = await page.request.get(`${BASE_URL}/api/leases/${createdLeaseId}`);
        if (current.ok()) {
          const data = (await current.json()) as {
            leaseRevision: number;
            space?: { revision?: number };
          };
          await page.request.post(`${BASE_URL}/api/leases/${createdLeaseId}/void`, {
            headers,
            data: {
              expectedRevision: data.space?.revision ?? 1,
              expectedLeaseRevision: data.leaseRevision,
              idempotencyKey: crypto.randomUUID(),
              confirmed: true,
            },
          });
        }
      }
      if (createdTenantId) {
        const current = await page.request.get(`${BASE_URL}/api/tenants/${createdTenantId}`);
        if (current.ok()) {
          const data = (await current.json()) as { profile?: { revision: number } };
          await page.request.post(`${BASE_URL}/api/tenants/${createdTenantId}/archive`, {
            headers,
            data: {
              expectedRevision: data.profile?.revision ?? 1,
              idempotencyKey: crypto.randomUUID(),
              confirmed: true,
            },
          });
        }
      }
    }

    await page.goto("/settings/recovery", { waitUntil: "networkidle" });
    const leftoverSmokeDrafts = page.getByRole("listitem").filter({ hasText: "[SMOKE-" });
    while ((await leftoverSmokeDrafts.count()) > 0) {
      await leftoverSmokeDrafts.first().getByRole("button", { name: "Discard" }).click();
      await page.waitForTimeout(300);
    }
    await expect(page.getByRole("listitem").filter({ hasText: tenantName })).toHaveCount(0);

    guard.assertClean();
  });

  test("SMOKE-04: Financial ledger, reporting parity and logical storage accounting", async ({
    page,
  }) => {
    const guard = attachObservabilityGuard(page);
    await ensureSignedIn(page);

    const today = isoDateOffset(0);
    const monthStart = `${today.slice(0, 7)}-01`;
    const reportPath = `/api/money/properties?fromOn=${monthStart}&throughOn=${today}&propertyState=all`;

    const baselineReport = await fetchJson<FinancialReportingResponse>(page.request, reportPath);
    const baselineExpensesMinor = extractExpensesPaidMinor(baselineReport);

    const properties = await fetchJson<PropertyListResponse>(page.request, "/api/properties");
    const firstProp = await fetchJson<PropertyDetailResponse>(
      page.request,
      `/api/properties/${properties.items[0].id}`,
    );
    const categories = await fetchJson<ExpenseCategoryItem[]>(
      page.request,
      "/api/expense-categories",
    );
    expect(categories.length).toBeGreaterThan(0);

    const headers = await hostedApiHeaders(page);
    let createdExpenseId: string | null = null;

    try {
      // 4.2 Invalid amount (0.00) must be rejected cleanly with 400/422.
      const invalidExpense = await page.request.post(`${BASE_URL}/api/expenses`, {
        headers,
        data: {
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          propertyId: firstProp.id,
          spaceId: firstProp.spaces[0].id,
          categoryId: categories[0].id,
          payeeName: `${RUN_TAG} Smoke Hardware Supply`,
          paidByKind: "local_operator",
          paidOn: today,
          amount: "0.00",
          currencyCode: "USD",
          description: `${RUN_TAG} Invalid Zero Expense`,
        },
      });
      expect([400, 422]).toContain(invalidExpense.status());

      // 4.3 Record valid $12.34 paid expense.
      const createExpense = await page.request.post(`${BASE_URL}/api/expenses`, {
        headers,
        data: {
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          propertyId: firstProp.id,
          spaceId: firstProp.spaces[0].id,
          categoryId: categories[0].id,
          payeeName: `${RUN_TAG} Smoke Hardware Supply`,
          paidByKind: "local_operator",
          paidOn: today,
          amount: "12.34",
          currencyCode: "USD",
          description: `${RUN_TAG} Filter Replacement`,
        },
      });
      expect(
        createExpense.ok(),
        `Create expense failed (${createExpense.status()}): ${await createExpense.text()}`,
      ).toBe(true);
      const expense = (await createExpense.json()) as { id: string; expenseRevision: number };
      createdExpenseId = expense.id;

      // Verify in UI and Reporting + Settings usage accounting.
      await page.goto(`/money?tab=expenses&propertyId=${firstProp.id}`, {
        waitUntil: "networkidle",
      });
      await expect(
        page.getByRole("link", { name: `${RUN_TAG} Smoke Hardware Supply` }),
      ).toBeVisible();

      {
        const afterReport = await fetchJson<FinancialReportingResponse>(page.request, reportPath);
        expect(extractExpensesPaidMinor(afterReport)).toBe(baselineExpensesMinor + 1234);
      }

      const settings = await fetchJson<HostedSettingsResponse>(
        page.request,
        "/api/hosted/settings",
      );
      expect(settings.usage.state).toBe("ready");
      expect(settings.usage.data?.used_bytes ?? -1).toBeGreaterThanOrEqual(0);
      expect(settings.usage.data?.used_bytes ?? 50_000_001).toBeLessThan(50_000_000);

      // 4.5 Void expense and confirm Reporting returns to baseline.
      const voidResp = await page.request.post(
        `${BASE_URL}/api/expenses/${createdExpenseId}/void`,
        {
          headers,
          data: {
            expectedRevision: expense.expenseRevision,
            idempotencyKey: crypto.randomUUID(),
            confirmed: true,
            reason: `${RUN_TAG} post-deploy smoke cleanup`,
          },
        },
      );
      expect(voidResp.ok(), `Void expense failed: ${await voidResp.text()}`).toBe(true);
      createdExpenseId = null;

      {
        const finalReport = await fetchJson<FinancialReportingResponse>(page.request, reportPath);
        expect(extractExpensesPaidMinor(finalReport)).toBe(baselineExpensesMinor);
      }
    } finally {
      if (createdExpenseId) {
        const current = await page.request.get(`${BASE_URL}/api/expenses/${createdExpenseId}`);
        if (current.ok()) {
          const data = (await current.json()) as { expenseRevision: number };
          const cleanup = await page.request.post(
            `${BASE_URL}/api/expenses/${createdExpenseId}/void`,
            {
              headers,
              data: {
                expectedRevision: data.expenseRevision,
                idempotencyKey: crypto.randomUUID(),
                confirmed: true,
                reason: `${RUN_TAG} finally cleanup`,
              },
            },
          );
          expect(cleanup.ok(), `Void smoke expense: ${cleanup.status()}`).toBe(true);
        }
      }
    }

    guard.assertClean();
  });

  test("SMOKE-05: Maintenance issue, appointment scheduling, Home calendar and finish flow", async ({
    page,
  }) => {
    const guard = attachObservabilityGuard(page);
    await ensureSignedIn(page);

    const properties = await fetchJson<PropertyListResponse>(page.request, "/api/properties");
    const firstProp = await fetchJson<PropertyDetailResponse>(
      page.request,
      `/api/properties/${properties.items[0].id}`,
    );
    const headers = await hostedApiHeaders(page);
    const tomorrow = isoDateOffset(1);
    const issueTitle = `${RUN_TAG} Smoke Valve Check`;
    const appointmentTitle = `${RUN_TAG} Valve Inspection`;

    let createdIssueId: string | null = null;
    let createdAppointmentId: string | null = null;

    try {
      // 5.1 Create maintenance issue.
      const issueResp = await page.request.post(`${BASE_URL}/api/maintenance-issues`, {
        headers,
        data: {
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          propertyId: firstProp.id,
          spaceId: firstProp.spaces[0].id,
          summary: issueTitle,
          description: `${RUN_TAG} Post-deployment health verification issue.`,
          category: "plumbing",
          priority: "normal",
          reportedAtUtc: new Date(Date.now() - 60_000).toISOString(),
          reporter: { role: "manager", subjectKind: "local_operator" },
        },
      });
      expect(
        issueResp.ok(),
        `Create issue failed (${issueResp.status()}): ${await issueResp.text()}`,
      ).toBe(true);
      const issue = (await issueResp.json()) as { id: string; revision: number };
      createdIssueId = issue.id;

      // 5.2 Schedule a maintenance appointment for tomorrow.
      const apptResp = await page.request.post(
        `${BASE_URL}/api/maintenance-issues/${createdIssueId}/appointments`,
        {
          headers,
          data: {
            expectedRevision: issue.revision,
            idempotencyKey: crypto.randomUUID(),
            purpose: appointmentTitle,
            startsAtUtc: `${tomorrow}T17:00:00Z`,
            endsAtUtc: `${tomorrow}T18:00:00Z`,
            scheduledTimezone: "America/Los_Angeles",
            instructions: `${RUN_TAG} Scheduled smoke appointment.`,
          },
        },
      );
      expect(
        apptResp.ok(),
        `Schedule appointment failed (${apptResp.status()}): ${await apptResp.text()}`,
      ).toBe(true);
      const appt = (await apptResp.json()) as { id: string };
      createdAppointmentId = appt.id;

      // 5.3 Verify appointment surfaces on /home Calendar and appointments.
      await page.goto("/home", { waitUntil: "networkidle" });
      await expect(
        page
          .getByRole("region", { name: "Calendar and appointments" })
          .getByRole("button", { name: issueTitle }),
      ).toBeVisible();

      // 5.4 Exercise UI maintenance.appointment.finish (regression guard for Slice 1.2 draft-lease headers).
      await page.goto(
        `/maintenance?workflow=maintenance.appointment.finish&target=${createdIssueId}&child=${createdAppointmentId}`,
        { waitUntil: "networkidle" },
      );
      const finishForm = page.getByRole("region", { name: "Finish appointment" });
      await finishForm.getByRole("checkbox", { name: "I confirm this lifecycle change" }).check();
      await finishForm.getByRole("checkbox", { name: "Cancelled", exact: true }).check();
      await finishForm
        .getByRole("textbox", { name: "Reason", exact: true })
        .fill(`${RUN_TAG} smoke appointment cancelled cleanly`);

      const finishResponsePromise = page.waitForResponse(
        (resp) =>
          resp.url().includes(`/api/maintenance-appointments/${createdAppointmentId}/`) &&
          resp.request().method() === "POST",
        { timeout: 15_000 },
      );
      await finishForm.getByRole("button", { name: "Save finish appointment" }).click();
      const finishResponse = await finishResponsePromise;
      expect(
        finishResponse.status(),
        `Finish appointment must not fail with 409 lease error: ${await finishResponse.text()}`,
      ).toBe(200);
      createdAppointmentId = null;

      // 5.5 Cancel the synthetic maintenance issue cleanly.
      const issueDetail = await fetchJson<{ revision: number }>(
        page.request,
        `/api/maintenance-issues/${createdIssueId}`,
      );
      const cancelIssue = await page.request.post(
        `${BASE_URL}/api/maintenance-issues/${createdIssueId}/cancel`,
        {
          headers,
          data: {
            expectedRevision: issueDetail.revision,
            idempotencyKey: crypto.randomUUID(),
            confirmed: true,
            reason: `${RUN_TAG} post-deploy smoke cleanup`,
          },
        },
      );
      expect(cancelIssue.ok(), `Cancel issue failed: ${await cancelIssue.text()}`).toBe(true);
      createdIssueId = null;
    } finally {
      if (createdAppointmentId && createdIssueId) {
        const issue = await fetchJson<{ revision: number }>(
          page.request,
          `/api/maintenance-issues/${createdIssueId}`,
        );
        const cleanup = await page.request.post(
          `${BASE_URL}/api/maintenance-appointments/${createdAppointmentId}/cancel`,
          {
            headers,
            data: {
              expectedRevision: issue.revision,
              idempotencyKey: crypto.randomUUID(),
              confirmed: true,
              reason: `${RUN_TAG} finally cleanup`,
            },
          },
        );
        expect(cleanup.ok(), `Cancel smoke appointment: ${cleanup.status()}`).toBe(true);
      }
      if (createdIssueId) {
        const current = await page.request.get(
          `${BASE_URL}/api/maintenance-issues/${createdIssueId}`,
        );
        if (current.ok()) {
          const data = (await current.json()) as { revision: number };
          await page.request.post(`${BASE_URL}/api/maintenance-issues/${createdIssueId}/cancel`, {
            headers,
            data: {
              expectedRevision: data.revision,
              idempotencyKey: crypto.randomUUID(),
              confirmed: true,
              reason: `${RUN_TAG} finally cleanup`,
            },
          });
        }
      }
    }

    await page.goto("/settings/recovery", { waitUntil: "networkidle" });
    await expect(page.getByRole("listitem").filter({ hasText: RUN_TAG })).toHaveCount(0);

    guard.assertClean();
  });
});
