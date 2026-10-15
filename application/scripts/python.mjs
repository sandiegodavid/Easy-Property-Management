import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const python =
  process.env.EPM_PYTHON ??
  (existsSync(`${root}.venv/bin/python`)
    ? `${root}.venv/bin/python`
    : `${root}../.venv/easy-property-management/bin/python`);
const result = spawnSync(python, process.argv.slice(2), {
  cwd: root,
  env: { ...process.env, PYTHONPATH: `${root}apps/server` },
  stdio: "inherit",
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
