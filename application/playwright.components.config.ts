import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./apps/web/component-tests",
  use: { browserName: "chromium", baseURL: "http://127.0.0.1:18746" },
  webServer: {
    command: "npm run dev --workspace @epm/web -- --port 18746",
    url: "http://127.0.0.1:18746",
    reuseExistingServer: false,
  },
});
