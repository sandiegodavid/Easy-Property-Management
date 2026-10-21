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
          payload: { title: `Private draft ${index}` },
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
    await expect(resume).toHaveText("Resume: Create task");
    await expect(resume).toHaveAttribute("href", `/tasks?workflow=task.create&resume=${id}`);
  }
  await expect(page.getByText(/Private draft/)).toHaveCount(0);
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
});

test.describe("unfinished form presentation", () => {
  test.use({ timezoneId: "America/Los_Angeles", locale: "en-US" });

  for (const [instant, local] of [
    ["2026-01-02T07:30:00Z", "Jan 1, 2026, 11:30 PM"],
    ["2026-07-02T07:30:00Z", "Jul 2, 2026, 12:30 AM"],
  ] as const) {
    test(`saved workflows use human titles, states and local time for ${instant}`, async ({
      page,
    }) => {
      const states = [
        ["active", "Draft saved"],
        ["outcome_unknown", "Submission needs checking"],
        ["reconciled", "Submission checked"],
        ["discarded", "Discarded"],
        ["expired", "Expired"],
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
      await page.route("**/api/operator/recovery?*", (route) =>
        route.fulfill({
          json: {
            items: records,
            matchingTotal: records.length,
            nextCursor: null,
            asOf: instant,
            sourceRevision: "1",
          } satisfies components["schemas"]["RecoveryPage"],
        }),
      );
      await page.goto("/settings/recovery");
      for (const [index, [status, text]] of states.entries()) {
        const row = page.locator("#workspace-content li").filter({ hasText: text });
        await expect(
          row.getByRole("heading", { name: "Report maintenance issue", exact: true }),
        ).toBeVisible();
        await expect(row.locator("time")).toHaveText(`${local} · America/Los_Angeles`);
        await expect(row.locator("time")).toHaveAttribute("datetime", instant);
        await expect(row).not.toContainText("maintenance.issue.create");
        await expect(row).not.toContainText(instant);
        const resume = row.getByRole("link", {
          name: "Resume: Report maintenance issue",
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
    });
  }
});
