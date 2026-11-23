# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: component-tests/hosted-settings.spec.ts >> hosted mode reports unavailable storage usage honestly without fabricating zero bytes
- Location: component-tests/hosted-settings.spec.ts:77:1

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/component-tests/hosted-settings.html?mode=hosted", waiting until "load"

```

# Test source

```ts
  2   | 
  3   | const fixture = "/component-tests/hosted-settings.html";
  4   | 
  5   | const READY_SETTINGS = {
  6   |   surface: "operator_settings",
  7   |   delivery_owner: "H04",
  8   |   scope: {
  9   |     kind: "workspace",
  10  |     operator_id: "11111111-1111-4111-8111-111111111111",
  11  |     workspace_id: "22222222-2222-4222-8222-222222222222",
  12  |   },
  13  |   usage: {
  14  |     state: "ready",
  15  |     data: {
  16  |       plan: "free",
  17  |       usable_bytes: 50_000_000,
  18  |       used_bytes: 12_500_000,
  19  |     },
  20  |     freshness: {
  21  |       state: "known",
  22  |       as_of: 1795377600000,
  23  |       source_revision: "usage:1",
  24  |     },
  25  |   },
  26  |   protection: {
  27  |     state: "unavailable",
  28  |     data: null,
  29  |     freshness: {
  30  |       state: "unavailable",
  31  |       error_code: "backup_protection_unavailable",
  32  |     },
  33  |   },
  34  |   support_contact: "pilot-support@example.com",
  35  |   maintenance: {
  36  |     state: "unavailable",
  37  |     data: null,
  38  |     freshness: {
  39  |       state: "unavailable",
  40  |       error_code: "no_announced_maintenance",
  41  |     },
  42  |   },
  43  |   actions: [{ action: "operator_read_settings", enabled: true }],
  44  |   usageBreakdown: {
  45  |     committedDbBytes: 2_500_000,
  46  |     retainedFileBytes: 10_000_000,
  47  |     reservedBytes: 0,
  48  |     remainingBytes: 37_500_000,
  49  |     measurementVersion: "logical-v1",
  50  |   },
  51  | };
  52  | 
  53  | test("hosted mode displays Free pilot plan, usage, unavailable protection, support contact, and zero upgrade controls", async ({
  54  |   page,
  55  | }) => {
  56  |   await page.route("**/api/hosted/settings", (route) => route.fulfill({ json: READY_SETTINGS }));
  57  | 
  58  |   await page.goto(`${fixture}?mode=hosted`);
  59  | 
  60  |   await expect(page.getByRole("heading", { name: "Workspace plan and storage" })).toBeVisible();
  61  |   await expect(page.getByText("Free pilot (50.00 MB logical storage)")).toBeVisible();
  62  |   await expect(page.getByRole("progressbar", { name: "Free pilot storage usage" })).toBeVisible();
  63  |   await expect(
  64  |     page.getByText("12.50 MB of 50.00 MB used (25%) — 37.50 MB remaining."),
  65  |   ).toBeVisible();
  66  |   await expect(page.getByText("Database: 2.50 MB · Retained files: 10.00 MB")).toBeVisible();
  67  |   await expect(page.getByText("Observed at 2026-11-22T20:00:00.000Z")).toBeVisible();
  68  |   await expect(page.getByText("Unavailable — backup protection is not yet active.")).toBeVisible();
  69  |   await expect(page.getByText("pilot-support@example.com")).toBeVisible();
  70  | 
  71  |   // Explicit exclusions: zero paid-upgrade, billing, plan-change, or idle-wake controls.
  72  |   const bodyText = (await page.locator("body").textContent()) ?? "";
  73  |   expect(bodyText).not.toMatch(/upgrade|billing|paid plan|change plan|schedule maintenance|wake/i);
  74  |   await expect(page.getByText("Maintenance notice")).toHaveCount(0);
  75  | });
  76  | 
  77  | test("hosted mode reports unavailable storage usage honestly without fabricating zero bytes", async ({
  78  |   page,
  79  | }) => {
  80  |   await page.route("**/api/hosted/settings", (route) =>
  81  |     route.fulfill({
  82  |       json: {
  83  |         ...READY_SETTINGS,
  84  |         usage: {
  85  |           state: "unavailable",
  86  |           data: null,
  87  |           freshness: { state: "unavailable", error_code: "usage_state_unreadable" },
  88  |         },
  89  |         protection: {
  90  |           state: "ready",
  91  |           data: { status: "degraded", last_verified_at: 1795377600000 },
  92  |         },
  93  |         usageBreakdown: null,
  94  |         maintenance: {
  95  |           state: "ready",
  96  |           data: { message: "Planned maintenance Sunday 02:00 UTC." },
  97  |         },
  98  |       },
  99  |     }),
  100 |   );
  101 | 
> 102 |   await page.goto(`${fixture}?mode=hosted`);
      |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  103 | 
  104 |   await expect(page.getByText("Unavailable (usage_state_unreadable).")).toBeVisible();
  105 |   await expect(
  106 |     page.getByText("Degraded — latest verified point: 2026-11-22T20:00:00.000Z"),
  107 |   ).toBeVisible();
  108 |   await expect(page.getByRole("progressbar")).toHaveCount(0);
  109 |   await expect(page.getByText("Planned maintenance Sunday 02:00 UTC.")).toBeVisible();
  110 | });
  111 | 
  112 | test("local mode does not render HostedSettings or call /api/hosted/settings", async ({ page }) => {
  113 |   let settingsCalls = 0;
  114 |   await page.route("**/api/hosted/settings", async (route) => {
  115 |     settingsCalls += 1;
  116 |     await route.fulfill({ json: READY_SETTINGS });
  117 |   });
  118 | 
  119 |   await page.goto(`${fixture}?mode=local`);
  120 | 
  121 |   await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  122 |   await expect(page.getByRole("heading", { name: "Workspace plan and storage" })).toHaveCount(0);
  123 |   expect(settingsCalls).toBe(0);
  124 | });
  125 | 
  126 | test("507 hosted_storage_quota_exceeded preserves form input as a definite rejection", async ({
  127 |   page,
  128 | }) => {
  129 |   await page.route("**/api/hosted/settings", (route) => route.fulfill({ json: READY_SETTINGS }));
  130 |   await page.route("**/api/properties", (route) =>
  131 |     route.fulfill({
  132 |       status: 507,
  133 |       json: {
  134 |         detail: {
  135 |           code: "hosted_storage_quota_exceeded",
  136 |           message:
  137 |             "Workspace storage limit (50 MB Free pilot) reached. Remove files or contact pilot-support@example.com.",
  138 |         },
  139 |       },
  140 |     }),
  141 |   );
  142 | 
  143 |   await page.goto(`${fixture}?mode=hosted`);
  144 |   const input = page.getByLabel("Property name");
  145 |   await input.fill("123 Oak Street");
  146 |   await page.getByRole("button", { name: "Save property" }).click();
  147 | 
  148 |   await expect(page.getByRole("alert")).toContainText("50 MB Free pilot");
  149 |   await expect(page.getByTestId("outcome-flag")).toHaveText("definite");
  150 |   await expect(input).toHaveValue("123 Oak Street");
  151 | });
  152 | 
```