import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test("packaged recovery route loads bounded metadata with reselection guidance", async ({
  page,
}) => {
  await page.goto("/home");
  const ids = await page.evaluate(async () => {
    const saved: string[] = [];
    for (let index = 0; index < 2; index++) {
      const id = crypto.randomUUID();
      const result = await fetch(`/api/operator/recovery/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formKey: "task.create",
          schemaVersion: 1,
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          payload: { title: `Saved task ${index}` },
        }),
      });
      if (!result.ok) throw new Error("Fixture save failed.");
      saved.push(id);
    }
    return saved;
  });
  const reads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/operator/recovery")) reads.push(request.url());
  });
  await page.goto("/settings/recovery");
  await expect(page.getByRole("heading", { name: "Unfinished forms" })).toBeVisible();
  await expect(page.getByText(/Files and credentials must be selected again/)).toBeVisible();
  for (const id of ids) {
    const resume = page.locator(`a[href*="resume=${id}"]`);
    await expect(resume).toHaveText("Continue editing: Create task");
    await expect(resume).toHaveAttribute("href", `/tasks?workflow=task.create&resume=${id}`);
  }
  await expect(page.getByRole("heading", { name: /Saved task/ })).toHaveCount(2);
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
  const card = page
    .locator("li.recovery-form-card")
    .filter({ has: page.locator(`a[href*="resume=${ids[0]}"]`) });
  page.once("dialog", (dialog) => void dialog.accept());
  await card.getByRole("button", { name: "Discard", exact: true }).click();
  await expect(page.locator(`a[href*="resume=${ids[0]}"]`)).toHaveCount(0);
  await expect(page.locator(`a[href*="resume=${ids[1]}"]`)).toBeVisible();
});

test("information review drafts have exactly one resume destination and can be discarded", async ({
  page,
}) => {
  const id = "00000000-0000-4000-8000-000000000599";
  await page.route("**/api/operator/recovery?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id,
            formKey: "coverage.review",
            status: "active",
            savedAt: "2026-01-02T07:30:00Z",
            expiresAt: "2099-01-01T00:00:00Z",
            schemaVersion: 1,
            revision: 1,
            sourceId: null,
            sourceKind: null,
            baseSourceRevision: null,
          },
        ],
        matchingTotal: 1,
        nextCursor: null,
        asOf: "2026-01-02T07:30:00Z",
        sourceRevision: "1",
      },
    }),
  );
  await page.goto("/settings/recovery");
  await expect(page.getByText("1 form", { exact: true })).toBeVisible();
  const card = page.locator(".recovery-form-card");
  await expect(card.getByRole("link")).toHaveCount(1);
  await expect(
    card.getByRole("link", { name: "Continue editing: Information review" }),
  ).toHaveAttribute("href", `/coverage/reviews/${id}`);
  await expect(card).not.toContainText("Resume from the owning workflow");
  await expect(card.getByRole("button", { name: "Discard", exact: true })).toBeVisible();
});

test.describe("unfinished form presentation", () => {
  test.use({ timezoneId: "America/Los_Angeles", locale: "en-US" });

  for (const [instant, local] of [
    ["2026-01-02T07:30:00Z", "Jan 1, 2026, 11:30 PM"],
    ["2026-07-02T07:30:00Z", "Jul 2, 2026, 12:30 AM"],
  ] as const) {
    test(`saved workflows use human titles, states and local time for ${instant}`, async ({
      page,
    }, testInfo) => {
      const states = [
        ["active", "Draft saved"],
        ["outcome_unknown", "Submission needs checking"],
      ] as const;
      const records: components["schemas"]["RecoveryMetadata"][] = states.map(([status]) => ({
        id: crypto.randomUUID(),
        formKey: "maintenance.issue.create",
        status,
        savedAt: instant,
        expiresAt: "2099-01-01T00:00:00Z",
        schemaVersion: 1,
        revision: 1,
        sourceId: null,
        sourceKind: null,
        baseSourceRevision: null,
      }));
      const terminal = (["reconciled", "discarded", "expired"] as const).map((status) => ({
        ...records[0],
        id: crypto.randomUUID(),
        status,
      }));
      await page.route("**/api/operator/recovery?*", (route) =>
        route.fulfill({
          json: {
            items: [...records, ...terminal],
            matchingTotal: records.length,
            nextCursor: null,
            asOf: instant,
            sourceRevision: "1",
          } satisfies components["schemas"]["RecoveryPage"],
        }),
      );
      await page.goto("/settings/recovery");
      await expect(page.locator(".recovery-form-card")).toHaveCount(2);
      for (const record of terminal)
        await expect(page.locator(`a[href*="resume=${record.id}"]`)).toHaveCount(0);
      for (const [index, [status, text]] of states.entries()) {
        const row = page.locator("#workspace-content li").filter({ hasText: text });
        await expect(
          row.getByRole("heading", { name: "Report maintenance issue", exact: true }),
        ).toBeVisible();
        await expect(row).toHaveClass(/recovery-form-card/);
        await expect(row.locator(".record-pill")).toHaveText(text);
        await expect(row.locator("time")).toHaveText(`${local} · America/Los_Angeles`);
        await expect(row.locator("time")).toHaveAttribute("datetime", instant);
        await expect(row).not.toContainText("maintenance.issue.create");
        await expect(row).not.toContainText(instant);
        const resume = row.getByRole("link", {
          name:
            status === "outcome_unknown"
              ? "View submission: Report maintenance issue"
              : "Continue editing: Report maintenance issue",
          exact: true,
        });
        if (status === "active" || status === "outcome_unknown") {
          await expect(resume).toHaveAttribute(
            "href",
            `/maintenance?workflow=maintenance.issue.create&resume=${records[index].id}`,
          );
        } else await expect(row.getByRole("link")).toHaveCount(0);
        await expect(
          row.getByRole("button", { name: "Check submission", exact: true }),
        ).toHaveCount(status === "outcome_unknown" ? 1 : 0);
      }
      await expect(page.locator("#workspace-content")).not.toContainText("outcome_unknown");
      for (const theme of ["light", "dark"])
        for (const width of [1280, 390]) {
          await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
          await page.setViewportSize({ width, height: 900 });
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          ).toBe(true);
          await page.screenshot({
            path: testInfo.outputPath(`unfinished-${theme}-${width}.png`),
            fullPage: true,
          });
        }
    });
  }
});
