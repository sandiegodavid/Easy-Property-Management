import { defineConfig } from "@playwright/test";

// Runs the demo-workspace suites in apps/web/tests-demo against a manually
// started demo server (see application/demo/README.md):
//
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// then: npx playwright test --config playwright.demo.config.ts
//
// No webServer is defined on purpose: the demo workspace is seeded once and
// reused across runs, so the server must already be running on port 8001.
export default defineConfig({
  testDir: "./apps/web/tests-demo",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    browserName: "chromium",
    baseURL: "http://127.0.0.1:8001",
    trace: "retain-on-failure",
  },
});
