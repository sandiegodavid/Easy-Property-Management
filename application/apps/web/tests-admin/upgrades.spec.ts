import { expect, test } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
const target = {
  release: "release-20261101-01",
  digest: "a".repeat(64),
  installed: 1,
  notes: "Routine compatible release",
  eligible: true,
  blockers: [],
  preserve_sessions: true,
  compatibility_digest: "b".repeat(64),
};
const steps = [
  "revalidate",
  "pause",
  "stop",
  "recovery",
  "validate",
  "switch",
  "start",
  "verify",
  "accept",
];

test("installed-release upgrade checks readiness, retains lost submission and explicitly accepts", async ({
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
  let operationId = "";
  let kind = "upgrade_check";
  let state = "succeeded";
  let writes = 0;
  const accepted: string[] = [];
  let lostStart = true;
  function view() {
    const kinds = kind === "upgrade_check" ? ["readiness"] : steps;
    return {
      operation: {
        id: operationId,
        target: "b",
        kind,
        state,
        revision: 2,
        cancel_requested: 0,
        error: null,
        created: 100,
        updated: 101,
        result: null,
        steps: kinds.map((name, index) => ({
          kind: name,
          sequence: index,
          state: name === "accept" && state !== "succeeded" ? "intent" : "verified",
          reference: null,
          checked: 100,
        })),
      },
      original_release: "release-20261031-01",
      target,
      workspace_id: "00000000-0000-4000-8000-000000000001",
      session_handling: "preserve",
      evidence: [],
    };
  }
  await page.route("**/admin-api/operators/b", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            key: "b",
            name: "Operator B",
            email: "b@example.com",
            release: "release-20261031-01",
            registered_revision: 1,
          },
        ],
      },
    }),
  );
  await page.route("**/admin-api/operators/b/upgrade-options", (route) =>
    route.fulfill({
      json: {
        items: [
          target,
          {
            ...target,
            release: "release-20261102-01",
            eligible: false,
            blockers: ["Release qualification required."],
          },
        ],
      },
    }),
  );
  await page.route("**/admin-api/upgrades/*", (route) => route.fulfill({ json: view() }));
  await page.route("**/admin-api/upgrade-commands/*", (route) =>
    route.fulfill({ json: { found: true, operation: view() } }),
  );
  await page.route("**/upgrade-command", async (route) => {
    const body = route.request().postDataJSON() as {
      upgrade: { id: string; action: string; session_handling?: string; restore_access?: boolean };
      credential: string;
    };
    writes++;
    if (body.upgrade.action === "check") operationId = body.upgrade.id;
    if (body.upgrade.action === "start") {
      expect(body.upgrade.session_handling).toBe("preserve");
      expect(body.credential).toBe("private-start-grant");
      operationId = body.upgrade.id;
      kind = "upgrade";
      state = "waiting";
      if (lostStart) {
        lostStart = false;
        await route.abort();
        return;
      }
    }
    if (body.upgrade.action === "accept") {
      expect(body.upgrade.restore_access).toBe(true);
      accepted.push(body.upgrade.id);
      state = "succeeded";
    }
    await route.fulfill({ json: { id: operationId, revision: 1, state: "queued" } });
  });
  await page.goto("/operators/b/upgrade");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Upgrade operator" })).toBeVisible();
  await expect(page.getByText("Release qualification required.")).toBeVisible();
  await page.getByLabel("Target release").selectOption(target.release);
  await page.getByRole("button", { name: "Check readiness", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Prepare the interruption" })).toBeVisible();
  await expect(page.getByLabel("Session handling")).toHaveValue("preserve");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Review decision" }).click();
  await page.getByLabel("Action credential").fill("private-start-grant");
  await page.getByRole("button", { name: "Start upgrade", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original submission" })).toBeVisible();
  expect(writes).toBe(2);
  await page.getByRole("button", { name: "Check original submission" }).click();
  await expect(page.getByText("The selected release is running.", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "Verified upgrade checkpoints" }),
  ).toHaveAttribute("value", "8");
  await page.reload();
  expect(writes).toBe(2);
  await page.getByLabel("Restore access if the original authorization is still valid").check();
  await page.getByLabel("I reviewed the current result and access consequences.").check();
  await page.getByRole("button", { name: "Review decision" }).click();
  await page.getByLabel("Action credential").fill("private-accept-grant");
  await page
    .getByRole("button", { name: "Accept upgrade and restore access", exact: true })
    .click();
  await expect(page.getByText("Release acceptance completed.", { exact: false })).toBeVisible();
  expect(writes).toBe(3);
  expect(accepted).toHaveLength(1);
});

test("unqualified releases stay blocked and failed readiness requires remediation before a reviewed revoke-only upgrade", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await request.post("http://127.0.0.1:18756/__test/restore", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const issued = await request.post("http://127.0.0.1:18756/__test/issue", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const { credential } = (await issued.json()) as { credential: string };
  let state = "failed";
  let writes = 0;
  await page.route("**/admin-api/operators/b", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            key: "b",
            name: "Operator B",
            email: "b@example.com",
            release: "release-20261031-01",
            registered_revision: 1,
          },
        ],
      },
    }),
  );
  await page.route("**/admin-api/operators/b/upgrade-options", (route) =>
    route.fulfill({
      json: {
        items: [
          { ...target, preserve_sessions: false },
          {
            ...target,
            release: "release-20261102-01",
            eligible: false,
            blockers: ["Release qualification required."],
          },
        ],
      },
    }),
  );
  const operationId = "00000000-0000-4000-8000-000000000071";
  await page.route("**/admin-api/upgrades/*", (route) =>
    route.fulfill({
      json: {
        operation: {
          id: operationId,
          target: "b",
          kind: "upgrade_check",
          state,
          revision: 2,
          cancel_requested: 0,
          error: state === "failed" ? "admin_effect_conflict" : null,
          created: 100,
          updated: 101,
          result: null,
          steps: [
            {
              sequence: 0,
              kind: "readiness",
              state: state === "failed" ? "intent" : "verified",
              reference: null,
              checked: 100,
            },
          ],
        },
        target: { ...target, preserve_sessions: false },
        original_release: "release-20261031-01",
        workspace_id: null,
        session_handling: null,
        evidence: [],
      },
    }),
  );
  await page.route("**/upgrade-command", (route) => {
    writes++;
    return route.fulfill({ json: { id: operationId, revision: 1, state: "queued" } });
  });
  await page.goto("/operators/b/upgrade");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("option", { name: "release-20261102-01 — Unavailable" }),
  ).toHaveAttribute("disabled");
  await page.getByLabel("Target release").selectOption(target.release);
  await page.getByRole("button", { name: "Check readiness", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Private administrator step required");
  await expect(page.getByRole("button", { name: "Start upgrade", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Resume upgrade" })).toBeDisabled();
  expect(writes).toBe(1);
  state = "succeeded";
  await page.reload();
  await expect(page.getByLabel("Session handling")).toHaveValue("revoke");
  await expect(page.getByRole("option", { name: "Keep valid sessions" })).toHaveAttribute(
    "disabled",
  );
  await page.getByLabel("I agreed a maintenance window and reviewed the interruption.").check();
  await page.getByRole("button", { name: "Review decision" }).click();
  await expect(page.getByLabel("Action credential")).toHaveValue("");
  await expect(page.getByRole("button", { name: "Start upgrade", exact: true })).toBeDisabled();
  expect(writes).toBe(1);
});
