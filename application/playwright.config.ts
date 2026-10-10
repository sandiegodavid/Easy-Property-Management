import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    browserName: "chromium",
    baseURL: "http://127.0.0.1:18744",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node scripts/python.mjs scripts/web_smoke_server.py --port 18744 --state ready",
      url: "http://127.0.0.1:18744/openapi.json",
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command:
        "node scripts/python.mjs scripts/web_smoke_server.py --port 18745 --state unavailable",
      url: "http://127.0.0.1:18745/openapi.json",
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});
