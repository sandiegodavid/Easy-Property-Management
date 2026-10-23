import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/tests-hosted",
  // Use the established generated-output directory; run browser suites serially.
  outputDir: "./test-results/hosted",
  workers: 1,
  retries: 0,
  projects: [
    { name: "operator", testMatch: "session.spec.ts" },
    {
      name: "read-only",
      testMatch: "read-only.spec.ts",
      use: {
        baseURL: "https://demo-b.epm.test",
      },
    },
  ],
  use: {
    browserName: "chromium",
    baseURL: "https://demo.epm.test",
    ignoreHTTPSErrors: true,
    launchOptions: {
      args: [
        "--host-resolver-rules=MAP demo.epm.test:443 127.0.0.1:18748, MAP demo-b.epm.test:443 127.0.0.1:18749",
      ],
    },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node scripts/python.mjs scripts/hosted_browser_server.py --port 18748",
      url: "https://127.0.0.1:18748/sign-in",
      // Readiness is a 403: the product correctly rejects this IP Host.
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: "node scripts/python.mjs scripts/hosted_browser_server.py --port 18749 --read-only",
      url: "https://127.0.0.1:18749/sign-in",
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});
