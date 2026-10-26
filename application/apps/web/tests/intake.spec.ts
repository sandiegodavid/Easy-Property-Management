import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test("imported messages show named source participants and preserve plain text in both revisions", async ({
  page,
  request,
}, testInfo) => {
  const response = await request.post("/api/intake/sources", {
    data: {
      sourceKind: "email_message",
      channel: "email",
      subject: "Reported water leak",
      body: "Line_one\nLine_two",
      occurredAtUtc: occurred,
      originSystem: "local_operator",
      participants: [
        { role: "sender", display: "Taylor Example", address: "taylor@example.test" },
        { role: "recipient", address: "owner@example.test" },
        { role: "observer" },
      ],
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const created = (await response.json()) as Schema["SourceMutationResponse"];
  await page.goto(`/conversations?intake=true&source=${created.sourceId}`);
  const current = page.getByRole("article", { name: "Imported evidence", exact: true });
  await expect(
    current.getByRole("heading", { name: "Reported water leak", exact: true }),
  ).toBeVisible();
  await expect(current.locator(".imported-message-participants strong")).toHaveText([
    "Taylor Example",
    "owner@example.test",
    "Participant name not supplied",
  ]);
  await expect(current.locator(".imported-message-body p")).toHaveText("Line_one\nLine_two");
  await expect(current.locator("dd")).not.toContainText(["Line_one"]);
  await page.getByRole("button", { name: "Read retained revision 1", exact: true }).click();
  const historical = page.getByRole("article", {
    name: "Historical imported evidence",
    exact: true,
  });
  await expect(historical.locator(".imported-message-body p")).toHaveText("Line_one\nLine_two");
  await expect(historical.locator(".imported-message-participants strong")).toHaveText([
    "Taylor Example",
    "owner@example.test",
    "Participant name not supplied",
  ]);
  for (const theme of ["light", "dark"])
    for (const width of [1280, 390]) {
      await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: testInfo.outputPath(`intake-message-${theme}-${width}.png`),
        fullPage: true,
      });
    }
});
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
  await test.step(action, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  if (await page.locator(".saved-item").count()) return;
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
}

test("manual source admission resumes a saved draft and reconciles a lost response once", async ({
  page,
  request,
}) => {
  const originSystem = `recovery-test-${crypto.randomUUID()}`;
  await page.goto("/conversations");
  await page.getByRole("link", { name: "Retained sources", exact: true }).click();
  await expect(page.getByRole("region", { name: "Retained sources", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Retained sources", exact: true })).toBeVisible();
  await page.getByText("Retain evidence", { exact: true }).click();
  await page.getByRole("link", { name: "Retain source", exact: true }).click();
  await input(page, "Private source testimony");
  await page.getByLabel("Origin system (required)", { exact: true }).fill(originSystem);
  await page.getByRole("button", { name: "Add participants entry" }).click();
  await page.getByLabel("Role (required)").fill("reporter");
  await page.getByLabel("Address", { exact: true }).fill("private@example.test");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  await page.goto("/settings/recovery");
  await expect(page.getByText("Private source testimony", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Continue editing: Retain source", exact: true }).click();
  await expect(page.getByLabel("Body (required)")).toHaveValue("Private source testimony");
  await expect(page.getByLabel("Origin system (required)", { exact: true })).toHaveValue(
    originSystem,
  );
  let writes = 0;
  await page.route("**/api/intake/sources", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    writes++;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Retain source", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check submission" })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "View submission: Retain source", exact: true }).click();
  await page.getByRole("button", { name: "Check submission" }).click();
  await expect(page.locator(".saved-item")).toBeVisible();
  expect(writes).toBe(1);
  await page.getByRole("link", { name: "Back to retained source", exact: true }).click();
  await expect(page.getByRole("region", { name: "Retained source detail" })).toContainText(
    "private@example.test",
  );
  await expect(page.getByRole("region", { name: "Retained source detail" })).toContainText(
    occurred,
  );
  const sourceId = new URL(page.url()).searchParams.get("source");
  expect(sourceId).toBeTruthy();
  const records = await request.get(`/api/intake/sources?originSystem=${originSystem}&limit=25`);
  expect(records.ok(), await records.text()).toBe(true);
  const retained =
    (await records.json()) as Schema["app__modules__intake__api__responses__SourcePageResponse"];
  expect(retained.items.map((item) => item.sourceId)).toEqual([sourceId]);
  expect(retained.nextCursor).toBeNull();
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
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  await page.goto("/settings/recovery");
  await page
    .getByRole("link", { name: "Continue editing: Import source evidence", exact: true })
    .click();
  await page
    .getByLabel("Source attachment files", { exact: true })
    .setInputFiles([{ ...files[0], buffer: Buffer.from("Changed source") }, files[1]]);
  await expect(page.getByRole("alert")).toContainText("does not match");
  await page.getByLabel("Source attachment files", { exact: true }).setInputFiles(files);
  await expect(page.getByLabel("Attachment 1 role")).toHaveValue("raw_source");
  await save(page, "import source evidence");
  await page.getByRole("link", { name: "Back to retained source", exact: true }).click();
  await expect(page.getByRole("region", { name: "Retained source detail" })).toContainText(
    "Raw source",
  );
  const attachments = page.getByRole("region", { name: "Evidence attachments", exact: true });
  await expect(attachments).not.toContainText("raw_source");
  await expect(attachments).toContainText("Source attachment");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
  }
  const id = new URL(page.url()).searchParams.get("source")!;
  const detail = (await (
    await request.get(`/api/intake/sources/${id}`)
  ).json()) as Schema["SourceDetailResponse"];
  const hash = detail.attachments[0].file!.content_sha256;
  await expect(attachments.getByText(hash, { exact: true })).not.toBeVisible();
  await attachments.getByText("File verification details", { exact: true }).first().click();
  await expect(attachments.getByText(hash, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Read retained revision 1", exact: true }).click();
  const historicalAttachments = page.getByRole("region", {
    name: "Historical evidence attachments",
    exact: true,
  });
  await expect(historicalAttachments.getByText(hash, { exact: true })).not.toBeVisible();
  await historicalAttachments
    .getByText("File verification details", { exact: true })
    .first()
    .click();
  await expect(historicalAttachments.getByText(hash, { exact: true })).toBeVisible();
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
  const evidence = page.getByRole("region", { name: "Retained source detail", exact: true });
  await expect(evidence).not.toContainText(original.sourceId);
  await expect(evidence).toContainText("Superseded");
  await expect(page.getByRole("region", { name: "Retained source detail" })).toContainText(
    "Clarify original testimony",
  );
  await page.getByRole("button", { name: "Read retained revision 1", exact: true }).click();
  const historical = page.getByRole("region", { name: "Selected retained evidence revision" });
  await expect(historical).toContainText("Original evidence");
  await expect(historical).not.toContainText("Corrected evidence");
  await page.getByRole("button", { name: "Read retained revision 2", exact: true }).click();
  await expect(historical).toContainText("Corrected evidence");
  await page.route(
    `**/api/intake/sources/${original.sourceId}/revisions/${original.evidenceRevisionId}`,
    (route) =>
      route.fulfill({
        status: 503,
        json: { detail: { code: "audit_unavailable", message: "Required revision audit failed" } },
      }),
  );
  await page.getByRole("button", { name: "Read retained revision 1", exact: true }).click();
  await expect(historical).toContainText("Revision evidence is withheld");
  await expect(historical).not.toContainText("Original evidence");
  await page.getByRole("link", { name: "Open replacement source" }).click();
  await expect(page.getByRole("region", { name: "Retained source detail" })).toContainText(
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
  await expect(page.getByText(/retained sources? on this page/)).toBeVisible();
  const rows = page.locator(".work-directory-card");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).not.toContainText("Source id");
  await expect(rows.first()).not.toContainText("Source revision");
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
  await page.getByRole("button", { name: "Save source correction", exact: true }).click();
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

test("retention does not create conversations; explicit source links preserve independent history", async ({
  request,
  page,
}) => {
  const before = (await (
    await request.get("/api/communications?limit=100")
  ).json()) as Schema["CommunicationPage"];
  const original = await source(request, "Independent retained source");
  const after = (await (
    await request.get("/api/communications?limit=100")
  ).json()) as Schema["CommunicationPage"];
  expect(after.items.map((item) => item.id)).toEqual(before.items.map((item) => item.id));
  const partyResponse = await request.post("/api/parties", {
    data: {
      partyKind: "individual",
      displayName: "Intake source reporter",
      contacts: [],
      confirmedNewParty: true,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(partyResponse.ok(), await partyResponse.text()).toBe(true);
  const party = (await partyResponse.json()) as { id: string };
  const response = await request.post("/api/communications", {
    data: {
      direction: "inbound",
      channel: "email",
      subject: "Explicit retained-source conversation",
      body: "Operator recorded discussion, not copied source",
      occurredAtUtc: occurred,
      occurredTimezone: "America/Los_Angeles",
      record: true,
      participants: [{ partyId: party.id, role: "sender" }],
      links: [{ entityType: "intake_source", entityId: original.sourceId }],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const conversation = (await response.json()) as Schema["CommunicationReceiptResponse"];
  const replacement = await request.post(`/api/intake/sources/${original.sourceId}/supersede`, {
    data: {
      sourceKind: "operator_note",
      channel: "internal",
      body: "Correct source identity",
      occurredAtUtc: occurred,
      originSystem: "local_operator",
      expectedSourceRevision: original.sourceRevision,
      expectedEvidenceRevisionId: original.evidenceRevisionId,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(replacement.ok(), await replacement.text()).toBe(true);
  const successor = (await replacement.json()) as Schema["SourceMutationResponse"];
  const current = (await (
    await request.get(`/api/communications/${conversation.id}`)
  ).json()) as Schema["CommunicationResponse"];
  expect(current.body).toBe(conversation.body);
  expect(current.revision).toBe(conversation.revision);
  expect(current.links[0].entityId).toBe(original.sourceId);
  expect(current.links[0].context).toMatchObject({
    technicalStatus: "superseded",
    isCurrent: false,
    supersededBySourceId: successor.sourceId,
  });
  await page.goto(`/conversations?record=communication&id=${conversation.id}`);
  await expect(
    page.getByText("Operator recorded discussion, not copied source", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("superseded", { exact: true })).toBeVisible();
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
  await expect(page.getByText(/^25 retained sources on this page/)).toBeVisible();
  const first = await page
    .locator('a[href*="&source="]')
    .evaluateAll((links) =>
      links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("source")),
    );
  await page.getByRole("button", { name: "Next sources", exact: true }).click();
  await expect(page.getByText(/^5 retained sources on this page/)).toBeVisible();
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
