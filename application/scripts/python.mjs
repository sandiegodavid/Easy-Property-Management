import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const result = spawnSync(
  process.env.EPM_PYTHON ?? `${root}../.venv/easy-property-management/bin/python`,
  process.argv.slice(2),
  { cwd: root, env: { ...process.env, PYTHONPATH: `${root}apps/server` }, stdio: "inherit" },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
