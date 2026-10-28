import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/tests-admin",
  outputDir: "./test-results/admin",
  workers: 1,
  retries: 0,
  use: {
    browserName: "chromium",
    baseURL: "http://epm-admin.localhost:18756",
    // Sign-in credentials and cookies must never be recorded into traces.
    trace: "off",
    launchOptions: {
      args: ["--host-resolver-rules=MAP epm-admin.localhost 127.0.0.1"],
    },
  },
  webServer: {
    command: "node scripts/python.mjs scripts/admin_browser_server.py --port 18756",
    url: "http://127.0.0.1:18756/",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
