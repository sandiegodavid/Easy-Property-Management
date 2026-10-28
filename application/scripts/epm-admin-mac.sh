#!/bin/bash
# Private IAP launcher. No credentials in URLs, arguments or browser storage.
set -euo pipefail
if [[ $# != 4 || ! "$4" =~ ^[0-9]{4,5}$ ]] || (( 10#$4 < 1024 || 10#$4 > 65535 )); then
  echo 'Usage: epm-admin-mac.sh PROJECT ZONE VM INSTALLED_ADMIN_PORT' >&2
  exit 2
fi
project=$1
zone=$2
vm=$3
port=$4
# Validate remote-command tokens; these are installation selectors, never shell input.
for selector in "$project" "$zone" "$vm"; do
  if [[ ! "$selector" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]]; then
    echo 'Invalid cloud installation selector.' >&2
    exit 2
  fi
done
printf 'Keep this terminal open. Paste the one-use credential into the private Admin sign-in.\n'
printf 'Private Admin URL: http://epm-admin.localhost:%s\n' "$port"
# Fail rather than displace an existing listener. Forward binds only the local loopback address.
# Bootstrap output is terminal-only; SSH logs must not capture interactive output.
gcloud compute ssh "$vm" --project="$project" --zone="$zone" --tunnel-through-iap \
  --ssh-flag=-oExitOnForwardFailure=yes \
  --ssh-flag="-L127.0.0.1:${port}:127.0.0.1:${port}" \
  --command='sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py bootstrap && sleep 28800' &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for ((attempt=0; attempt<90; attempt++)); do
  if ! kill -0 "$forward_pid" 2>/dev/null; then
    wait "$forward_pid"
    exit 1
  fi
  if curl --noproxy '*' --resolve "epm-admin.localhost:${port}:127.0.0.1" \
      --connect-timeout 1 --max-time 2 --silent --fail \
      "http://epm-admin.localhost:${port}/" --output /dev/null; then
    open "http://epm-admin.localhost:${port}/"
    wait "$forward_pid"
    exit 0
  fi
  sleep 1
done
echo 'Private forward did not become ready. Check the installed listener and hostname.' >&2
exit 1
