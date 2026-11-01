import { expect, test } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
const handoffId = "00000000-0000-4000-8000-000000000001";
const reportId = "00000000-0000-4000-8000-000000000002";

test("recovery checklist survives reload and explicit completion keeps its original attempt", async ({
  page,
  request,
}) => {
  await page.clock.install();
  await request.post("http://127.0.0.1:18756/__test/restore", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const issued = await request.post("http://127.0.0.1:18756/__test/issue", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const { credential } = (await issued.json()) as { credential: string };
  let active = false;
  let revision = 1;
  let recoveryState = "verified";
  let completion: string | null = null;
  let commands = 0;
  const now = Date.now() / 1000;
  await page.route("**/admin-api/operators/b/source-status", (route) =>
    route.fulfill({
      json: {
        admin_revision: revision,
        binding_revision: 1,
        admin_fence: 0,
        generation: 0,
        active,
        identity_approved: true,
        binding_matches_configuration: true,
        enrollments: [],
      },
    }),
  );
  await page.route("**/admin-api/operators/b/recovery-handoff", (route) =>
    route.fulfill({
      json: {
        id: handoffId,
        expected_revision: revision,
        state: recoveryState,
        binding: {
          workspace_id: "00000000-0000-4000-8000-000000000003",
          binding_revision: 1,
          subject: "verified-operator-subject",
          configuration_digest: "a".repeat(64),
          release: "qualified-release",
        },
        completion,
        private_command: `sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py verify-onboarding --handoff ${handoffId}`,
        report: {
          id: reportId,
          observed: now,
          expires: now + 86400,
          snapshot_marker: "verified-snapshot",
          completed: { readback: now },
          readback: true,
        },
      },
    }),
  );
  await page.route("**/reauthenticate", (route) => route.fulfill({ json: { authorized: true } }));
  await page.route("**/commands", async (route) => {
    commands++;
    const value = route.request().postDataJSON() as {
      command: { operation_id: string; action: string; evidence_id: string; acceptance_id: string };
    };
    expect(value.command.action).toBe(commands === 1 ? "complete_onboarding" : "enable");
    expect(value.command.evidence_id).toBe(reportId);
    expect(value.command.acceptance_id).toBe(reportId);
    completion ??= value.command.operation_id;
    active = true;
    revision++;
    await route.fulfill({ json: { active: true } });
  });
  await page.goto("/operators/b");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const panel = page.getByRole("region", { name: "Access and onboarding controls" });
  await expect(panel.getByRole("heading", { name: "Verify onboarding recovery" })).toBeVisible();
  await expect(panel.locator("pre").first()).toContainText(handoffId);
  await expect(panel).toContainText("verified-operator-subject");
  await expect(panel).toContainText("qualified-release");
  await page.reload();
  await expect(panel.locator("pre").first()).toContainText(handoffId);
  const actions = panel.getByRole("combobox", { name: "Action", exact: true });
  await expect(actions.locator('option[value="enable"]')).toHaveCount(0);
  await expect(actions.locator('option[value="complete_onboarding"]')).toBeEnabled();
  await panel
    .getByRole("combobox", { name: "Action", exact: true })
    .selectOption("complete_onboarding");
  await panel.getByLabel("Reason", { exact: true }).fill("Verified exact current binding");
  await panel.getByRole("checkbox").check();
  await panel.getByLabel("One-use action credential").fill("synthetic-action-grant");
  await panel.getByRole("button", { name: "Authorize reviewed change" }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Action authorized" })).toBeFocused();
  await panel.getByRole("button", { name: "Confirm access change" }).click();
  await expect(panel.getByRole("link", { name: "Check original operation" })).toHaveAttribute(
    "href",
    `/operations/${completion}`,
  );
  await expect(panel.getByRole("button", { name: "Confirm access change" })).toBeDisabled();
  expect(commands).toBe(1);
  await page.clock.runFor(6000);
  await expect(panel.getByRole("link", { name: "Check original operation" })).toHaveAttribute(
    "href",
    `/operations/${completion}`,
  );
  await expect(panel.getByRole("button", { name: "Confirm access change" })).toBeDisabled();
  await page.reload();
  await expect(panel.getByRole("heading", { name: "Onboarding complete" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Copy ready-to-use instructions" })).toBeVisible();
  // A disabled, completed binding offers re-enable, but only with current proof.
  active = false;
  revision++;
  recoveryState = "stale";
  await page.reload();
  await expect(actions.locator('option[value="enable"]')).toHaveJSProperty("disabled", true);
  await expect(actions.locator('option[value="complete_onboarding"]')).toHaveCount(0);
  recoveryState = "verified";
  await page.reload();
  await expect(actions.locator('option[value="enable"]')).toBeEnabled();
  await actions.selectOption("enable");
  await panel.getByLabel("Reason", { exact: true }).fill("Re-enable the completed binding");
  await panel.getByRole("checkbox").check();
  await panel.getByLabel("One-use action credential").fill("synthetic-action-grant");
  await panel.getByRole("button", { name: "Authorize reviewed change" }).click();
  await panel.getByRole("button", { name: "Confirm access change" }).click();
  await expect(panel.getByRole("link", { name: "Check original operation" })).toBeVisible();
  expect(commands).toBe(2);
  // Renewal or replacement installs a binding without a completion.
  active = false;
  revision++;
  completion = null;
  await page.reload();
  await expect(actions.locator('option[value="enable"]')).toHaveCount(0);
  await expect(actions.locator('option[value="complete_onboarding"]')).toBeEnabled();
});
