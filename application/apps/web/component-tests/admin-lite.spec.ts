import { expect, test } from "@playwright/test";

const OPERATOR_ID = "00000000-0000-4000-8000-000000000701";
const WORKSPACE_ID = "00000000-0000-4000-8000-000000000702";
const RELEASE_ID = "00000000-0000-4000-8000-000000000703";
const POLICY_ID = "00000000-0000-4000-8000-000000000704";
const INVITATION_ID = "00000000-0000-4000-8000-000000000705";

const BOOTSTRAP = {
  deploymentId: "00000000-0000-4000-8000-000000000700",
  publicBaseDomain: "epmdemo.xyz",
  loginOrigin: "https://login.epmdemo.xyz",
  registryGeneration: 1,
  freePolicy: {
    policy_id: POLICY_ID,
    plan_code: "free",
    policy_version: 1,
    usable_bytes: 50_000_000,
  },
  qualifiedOperatorReleases: [
    {
      release_id: RELEASE_ID,
      artifact_ref: "operator-image:v1",
      artifact_digest: "a".repeat(64),
      qualified_at: 1_700_000_000_000,
    },
  ],
  admissionCommitment: {
    warm_memory_bytes: 268435456,
    cpu_millis: 500,
    workspace: { bytes: 134217728, inodes: 4096 },
    control: { bytes: 16777216, inodes: 1024 },
    scratch: { bytes: 67108864, inodes: 1024 },
  },
  capacity: {
    available: true,
    profileRef: "pilot0-free-v1",
    profileRevision: 1,
    snapshotRevision: 3,
    observedAt: 1_700_000_000_000,
    commitmentCount: 1,
  },
};

const READY_OPERATOR = {
  operator_id: OPERATOR_ID,
  workspace_id: WORKSPACE_ID,
  display_name: "Cedar Crest",
  slug: "cedar-crest",
  setup_state: "ready_for_claim",
  desired_enabled: true,
  access: {
    state: "ready",
    data: { effective_enabled: false },
    freshness: { state: "known", as_of: 1_700_000_000_000, source_revision: "source:2" },
  },
  usage: {
    state: "ready",
    data: { plan: "free", usable_bytes: 50_000_000, used_bytes: 1_250_000 },
    freshness: { state: "known", as_of: 1_700_000_000_000, source_revision: "source:2" },
  },
  protection: {
    state: "unavailable",
    data: null,
    freshness: { state: "unavailable", error_code: "backup_protection_unavailable" },
  },
  release_id: RELEASE_ID,
  operation: {
    operation: {
      operation_id: "00000000-0000-4000-8000-000000000709",
      kind: "provision",
      idempotency_key: "create-cedar",
    },
    state: "succeeded",
    revision: 1,
    observed_at: 1_700_000_000_000,
  },
  actions: [
    { action: "admin_refresh_source", enabled: true },
    { action: "admin_reissue_invitation", enabled: true },
  ],
};

