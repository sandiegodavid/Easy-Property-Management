# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: component-tests/admin-lite.spec.ts >> Admin-lite directory, add operator preservation on 409, and detail invitation flow
- Location: component-tests/admin-lite.spec.ts:84:1

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/admin/index.html", waiting until "load"

```

# Test source

```ts
  88  |     route.fulfill({
  89  |       json: { expiresAt: Date.now() + 3_600_000, csrfToken: "admin-csrf-token" },
  90  |     }),
  91  |   );
  92  |   await page.route("**/api/admin/bootstrap", (route) => route.fulfill({ json: BOOTSTRAP }));
  93  |   await page.route("**/api/admin/operators?*", (route) =>
  94  |     route.fulfill({
  95  |       json: {
  96  |         directory: {
  97  |           state: "ready",
  98  |           data: {
  99  |             items: [READY_OPERATOR],
  100 |             matching_total: 1,
  101 |             freshness: { state: "known", as_of: 1_700_000_000_000, source_revision: "registry:1" },
  102 |           },
  103 |         },
  104 |         nextCursor: null,
  105 |         actions: [{ action: "admin_create_assignment", enabled: true }],
  106 |       },
  107 |     }),
  108 |   );
  109 | 
  110 |   let createAttempts = 0;
  111 |   await page.route("**/api/admin/operators", async (route) => {
  112 |     if (route.request().method() !== "POST") return route.fallback();
  113 |     createAttempts += 1;
  114 |     expect(route.request().headers()["x-csrf-token"]).toBe("admin-csrf-token");
  115 |     if (createAttempts === 1) {
  116 |       return route.fulfill({
  117 |         status: 409,
  118 |         json: {
  119 |           code: "capacity_insufficient",
  120 |           message: "Insufficient host capacity for another Free operator workspace.",
  121 |           limitingResources: ["memory_bytes"],
  122 |         },
  123 |       });
  124 |     }
  125 |     return route.fulfill({
  126 |       status: 201,
  127 |       json: {
  128 |         operation: {
  129 |           operation_id: "00000000-0000-4000-8000-000000000799",
  130 |           kind: "create_assignment",
  131 |           idempotency_key: "key-1",
  132 |         },
  133 |         state: "pending",
  134 |         revision: 1,
  135 |         observed_at: 1_700_000_000_000,
  136 |       },
  137 |     });
  138 |   });
  139 | 
  140 |   await page.route(`**/api/admin/operators/${OPERATOR_ID}`, (route) =>
  141 |     route.fulfill({
  142 |       json: {
  143 |         operator: READY_OPERATOR,
  144 |         operatorRevision: 3,
  145 |         readiness: {
  146 |           state: "ready",
  147 |           data: {
  148 |             state: "unavailable",
  149 |             checks: [
  150 |               { name: "isolation", state: "passed", evidence_ref: "host:1" },
  151 |               { name: "schema", state: "passed", evidence_ref: "host:1" },
  152 |               { name: "routing", state: "passed", evidence_ref: "host:1" },
  153 |               { name: "protection", state: "unavailable", evidence_ref: null },
  154 |               { name: "binding", state: "passed", evidence_ref: "host:1" },
  155 |             ],
  156 |           },
  157 |         },
  158 |         refresh_operation: null,
  159 |         actions: READY_OPERATOR.actions,
  160 |       },
  161 |     }),
  162 |   );
  163 | 
  164 |   await page.route(`**/api/admin/operators/${OPERATOR_ID}/refresh`, (route) => {
  165 |     const body = route.request().postDataJSON() as { expectedRevision?: number };
  166 |     expect(body.expectedRevision).toBe(3);
  167 |     return route.fulfill({ json: { state: "succeeded" } });
  168 |   });
  169 |   await page.route(`**/api/admin/operators/${OPERATOR_ID}/invitations`, (route) => {
  170 |     const body = route.request().postDataJSON() as { expectedRevision?: number };
  171 |     expect(body.expectedRevision).toBe(3);
  172 |     return route.fulfill({
  173 |       status: 201,
  174 |       json: {
  175 |         outcome: READY_OPERATOR.operation,
  176 |         invitationId: INVITATION_ID,
  177 |         token: "one-time-claim-token",
  178 |         expiresAt: Date.now() + 86_400_000,
  179 |       },
  180 |     });
  181 |   });
  182 |   await page.route(
  183 |     `**/api/admin/operators/${OPERATOR_ID}/invitations/${INVITATION_ID}/delivered`,
  184 |     (route) => route.fulfill({ json: { invitationId: INVITATION_ID, revision: 2, state: "sent" } }),
  185 |   );
  186 | 
  187 |   await page.setViewportSize({ width: 390, height: 844 });
> 188 |   await page.goto("/admin/index.html");
      |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  189 |   await expect(page.getByRole("heading", { name: "Operators (1)" })).toBeVisible();
  190 |   await expect(page.getByText("Cedar Crest")).toBeVisible();
  191 |   await expect(page.getByText("1.25 MB / 50.00 MB")).toBeVisible();
  192 | 
  193 |   // Add operator preserves input on 409 capacity conflict, then succeeds on retry.
  194 |   await page.getByRole("button", { name: "Add operator" }).click();
  195 |   await expect(page.getByText("Free pilot (50.00 MB logical storage allowance)")).toBeVisible();
  196 |   await page.getByLabel("Display name").fill("Maple Grove");
  197 |   await page.getByLabel("Invited email").fill("maple@example.invalid");
  198 |   await page.getByLabel("Workspace slug").fill("maple-grove");
  199 |   await page.getByLabel("Support contact").fill("support@epmdemo.xyz");
  200 |   await page.getByRole("button", { name: "Create operator" }).click();
  201 | 
  202 |   await expect(page.getByRole("alert")).toContainText("memory_bytes");
  203 |   await expect(page.getByLabel("Display name")).toHaveValue("Maple Grove");
  204 | 
  205 |   await page.getByRole("button", { name: "Create operator" }).click();
  206 |   await expect(page.getByRole("heading", { name: "Operators (1)" })).toBeVisible();
  207 | 
  208 |   // Inspect operator detail, refresh source, issue one-time invitation, and mark delivered.
  209 |   await page.setViewportSize({ width: 1440, height: 900 });
  210 |   await page.getByRole("button", { name: "Inspect" }).click();
  211 |   await expect(page.getByRole("heading", { name: "Cedar Crest" })).toBeVisible();
  212 |   await expect(page.getByText("protection: unavailable", { exact: true })).toBeVisible();
  213 | 
  214 |   await page.getByRole("button", { name: "Refresh source" }).click();
  215 |   await expect(page.getByText("Source observation refreshed.")).toBeVisible();
  216 | 
  217 |   await page.getByRole("button", { name: "Issue / reissue invitation" }).click();
  218 |   await expect(
  219 |     page.getByText(`/auth/start#invitation=${INVITATION_ID}&token=one-time-claim-token`),
  220 |   ).toBeVisible();
  221 |   await page.getByRole("button", { name: "Mark delivered" }).click();
  222 |   await expect(page.getByText("Delivery confirmed.")).toBeVisible();
  223 | });
  224 | 
```