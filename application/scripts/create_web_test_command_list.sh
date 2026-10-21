#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: create_web_test_command_list.sh OUTPUT_FILE

Create a file containing one `npm run test:web` command for each
apps/web/tests/*.spec.ts file, sorted alphabetically by filename.
OUTPUT_FILE is resolved from the current directory and must not already exist.
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

output_file="$1"
if [[ -e "$output_file" ]]; then
  printf 'Output file already exists: %s\n' "$output_file" >&2
  exit 1
fi
if [[ ! -d "$(dirname -- "$output_file")" ]]; then
  printf 'Output directory does not exist: %s\n' "$(dirname -- "$output_file")" >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
tests_dir="$script_dir/../apps/web/tests"
sorted_names="$(
  find "$tests_dir" -maxdepth 1 -type f -name '*.spec.ts' -exec basename {} \; |
    LC_ALL=C sort
)"
if [[ -z "$sorted_names" ]]; then
  printf 'No web test spec files found in %s\n' "$tests_dir" >&2
  exit 1
fi

printf '%s\n' "$sorted_names" |
  sed 's#^#npm run test:web -- apps/web/tests/#' > "$output_file"
command_count="$(printf '%s\n' "$sorted_names" | wc -l | tr -d ' ')"
printf 'Wrote %s test commands to %s\n' "$command_count" "$output_file"