test("Admin-lite directory, add operator preservation on 409, and detail invitation flow", async ({
  page,
}) => {
  await page.route("**/api/admin/session", (route) =>
    route.fulfill({
      json: { expiresAt: Date.now() + 3_600_000, csrfToken: "admin-csrf-token" },
    }),
  );
  await page.route("**/api/admin/bootstrap", (route) => route.fulfill({ json: BOOTSTRAP }));
  await page.route("**/api/admin/operators?*", (route) =>
    route.fulfill({
      json: {
        directory: {
          state: "ready",
          data: {
            items: [READY_OPERATOR],
            matching_total: 1,
            freshness: { state: "known", as_of: 1_700_000_000_000, source_revision: "registry:1" },
          },
        },
        nextCursor: null,
        actions: [{ action: "admin_create_assignment", enabled: true }],
      },
    }),
  );

  let createAttempts = 0;
  await page.route("**/api/admin/operators", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    createAttempts += 1;
    expect(route.request().headers()["x-csrf-token"]).toBe("admin-csrf-token");
    if (createAttempts === 1) {
      return route.fulfill({
        status: 409,
        json: {
          code: "capacity_insufficient",
          message: "Insufficient host capacity for another Free operator workspace.",
          limitingResources: ["memory_bytes"],
        },
      });
    }
    return route.fulfill({
      status: 201,
      json: {
        operation: {
          operation_id: "00000000-0000-4000-8000-000000000799",
          kind: "create_assignment",
          idempotency_key: "key-1",
        },
        state: "pending",
        revision: 1,
        observed_at: 1_700_000_000_000,
      },
    });
  });

  await page.route(`**/api/admin/operators/${OPERATOR_ID}`, (route) =>
    route.fulfill({
      json: {
        operator: READY_OPERATOR,
        readiness: {
          state: "ready",
          data: {
            state: "unavailable",
            checks: [
              { name: "isolation", state: "passed", evidence_ref: "host:1" },
              { name: "schema", state: "passed", evidence_ref: "host:1" },
              { name: "routing", state: "passed", evidence_ref: "host:1" },
              { name: "protection", state: "unavailable", evidence_ref: null },
              { name: "binding", state: "passed", evidence_ref: "host:1" },
            ],
          },
        },
        refresh_operation: null,
        actions: READY_OPERATOR.actions,
      },
    }),
  );

  await page.route(`**/api/admin/operators/${OPERATOR_ID}/refresh`, (route) =>
    route.fulfill({ json: { state: "succeeded" } }),
  );
  await page.route(`**/api/admin/operators/${OPERATOR_ID}/invitations`, (route) =>
    route.fulfill({
      status: 201,
      json: {
        outcome: READY_OPERATOR.operation,
        invitationId: INVITATION_ID,
        token: "one-time-claim-token",
        expiresAt: Date.now() + 86_400_000,
      },
    }),
  );
  await page.route(
    `**/api/admin/operators/${OPERATOR_ID}/invitations/${INVITATION_ID}/delivered`,
    (route) => route.fulfill({ json: { invitationId: INVITATION_ID, revision: 2, state: "sent" } }),
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/index.html");
  await expect(page.getByRole("heading", { name: "Operators (1)" })).toBeVisible();
  await expect(page.getByText("Cedar Crest")).toBeVisible();
  await expect(page.getByText("1.25 MB / 50.00 MB")).toBeVisible();

  // Add operator preserves input on 409 capacity conflict, then succeeds on retry.
  await page.getByRole("button", { name: "Add operator" }).click();
  await expect(page.getByText("Free pilot (50.00 MB logical storage allowance)")).toBeVisible();
  await page.getByLabel("Display name").fill("Maple Grove");
  await page.getByLabel("Invited email").fill("maple@example.invalid");
  await page.getByLabel("Workspace slug").fill("maple-grove");
  await page.getByLabel("Support contact").fill("support@epmdemo.xyz");
  await page.getByRole("button", { name: "Create operator" }).click();

  await expect(page.getByRole("alert")).toContainText("memory_bytes");
  await expect(page.getByLabel("Display name")).toHaveValue("Maple Grove");

  await page.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByRole("heading", { name: "Operators (1)" })).toBeVisible();

  // Inspect operator detail, refresh source, issue one-time invitation, and mark delivered.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Inspect" }).click();
  await expect(page.getByRole("heading", { name: "Cedar Crest" })).toBeVisible();
  await expect(page.getByText("protection: unavailable", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Refresh source" }).click();
  await expect(page.getByText("Source observation refreshed.")).toBeVisible();

  await page.getByRole("button", { name: "Issue / reissue invitation" }).click();
  await expect(page.getByText("one-time-claim-token")).toBeVisible();
  await page.getByRole("button", { name: "Mark delivered" }).click();
  await expect(page.getByText("Delivery confirmed.")).toBeVisible();
});
