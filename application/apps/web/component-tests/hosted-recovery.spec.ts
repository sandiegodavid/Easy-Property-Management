import { expect, test } from "@playwright/test";

const OPERATOR_FIXTURE = "/component-tests/hosted-recovery.html";
const POINT_ID = "01960000-0000-7000-8000-000000000801";
const PREVIEW_ID = "01960000-0000-7000-8000-000000000802";
const OP_ID = "01960000-0000-7000-8000-000000000803";
const ADMIN_OPERATOR_ID = "00000000-0000-4000-8000-000000000701";
const ADMIN_WORKSPACE_ID = "00000000-0000-4000-8000-000000000702";
const ADMIN_RELEASE_ID = "00000000-0000-4000-8000-000000000703";

const BASE_RECOVERY_STATUS = {
  mode: "recovery",
  state: "choose_point",
  availability_reason: null,
  selected_point_id: POINT_ID,
  catalog: {
    state: "ready",
    data: {
      items: [
        {
          resource_id: POINT_ID,
          captured_at: 1_795_377_600_000,
          verified_at: 1_795_377_660_000,
          schema_compatible: true,
        },
      ],
      freshness: { state: "known", as_of: 1_795_377_660_000 },
    },
  },
  protection: {
    state: "unchanged",
    lastPointId: POINT_ID,
    lastCapturedAt: 1_795_377_600_000,
    lastVerifiedAt: 1_795_377_660_000,
    lastCheckedAt: 1_795_381_200_000,
    dirtySince: null,
    lastErrorCode: null,
  },
  startup: {
    mode: "recovery",
    reason: "business_db_corrupt",
    interruptedRestoreId: null,
    pendingAcceptanceId: null,
  },
};

test("Operator minimal recovery mode shows unchanged honesty, preview -> step-up -> confirm -> check -> accept without business API calls", async ({
  page,
}) => {
  let businessCalls = 0;
  await page.route("**/api/properties*", async (route) => {
    businessCalls += 1;
    await route.fulfill({ status: 503, json: { error: { code: "recovery_mode_active" } } });
  });
  await page.route("**/api/hosted/recovery/status", (route) =>
    route.fulfill({ json: BASE_RECOVERY_STATUS }),
  );
  await page.route("**/api/hosted/recovery/preview", async (route) => {
    expect(route.request().headers()["x-epm-csrf"]).toBe("operator-csrf-token");
    await route.fulfill({
      json: {
        previewId: PREVIEW_ID,
        pointId: POINT_ID,
        workspaceId: ADMIN_WORKSPACE_ID,
        sourceEpoch: 2,
        sourceGeneration: 1,
        currentBusinessRevision: "20260401_0001",
        selectedCapturedAt: 1_795_377_600_000,
        selectedVerifiedAt: 1_795_377_660_000,
        exactRequestHash: "a".repeat(64),
        expiresAt: 1_795_385_000_000,
        recoveryMode: true,
        stepUpChallengeId: "chal-001",
        stepUpExpiresAt: 1_795_385_000_000,
      },
    });
  });
  await page.route("**/api/hosted/recovery/confirm", async (route) => {
    expect(route.request().headers()["x-epm-csrf"]).toBe("operator-csrf-token");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body.point_id).toBe(POINT_ID);
    expect(body.preview_id).toBe(PREVIEW_ID);
    await route.fulfill({
      json: {
        operation: { operation_id: OP_ID, kind: "restore_workspace", idempotency_key: "k1" },
        state: "succeeded",
        revision: 2,
        observed_at: 1_795_381_300_000,
      },
    });
  });
  await page.route(`**/api/hosted/recovery/operations/${OP_ID}`, (route) =>
    route.fulfill({
      json: {
        operationId: OP_ID,
        pointId: POINT_ID,
        previewId: PREVIEW_ID,
        phase: "switched",
        state: "succeeded",
        acceptedAt: null,
      },
    }),
  );
  await page.route("**/api/hosted/recovery/accept", (route) =>
    route.fulfill({
      json: { operationId: OP_ID, phase: "accepted", acceptedAt: 1_795_381_400_000 },
    }),
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(OPERATOR_FIXTURE);

  await expect(page.getByRole("heading", { name: "Workspace recovery mode" })).toBeVisible();
  await expect(page.getByText("Protected — unchanged since verified point")).toBeVisible();
  await expect(page.getByText("2026-11-22T20:00:00.000Z").first()).toBeVisible();

  await page.getByRole("button", { name: "Preview restore" }).click();
  await expect(page.getByRole("heading", { name: "Confirm workspace restore" })).toBeFocused();

  await page
    .getByLabel("Fresh authentication verification token")
    .fill("step-up-grant-token-123456");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Confirm restore" }).click();

  await expect(page.getByText(/Workspace restore switched/)).toBeVisible();
  await page.getByRole("button", { name: "Check restore status" }).click();
  await expect(page.getByText(/Phase:/)).toBeVisible();
  await page.getByRole("button", { name: "Accept restored workspace" }).click();
  await expect(page.getByText("Restored workspace accepted.")).toBeVisible();
  expect(businessCalls).toBe(0);
});

