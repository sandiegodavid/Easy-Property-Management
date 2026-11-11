import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/hosted-status-tests",
  workers: 1,
  retries: 0,
  use: { browserName: "chromium", baseURL: "http://127.0.0.1:18753" },
  webServer: {
    command: "node scripts/python.mjs scripts/hosted_status_smoke_server.py",
    url: "http://127.0.0.1:18753/health/live",
    reuseExistingServer: false,
  },
});
