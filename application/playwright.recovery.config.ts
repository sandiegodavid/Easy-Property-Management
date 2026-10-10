import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/component-tests",
  testMatch: "recovery.spec.ts",
  workers: 1,
  retries: 0,
  use: { browserName: "chromium", baseURL: "http://127.0.0.1:18746", trace: "retain-on-failure" },
  webServer: [
    {
      command: "node scripts/python.mjs scripts/web_smoke_server.py --port 18744 --state ready",
      url: "http://127.0.0.1:18744/openapi.json",
      timeout: 90_000,
    },
    {
      command: "npm run dev --workspace @epm/web -- --port 18746",
      url: "http://127.0.0.1:18746",
      env: { EPM_API_TARGET: "http://127.0.0.1:18744" },
    },
  ],
});