test("Operator recovery shows degraded overdue state honestly and allows catalog reconstruction when empty", async ({
  page,
}) => {
  await page.route("**/api/hosted/recovery/status", (route) =>
    route.fulfill({
      json: {
        ...BASE_RECOVERY_STATUS,
        mode: "normal",
        state: "unavailable",
        availability_reason: "no_verified_points",
        selected_point_id: null,
        catalog: { state: "ready", data: { items: [], freshness: { state: "known" } } },
        protection: {
          ...BASE_RECOVERY_STATUS.protection,
          state: "overdue",
          lastErrorCode: "backup_stale",
        },
        startup: {
          mode: "normal",
          reason: null,
          interruptedRestoreId: null,
          pendingAcceptanceId: null,
        },
      },
    }),
  );
  await page.route("**/api/hosted/recovery/reconstruct", (route) =>
    route.fulfill({ json: { scannedManifests: 2, importedPoints: 2, skippedPoints: 0 } }),
  );

  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto(OPERATOR_FIXTURE);

  await expect(page.getByText("Degraded")).toBeVisible();
  await expect(page.getByText(/backup_stale/)).toBeVisible();
  await page.getByRole("button", { name: "Reconstruct catalog from off-host backup" }).click();
  await expect(page.getByText(/2 verified point\(s\) imported/)).toBeVisible();
});

