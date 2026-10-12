import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";

// A full acceptance run gives each workflow suite a fresh disposable workspace.
// Saved forms intentionally survive within a suite; unrelated suites must not
// exhaust the product's bounded recovery capacity or share preference/clock state.
const requested = process.argv.slice(2);
const suites = requested.length
  ? [requested]
  : readdirSync("apps/web/tests")
      .filter((name) => name.endsWith(".spec.ts"))
      .sort()
      .map((name) => [`apps/web/tests/${name}`]);
for (const suite of suites) {
  const result = spawnSync(
    process.execPath,
    ["node_modules/@playwright/test/cli.js", "test", ...suite],
    {
      stdio: "inherit",
      env: process.env,
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
