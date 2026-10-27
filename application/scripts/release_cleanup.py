"""Conservative installed-release cleanup; never removes data or checkpoints."""

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

RELEASES = Path("/opt/epm/releases")
REFERENCES = (
    Path("/etc/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/run/systemd/system"),
    Path("/etc/crontab"),
    Path("/etc/cron.d"),
    Path("/etc/cron.daily"),
    Path("/etc/cron.hourly"),
    Path("/etc/cron.weekly"),
    Path("/etc/cron.monthly"),
    Path("/var/spool/cron"),
    Path("/etc/epm"),
    Path("/var/lib/epm-a/hosted-local.json"),
    Path("/var/lib/epm-b/hosted-local.json"),
)
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def references_in(data, root):
    prefix = re.escape(str(root).encode())
    return {name.decode() for name in re.findall(prefix + rb"/([A-Za-z0-9][A-Za-z0-9._-]*)", data)}


def scan_path(path):
    """Scan reference files without traversing directory symlinks."""
    if path.is_symlink():
        yield path, os.readlink(path).encode()
    if path.is_file():
        yield path, path.read_bytes()
    elif path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            yield from scan_path(child)
    elif path.exists() and not path.is_symlink():
        raise ValueError(f"Cannot inspect non-regular reference: {path}")


def protect_entry(root, entry, protect):
    require(NAME.fullmatch(entry.name) is not None, f"Unexpected release entry: {entry.name}")
    if entry.is_symlink() or not entry.is_dir():
        protect(entry.name, "not a regular release directory")
        if entry.is_symlink():
            resolved = entry.resolve(strict=True)
            if resolved.is_relative_to(root):
                protect(resolved.relative_to(root).parts[0], f"release alias: {entry.name}")
        return
    protect_checkpoints(root, entry, protect)


def protect_checkpoints(root, entry, protect):
    state = entry / "wizard-state"
    if state.exists() or state.is_symlink():
        if state.is_symlink() or not state.is_dir():
            protect(entry.name, "unexpected checkpoint path")
        else:
            records = [p for p in state.iterdir() if p.name != "archive-sha256.txt"]
            if records:
                protect(
                    entry.name, "contains deployment/reset checkpoints; retain recovery history"
                )
            for path, data in scan_path(state):
                for name in references_in(data, root):
                    protect(name, f"rollback reference: {path}")


def inventory(root, sources, effective, processes, keep):
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode), "Release root must be a real directory.")
    reasons = {}

    def protect(name, reason):
        reasons.setdefault(name, set()).add(reason)

    for name in keep:
        require(NAME.fullmatch(name) is not None, "Invalid rollback release name.")
        require((root / name).is_dir(), f"Retained release does not exist: {name}")
        protect(name, "explicit rollback retention")
    for name in references_in(effective, root):
        protect(name, "effective A/B service command")
    for path, data in processes:
        for name in references_in(data, root):
            protect(name, f"running process: {path}")
    entries = sorted(root.iterdir())
    for entry in entries:
        protect_entry(root, entry, protect)
    for source in sources:
        for path, data in scan_path(source):
            for name in references_in(data, root):
                protect(name, f"configuration/job reference: {path}")
    return {entry.name: sorted(reasons.get(entry.name, ())) for entry in entries}


def process_references():
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        for leaf in ("cmdline", "maps", "cwd", "exe"):
            path = process / leaf
            try:
                data = os.readlink(path).encode() if leaf in {"cwd", "exe"} else path.read_bytes()
                yield path, data
            except FileNotFoundError:
                continue  # Process exited, or a kernel thread has no executable.
            except ProcessLookupError:
                continue  # Process exited during inspection.


def host_inventory(keep):
    commands = []
    for instance in ("a", "b"):
        result = subprocess.run(
            ["systemctl", "show", f"epm-hosted@{instance}.service", "-p", "ExecStart", "--value"],
            check=True,
            capture_output=True,
        )
        require(
            references_in(result.stdout, RELEASES),
            f"Cannot identify instance {instance}'s release.",
        )
        commands.append(result.stdout)
    return inventory(RELEASES, REFERENCES, b"\n".join(commands), process_references(), keep)


def remove_release(name, keep):
    require(NAME.fullmatch(name) is not None, "Invalid release name.")
    current = host_inventory(keep)  # Recheck all protections immediately before removal.
    require(name in current, "Release does not exist.")
    require(not current[name], "Release is protected: " + "; ".join(current[name]))
    target = RELEASES / name
    # Never cross a mounted workspace, even if it was placed inside a release.
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
        require(not mount.is_relative_to(target), "Release contains a mount; inspect manually.")
    for directory in (RELEASES.parent, RELEASES, target):
        info = directory.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            "Release paths must be root-owned real directories, not writable by other users.",
        )
    require(shutil.rmtree.avoids_symlink_attacks, "Safe directory removal is unavailable.")
    shutil.rmtree(target)
    print(f"Removed installed release: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "check", "remove"))
    parser.add_argument("--release")
    parser.add_argument("--keep", action="append", required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, "Run this helper through the VM cleanup wizard with sudo.")
    if args.action == "remove":
        require(args.release is not None, "Select one exact release.")
        remove_release(args.release, args.keep)
        return
    entries = host_inventory(args.keep)
    if args.action == "check":
        require(args.release in entries, "Select an installed release.")
        require(not entries[args.release], "Protected: " + "; ".join(entries[args.release]))
        print(f"Eligible for removal: {RELEASES / args.release}")
    else:
        for name, reasons in entries.items():
            print(
                f"{name}: " + ("KEEP — " + "; ".join(reasons) if reasons else "eligible for review")
            )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Cleanup stopped: {error}") from error
