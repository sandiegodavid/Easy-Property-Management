"""Release-tooling checkpoints for an explicit synthetic demo reset, never an API."""

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from uuid import UUID

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.recovery_publication import (
    load_recovery_configuration,
)
from app.modules.hosted_access.infrastructure.storage_budget import validate_storage_volume
from app.modules.workspace.application.service import WorkspaceService
from app.platform.product_migrations import current_revision

RELEASES = Path("/opt/epm/releases")
CONFIGS = Path("/etc/epm")
DATA = Path("/var/lib")
BACKUPS = Path("/var/backups")
SYSTEMD = Path("/etc/systemd/system")
ROOT_UID = 0
STEPS = ("backed_up", "restored", "initialized", "switched", "activated", "accepted")
DESCRIPTOR_KEYS = {
    "format",
    "release",
    "instance",
    "source_commit",
    "workspace_id",
    "schema_revision",
    "archive_sha256",
    "workspace_bytes",
}
FIELDS = {
    "phase",
    "candidate_local",
    "candidate_hosted",
    "bootstrap_local",
    "workspace",
    "old_workspace",
    "administration_database",
    "archive",
    "backup",
    "old_python",
}


class ResetError(ValueError):
    """An operator-safe reset failure, with no supplied configuration contents."""


def require(condition, message):
    if not condition:
        raise ResetError(message)


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, data, identity):
    """Publish a complete file with final ownership/mode before rename."""
    path = Path(path)
    uid, gid, mode = identity
    descriptor, temporary = tempfile.mkstemp(prefix=".reset-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def save_plan(record, plan):
    atomic_write(record / "reset.json", json_bytes(plan), (0, 0, 0o600))


def load_plan(record):
    record = Path(record)
    info = record.lstat()
    require(
        stat.S_ISDIR(info.st_mode) and info.st_uid == ROOT_UID and not info.st_mode & 0o077,
        "Reset record must be a root-private directory.",
    )
    require(
        record.parent.name == "wizard-state" and record.parent.parent.parent == RELEASES,
        "Reset record must belong to an installed release.",
    )
    require(record.resolve() == record, "Reset record cannot use symlinks.")
    metadata = (record / "reset.json").lstat()
    require(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == ROOT_UID
        and not metadata.st_mode & 0o077,
        "Reset checkpoint must be a root-private regular file.",
    )
    plan = read_json(record / "reset.json")
    require(plan["release"] == record.parent.parent.name, "Wrong reset release.")
    require(plan["instance"] in {"a", "b"}, "Invalid reset instance.")
    require(record.name.startswith(plan["instance"] + "."), "Wrong reset instance.")
    require(
        plan["phase"]
        in {"prepared", "switching", "rolling_back", "rolled_back", "rollback_accepted", *STEPS},
        "Invalid reset phase.",
    )
    require(
        plan["completed"] == list(STEPS[: len(plan["completed"])]), "Invalid reset checkpoints."
    )
    return plan


def event(record, plan, phase):
    plan["phase"] = phase
    plan["events"].append({"phase": phase, "at": datetime.now(UTC).isoformat()})
    save_plan(record, plan)


def describe(args):
    require(not args.output.exists(), "Descriptor already exists.")
    service = WorkspaceService.from_local_config(args.config)
    manifest = service.open(integrity_check=True)
    size = sum(p.stat().st_size for p in service.paths.root.rglob("*") if p.is_file())
    descriptor = {
        "format": 1,
        "release": args.release,
        "instance": args.instance,
        "source_commit": args.source,
        "workspace_id": str(UUID(manifest.workspace_id)),
        "schema_revision": current_revision(),
        "archive_sha256": file_hash(args.archive),
        "workspace_bytes": size,
    }
    args.output.write_bytes(json_bytes(descriptor))
    args.output.chmod(0o600)
    print(f"{args.instance}: {descriptor['archive_sha256']} (workspace {manifest.workspace_id})")


def validate_descriptor(value, release, instance):
    require(isinstance(value, dict) and set(value) == DESCRIPTOR_KEYS, "Invalid demo descriptor.")
    require(type(value["format"]) is int and value["format"] == 1, "Invalid descriptor format.")
    require(
        value["release"] == release.name and value["instance"] == instance,
        "Demo archive belongs to another release or instance.",
    )
    require(
        value["source_commit"] == (release / "SOURCE_COMMIT.txt").read_text().strip(),
        "Demo source does not match the installed release.",
    )
    require(value["schema_revision"] == current_revision(), "Demo schema revision differs.")
    require(isinstance(value["workspace_id"], str), "Invalid demo UUID.")
    require(str(UUID(value["workspace_id"])) == value["workspace_id"], "Invalid demo UUID.")
    require(
        isinstance(value["archive_sha256"], str)
        and re.fullmatch(r"[a-f0-9]{64}", value["archive_sha256"]),
        "Invalid archive checksum.",
    )
    require(
        type(value["workspace_bytes"]) is int and value["workspace_bytes"] > 0,
        "Invalid demo workspace size.",
    )


def snapshot(record, name, path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), "Configuration must be a regular file.")
    data = path.read_bytes()
    atomic_write(record / name, data, (0, 0, 0o600))
    return {
        "path": str(path),
        "snapshot": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "identity": [info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)],
    }


