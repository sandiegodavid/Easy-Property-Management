import { expect, test, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
async function mockRecovery(page: Page) {
  const records = new Map<string, Schema["RecoveryResponse"]>();
  await page.route("**/api/operator/recovery**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/operator/recovery")
      return route.fulfill({
        json: {
          items: [...records.values()],
          nextCursor: null,
          matchingTotal: records.size,
          asOf: "2026-10-12T12:00:00Z",
          sourceRevision: "1",
        },
      });
    const parts = path.split("/");
    const id = parts[4];
    if (route.request().method() === "GET") return route.fulfill({ json: records.get(id) });
    const body = route.request().postDataJSON() as Record<string, unknown>;
    if (parts[5] === "attempt") {
      records.set(id, {
        ...records.get(id)!,
        status: "outcome_unknown",
        attemptKey: body.attemptKey as string,
        requestFingerprint: "a".repeat(64),
        revision: 2,
      });
    } else if (parts[5] === "reconcile") {
      records.set(id, { ...records.get(id)!, status: "reconciled", revision: 3 });
    } else {
      records.set(id, {
        ...(body as Schema["RecoveryInput"]),
        id,
        revision: 1,
        status: "active",
        attemptKey: null,
        requestFingerprint: null,
        receipt: null,
        reuseState: "available",
        asOf: "2026-10-12T12:00:00Z",
        savedAt: "2026-10-12T12:00:00Z",
        expiresAt: "2026-11-12T12:00:00Z",
        baseSourceRevision: (body.baseSourceRevision as string | null) ?? null,
        sourceKind: (body.sourceKind as string | null) ?? null,
        sourceId: (body.sourceId as string | null) ?? null,
      });
    }
    return route.fulfill({ json: records.get(id) });
  });
  return records;
}
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

test("AI destination settings persist through the source API and disclose unavailable adapters", async ({
  page,
  request,
}) => {
  await page.goto("/settings/ai");
  await expect(page.getByRole("heading", { name: "Built-in AI assistance" })).toBeVisible();
  await expect(page.getByText("No AI adapters are registered in this installation.")).toBeVisible();
  await expect(page.getByText("No AI actions are registered.")).toBeVisible();
  const pause = page.getByRole("checkbox", { name: "Pause all AI assistance" });
  await expect(pause).not.toBeChecked();
  await pause.click();
  await expect(page.getByText("All AI assistance is paused.")).toBeVisible();
  await expect(pause).toBeChecked();
  const paused = await request.get("/api/ai/settings");
  expect(((await paused.json()) as Schema["SettingsResponse"]).killSwitch).toBe(true);
  await pause.click();
  await expect(page.getByText("AI pause is cleared.")).toBeVisible();
  const resumed = await request.get("/api/ai/settings");
  expect(((await resumed.json()) as Schema["SettingsResponse"]).killSwitch).toBe(false);
});

