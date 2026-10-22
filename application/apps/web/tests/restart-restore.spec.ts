import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import { spawn, execFile, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { promisify } from "node:util";

type Schema = components["schemas"];
const execute = promisify(execFile);
const origin = "http://127.0.0.1:18747";
const python = process.env.EPM_PYTHON ?? resolve("../.venv/easy-property-management/bin/python");
const env = { ...process.env, PYTHONPATH: resolve("apps/server") };

test("lost response survives a process restart and encrypted restore with the original receipt and saved form", async ({
  page,
  playwright,
}) => {
  test.setTimeout(120_000);
  page.on("dialog", (dialog) => void dialog.accept());
  const root = await mkdtemp(resolve(tmpdir(), "epm-ui-acceptance-"));
  let server: ChildProcess | undefined;
  const stop = async () => {
    if (!server || server.exitCode !== null || server.signalCode !== null) return;
    const exited = new Promise<void>((done) => server!.once("exit", () => done()));
    server.kill("SIGTERM");
    const timeout = setTimeout(() => server?.kill("SIGKILL"), 5_000);
    try {
      await exited;
    } finally {
      clearTimeout(timeout);
    }
  };
  const start = async () => {
    server = spawn(
      python,
      ["scripts/web_smoke_server.py", "--port", "18747", "--state", "ready", "--directory", root],
      { env, stdio: "ignore" },
    );
    await expect
      .poll(
        async () => {
          try {
            return (await fetch(`${origin}/openapi.json`)).status;
          } catch {
            return 0;
          }
        },
        { timeout: 60_000 },
      )
      .toBe(200);
  };
  const api = await playwright.request.newContext({
    baseURL: origin,
    extraHTTPHeaders: { Origin: origin },
    timeout: 10_000,
  });
  try {
    await start();
    const created = await api.post("/api/tasks", {
      data: {
        title: "Durable acceptance task",
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const task = (await created.json()) as Schema["TaskCreationResponse"];
    const home = await api.post("/api/properties", {
      data: {
        displayName: "Portable acceptance property",
        addressLine1: "10 Maple Street",
        city: "Portland",
        region: "OR",
        postalCode: "97201",
        countryCode: "US",
        propertyType: "single_family_home",
        ownerships: [{ ownerKind: "local_operator" }],
        expectedPropertyRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(home.ok(), await home.text()).toBe(true);
    const property = (await home.json()) as Schema["PropertyMutationResponse"];
    const issueResponse = await api.post("/api/maintenance-issues", {
      data: {
        propertyId: property.id,
        summary: "Portable evidence",
        description: "Retained inspection context",
        category: "plumbing",
        priority: "normal",
        reportedAtUtc: new Date(Date.now() - 60_000).toISOString(),
        reporter: { role: "manager", subjectKind: "local_operator" },
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(issueResponse.ok(), await issueResponse.text()).toBe(true);
    const issue = (await issueResponse.json()) as Schema["IssueCommandResponse"];
    const bytes = Buffer.from("Immutable portable evidence bytes");
    const uploaded = await api.post("/api/files", {
      multipart: {
        file: { name: "portable.txt", mimeType: "text/plain", buffer: bytes },
        entity_type: "maintenance_issue",
        entity_id: issue.id,
        purpose: "supporting_document",
        idempotency_key: crypto.randomUUID(),
      },
    });
    expect(uploaded.ok(), await uploaded.text()).toBe(true);
    const evidence = (await uploaded.json()) as Schema["FileUploadResponse"];
    const archived = await api.post(`/api/file-links/${evidence.links[0].id}/archive`, {
      data: {
        expectedRevision: evidence.links[0].revision,
        idempotencyKey: crypto.randomUUID(),
        confirmed: true,
        reason: "Retain contextual evidence history",
      },
    });
    expect(archived.ok(), await archived.text()).toBe(true);
    const evidenceHistory = (await (
      await api.get(`/api/files/${evidence.id}`)
    ).json()) as Schema["FileMetadataResponse"];
    const sourceImport = await api.post("/api/intake/sources/import", {
      multipart: {
        metadata: JSON.stringify({
          sourceKind: "email_message",
          channel: "email",
          body: "Portable source evidence",
          occurredAtUtc: "2026-01-02T12:00:00-05:00",
          originSystem: "local_operator",
          idempotencyKey: crypto.randomUUID(),
        }),
        attachmentRoles: JSON.stringify(["raw_source"]),
        files: { name: "retained.eml", mimeType: "message/rfc822", buffer: bytes },
      },
    });
    expect(sourceImport.ok(), await sourceImport.text()).toBe(true);
    const imported = (await sourceImport.json()) as Schema["SourceMutationResponse"];
    const sourceCorrection = await api.post(`/api/intake/sources/${imported.sourceId}/correct`, {
      data: {
        sourceKind: "email_message",
        channel: "email",
        body: "Corrected portable source evidence",
        occurredAtUtc: "2026-01-02T12:00:00-05:00",
        originSystem: "local_operator",
        correctionReason: "Preserve contextual correction history",
        expectedSourceRevision: imported.sourceRevision,
        expectedEvidenceRevisionId: imported.evidenceRevisionId,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(sourceCorrection.ok(), await sourceCorrection.text()).toBe(true);
    const corrected = (await sourceCorrection.json()) as Schema["CorrectionResponse"];
    const sourceReplacement = await api.post(`/api/intake/sources/${imported.sourceId}/supersede`, {
      data: {
        sourceKind: "email_message",
        channel: "email",
        body: "Replacement portable source evidence",
        occurredAtUtc: "2026-01-02T12:00:00-05:00",
        originSystem: "local_operator",
        expectedSourceRevision: corrected.sourceRevision,
        expectedEvidenceRevisionId: corrected.evidenceRevisionId,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(sourceReplacement.ok(), await sourceReplacement.text()).toBe(true);
    const replacement = (await sourceReplacement.json()) as Schema["SourceMutationResponse"];
    const replacementHistory = (await (
      await api.get(`/api/intake/sources/${replacement.sourceId}`)
    ).json()) as Schema["SourceDetailResponse"];
    const sourceHistory = (await (
      await api.get(`/api/intake/sources/${imported.sourceId}`)
    ).json()) as Schema["SourceDetailResponse"];
    await page.goto(`${origin}/settings`);
    await page.getByRole("radio", { name: "Dark", exact: true }).check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto(`${origin}/tasks?workflow=task.edit&target=${task.id}`);
    await page.getByLabel("Title", { exact: true }).fill("Private durable form text");
    await page.getByRole("button", { name: "Save unfinished form" }).click();
    await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
    const recoveryResponse = await api.get("/api/operator/recovery?limit=50");
    const recovery = (await recoveryResponse.json()) as Schema["RecoveryPage"];
    const form = recovery.items.find((item) => item.formKey === "task.edit")!;
    let writes = 0;
    let commandKey = "";
    let originalReceipt: Schema["TaskMutationResponse"] | undefined;
    await page.route(`**/api/tasks/${task.id}/start`, async (route) => {
      writes++;
      commandKey = (JSON.parse(route.request().postData()!) as { idempotencyKey: string })
        .idempotencyKey;
      const committed = await route.fetch();
      expect(committed.ok()).toBe(true);
      originalReceipt = (await committed.json()) as Schema["TaskMutationResponse"];
      await route.abort("failed");
    });
    // Leave the saved editor through an explicit full load, preserving its durable form.
    await page.goto(`${origin}/tasks?workflow=task.start&target=${task.id}`);
    await page.getByRole("button", { name: "Save start task", exact: true }).click();
    await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
    const attempts = (await (
      await api.get("/api/operator/recovery?limit=50")
    ).json()) as Schema["RecoveryPage"];
    const interrupted = attempts.items.find((item) => item.formKey === "task.start")!;
    expect(interrupted).toBeDefined();
    const before = (await (
      await api.get(`/api/tasks/${task.id}`)
    ).json()) as Schema["TaskResponse"];
    const bootstrap = (await (
      await api.get("/api/operator/bootstrap")
    ).json()) as Schema["BootstrapResponse"];
    await stop();
    await start();
    const restarted = (await (
      await api.get("/api/operator/bootstrap")
    ).json()) as Schema["BootstrapResponse"];
    expect(restarted.workspaceId).toBe(bootstrap.workspaceId);
    expect(restarted.runtimeEpoch).not.toBe(bootstrap.runtimeEpoch);
    await page.goto(
      `${origin}/tasks?workflow=task.start&target=${task.id}&resume=${interrupted.id}`,
    );
    await page.getByRole("button", { name: "Check original result" }).click();
    await expect(
      page.getByText("This is the original committed response.", { exact: true }),
    ).toBeVisible();
    expect(writes).toBe(1);
    await stop();
    await execute(python, ["scripts/web_acceptance_restore.py", root], { env });
    await start();
    const restored = (await (
      await api.get("/api/operator/bootstrap")
    ).json()) as Schema["BootstrapResponse"];
    expect(restored.workspaceId).toBe(bootstrap.workspaceId);
    expect(restored.runtimeEpoch).not.toBe(restarted.runtimeEpoch);
    const after = (await (await api.get(`/api/tasks/${task.id}`)).json()) as Schema["TaskResponse"];
    expect({ ...after, asOf: before.asOf }).toEqual(before);
    expect(await (await api.get(`/api/tasks/mutation-operations/${commandKey}`)).json()).toEqual(
      originalReceipt,
    );
    expect(await (await api.get(`/api/files/${evidence.id}`)).json()).toEqual(evidenceHistory);
    expect(await (await api.get(`/api/files/${evidence.id}/content`)).body()).toEqual(bytes);
    expect(await (await api.get(`/api/intake/sources/${imported.sourceId}`)).json()).toEqual(
      sourceHistory,
    );
    expect(await (await api.get(`/api/intake/sources/${replacement.sourceId}`)).json()).toEqual(
      replacementHistory,
    );
    await page.goto(`${origin}/tasks?workflow=task.edit&target=${task.id}&resume=${form.id}`);
    await expect(page.getByLabel("Title", { exact: true })).toHaveValue(
      "Private durable form text",
    );
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const browserStorage = await page.evaluate(() =>
      JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
    );
    expect(browserStorage).not.toContain("Private durable form text");
    expect(browserStorage).not.toContain("Durable acceptance task");
    const retained = (await (
      await api.get("/api/operator/recovery?limit=50")
    ).json()) as Schema["RecoveryPage"];
    expect(retained.items.find((item) => item.id === form.id)).toEqual(form);
  } finally {
    await stop();
    await api.dispose();
    await rm(root, { recursive: true, force: true });
  }
});