def instance_paths(instance):
    base = DATA / f"epm-{instance}"
    return base, base / "hosted-local.json", CONFIGS / f"hosted-{instance}.json"


def build_candidate(args, deployment, descriptor):
    base, local, hosted = instance_paths(args.instance)
    old_local = read_json(local)
    old_workspace = Path(old_local["localWorkspacePath"])
    require(
        old_workspace.resolve() == old_workspace
        and deployment.storage_volume in old_workspace.parents,
        "Old workspace is not a real child of the configured volume.",
    )
    old_id = read_json(old_workspace / "workspace.json")["workspaceId"]
    require(old_id == str(deployment.workspace_id), "Old workspace/configuration binding differs.")
    new_id = descriptor["workspace_id"]
    require(new_id != old_id, "Reset must use a new workspace identity.")
    other = CONFIGS / f"hosted-{'b' if args.instance == 'a' else 'a'}.json"
    require(
        new_id != str(load_hosted_deployment(other).workspace_id),
        "A and B must have distinct UUIDs.",
    )
    workspace = deployment.storage_volume / f"demo-{args.release}-{new_id}"
    admin = base / "access" / f"hosted-access-{new_id}.sqlite"
    require(
        not workspace.exists()
        and not workspace.is_symlink()
        and not admin.exists()
        and not admin.is_symlink(),
        "Fresh workspace or administration destination already exists.",
    )
    candidate = read_json(hosted)
    candidate.update(workspace_id=new_id, administration_database=str(admin))
    HostedDeployment.model_validate(candidate)
    old_local["localWorkspacePath"] = str(workspace)
    return old_workspace, workspace, admin, old_local, candidate


def make_plan(args, deployment, descriptor):
    old, workspace, admin, local, hosted = build_candidate(args, deployment, descriptor)
    identity = pwd.getpwnam(f"epm-{args.instance}")
    candidate_dir = CONFIGS / f"reset-{args.record.name}"
    candidate_dir.mkdir(mode=0o750)
    os.chown(candidate_dir, 0, identity.pw_gid)
    files = {
        "candidate_local": local,
        "candidate_hosted": hosted,
        "bootstrap_local": {
            "localWorkspacePath": str(workspace.parent / (".bootstrap-" + workspace.name))
        },
    }
    paths = {}
    for name, value in files.items():
        path = candidate_dir / f"{name}.json"
        atomic_write(path, json_bytes(value), (0, identity.pw_gid, 0o640))
        paths[name] = str(path)
    return {
        "release": args.release,
        "instance": args.instance,
        "phase": "prepared",
        "completed": [],
        "events": [],
        "workspace": str(workspace),
        "old_workspace": str(old),
        "administration_database": str(admin),
        "archive": str(args.archive),
        "archive_sha256": descriptor["archive_sha256"],
        "workspace_id": descriptor["workspace_id"],
        "workspace_bytes": descriptor["workspace_bytes"],
        "old_python": args.old_python,
        "backup": str(
            BACKUPS / f"epm-{args.instance}" / f"before-reset-{args.record.name}.epm-backup"
        ),
        **paths,
    }