test("AI draft detail separates governed input and blocks unsupported or stale approval", async ({
  page,
}) => {
  const recovery = await mockRecovery(page);
  const id = "00000000-0000-4000-8000-000000000091";
  const draft: Schema["DraftDetailResponse"] = {
    id,
    runId: "00000000-0000-4000-8000-000000000092",
    entityKind: "summary",
    status: "proposed",
    version: 1,
    sourceEntityType: "maintenance_issue",
    sourceEntityId: "issue-91",
    actionType: "maintenance.summary",
    owningModule: "maintenance",
    updatedAt: "2026-10-12T12:00:00Z",
    draftPayload: { summary: "Suggested summary" },
    confidence: { label: "medium", provenance: "registered synthetic assessment" },
    governedInput: { description: "Bounded source text" },
    sourceRevision: "3",
    sourceFingerprint: "a".repeat(64),
    currentSource: {
      revision: "4",
      fingerprint: "b".repeat(64),
      tombstoned: false,
      availability: "available",
      comparisonState: "changed",
    },
    approvalAvailable: false,
    reviewHistory: [],
    provenance: {
      executionKind: "provider_generation",
      transportProvider: "registered-provider",
      adapterVersion: "1",
      modelIdentifier: "summary-model",
      executionLocation: "on_device",
      modelArtifactDigest: "sha256:local",
      quantization: "Q4",
      runtimeId: "runtime",
      runtimeVersion: "1",
      promptTemplateId: "maintenance.summary",
      promptTemplateVersion: 1,
      outputSchemaVersion: 1,
      redactionProfile: "maintenance-summary",
      redactionProfileVersion: 1,
      promptTokens: 12,
      completionTokens: 8,
      correlationId: "00000000-0000-4000-8000-000000000093",
    },
    supersedesDraftId: "00000000-0000-4000-8000-000000000090",
    createdAt: "2026-10-12T12:00:00Z",
    terminalAt: null,
  };
  await page.route(`**/api/ai/drafts/${id}`, (route) => route.fulfill({ json: draft }));
  await page.goto(`/ai/review/${id}`);
  await expect(page.getByRole("heading", { name: "Review AI draft" })).toBeVisible();
  await expect(page.getByText("sha256:local", { exact: true })).toBeVisible();
  await expect(page.getByText("runtime 1 · quantization Q4", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: draft.supersedesDraftId! })).toHaveAttribute(
    "href",
    `/ai/review/${draft.supersedesDraftId}`,
  );
  await page.getByText("Registered confidence and provenance", { exact: true }).click();
  await expect(
    page.locator("pre").filter({ hasText: "registered synthetic assessment" }),
  ).toBeVisible();
  await page.getByText("Governed input sent for this draft").click();
  await expect(page.locator("pre").filter({ hasText: "Bounded source text" })).toBeVisible();
  await expect(page.getByText(/available; changed/)).toBeVisible();
  await expect(page.getByText(/no owning-domain approval handler is registered/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve through/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save draft edits" })).toBeEnabled();
  draft.approvalAvailable = true;
  draft.currentSource = {
    ...draft.currentSource!,
    revision: "3",
    fingerprint: "a".repeat(64),
    comparisonState: "current",
  };
  let approvals = 0;
  let edits = 0;
  await page.route(`**/api/ai/drafts/${id}/approve`, async (route) => {
    approvals += 1;
    expect([...recovery.values()].some((item) => item.status === "outcome_unknown")).toBe(true);
    draft.status = "approved";
    draft.terminalAt = "2026-10-12T12:05:00Z";
    draft.reviewHistory = [
      {
        id: "00000000-0000-4000-8000-000000000094",
        decision: "approved",
        draftVersionBefore: draft.version,
        draftVersionAfter: draft.version,
        operatorNote: "Reviewed against current source",
        resultEntityType: "maintenance_issue",
        resultEntityId: "issue-91",
        correlationId: draft.provenance.correlationId,
        decidedAt: draft.terminalAt,
      },
    ];
    return route.fulfill({ json: { id } });
  });
  await page.route(`**/api/ai/drafts/${id}`, async (route) => {
    if (route.request().method() === "PATCH") {
      edits += 1;
      const body = route.request().postDataJSON() as { draftPayload: Record<string, unknown> };
      draft.draftPayload = body.draftPayload;
      draft.version += 1;
      draft.status = "edited";
      return route.abort();
    }
    return route.fulfill({ json: draft });
  });
  await page.reload();
  const payload = page.getByLabel("Draft payload (registered schema)");
  const review = page.getByLabel("I reviewed the current source shown above.");
  const approve = page.getByRole("button", { name: /Approve through/ });
  await review.check();
  await expect(approve).toBeEnabled();
  await payload.fill('{"summary":"Corrected"}');
  await expect(review).not.toBeChecked();
  await expect(approve).toBeDisabled();
  await payload.fill("invalid JSON");
  await expect(approve).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save draft edits" })).toBeDisabled();
  await payload.fill('{"summary":"Corrected"}');
  await page.getByRole("button", { name: "Save draft edits" }).click();
  await expect(
    page.getByRole("button", { name: "Reconcile original review command" }),
  ).toBeVisible();
  await page.reload();
  await expect(approve).toBeDisabled();
  await page.route("**/api/ai/command-operations/by-key/*", (route) =>
    route.fulfill({ json: { id, action: "edited", result: draft } }),
  );
  await page.getByRole("button", { name: "Reconcile original review command" }).click();
  await expect(page.getByRole("region", { name: "AI draft updated", exact: true })).toContainText(
    "Corrected",
  );
  await expect(payload).toHaveCount(0);
  await page.getByRole("button", { name: "Continue reviewing draft", exact: true }).click();
  await expect(payload).toContainText("Corrected");
  await expect(review).not.toBeChecked();
  await review.check();
  await approve.click();
  await expect(page.getByText("The owning domain recorded the approved result.")).toBeVisible();
  await expect(page.getByText("Recorded result: maintenance_issue · issue-91")).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve through/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save draft edits" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Dismiss draft" })).toHaveCount(0);
  await expect(payload).toBeDisabled();
  expect(approvals).toBe(1);
  expect(edits).toBe(1);
});

