#!/usr/bin/env bash
# Build the combined backend/frontend wheel without opening an operator workspace.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: build_wheel.sh [--install-deps]

Run from any directory. Checks frontend quality/contracts, builds React, packages
Python and public assets, and verifies the resulting wheel in application/dist.

  --install-deps  Run npm ci before building (requires registry access/cache).
  --help         Show this help.

Prerequisites: Python >=3.12 with the project backend dependencies, Node >=22.13,
npm, uv, and cached Python build dependencies (the packager uses uv --offline).
Set EPM_PYTHON to an interpreter path to override environment discovery.
This builds an artifact; it does not install it or modify a workspace/config.
HELP
}

install_dependencies=false
for argument in "$@"; do
  case "$argument" in
    --install-deps) install_dependencies=true ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
  esac
done

application_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for tool in node npm uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required tool is missing from PATH: %s\n' "$tool" >&2
    exit 1
  fi
done

if [[ -n "${EPM_PYTHON:-}" ]]; then
  build_python="$EPM_PYTHON"
elif [[ -x "$application_dir/.venv/bin/python" ]]; then
  build_python="$application_dir/.venv/bin/python"
elif [[ -x "$application_dir/../.venv/easy-property-management/bin/python" ]]; then
  build_python="$application_dir/../.venv/easy-property-management/bin/python"
else
  printf 'No project Python environment found. Install dependencies and set EPM_PYTHON.\n' >&2
  exit 1
fi
# Resolve before changing directories, including a caller-relative override.
EPM_PYTHON="$("$build_python" -c 'import sys; print(sys.executable)')"
export EPM_PYTHON
cd -- "$application_dir"

"$EPM_PYTHON" -c 'import sys; sys.exit("Python >=3.12 is required.") if sys.version_info < (3, 12) else None'
node --input-type=module -e '
const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 13)) {
  console.error("Node >=22.13 is required."); process.exit(1);
}'

if [[ "$install_dependencies" == true ]]; then
  npm ci
elif [[ ! -d node_modules ]]; then
  printf 'Node dependencies are missing. Re-run with --install-deps or run npm ci.\n' >&2
  exit 1
fi

printf '\nChecking frontend quality…\n'
npm run check
printf '\nBuilding the frontend and combined Python wheel…\n'
if ! npm run package:web; then
  printf '\nBuild failed. If uv reports uncached build dependencies, run uv build --wheel once online, then retry this script.\n' >&2
  exit 1
fi

"$EPM_PYTHON" - <<'PY'
from pathlib import Path
import tomllib
from zipfile import ZipFile

project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
name = project["name"].replace("-", "_")
wheel = Path("dist") / f"{name}-{project['version']}-py3-none-any.whl"
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
    if not {"app/__main__.py", "app/web_build/index.html"} <= names:
        raise SystemExit("Wheel is missing Python entry point or compiled frontend.")
    if not any(n.startswith("app/web_build/assets/") and n.endswith(".js") for n in names):
        raise SystemExit("Wheel is missing compiled JavaScript assets.")
    bad_file = archive.testzip()
    if bad_file:
        raise SystemExit(f"Wheel integrity check failed: {bad_file}")
print(f"\nWheel ready: {wheel.resolve()}")
print("Standalone runtime still requires the checkout's schema resources; see README.")
PY
