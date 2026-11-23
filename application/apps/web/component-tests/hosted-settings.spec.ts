import { expect, test } from "@playwright/test";

const fixture = "/component-tests/hosted-settings.html";

const READY_SETTINGS = {
  surface: "operator_settings",
  delivery_owner: "H04",
  scope: {
    kind: "workspace",
    operator_id: "11111111-1111-4111-8111-111111111111",
    workspace_id: "22222222-2222-4222-8222-222222222222",
  },
  usage: {
    state: "ready",
    data: {
      plan: "free",
      usable_bytes: 50_000_000,
      used_bytes: 12_500_000,
    },
    freshness: {
      state: "known",
      as_of: 1795377600000,
      source_revision: "usage:1",
    },
  },
  protection: {
    state: "unavailable",
    data: null,
    freshness: {
      state: "unavailable",
      error_code: "backup_protection_unavailable",
    },
  },
  support_contact: "pilot-support@example.com",
  maintenance: {
    state: "unavailable",
    data: null,
    freshness: {
      state: "unavailable",
      error_code: "no_announced_maintenance",
    },
  },
  actions: [{ action: "operator_read_settings", enabled: true }],
  usageBreakdown: {
    committedDbBytes: 2_500_000,
    retainedFileBytes: 10_000_000,
    reservedBytes: 0,
    remainingBytes: 37_500_000,
    measurementVersion: "logical-v1",
  },
};

test("hosted mode displays Free pilot plan, usage, unavailable protection, support contact, and zero upgrade controls", async ({
  page,
}) => {
  await page.route("**/api/hosted/settings", (route) => route.fulfill({ json: READY_SETTINGS }));

  await page.goto(`${fixture}?mode=hosted`);

  await expect(page.getByRole("heading", { name: "Workspace plan and storage" })).toBeVisible();
  await expect(page.getByText("Free pilot (50.00 MB logical storage)")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Free pilot storage usage" })).toBeVisible();
  await expect(
    page.getByText("12.50 MB of 50.00 MB used (25%) — 37.50 MB remaining."),
  ).toBeVisible();
  await expect(page.getByText("Database: 2.50 MB · Retained files: 10.00 MB")).toBeVisible();
  await expect(page.getByText("Observed at 2026-11-22T20:00:00.000Z")).toBeVisible();
  await expect(page.getByText("Unavailable — backup protection is not yet active.")).toBeVisible();
  await expect(page.getByText("pilot-support@example.com")).toBeVisible();

  // Explicit exclusions: zero paid-upgrade, billing, plan-change, or idle-wake controls.
  const bodyText = (await page.locator("body").textContent()) ?? "";
  expect(bodyText).not.toMatch(/upgrade|billing|paid plan|change plan|schedule maintenance|wake/i);
  await expect(page.getByText("Maintenance notice")).toHaveCount(0);
});

test("hosted mode reports unavailable storage usage honestly without fabricating zero bytes", async ({
  page,
}) => {
  await page.route("**/api/hosted/settings", (route) =>
    route.fulfill({
      json: {
        ...READY_SETTINGS,
        usage: {
          state: "unavailable",
          data: null,
          freshness: { state: "unavailable", error_code: "usage_state_unreadable" },
        },
        protection: {
          state: "ready",
          data: { status: "degraded", last_verified_at: 1795377600000 },
        },
        usageBreakdown: null,
        maintenance: {
          state: "ready",
          data: { message: "Planned maintenance Sunday 02:00 UTC." },
        },
      },
    }),
  );

  await page.goto(`${fixture}?mode=hosted`);

  await expect(page.getByText("Unavailable (usage_state_unreadable).")).toBeVisible();
  await expect(
    page.getByText("Degraded — latest verified point: 2026-11-22T20:00:00.000Z"),
  ).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.getByText("Planned maintenance Sunday 02:00 UTC.")).toBeVisible();
});

test("local mode does not render HostedSettings or call /api/hosted/settings", async ({ page }) => {
  let settingsCalls = 0;
  await page.route("**/api/hosted/settings", async (route) => {
    settingsCalls += 1;
    await route.fulfill({ json: READY_SETTINGS });
  });

  await page.goto(`${fixture}?mode=local`);

  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Workspace plan and storage" })).toHaveCount(0);
  expect(settingsCalls).toBe(0);
});

test("507 hosted_storage_quota_exceeded preserves form input as a definite rejection", async ({
  page,
}) => {
  await page.route("**/api/hosted/settings", (route) => route.fulfill({ json: READY_SETTINGS }));
  await page.route("**/api/properties", (route) =>
    route.fulfill({
      status: 507,
      json: {
        detail: {
          code: "hosted_storage_quota_exceeded",
          message:
            "Workspace storage limit (50 MB Free pilot) reached. Remove files or contact pilot-support@example.com.",
        },
      },
    }),
  );

  await page.goto(`${fixture}?mode=hosted`);
  const input = page.getByLabel("Property name");
  await input.fill("123 Oak Street");
  await page.getByRole("button", { name: "Save property" }).click();

  await expect(page.getByRole("alert")).toContainText("50 MB Free pilot");
  await expect(page.getByTestId("outcome-flag")).toHaveText("definite");
  await expect(input).toHaveValue("123 Oak Street");
});
