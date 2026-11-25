import { defineConfig } from "@playwright/test";

const baseURL = process.env.EPM_SMOKE_BASE_URL ?? "http://localhost:18802";
const storageState = process.env.EPM_SMOKE_STORAGE_STATE || undefined;

export default defineConfig({
  testDir: "./apps/web/tests-hosted",
  testMatch: "operator-smoke.spec.ts",
  outputDir: "./test-results/hosted-smoke",
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    browserName: "chromium",
    baseURL,
    storageState,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