test("draft status and bounded continuation pages have truthful empty states and a reset", async ({
  page,
}) => {
  const id = "00000000-0000-4000-8000-000000000095";
  const requests: URL[] = [];
  await page.route("**/api/ai/drafts?*", (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const first = !url.searchParams.has("cursor") && url.searchParams.get("status") === "proposed";
    return route.fulfill({
      json: {
        items: first
          ? [
              {
                id,
                runId: "00000000-0000-4000-8000-000000000096",
                entityKind: "summary",
                actionType: "record.summary",
                owningModule: "records",
                sourceEntityType: "record",
                sourceEntityId: "record-1",
                version: 1,
                status: "proposed",
                updatedAt: "2026-10-12T12:00:00Z",
              } satisfies Schema["DraftSummaryResponse"],
            ]
          : [],
        nextCursor: first ? "opaque-next-page" : null,
      },
    });
  });
  await page.goto("/settings/ai");
  await expect(page.getByRole("link", { name: "summary · record.summary" })).toBeVisible();
  await page.getByRole("button", { name: "Next drafts" }).click();
  await expect(page.getByText("No AI drafts match this status on this page.")).toBeVisible();
  await page.getByRole("button", { name: "First drafts page" }).click();
  await expect(page.getByRole("link", { name: "summary · record.summary" })).toBeVisible();
  await page.getByLabel("Draft status").selectOption("approved");
  await expect(page.getByText("No AI drafts match this status on this page.")).toBeVisible();
  await expect(page.getByRole("button", { name: "First drafts page" })).toHaveCount(0);
  expect(requests.some((url) => url.searchParams.get("cursor") === "opaque-next-page")).toBe(true);
  expect(requests.at(-1)?.searchParams.get("status")).toBe("approved");
  expect(requests.every((url) => url.searchParams.get("pageSize") === "100")).toBe(true);
});