def prepare_plan(args):
    release = RELEASES / args.release
    require(args.record.parent == release / "wizard-state", "Invalid reset record location.")
    require(
        not (args.record / "reset.json").exists(), "Reset is already planned; choose resume-reset."
    )
    descriptor = read_json(args.descriptor)
    validate_descriptor(descriptor, release, args.instance)
    require(
        file_hash(args.archive) == args.checksum == descriptor["archive_sha256"],
        "Demo archive does not match the independent Mac checksum.",
    )
    require(
        re.fullmatch(r"/opt/epm/releases/[A-Za-z0-9._-]+/venv/bin/python", args.old_python),
        "Invalid previous interpreter.",
    )
    _, local, hosted = instance_paths(args.instance)
    deployment = load_hosted_deployment(hosted)
    plan = make_plan(args, deployment, descriptor)
    plan["originals"] = [
        snapshot(args.record, "local.before", local),
        snapshot(args.record, "hosted.before", hosted),
    ]
    dropin = SYSTEMD / f"epm-hosted@{args.instance}.service.d/90-release.conf"
    if dropin.exists() or dropin.is_symlink():
        plan["originals"].append(snapshot(args.record, "dropin.before", dropin))
    else:
        plan["originals"].append({"path": str(dropin), "snapshot": None, "identity": [0, 0, 0o644]})
    prepare_recovery(args.record, plan, deployment)
    plan["candidate_hashes"] = {
        key: file_hash(plan[key])
        for key in ("candidate_local", "candidate_hosted", "bootstrap_local", "candidate_recovery")
        if key in plan
    }
    event(args.record, plan, "prepared")


def prepare_recovery(record, plan, deployment):
    """Separate new-workspace retention from all retained old recovery points."""
    path = CONFIGS / f"recovery-{plan['instance']}.json"
    if not path.exists():
        return
    existing = load_recovery_configuration(path)
    require(existing.workspace_id == deployment.workspace_id, "Old recovery binding differs.")
    ledger_dir = existing.ledger_path.parent / f"workspace-{plan['workspace_id']}"
    ledger_dir.mkdir(mode=0o700)
    raw = read_json(path)
    raw.update(workspace_id=plan["workspace_id"], ledger_path=str(ledger_dir / "ledger.json"))
    candidate = record / "recovery.candidate"
    atomic_write(candidate, json_bytes(raw), (0, 0, 0o600))
    plan["candidate_recovery"] = str(candidate)
    plan["originals"].append(snapshot(record, "recovery.before", path))


def check_stopped(plan):
    unit = f"epm-hosted@{plan['instance']}.service"
    result = subprocess.run(
        ["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveState"],
        capture_output=True,
        text=True,
        check=True,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines())
    require(
        values["MainPID"] == "0" and values["ActiveState"] in {"inactive", "failed"},
        "The owning service must remain stopped.",
    )


def candidate_replacements(plan):
    instance = plan["instance"]
    python = RELEASES / plan["release"] / "venv/bin/python"
    local, hosted = [original["path"] for original in plan["originals"][:2]]
    command = (
        f"[Service]\nExecStart=\nExecStart={python} -m app --config "
        f"{local} serve-hosted --deployment {hosted} --port {8001 if instance == 'a' else 8002}\n"
    )
    replacements = [
        Path(plan["candidate_local"]).read_bytes(),
        Path(plan["candidate_hosted"]).read_bytes(),
        command.encode(),
    ]
    if "candidate_recovery" in plan:
        replacements.append(Path(plan["candidate_recovery"]).read_bytes())
    return replacements


def verify_candidate(plan):
    require(file_hash(plan["archive"]) == plan["archive_sha256"], "Demo archive changed.")
    workspace = Path(plan["workspace"])
    manifest = read_json(workspace / "workspace.json")
    require(
        manifest["workspaceId"] == plan["workspace_id"], "Restored UUID differs from descriptor."
    )
    value = read_json(plan["candidate_hosted"])
    require(
        value["workspace_id"] == plan["workspace_id"]
        and value["administration_database"] == plan["administration_database"],
        "Candidate identity changed.",
    )


def check_config_sources(record, plan):
    for original in plan["originals"]:
        if original["snapshot"]:
            require(
                file_hash(record / original["snapshot"]) == original["sha256"],
                "Original configuration snapshot changed; inspect manually.",
            )
    for field, expected in plan["candidate_hashes"].items():
        require(
            file_hash(plan[field]) == expected, "Candidate configuration changed; inspect manually."
        )


