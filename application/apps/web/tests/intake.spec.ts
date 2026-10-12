import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
const occurred = "2026-01-02T12:00:00-05:00";
async function source(request: APIRequestContext, body: string, originSystem = "local_operator") {
  const response = await request.post("/api/intake/sources", {
    data: {
      sourceKind: "operator_note",
      channel: "internal",
      body,
      occurredAtUtc: occurred,
      originSystem,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schema["SourceMutationResponse"];
}
async function input(page: Page, body: string) {
  await page.getByLabel("Body (required)", { exact: true }).fill(body);
  await page.getByLabel("Occurred at utc (required)", { exact: true }).fill(occurred);
}
async function save(page: Page, action: string) {
  await page.getByRole("button", { name: `Save ${action}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
}

test("manual source admission resumes a saved draft and reconciles a lost response once", async ({
  page,
  request,
}) => {
  await page.goto("/conversations");
  await page.getByRole("link", { name: "Retained source evidence", exact: true }).click();
  await page.getByText("Retain evidence", { exact: true }).click();
  await page.getByRole("link", { name: "Retain source", exact: true }).click();
  await input(page, "Private source testimony");
  await page.getByRole("button", { name: "Add participants entry" }).click();
  await page.getByLabel("Role (required)").fill("reporter");
  await page.getByLabel("Address", { exact: true }).fill("private@example.test");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await expect(page.getByText("Private source testimony", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Resume intake.source.admit", exact: true }).click();
  await expect(page.getByLabel("Body (required)")).toHaveValue("Private source testimony");
  let writes = 0;
  await page.route("**/api/intake/sources", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    writes++;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save retain source", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume intake.source.admit", exact: true }).click();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  await page.getByRole("link", { name: "Open current source evidence" }).click();
  await expect(page.getByRole("region", { name: "Source evidence detail" })).toContainText(
    "private@example.test",
  );
  await expect(page.getByRole("region", { name: "Source evidence detail" })).toContainText(
    occurred,
  );
  const records = await request.get("/api/intake/sources?originSystem=local_operator&limit=25");
  expect(
    ((await records.json()) as Schema["app__modules__intake__api__responses__SourcePageResponse"])
      .items,
  ).toHaveLength(1);
});

test("multipart import preserves ordered roles and rejects changed bytes after form recovery", async ({
  page,
  request,
}) => {
  await page.goto("/conversations?workflow=intake.source.import");
  await input(page, "Imported retained body");
  const files = [
    {
      name: "message.eml",
      mimeType: "message/rfc822",
      buffer: Buffer.from("Original raw message"),
    },
    { name: "photo.txt", mimeType: "text/plain", buffer: Buffer.from("Original support evidence") },
  ];
  await page.getByLabel("Source attachment files", { exact: true }).setInputFiles(files);
  await expect(page.getByLabel("Attachment 1 role")).toBeVisible();
  await page.getByLabel("Attachment 1 role").selectOption("raw_source");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume intake.source.import", exact: true }).click();
  await page
    .getByLabel("Source attachment files", { exact: true })
    .setInputFiles([{ ...files[0], buffer: Buffer.from("Changed source") }, files[1]]);
  await expect(page.getByRole("alert")).toContainText("does not match");
  await page.getByLabel("Source attachment files", { exact: true }).setInputFiles(files);
  await expect(page.getByLabel("Attachment 1 role")).toHaveValue("raw_source");
  await save(page, "import source evidence");
  await page.getByRole("link", { name: "Open current source evidence" }).click();
  await expect(page.getByRole("region", { name: "Source evidence detail" })).toContainText(
    "raw_source",
  );
  const id = new URL(page.url()).searchParams.get("source")!;
  const detail = (await (
    await request.get(`/api/intake/sources/${id}`)
  ).json()) as Schema["SourceDetailResponse"];
  expect(detail.attachments.map((entry) => entry.role)).toEqual([
    "raw_source",
    "source_attachment",
  ]);
  expect(detail.attachments.map((entry) => entry.displayOrder)).toEqual([0, 1]);
  for (const [index, entry] of detail.attachments.entries()) {
    expect(await (await request.get(`/api/files/${entry.file!.file_id}/content`)).body()).toEqual(
      files[index].buffer,
    );
  }
});

test("correction, dismissal, reopening and supersession retain source history", async ({
  page,
  request,
}) => {
  const original = await source(request, "Original evidence");
  await page.goto(`/conversations?workflow=intake.source.correct&target=${original.sourceId}`);
  await page.getByLabel("Body (required)").fill("Corrected evidence");
  await page.getByLabel("Correction reason (required)").fill("Clarify original testimony");
  await save(page, "correct source");
  await page.goto(`/conversations?workflow=intake.source.dismiss&target=${original.sourceId}`);
  await page.getByLabel("Reason (required)").fill("Reviewed without further action");
  await save(page, "dismiss source");
  await page.goto(`/conversations?workflow=intake.source.reopen&target=${original.sourceId}`);
  await page.getByLabel("Reason (required)").fill("New context needs review");
  await save(page, "reopen source");
  await page.goto(`/conversations?workflow=intake.source.supersede&target=${original.sourceId}`);
  await page.getByLabel("Body (required)").fill("Replacement evidence");
  await save(page, "supersede source");
  const detail = (await (
    await request.get(`/api/intake/sources/${original.sourceId}`)
  ).json()) as Schema["SourceDetailResponse"];
  expect(detail.technicalStatus).toBe("superseded");
  expect(detail.evidence.body).toBe("Corrected evidence");
  expect(detail.revisions).toHaveLength(2);
  await page.goto(`/conversations?intake=true&source=${original.sourceId}`);
  await expect(page.getByRole("region", { name: "Source evidence detail" })).toContainText(
    "Clarify original testimony",
  );
  await page.getByRole("link", { name: "Open replacement source" }).click();
  await expect(page.getByRole("region", { name: "Source evidence detail" })).toContainText(
    "Replacement evidence",
  );
});

test("audited detail failure withholds evidence and directory reads have no per-row fan-out", async ({
  page,
  request,
}) => {
  const first = await source(request, "Sensitive body must remain withheld");
  await source(request, "Another private source");
  const reads: string[] = [];
  page.on("request", (item) => {
    if (item.url().includes("/api/intake/sources")) reads.push(item.url());
  });
  await page.goto("/conversations?intake=true&channel=internal&hasDuplicate=false");
  await expect(page.getByText("sources on this bounded page", { exact: false })).toBeVisible();
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=25");
  expect(reads[0]).toContain("channel=internal");
  await page.route(`**/api/intake/sources/${first.sourceId}`, (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail: { code: "audit_unavailable", message: "Required sensitive-read audit failed" },
      },
    }),
  );
  await page.goto(`/conversations?intake=true&source=${first.sourceId}`);
  await expect(page.getByRole("alert")).toContainText("Evidence is withheld");
  await expect(page.getByText("Sensitive body must remain withheld", { exact: true })).toHaveCount(
    0,
  );
});

test("a stale correction preserves edits and requires review of current source evidence", async ({
  page,
  request,
}) => {
  const original = await source(request, "Initial source context");
  await page.goto(`/conversations?workflow=intake.source.correct&target=${original.sourceId}`);
  await page.getByLabel("Body (required)").fill("My retained correction");
  await page.getByLabel("Correction reason (required)").fill("My contextual reason");
  const concurrent = await request.post(`/api/intake/sources/${original.sourceId}/correct`, {
    data: {
      sourceKind: "operator_note",
      channel: "internal",
      body: "Concurrent source correction",
      occurredAtUtc: occurred,
      originSystem: "local_operator",
      correctionReason: "Another operator clarified the source",
      expectedSourceRevision: original.sourceRevision,
      expectedEvidenceRevisionId: original.evidenceRevisionId,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(concurrent.ok(), await concurrent.text()).toBe(true);
  await page.getByRole("button", { name: "Save correct source", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Body (required)")).toHaveValue("My retained correction");
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await expect(page.getByRole("region", { name: "Current source review" })).toContainText(
    "Concurrent source correction",
  );
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await save(page, "correct source");
  const current = await request.get(`/api/intake/sources/${original.sourceId}`);
  const result = (await current.json()) as Schema["SourceDetailResponse"];
  expect(result.evidence.body).toBe("My retained correction");
  expect(result.revisions).toHaveLength(3);
});

test("source directory continuation preserves filters without gaps or detail requests", async ({
  page,
  request,
}) => {
  const origin = `bounded-${crypto.randomUUID()}`;
  const expected = new Set<string>();
  for (let index = 0; index < 30; index++)
    expected.add((await source(request, `Bounded source ${index}`, origin)).sourceId);
  const reads: string[] = [];
  page.on("request", (item) => {
    if (item.url().includes("/api/intake/sources")) reads.push(item.url());
  });
  await page.goto(`/conversations?intake=true&originSystem=${origin}&channel=internal`);
  await expect(page.getByText(/^25 sources on this bounded page/)).toBeVisible();
  const first = await page
    .locator('a[href*="&source="]')
    .evaluateAll((links) =>
      links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("source")),
    );
  await page.getByRole("button", { name: "Next sources", exact: true }).click();
  await expect(page.getByText(/^5 sources on this bounded page/)).toBeVisible();
  const second = await page
    .locator('a[href*="&source="]')
    .evaluateAll((links) =>
      links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("source")),
    );
  expect(new Set([...first, ...second])).toEqual(expected);
  expect(first.length + second.length).toBe(30);
  expect(reads).toHaveLength(2);
  expect(
    reads.every(
      (url) =>
        url.includes("limit=25") &&
        url.includes(`originSystem=${origin}`) &&
        url.includes("channel=internal"),
    ),
  ).toBe(true);
});