test("cloud setup records disclosure, keeps credentials write-only and never repeats an uncertain effect", async ({
  page,
}) => {
  const recovery = await mockRecovery(page);
  const id = "00000000-0000-4000-8000-000000000101";
  const stamp = "2026-10-12T12:00:00Z";
  const adapter: Schema["RegisteredAdapterResponse"] = {
    adapterId: "sample-cloud",
    adapterVersion: "1",
    executionLocation: "cloud",
    models: ["summary-v1"],
    credentialRequired: true,
    capabilities: ["structured_output"],
    inputModalities: ["text"],
  };
  const action: Schema["RegisteredActionResponse"] = {
    actionType: "record.summary",
    owningModule: "records",
    maxRunsPerUtcDay: 10,
    maxPromptTokens: 1000,
    maxCompletionTokens: 500,
    requiredCapabilities: ["structured_output"],
    requiredInputModalities: ["text"],
    requiredDataClasses: ["record_summary"],
  };
  const settings: Schema["SettingsResponse"] = {
    killSwitch: false,
    builtInEnabled: false,
    defaultConnectionId: null,
    updatedAt: stamp,
    revision: 1,
    readiness: { ready: false, reason: "no_default_connection" },
    registeredAdapters: [adapter],
    actions: [action],
  };
  let connection: Schema["ModelConnectionResponse"] | null = null;
  let credentialRequests = 0;
  let connectionRequests = 0;
  let external: Schema["ExternalEffectResponse"] | null = null;
  let limit: Schema["ActionLimitResponse"] = {
    actionType: action.actionType,
    enabled: true,
    connectionId: id,
    maxRunsPerUtcDay: 10,
    maxPromptTokens: 1000,
    maxCompletionTokens: 500,
    allowedModels: ["sample-cloud@1:summary-v1", "sample-cloud@1:other"],
    updatedAt: stamp,
    revision: 1,
  };
  await page.route("**/api/ai/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/ai/settings" && request.method() === "GET")
      return route.fulfill({ json: settings });
    if (path === "/api/ai/connections" && request.method() === "GET")
      return route.fulfill({ json: connection ? [connection] : [] });
    if (path === "/api/ai/limits" && request.method() === "GET")
      return route.fulfill({
        json: [limit],
      });
    if (path === `/api/ai/limits/${action.actionType}` && request.method() === "PUT") {
      limit = {
        ...limit,
        ...(request.postDataJSON() as Schema["LimitInput"]),
        revision: limit.revision + 1,
      };
      return route.fulfill({ json: { ...limit, operationId: crypto.randomUUID() } });
    }
    if (path === `/api/ai/connections/${id}` && request.method() === "PATCH") {
      connection = {
        ...connection!,
        ...(request.postDataJSON() as { enabled: boolean }),
        revision: connection!.revision + 1,
      };
      return route.fulfill({ json: { ...connection, operationId: crypto.randomUUID() } });
    }
    if (path === `/api/ai/connections/${id}/test`) {
      return route.fulfill({
        json: {
          ...external!,
          action: "connection_probe",
          revision: connection!.revision,
          status: "completed",
          result: { status: "completed", ready: true },
          idempotencyKey: (request.postDataJSON() as { idempotencyKey: string }).idempotencyKey,
        },
      });
    }
    if (path === "/api/ai/redaction-profiles" && request.method() === "GET")
      return route.fulfill({ json: [] });
    if (path === "/api/ai/drafts" && request.method() === "GET")
      return route.fulfill({ json: { items: [], nextCursor: null } });
    if (path === "/api/ai/connections" && request.method() === "POST") {
      connectionRequests += 1;
      expect(
        [...recovery.values()].some(
          (item) => item.formKey === "ai.connection.create" && item.status === "outcome_unknown",
        ),
      ).toBe(true);
      connection = {
        id,
        label: "Sample cloud",
        revision: 1,
        adapterId: adapter.adapterId,
        adapterVersion: adapter.adapterVersion,
        modelIdentifier: adapter.models[0],
        executionLocation: "cloud",
        enabled: true,
        cloudDataClasses: [],
        disclosureVersion: null,
        disclosureAcceptedAt: null,
        credentialPresent: false,
        modelArtifactDigest: null,
        quantization: null,
        runtimeId: null,
        runtimeVersion: null,
        createdAt: stamp,
        updatedAt: stamp,
      };
      return route.abort();
    }
    if (path.startsWith("/api/ai/command-operations/by-key/"))
      return route.fulfill({ json: { id, action: "connection_create", result: connection } });
    if (path === `/api/ai/connections/${id}/disclosure` && request.method() === "PUT") {
      connection = {
        ...connection!,
        revision: 2,
        cloudDataClasses: ["record_summary"],
        disclosureVersion: "AI-GOV-001-v1",
        disclosureAcceptedAt: stamp,
        updatedAt: stamp,
      };
      return route.fulfill({ json: { ...connection, operationId: crypto.randomUUID() } });
    }
    if (path === `/api/ai/connections/${id}/credential` && request.method() === "PUT") {
      credentialRequests += 1;
      external = {
        operationId: crypto.randomUUID(),
        idempotencyKey: (request.postDataJSON() as { idempotencyKey: string }).idempotencyKey,
        connectionId: id,
        action: "credential_set",
        revision: 3,
        updatedAt: stamp,
        status: "outcome_unknown",
        result: null,
        createdAt: stamp,
        completedAt: null,
        requiresDeviceValidation: true,
      };
      expect(
        [...recovery.values()].some(
          (item) =>
            item.attemptKey === external!.idempotencyKey && item.status === "outcome_unknown",
        ),
      ).toBe(true);
      return route.abort();
    }
    if (path.startsWith("/api/ai/external-operations/by-key/") && request.method() === "GET")
      return route.fulfill({ json: external });
    if (path.startsWith("/api/ai/external-operations/") && path.endsWith("/acknowledge-unknown")) {
      connection = { ...connection!, credentialPresent: true };
      external = {
        ...external!,
        status: "abandoned",
        result: { status: "abandoned" },
        completedAt: stamp,
      };
      return route.fulfill({ json: external });
    }
    return route.fulfill({ status: 404, json: { detail: "unhandled test request" } });
  });

  await page.goto("/settings/ai");
  await page.getByLabel("Connection label").fill("Sample cloud");
  await page.getByLabel("Adapter and version").selectOption("sample-cloud@1");
  await page
    .getByRole("region", { name: "Model connections" })
    .getByRole("combobox")
    .nth(1)
    .selectOption("summary-v1");
  await page.getByRole("button", { name: "Create connection" }).click();
  await expect(page.getByText(/The response was interrupted/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Create connection" })).toBeDisabled();
  await page.getByRole("button", { name: "Check original command receipt" }).click();
  await expect(page.getByRole("region", { name: "Connection saved", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create connection", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Record cloud disclosure" })).toBeDisabled();
  expect(connectionRequests).toBe(1);
  await expect(page.getByText("Credential: Not configured.")).toBeVisible();
  await page
    .getByLabel("I understand this named cloud destination receives the listed data classes.")
    .check();
  await page.getByRole("button", { name: "Record cloud disclosure" }).click();
  await expect(page.getByText("Cloud disclosure saved for this connection.")).toBeVisible();
  const secret = "test-only-secret-not-to-retain";
  const credential = page.getByLabel("Provider credential (write-only)");
  await credential.fill(secret);
  await page.getByRole("button", { name: "Set or replace credential" }).click();
  await expect(page.getByText(/The response was interrupted/)).toBeVisible();
  await expect(credential).toHaveValue("");
  await expect(page.getByText(secret)).toHaveCount(0);
  expect(JSON.stringify([...recovery.values()])).not.toContain(secret);
  await expect(page.getByRole("button", { name: "Run synthetic connection test" })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("button", { name: "Set or replace credential" })).toBeDisabled();
  await page.getByRole("button", { name: "Check external-operation status" }).click();
  await expect(page.getByText("External operation status: outcome_unknown.")).toBeVisible();
  await page.getByRole("button", { name: "Acknowledge unknown outcome" }).click();
  await expect(page.getByText(/Uncertainty was recorded as abandoned/)).toBeVisible();
  expect(credentialRequests).toBe(1);
  await page.getByRole("button", { name: "Run synthetic connection test" }).click();
  await expect(page.getByText("Synthetic connection test passed.")).toBeVisible();
  await page.getByText("record.summary · records").click();
  await expect(page.getByText(/Available for new requests/)).toBeVisible();
  await page.getByRole("checkbox", { name: "sample-cloud@1:summary-v1", exact: true }).click();
  await expect(page.getByText(/The selected model is not allowed/)).toBeVisible();
  await page.getByLabel("Enable this connection").click();
  await expect(page.getByText("The selected connection is disabled.")).toBeVisible();
});
