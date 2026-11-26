#!/usr/bin/env bash
#
# Interactive wizard for adding a Pilot 0 Operator on epm-h02-host (epmdemo.xyz),
# following docs/hosting/operations/pilot0-admission-and-incidents.md.
#
# Everything above the "STAGES" marker is the shared wizard library.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: consistent interactive UX across EPM wizards.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

TOTAL_STAGES=0
_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()
SKIPPED=()

_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  This wizard walks through the Pilot 0 operator admission runbook step by step,\n' "$DIM"
  printf '  running host commands over IAP SSH and pausing for browser MFA/Admin-lite steps.\n'
  printf '  Stop any time with Ctrl-C and re-run later — saved values are remembered.%s\n' "$RESET"
  pause "Ready to start?"
}

stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

say()  { printf '  %s\n' "$1"; }
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }
ok()   { printf '  %s✓ %s%s\n' "$GREEN" "$1" "$RESET"; }

open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview      >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open     >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open         >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser; visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser; visit it manually: $url"
}

pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

ask() {
  local key="$1" prompt="$2" fallback="${3:-}" current input
  current=$(_existing "$key" || true)
  [[ -z "$current" && -n "$fallback" ]] && current="$fallback"
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[%s]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$current" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ saved%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

finish() {
  _clear
  printf '\n%s%s  ✓ Pilot 0 Operator admission workflow finished%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} )) && note "saved ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to complete manually:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES: Pilot 0 Operator admission (docs/hosting/operations/pilot0-admission-and-incidents.md)
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=8

DEFAULT_PROJECT="project-47b72bb7-ba90-42c9-910"
DEFAULT_ZONE="us-west1-b"
DEFAULT_INSTANCE="epm-h02-host"
DEFAULT_BASE_DOMAIN="epmdemo.xyz"
DEFAULT_DEPLOYMENT_ID="b77f7c7e-c89c-4d44-b337-e8d4f13ee46f"
DEFAULT_KMS_KEY="projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek"
DEMO_DATASET_SHA256="2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a"

die() { printf '\nStopped: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Required command missing: $1"; }
require_value() { [[ -n "$2" && "$2" != *$'\n'* && "$2" != *$'\r'* ]] || die "Invalid $1."; }
valid_gcp_ident() { [[ "$1" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]]; }
valid_uuid() { [[ "$1" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; }
valid_slug() {
  [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
    && [[ "$1" != "admin" && "$1" != "login" ]]
}
valid_host_uid() { [[ "$1" =~ ^[0-9]+$ ]] && (( "$1" >= 100000 && "$1" <= 999999 )); }
valid_workspace_mode() { [[ "$1" == "empty" || "$1" == "synthetic" ]]; }
valid_image_ref() {
  [[ -n "$1" && "$1" != *$'\n'* && "$1" != *$'\r'* && "$1" != *[[:space:]]* ]] \
    && [[ "$1" =~ ^(sha256:[0-9a-f]{64}|[a-zA-Z0-9._/@:-]+)$ ]]
}
valid_domain() { [[ "$1" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]]; }

state_directory() {
  if [[ "$(uname -s)" == Darwin ]]; then
    printf '%s/Library/Application Support/EPM/pilot0-wizard' "$HOME"
  else
    printf '%s/epm/pilot0-wizard' "${XDG_STATE_HOME:-$HOME/.local/state}"
  fi
}

vm_ssh() {
  local remote_cmd="$1"
  gcloud compute ssh "$GCP_INSTANCE" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --tunnel-through-iap \
    --command="$remote_cmd"
}

vm_scp() {
  local local_path="$1" remote_path="$2"
  gcloud compute scp "$local_path" "$GCP_INSTANCE:$remote_path" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --tunnel-through-iap
}

stage_pre_admission_gate() {
  stage "Connection & Pre-Admission Gate"
  for tool in gcloud curl; do need "$tool"; done

  ask GCP_PROJECT "GCP Project ID:" "$DEFAULT_PROJECT"
  valid_gcp_ident "$GCP_PROJECT" || die "Invalid GCP Project ID: $GCP_PROJECT"
  ask GCP_ZONE "GCP Zone:" "$DEFAULT_ZONE"
  valid_gcp_ident "$GCP_ZONE" || die "Invalid GCP Zone: $GCP_ZONE"
  ask GCP_INSTANCE "GCP Host Instance:" "$DEFAULT_INSTANCE"
  valid_gcp_ident "$GCP_INSTANCE" || die "Invalid GCP Instance: $GCP_INSTANCE"
  ask BASE_DOMAIN "Hosted base domain:" "$DEFAULT_BASE_DOMAIN"
  valid_domain "$BASE_DOMAIN" || die "Invalid base domain: $BASE_DOMAIN"
  write_env GCP_PROJECT "$GCP_PROJECT"
  write_env GCP_ZONE "$GCP_ZONE"
  write_env GCP_INSTANCE "$GCP_INSTANCE"
  write_env BASE_DOMAIN "$BASE_DOMAIN"

  printf '\n'
  say "Pre-Admission Gate (Section 1 of pilot0-admission-and-incidents.md):"
  step "1. Verified Capacity Headroom: check Admin-lite Cohort Overview & host metrics (never overcommit)."
  step "2. Google OAuth Testing Allowlist: add the invited operator's exact Google email in GCP Console."
  step "3. Pilot 0 Disclosure: Free, invitation-only, best-effort, 24h nightly backup objective, platform-managed keys, no SLA."
  printf '\n'

  if confirm "Check live host disk, inode, and RAM headroom on $GCP_INSTANCE now?"; then
    vm_ssh 'df -h / /srv/epm/data && echo "--- inodes ---" && df -i /srv/epm/data && echo "--- memory ---" && free -h'
  fi

  if confirm "Open GCP Google Auth Platform Audience (Test users) in your browser?"; then
    open_url "https://console.cloud.google.com/auth/audience?project=$GCP_PROJECT"
  fi

  confirm "Confirm all 3 pre-admission gates (capacity headroom, OAuth allowlist, Pilot 0 disclosure) are satisfied?" \
    || die "Complete the pre-admission gates before admitting a Pilot 0 operator."
}

stage_admin_assignment_and_lookup() {
  stage "Step 1 — Create Assignment in Admin-lite & Select Pending Operator"
  step "Sign in to https://admin.$BASE_DOMAIN/ with Google + TOTP MFA."
  step "Create the operator assignment (exact email, canonical workspace_slug, Free 50 MB allowance, latest qualified Operator release)."
  step "Choose 'Empty workspace (default)' for real operators or 'Synthetic sample portfolio' for demos."
  step "Confirm the operator appears in Admin-lite as Pending."

  if confirm "Open https://admin.$BASE_DOMAIN/ in your browser?"; then
    open_url "https://admin.$BASE_DOMAIN/"
  fi
  pause "Press Enter once the Pending assignment exists in Admin-lite..."

  say "Querying recent operators in admin.sqlite on $GCP_INSTANCE..."
  vm_ssh "sudo /opt/epm/python/bin/python3 -c '
import sqlite3
conn = sqlite3.connect(\"/srv/epm/data/host/h0312-identity/admin.sqlite\")
rows = conn.execute(
    \"SELECT o.operator_id, o.workspace_id, o.workspace_slug, o.setup_state, op.operation_id, op.state \"
    \"FROM operators o JOIN operations op ON op.operator_id = o.operator_id \"
    \"ORDER BY o.created_at DESC LIMIT 10\"
).fetchall()
print(\"operator_id | workspace_id | slug | setup_state | operation_id | op_state\")
for row in rows:
    print(\" | \".join(str(x) for x in row))
conn.close()
'"

  printf '\n'
  ask OPERATOR_ID "OPERATOR_ID (UUID):"
  valid_uuid "$OPERATOR_ID" || die "Invalid OPERATOR_ID UUID: $OPERATOR_ID"
  ask WORKSPACE_ID "WORKSPACE_ID (UUID):"
  valid_uuid "$WORKSPACE_ID" || die "Invalid WORKSPACE_ID UUID: $WORKSPACE_ID"
  ask WORKSPACE_SLUG "WORKSPACE_SLUG (e.g. demo-c):"
  valid_slug "$WORKSPACE_SLUG" || die "Invalid WORKSPACE_SLUG: $WORKSPACE_SLUG"
  ask OPERATION_ID "OPERATION_ID (UUID):"
  valid_uuid "$OPERATION_ID" || die "Invalid OPERATION_ID UUID: $OPERATION_ID"
  ask WORKSPACE_MODE "Workspace mode (empty or synthetic):" "empty"
  valid_workspace_mode "$WORKSPACE_MODE" || die "Workspace mode must be 'empty' or 'synthetic'."

  write_env OPERATOR_ID "$OPERATOR_ID"
  write_env WORKSPACE_ID "$WORKSPACE_ID"
  write_env WORKSPACE_SLUG "$WORKSPACE_SLUG"
  write_env OPERATION_ID "$OPERATION_ID"
  write_env WORKSPACE_MODE "$WORKSPACE_MODE"
}

stage_resolve_image_and_demo_assets() {
  stage "Step 2a — Resolve Assigned Image & Verify Demo Assets"
  say "Resolving immutable Docker image ID for $OPERATOR_ID via launch_operator.py..."
  OPERATOR_IMAGE="$(vm_ssh "sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py --resolve-image '$OPERATOR_ID'" | tr -d '\r' | tail -n1)"
  valid_image_ref "$OPERATOR_IMAGE" || die "Failed to resolve assigned Docker image (got: '$OPERATOR_IMAGE'). Check the assignment and local image on $GCP_INSTANCE."
  ok "Assigned Docker image: $OPERATOR_IMAGE"
  write_env OPERATOR_IMAGE "$OPERATOR_IMAGE"

  if [[ "$WORKSPACE_MODE" == "synthetic" ]]; then
    say "Checking /opt/epm/demo/dataset.json SHA-256 on $GCP_INSTANCE..."
    local remote_sha=""
    remote_sha="$(vm_ssh "sudo sha256sum /opt/epm/demo/dataset.json 2>/dev/null | awk '{print \$1}'" | tr -d '\r' | tail -n1 || true)"
    if [[ "$remote_sha" == "$DEMO_DATASET_SHA256" ]]; then
      ok "/opt/epm/demo/dataset.json matches pinned SHA-256 ($DEMO_DATASET_SHA256)."
    else
      warn "/opt/epm/demo/dataset.json missing or mismatched (found: '${remote_sha:-missing}')."
      local local_dataset="$REPO_ROOT/application/demo/dataset.json"
      local local_seed="$REPO_ROOT/application/demo/seed.py"
      [[ -f "$local_dataset" && -f "$local_seed" ]] || die "Local demo files not found under $REPO_ROOT/application/demo/."
      if confirm "Upload application/demo/{dataset.json,seed.py} to /opt/epm/demo/ on $GCP_INSTANCE?"; then
        vm_scp "$local_dataset" "/tmp/epm-demo-dataset.json"
        vm_scp "$local_seed" "/tmp/epm-demo-seed.py"
        vm_ssh "sudo install -d -m 0755 /opt/epm/demo && sudo mv /tmp/epm-demo-dataset.json /opt/epm/demo/dataset.json && sudo mv /tmp/epm-demo-seed.py /opt/epm/demo/seed.py && sudo chmod 0644 /opt/epm/demo/dataset.json /opt/epm/demo/seed.py"
        remote_sha="$(vm_ssh "sudo sha256sum /opt/epm/demo/dataset.json | awk '{print \$1}'" | tr -d '\r' | tail -n1)"
        [[ "$remote_sha" == "$DEMO_DATASET_SHA256" ]] || die "Uploaded dataset.json SHA-256 mismatch: $remote_sha"
        ok "Uploaded and verified /opt/epm/demo/{dataset.json,seed.py}."
      else
        die "Synthetic sample portfolio requires verified /opt/epm/demo/dataset.json."
      fi
    fi
  else
    note "Empty workspace mode selected; skipping /opt/epm/demo/ check."
  fi
  pause
}

stage_provision_workspace() {
  stage "Step 2b — Provision Workspace via ManualProvisioner"
  say "Target operator: $WORKSPACE_SLUG ($OPERATOR_ID)"
  say "Operation ID:    $OPERATION_ID"
  say "Image:           $OPERATOR_IMAGE"
  note "Uses workspace_root=/data/workspace/active so .workspace.server.lock sits inside the writable bind mount."

  if ! confirm "Run ManualProvisioner on $GCP_INSTANCE? (Skip if already provisioned on a resume)"; then
    SKIPPED+=("Step 2b ManualProvisioner (skipped by operator)")
    return
  fi

  vm_ssh "sudo bash -s" <<EOF
set -euo pipefail
OPERATOR_ID='$OPERATOR_ID'
OPERATION_ID='$OPERATION_ID'
OPERATOR_IMAGE='$OPERATOR_IMAGE'

mkdir -p "/srv/epm/data/workspace/\$OPERATOR_ID" "/srv/epm/data/control/\$OPERATOR_ID" "/srv/epm/data/scratch/\$OPERATOR_ID"
chown -R 65532:65532 "/srv/epm/data/workspace/\$OPERATOR_ID" "/srv/epm/data/control/\$OPERATOR_ID" "/srv/epm/data/scratch/\$OPERATOR_ID"
chmod 0700 "/srv/epm/data/workspace/\$OPERATOR_ID" "/srv/epm/data/control/\$OPERATOR_ID" "/srv/epm/data/scratch/\$OPERATOR_ID"

docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 65532:65532 --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --mount type=bind,source=/srv/epm/data/host/h0312-identity,target=/admin \
  --mount "type=bind,source=/srv/epm/data/workspace/\$OPERATOR_ID,target=/data/workspace" \
  --mount "type=bind,source=/srv/epm/data/control/\$OPERATOR_ID,target=/data/control" \
  --mount "type=bind,source=/srv/epm/data/scratch/\$OPERATOR_ID,target=/data/scratch" \
  --mount type=bind,source=/opt/epm/demo,target=/demo,readonly \
  -e "OPERATION_ID=\$OPERATION_ID" \
  --pull never --entrypoint /opt/epm/venv/bin/python "\$OPERATOR_IMAGE" -B -c '
import os, time
from pathlib import Path
from app.modules.host_agent.infrastructure.manual_provision import ManualProvisionConfig, ManualProvisioner, ProvisionPaths
from app.modules.hosted_admin.infrastructure.provisioning_admission import AdminEffectAdmission
from app.platform.config import application_root
from app.platform.sqlite_engine import create_sqlite_engine

engine = create_sqlite_engine(Path("/admin/admin.sqlite"))
try:
    admission = AdminEffectAdmission(engine, clock=lambda: time.time_ns() // 1_000_000)
    cfg = ManualProvisionConfig(
        paths_for=lambda _intent: ProvisionPaths(
            workspace_root=Path("/data/workspace/active"),
            control_root=Path("/data/control"),
            scratch_root=Path("/data/scratch"),
        ),
        application_directory=application_root(),
        clock=lambda: time.time_ns() // 1_000_000,
        dataset_path=Path("/demo/dataset.json"),
    )
    print("Provision outcome:", ManualProvisioner(admission, cfg).provision(os.environ["OPERATION_ID"]))
finally:
    engine.dispose()
'
EOF
  ok "Workspace provisioning step completed."
  pause
}

stage_recovery_and_backup_principal() {
  stage "Step 2c — Initialize recovery.sqlite, Align workspace_id & Register Backup Principal"
  say "Checking registered backup principals in /srv/epm/data/host/backup-proxy/inventory.sqlite..."
  local suggested_uid=""
  suggested_uid="$(vm_ssh "sudo /opt/epm/python/bin/python3 -c '
import sqlite3
conn = sqlite3.connect(\"/srv/epm/data/host/backup-proxy/inventory.sqlite\")
rows = conn.execute(\"SELECT operator_id, host_uid FROM operator_principals ORDER BY host_uid\").fetchall()
existing = None
max_uid = 100000
for op_id, uid in rows:
    print(f\"  {op_id} -> {uid}\")
    if op_id == \"$OPERATOR_ID\":
        existing = uid
    if uid > max_uid:
        max_uid = uid
print(\"SUGGESTED_UID=\" + str(existing if existing is not None else max_uid + 1))
conn.close()
'" | tee /dev/stderr | awk -F= '/^SUGGESTED_UID=/{print $2}' | tr -d '\r' | tail -n1)"

  ask HOST_UID "HOST_UID for backup principal:" "${suggested_uid:-100001}"
  valid_host_uid "$HOST_UID" || die "Invalid HOST_UID (expected integer 100000..999999): $HOST_UID"
  write_env HOST_UID "$HOST_UID"

  if ! confirm "Initialize recovery.sqlite, align workspace_id, and register HOST_UID=$HOST_UID?"; then
    SKIPPED+=("Step 2c recovery.sqlite & backup principal registration (skipped by operator)")
    return
  fi

  vm_ssh "sudo bash -s" <<EOF
set -euo pipefail
OPERATOR_ID='$OPERATOR_ID'
WORKSPACE_ID='$WORKSPACE_ID'
HOST_UID='$HOST_UID'
OPERATOR_IMAGE='$OPERATOR_IMAGE'
DEPLOYMENT_ID='$DEFAULT_DEPLOYMENT_ID'
KMS_KEY='$DEFAULT_KMS_KEY'

rm -f "/srv/epm/data/control/\$OPERATOR_ID/recovery.sqlite"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 65532:65532 \
  --mount "type=bind,source=/srv/epm/data/control/\$OPERATOR_ID,target=/data/control" \
  -e "OPERATOR_ID=\$OPERATOR_ID" -e "WORKSPACE_ID=\$WORKSPACE_ID" \
  -e "DEPLOYMENT_ID=\$DEPLOYMENT_ID" -e "KMS_KEY=\$KMS_KEY" \
  --pull never --entrypoint /opt/epm/venv/bin/python "\$OPERATOR_IMAGE" -B -c '
import os, sqlite3
from pathlib import Path
from app.modules.workspace.infrastructure.hosted_recovery import kms_ref_to_db_ref
from app.platform.config import application_root
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

op_id, ws_id = os.environ["OPERATOR_ID"], os.environ["WORKSPACE_ID"]
dep_id, kms_key = os.environ["DEPLOYMENT_ID"], os.environ["KMS_KEY"]
rec_path = Path("/data/control/recovery.sqlite")
print("recovery.sqlite:", initialize_store(HostedStore.RECOVERY, rec_path, application_directory=application_root()))
rec = sqlite3.connect(str(rec_path))
rec.execute(
    "INSERT INTO recovery_meta (id, workspace_id, deployment_ref, source_generation, restore_generation, active_business_ref, encryption_key_ref, namespace_prefix, revision) "
    "VALUES (1, ?, ?, 1, 1, '\''active'\'', ?, ?, 1)",
    (ws_id, f"dep:{dep_id}", kms_ref_to_db_ref(kms_key), f"deployments/{dep_id}/operators/{op_id}/"),
)
rec.execute(
    "INSERT INTO backup_state (id, last_point_id, protected_business_revision, protected_files_generation, protected_source_generation, "
    "protection_state, dirty_since, last_checked_at, last_backup_attempt_at, consecutive_failures, last_error_code, revision) "
    "VALUES (1, NULL, NULL, NULL, NULL, '\''unknown'\'', NULL, NULL, NULL, 0, NULL, 1)"
)
rec.commit(); rec.close()
'

/opt/epm/python/bin/python3 - "\$OPERATOR_ID" "\$WORKSPACE_ID" "\$HOST_UID" <<'PY'
import json, sqlite3, sys, time
from pathlib import Path

op_id, ws_id, uid = sys.argv[1], sys.argv[2], int(sys.argv[3])
now = int(time.time() * 1000)

ws_json = Path(f"/srv/epm/data/workspace/{op_id}/active/workspace.json")
data = json.loads(ws_json.read_text())
data["workspaceId"] = ws_id
ws_json.write_text(json.dumps(data, indent=2) + "\n")

biz = sqlite3.connect(f"/srv/epm/data/workspace/{op_id}/active/database/property-management.sqlite")
biz.execute("UPDATE workspace_metadata SET workspace_id = ?", (ws_id,))
biz.commit(); biz.close()

inv = sqlite3.connect("/srv/epm/data/host/backup-proxy/inventory.sqlite")
existing = inv.execute(
    "SELECT host_uid FROM operator_principals WHERE operator_id = ?", (op_id,)
).fetchone()
if existing is None:
    inv.execute(
        "INSERT INTO operator_principals (operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
        "VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)",
        (op_id, ws_id, uid, uid, now),
    )
    inv.commit()
    print(f"Registered backup principal: operator_id={op_id} host_uid={uid}")
else:
    assert existing[0] == uid, f"Operator already registered with host_uid={existing[0]} (expected {uid})"
    print(f"Backup principal already registered with host_uid={uid}")
inv.close()
PY

chown -R 65532:65532 "/srv/epm/data/workspace/\$OPERATOR_ID" "/srv/epm/data/control/\$OPERATOR_ID" "/srv/epm/data/scratch/\$OPERATOR_ID"
EOF
  ok "recovery.sqlite initialized, workspace_id aligned, and backup principal registered."
  pause
}

stage_launch_and_initial_backup() {
  stage "Step 3a — Launch Container & Capture Initial Verified Backup"
  say "Launching epm-op-$WORKSPACE_SLUG, restarting epm-h03-identity.service, and capturing initial R2 + Cloud KMS recovery point."

  if ! confirm "Launch container and capture initial verified backup now?"; then
    SKIPPED+=("Step 3a launch & initial verified backup (skipped by operator)")
    return
  fi

  vm_ssh "sudo bash -s" <<EOF
set -euo pipefail
OPERATOR_ID='$OPERATOR_ID'
WORKSPACE_SLUG='$WORKSPACE_SLUG'
HOST_UID='$HOST_UID'
OPERATOR_IMAGE='$OPERATOR_IMAGE'

/opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "\$OPERATOR_ID"
systemctl restart epm-h03-identity.service
sleep 20
systemctl is-active epm-backup-proxy.service epm-h03-identity.service epm-gateway.service epm-tunnel.service epm-host-guardian.service

docker stop "epm-op-\$WORKSPACE_SLUG"
chown -R "\$HOST_UID:\$HOST_UID" \
  "/srv/epm/data/workspace/\$OPERATOR_ID" \
  "/srv/epm/data/control/\$OPERATOR_ID" \
  "/srv/epm/data/scratch/\$OPERATOR_ID" \
  "/etc/epm/pilot0-operators/\$OPERATOR_ID"

docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "\$HOST_UID:\$HOST_UID" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
  --mount "type=bind,source=/etc/epm/pilot0-operators/\$OPERATOR_ID,target=/control,readonly" \
  --mount "type=bind,source=/srv/epm/data/workspace/\$OPERATOR_ID,target=/data/workspace" \
  --mount "type=bind,source=/srv/epm/data/control/\$OPERATOR_ID,target=/data/control" \
  --mount "type=bind,source=/srv/epm/data/scratch/\$OPERATOR_ID,target=/data/scratch" \
  --mount type=bind,source=/run/epm-backup-proxy,target=/run/epm-backup-proxy \
  --pull never --entrypoint /opt/epm/venv/bin/python "\$OPERATOR_IMAGE" -B -c '
import time
from pathlib import Path
from app.modules.host_agent.infrastructure.backup_proxy import UnixBackupProxyClient
from app.modules.hosted_access.infrastructure.operator_entry import OperatorDeployment
from app.modules.hosted_access.infrastructure.shared_identity_entry import read_private
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.scheduler import WorkspaceBackupScheduler
from app.modules.workspace.infrastructure.hosted_recovery import HostedWorkspaceRecoveryService
from app.platform.sqlite_engine import create_sqlite_engine

cfg = OperatorDeployment.model_validate_json(read_private(Path("/control/deployment.json")))
b = cfg.binding; clock = lambda: time.time_ns() // 1_000_000
svc = HostedWorkspaceRecoveryService(
    recovery_engine=create_sqlite_engine(cfg.recovery_database),
    access_engine=create_sqlite_engine(cfg.access_database),
    backup_engine=ChunkedAeadBackupEngine(UnixBackupProxyClient(cfg.backup_proxy_socket, expected_proxy_uid=cfg.backup_proxy_uid)),
    operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id, deployment_id=b.deployment_id,
    workspace_root=Path("/data/workspace"), scratch_root=cfg.scratch_directory, release_ref=cfg.release_ref,
    business_schema_revision=cfg.business_schema_revision, access_schema_revision=cfg.access_schema_revision, clock=clock,
)
sched = WorkspaceBackupScheduler(svc, deployment_id=b.deployment_id, operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id, clock=clock, nightly_interval_ms=1000, jitter_window_seconds=0)
print("RUN_ONCE:", sched.run_once(), svc.read_protection_status())
'

chown -R 65532:65532 \
  "/srv/epm/data/workspace/\$OPERATOR_ID" \
  "/srv/epm/data/control/\$OPERATOR_ID" \
  "/srv/epm/data/scratch/\$OPERATOR_ID" \
  "/etc/epm/pilot0-operators/\$OPERATOR_ID"
docker start "epm-op-\$WORKSPACE_SLUG"
sleep 12
EOF
  ok "Container launched and initial verified backup captured."
  pause
}

stage_verify_health_projection_and_ingress() {
  stage "Step 3b — Verify Container Health, Admin Recovery Projection & Public Ingress"

  say "1. Probing container /health/live and /health/ready..."
  vm_ssh "sudo docker exec 'epm-op-$WORKSPACE_SLUG' /opt/epm/venv/bin/python -c '
import urllib.request
for name in (\"live\", \"ready\"):
    with urllib.request.urlopen(f\"http://127.0.0.1:8081/health/{name}\", timeout=5) as response:
        print(name, response.status, response.read().decode())
'"
  ok "Container /health/live and /health/ready returned 200."

  printf '\n'
  say "2. Checking Admin workspace_recovery_status projection..."
  local projection_out=""
  projection_out="$(vm_ssh "sudo /opt/epm/python/bin/python3 -c '
import sqlite3, sys
conn = sqlite3.connect(\"/srv/epm/data/host/h0312-identity/admin.sqlite\")
row = conn.execute(
    \"SELECT o.operator_id, o.workspace_id, r.protection_state, r.latest_point_ref, r.captured_at, r.verified_at, r.observed_at \"
    \"FROM operators o LEFT JOIN workspace_recovery_status r ON r.operator_id = o.operator_id \"
    \"WHERE o.workspace_slug = ?\",
    (sys.argv[1],),
).fetchone()
print(row)
conn.close()
' '$WORKSPACE_SLUG'")"
  say "$projection_out"
  if [[ "$projection_out" == *"'healthy'"* ]]; then
    ok "Admin recovery-status projection reports healthy."
  else
    warn "Admin recovery-status projection is not yet healthy. Check operator logs for relay warnings before treating backup reporting as complete."
  fi

  printf '\n'
  say "3. Checking public HTTPS ingress (https://$WORKSPACE_SLUG.$BASE_DOMAIN/auth/start)..."
  local ingress_headers=""
  ingress_headers="$(curl -sS -D - -o /dev/null "https://$WORKSPACE_SLUG.$BASE_DOMAIN/auth/start" | grep -i -E '^HTTP/|^location:' | tr -d '\r' || true)"
  say "$ingress_headers"
  if [[ "$ingress_headers" == *" 303"* && "$ingress_headers" == *"https://login.$BASE_DOMAIN/auth/start"* ]]; then
    ok "Public HTTPS ingress returned 303 -> https://login.$BASE_DOMAIN/auth/start."
  else
    warn "Unexpected ingress response (502 or non-303). Inspect gateway & operator logs:"
    note "  sudo journalctl -u epm-gateway.service --since '5 minutes ago' --no-pager"
    note "  sudo docker logs --since 10m epm-op-$WORKSPACE_SLUG"
    confirm "Continue despite ingress check warning?" || die "Resolve ingress before issuing the invitation."
  fi
  pause
}

stage_invitation_sync_and_claim() {
  stage "Step 4 — Issue Invitation, Sync assignment_revision & Complete Claim"
  step "In Admin-lite (https://admin.$BASE_DOMAIN/), open $WORKSPACE_SLUG and click 'Issue / reissue invitation' (requires recent MFA)."
  step "Email the single-use claim URL from dctech92130@gmail.com with the Pilot 0 disclosure."
  step "Click 'Mark delivered' in Admin-lite."

  if confirm "Open https://admin.$BASE_DOMAIN/ now?"; then
    open_url "https://admin.$BASE_DOMAIN/"
  fi

  if confirm "Sync assignment_revision on $GCP_INSTANCE now? (Run after issuing/delivering invitation)"; then
    vm_ssh "sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py '$OPERATOR_ID' && sudo systemctl restart epm-h03-identity.service && sleep 20"
    ok "Synced assignment_revision and restarted epm-h03-identity.service."
  else
    SKIPPED+=("Step 4.2 sync assignment_revision (launch_operator.py + restart epm-h03-identity.service)")
  fi

  printf '\n'
  step "Have the operator open their claim URL and complete 'Continue with Google'."
  if confirm "Run Pilot 0 manual claim completion binding now? (Only after operator completed first Google verification)"; then
    vm_ssh "sudo bash -s" <<EOF
set -euo pipefail
OPERATOR_ID='$OPERATOR_ID'

/opt/epm/python/bin/python3 - "\$OPERATOR_ID" <<'PY'
import sqlite3, sys, time

op_id = sys.argv[1]
now = int(time.time() * 1000)
ac = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
current_sub = ac.execute("SELECT subject FROM operators WHERE operator_id = ?", (op_id,)).fetchone()
if current_sub and current_sub[0]:
    print("Operator already bound to subject:", current_sub[0])
    ac.close()
else:
    row = ac.execute(
        "SELECT issuer, subject FROM managed_identity_sessions WHERE operator_id = ? ORDER BY issued_at DESC LIMIT 1",
        (op_id,),
    ).fetchone()
    assert row, "No verified managed_identity_sessions row found yet"
    issuer, sub = row
    ac.execute(
        "UPDATE operators SET subject = ?, setup_state = 'active', revision = revision + 1, updated_at = ? WHERE operator_id = ?",
        (sub, now, op_id),
    )
    ac.execute(
        "UPDATE invitations SET state = 'claimed', claimed_issuer = ?, claimed_subject = ?, claimed_at = ?, revision = revision + 1 "
        "WHERE operator_id = ? AND state IN ('pending_delivery', 'sent')",
        (issuer, sub, now, op_id),
    )
    ac.commit(); ac.close()

    oc = sqlite3.connect(f"/srv/epm/data/control/{op_id}/access.sqlite")
    oc.execute("UPDATE access_meta SET subject = ?, effective_access = 'enabled', revision = revision + 1 WHERE id = 1", (sub,))
    oc.commit(); oc.close()
    print("Bound verified subject:", issuer, sub)
PY

chown -R 65532:65532 "/srv/epm/data/host/h0312-identity" "/srv/epm/data/control/\$OPERATOR_ID"
/opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "\$OPERATOR_ID"
systemctl restart epm-h03-identity.service
sleep 20
EOF
    ok "Verified subject bound, container relaunched, and identity service restarted."
    step "Have the operator open a fresh tab to https://$WORKSPACE_SLUG.$BASE_DOMAIN/ and confirm Active + Healthy in Admin-lite."
  else
    SKIPPED+=("Step 4.3 manual claim completion binding after operator's first Google sign-in")
  fi
  pause
}

main() {
  if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    cat <<'USAGE'
Usage: bash application/scripts/epm-pilot0-add-operator.sh
Interactive wizard for adding a Pilot 0 Operator on epm-h02-host (epmdemo.xyz),
following docs/hosting/operations/pilot0-admission-and-incidents.md.
USAGE
    return
  fi
  [[ $# == 0 ]] || die "Use --help for usage."
  [[ -t 0 && -t 1 ]] || die "Run interactively in a terminal."

  umask 077
  local start_epoch end_epoch elapsed_min
  start_epoch="$(date +%s)"
  REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
  local state_dir
  state_dir="$(state_directory)"
  mkdir -p "$state_dir"
  ENV_FILE="${ENV_FILE_OVERRIDE:-$state_dir/add-operator.env}"

  banner "EPM · Pilot 0 Add Operator Wizard"

  stage_pre_admission_gate
  stage_admin_assignment_and_lookup
  stage_resolve_image_and_demo_assets
  stage_provision_workspace
  stage_recovery_and_backup_principal
  stage_launch_and_initial_backup
  stage_verify_health_projection_and_ingress
  stage_invitation_sync_and_claim

  end_epoch="$(date +%s)"
  elapsed_min=$(( (end_epoch - start_epoch + 59) / 60 ))
  finish
  say "Operator URL:    https://$WORKSPACE_SLUG.$BASE_DOMAIN/"
  say "Operator ID:     $OPERATOR_ID"
  say "Workspace ID:    $WORKSPACE_ID"
  say "Host UID:        ${HOST_UID:-unset}"
  say "Assigned Image:  ${OPERATOR_IMAGE:-unset}"
  say "Elapsed time:    ~${elapsed_min} min (log in docs/hosting/qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md)"
  printf '\n'
}

main "$@"