def replace_configs(record, plan, rollback=False):
    check_stopped(plan)
    check_config_sources(record, plan)
    if not rollback:
        require("initialized" in plan["completed"], "Restore and initialize before switching.")
        verify_candidate(plan)
    replacements = candidate_replacements(plan)
    changes = []
    for original, new in zip(plan["originals"], replacements, strict=True):
        path = Path(original["path"])
        require(not path.is_symlink(), "Configuration cannot be a symlink.")
        old = (record / original["snapshot"]).read_bytes() if original["snapshot"] else None
        current = path.read_bytes() if path.exists() else None
        require(
            current in (old, new), "Configuration changed outside this reset; inspect manually."
        )
        changes.append((path, old if rollback else new, original["identity"]))
    event(record, plan, "rolling_back" if rollback else "switching")
    for path, desired, identity in changes:
        if desired is None:
            path.unlink(missing_ok=True)
            sync_directory(path.parent)
        else:
            atomic_write(path, desired, identity)
    event(record, plan, "rolled_back" if rollback else "switched")
    if not rollback and "switched" not in plan["completed"]:
        plan["completed"].append("switched")
        save_plan(record, plan)


def mark(record, plan, step):
    require(
        plan["phase"] not in {"rolling_back", "rolled_back", "rollback_accepted"},
        "This reset is rolling back or has rolled back.",
    )
    require(step in STEPS, "Unknown reset checkpoint.")
    if step in plan["completed"]:
        return
    require(
        list(STEPS[: STEPS.index(step)]) == plan["completed"], "Reset checkpoint is out of order."
    )
    require(step != "switched", "Use the stopped configuration-switch operation.")
    if step == "backed_up":
        require(Path(plan["backup"]).is_file(), "Verified backup is missing.")
    if step == "restored":
        verify_candidate(plan)
    plan["completed"].append(step)
    event(record, plan, step)


def storage(args):
    require(args.bytes > 0, "Expected a positive demo workspace size.")
    deployment = load_hosted_deployment(args.deployment)
    volume, _ = validate_storage_volume(deployment, args.workspace)
    available = os.statvfs(volume).f_bavail * os.statvfs(volume).f_frsize
    require(
        available >= args.bytes * 2 + 32 * 1024 * 1024,
        "Not enough bounded-volume headroom to preserve the old demo and restore a new one.",
    )


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="action", required=True)
    descriptor = commands.add_parser("describe")
    for name in ("config", "archive", "output"):
        descriptor.add_argument("--" + name, type=Path, required=True)
    for name in ("release", "instance", "source"):
        descriptor.add_argument("--" + name, required=True)
    prepare = commands.add_parser("plan")
    for name in ("descriptor", "archive", "record"):
        prepare.add_argument("--" + name, type=Path, required=True)
    for name in ("release", "instance", "checksum", "old-python"):
        prepare.add_argument("--" + name, required=True)
    for name in ("field", "done", "mark", "switch", "rollback", "accept-rollback"):
        command = commands.add_parser(name)
        command.add_argument("--record", type=Path, required=True)
        if name in {"field", "done", "mark"}:
            command.add_argument("value")
    check = commands.add_parser("storage")
    check.add_argument("--deployment", type=Path, required=True)
    check.add_argument("--workspace", type=Path, required=True)
    check.add_argument("--bytes", type=int, required=True)
    return result


def main():
    args = parser().parse_args()
    if args.action == "describe":
        describe(args)
        return
    if args.action == "storage":
        storage(args)
        return
    require(os.geteuid() == 0, "Reset checkpoints/configuration operations require root.")
    if args.action == "plan":
        require(
            args.instance in {"a", "b"} and re.fullmatch(r"release-\d{8}-\d{2,}", args.release),
            "Invalid release or instance.",
        )
        prepare_plan(args)
        return
    plan = load_plan(args.record)
    dispatch_record(args, plan)


def dispatch_record(args, plan):
    if args.action == "field":
        require(args.value in FIELDS | {"workspace_bytes"}, "Field is not public reset metadata.")
        print(plan[args.value])
    elif args.action == "done":
        require(args.value in STEPS, "Unknown reset checkpoint.")
        # A missing checkpoint is distinct from unreadable/invalid metadata.
        raise SystemExit(0 if args.value in plan["completed"] else 3)
    elif args.action == "mark":
        mark(args.record, plan, args.value)
    elif args.action == "accept-rollback":
        require(
            plan["phase"] == "rolled_back", "Restore old configuration before accepting rollback."
        )
        event(args.record, plan, "rollback_accepted")
    else:
        replace_configs(args.record, plan, rollback=args.action == "rollback")


if __name__ == "__main__":
    try:
        main()
    except ResetError as error:
        sys.exit(str(error))
    except ValueError, OSError:
        sys.exit(
            "Reset metadata/configuration could not be validated or written. "
            "Inspect the private checkpoint; no configuration contents were printed."
        )