test("Admin-lite shows protection status, repair runtime confirmation + status lookup, and independent Control Recovery without customer restore controls", async ({
  page,
}) => {
  await page.route("**/api/admin/session", (route) =>
    route.fulfill({ json: { expiresAt: Date.now() + 3_600_000, csrfToken: "admin-csrf" } }),
  );
  await page.route("**/api/admin/bootstrap", (route) =>
    route.fulfill({
      json: {
        deploymentId: "00000000-0000-4000-8000-000000000700",
        publicBaseDomain: "epmdemo.xyz",
        loginOrigin: "https://login.epmdemo.xyz",
        registryGeneration: 1,
        freePolicy: {
          policy_id: "00000000-0000-4000-8000-000000000704",
          plan_code: "free",
          policy_version: 1,
          usable_bytes: 50_000_000,
        },
        qualifiedOperatorReleases: [],
        admissionCommitment: null,
        capacity: { available: false },
      },
    }),
  );
  const operatorSummary = {
    operator_id: ADMIN_OPERATOR_ID,
    workspace_id: ADMIN_WORKSPACE_ID,
    display_name: "Oak Ridge",
    slug: "oak-ridge",
    setup_state: "active",
    desired_enabled: true,
    access: { state: "ready", data: { effective_enabled: true }, freshness: { state: "known" } },
    usage: {
      state: "ready",
      data: { plan: "free", usable_bytes: 50_000_000, used_bytes: 5_000_000 },
      freshness: { state: "known" },
    },
    protection: {
      state: "ready",
      data: { status: "protected", state: "unchanged", last_verified_at: 1_795_377_660_000 },
      freshness: { state: "known", as_of: 1_795_377_660_000 },
    },
    release_id: ADMIN_RELEASE_ID,
    binding_id: "00000000-0000-4000-8000-000000000711",
    resource_generation: 1,
    operation: null,
    actions: [],
  };
  await page.route("**/api/admin/operators?*", (route) =>
    route.fulfill({
      json: {
        directory: {
          state: "ready",
          data: { items: [operatorSummary], matching_total: 1, freshness: { state: "known" } },
        },
        nextCursor: null,
        actions: [],
      },
    }),
  );
  await page.route(`**/api/admin/operators/${ADMIN_OPERATOR_ID}`, (route) =>
    route.fulfill({
      json: {
        operator: operatorSummary,
        operatorRevision: 2,
        readiness: { state: "ready", data: { state: "ready", checks: [] } },
        actions: [],
      },
    }),
  );
  await page.route(`**/api/admin/operators/${ADMIN_OPERATOR_ID}/repair-runtime`, (route) =>
    route.fulfill({
      json: {
        operation: { operation_id: OP_ID, kind: "repair_runtime", idempotency_key: "r1" },
        state: "succeeded",
        revision: 3,
        observed_at: 1_795_381_500_000,
      },
    }),
  );
  await page.route(`**/api/admin/operations/${OP_ID}`, (route) =>
    route.fulfill({
      json: {
        operation: { operation_id: OP_ID, kind: "repair_runtime", idempotency_key: "r1" },
        state: "succeeded",
        revision: 3,
        observed_at: 1_795_381_500_000,
      },
    }),
  );
  await page.route("**/api/admin/recovery/status", (route) =>
    route.fulfill({
      json: {
        mode: "recovery",
        reason: "admin_db_corrupt",
        activeAdminResourceRef: "admin-incarnation-1",
        catalog: {
          items: [
            {
              resource_id: POINT_ID,
              captured_at: 1_795_377_600_000,
              verified_at: 1_795_377_660_000,
            },
          ],
        },
      },
    }),
  );
  await page.route("**/api/admin/recovery/preview", (route) =>
    route.fulfill({
      json: {
        previewId: PREVIEW_ID,
        pointId: POINT_ID,
        deploymentId: "00000000-0000-4000-8000-000000000700",
        sourceGeneration: 1,
        selectedCapturedAt: 1_795_377_600_000,
        selectedVerifiedAt: 1_795_377_660_000,
        exactRequestHash: "b".repeat(64),
        expiresAt: 1_795_385_000_000,
      },
    }),
  );
  await page.route("**/api/admin/recovery/confirm", (route) =>
    route.fulfill({
      json: {
        operation: { operation_id: OP_ID, kind: "restore_control", idempotency_key: "c1" },
        state: "succeeded",
        revision: 2,
        observed_at: 1_795_381_600_000,
      },
    }),
  );

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/admin/index.html");

  await expect(page.getByText("Protected — unchanged")).toBeVisible();
  await page.getByRole("button", { name: "Inspect" }).click();

  await expect(page.getByRole("heading", { name: "Runtime repair" })).toBeVisible();
  // Zero customer-workspace restore or plaintext export buttons in Admin detail.
  await expect(
    page.getByRole("button", { name: /restore workspace|export plaintext/i }),
  ).toHaveCount(0);

  await page.getByLabel(/replaces the Operator runtime container only/).check();
  await page.getByRole("button", { name: "Repair runtime" }).click();
  await expect(page.getByText(/Runtime repair operation/)).toBeVisible();
  await page.getByRole("button", { name: "Check operation status" }).click();
  await expect(page.getByText(/repair_runtime\): succeeded/)).toBeVisible();

  // Switch to independent Admin Control-Plane Recovery surface.
  await page.getByRole("button", { name: "← Back to operators" }).click();
  await page.getByRole("button", { name: "Control recovery" }).click();
  await expect(page.getByRole("heading", { name: "Admin control-plane recovery" })).toBeVisible();
  await expect(page.getByText("Admin recovery mode")).toBeVisible();
  await page.getByRole("button", { name: "Preview control restore" }).click();
  await expect(page.getByRole("heading", { name: "Confirm control-plane restore" })).toBeFocused();
  await page.getByLabel(/Bootstrap Google \+ TOTP MFA/).check();
  await page.getByLabel(/restores the Admin control-plane database/).check();
  await page.getByRole("button", { name: "Confirm control restore" }).click();
  await expect(page.getByText(/Control-plane restore switched/)).toBeVisible();
});
