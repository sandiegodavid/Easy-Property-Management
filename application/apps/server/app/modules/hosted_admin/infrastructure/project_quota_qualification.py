"""Opt-in disposable-VM harness. Never installed into a live service or portal.

Run as root Linux with EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1. Only a fresh
image under /var/lib/epm-quota-qualification-* is formatted. Retained phase
state supports an actual VM reboot before explicit verification/cleanup.
"""

import argparse
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from app.modules.hosted_admin.infrastructure.project_quota import (
    ProjectBinding,
    ProjectQuota,
    QuotaUnavailable,
    attributes,
    SET_ATTRIBUTES,
)
from app.modules.hosted_admin.infrastructure.project_sandbox import service_properties

MIB = 1024 * 1024


def call(*args, **kwargs):
    return subprocess.run(
        [str(arg) for arg in args],
        check=True,
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 60),
        **kwargs,
    ).stdout.strip()


def guard():
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or sys.flags.optimize
        or os.environ.get("EPM_RUN_PROJECT_QUOTA_QUALIFICATION") != "1"
    ):
        raise QuotaUnavailable("Explicit disposable root Linux qualification is required")


class Laboratory:
    def __init__(self, root):
        guard()
        self.root = Path(root)
        if self.root.parent != Path("/var/lib") or not self.root.name.startswith(
            "epm-quota-qualification-"
        ):
            raise QuotaUnavailable("Qualification root is outside the disposable namespace")
        if (
            self.root.is_symlink()
            or self.root.stat().st_uid != 0
            or self.root.stat().st_mode & 0o022
        ):
            raise QuotaUnavailable("Unsafe qualification directory")
        self.mount = self.root / "data"
        self.state = json.loads((self.root / "state.json").read_text())
        self.projects = {
            key: ProjectQuota(
                ProjectBinding(
                    self.mount,
                    self.mount / key,
                    self.state["uuid"],
                    values["id"],
                    values["uid"],
                )
            )
            for key, values in self.state["projects"].items()
        }

    @classmethod
    def create(cls):
        guard()
        # Kernel updates may omit the matching extra module. Fail before any
        # image, mount, account or laboratory allocation in that case.
        call("/usr/sbin/modprobe", "quota_v2")
        root = Path(tempfile.mkdtemp(prefix="epm-quota-qualification-", dir="/var/lib"))
        root.chmod(0o711)
        image, mount = root / "shared.ext4", root / "data"
        image.touch(mode=0o600, exist_ok=False)
        with image.open("r+b") as stream:
            stream.truncate(256 * MIB)
        call("/usr/sbin/mkfs.ext4", "-q", "-F", "-O", "quota,project", "-I", "256", image)
        call("/usr/sbin/tune2fs", "-Q", "prjquota", image)
        mount.mkdir(mode=0o711)
        call("/usr/bin/mount", "-o", "loop,prjquota,nodev,nosuid,noexec", image, mount)
        mount.chmod(0o711)
        filesystem = json.loads(call("/usr/bin/findmnt", "-J", "-o", "UUID", "--target", mount))
        tag = uuid4().hex[:8]
        state = {"uuid": filesystem["filesystems"][0]["uuid"], "projects": {}, "users": []}
        (root / "state.json").write_text(json.dumps(state))
        for owner in ("a", "b"):
            user = f"epm-qtest-{tag}{owner}"
            call(
                "/usr/sbin/useradd",
                "--system",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                user,
            )
            state["users"].append(user)
            (root / "state.json").write_text(json.dumps(state))
            uid = pwd.getpwnam(user).pw_uid
            for role in ("workspace", "scratch", "control"):
                key = owner + "-" + role
                project_id = 1001 + len(state["projects"])
                directory = mount / key
                directory.mkdir(mode=0o700)
                quota = ProjectQuota(
                    ProjectBinding(mount, directory, state["uuid"], project_id, uid)
                )
                quota.initialize_empty()
                os.chown(directory, uid, pwd.getpwnam(user).pw_gid)
                quota.set_limits(8 * MIB, 64)
                state["projects"][key] = {"id": project_id, "uid": uid, "user": user}
                (root / "state.json").write_text(json.dumps(state))
        shutil.copyfile(Path(__file__).with_name("quota_actor.py"), root / "actor.py")
        (root / "actor.py").chmod(0o644)
        call(
            "/usr/bin/gcc",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            Path(__file__).with_name("quota_sandbox_exec.c"),
            "-o",
            root / "sandbox-exec",
        )
        return cls(root)

    def actor(self, owner, mode, program=None, *, workload="primitive"):
        directories = {
            role: self.mount / (owner + "-" + role) for role in ("workspace", "scratch", "control")
        }
        user = self.state["projects"][owner + "-workspace"]["user"]
        args = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--pipe",
            "--wait",
            "--collect",
            "--service-type=exec",
            "--unit=epm-quota-test-" + uuid4().hex,
        ]
        for prop in service_properties(user, directories, workload=workload):
            args.extend(["--property", prop])
        args.append(str(self.root / "sandbox-exec"))
        args.extend(
            program
            or [
                sys.executable,
                str(self.root / "actor.py"),
                mode,
                str(directories["workspace"]),
                str(self.mount / "b-workspace"),
                str(directories["scratch"]),
            ]
        )
        leak = os.open(self.root / "unbudgeted-descriptor", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            return json.loads(
                call(*args, pass_fds=(leak,), timeout=200 if workload == "seed" else 60)
            )
        finally:
            os.close(leak)

    def clear_files(self, key):
        root = self.projects[key].binding.directory
        for entry in root.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def run(self):
        results = {}
        other = self.mount / "b-workspace/secret"
        other.write_text("operator B retained evidence")
        os.chown(other, self.projects["b-workspace"].binding.uid, -1)
        before = hashlib.sha256(other.read_bytes()).hexdigest()
        results["sandbox"] = self.actor("a", "attacks")
        results["compatibility"] = self.compatibility()
        for key in ("a-workspace", "a-scratch"):
            results[key + "-attribution"] = self.projects[key].verify_tree()
        results["binding_failures"] = self.binding_failures()
        assert (self.root / "unbudgeted-descriptor").stat().st_size == 0
        self.clear_files("a-workspace")
        for mode, limit in (
            ("bytes", (MIB, 512)),
            ("inodes", (8 * MIB, 32)),
            ("deleted", (MIB, 512)),
        ):
            self.projects["a-workspace"].set_limits(*limit)
            results[mode] = self.actor("a", mode)
            observed = self.projects["a-workspace"].observe()
            assert observed["allocated_bytes"] <= observed["hard_bytes"]
            assert observed["allocated_inodes"] <= observed["hard_inodes"]
            results[mode + "-usage"] = observed
            assert hashlib.sha256(other.read_bytes()).hexdigest() == before
            self.clear_files("a-workspace")
        self.projects["a-workspace"].set_limits(8 * MIB, 64)
        retained = self.projects["a-workspace"].observe()
        call("/usr/bin/umount", self.mount)
        call(
            "/usr/bin/mount",
            "-o",
            "loop,prjquota,nodev,nosuid,noexec",
            self.root / "shared.ext4",
            self.mount,
        )
        assert self.projects["a-workspace"].observe() == retained
        results["remount"] = "limits-and-attribution-retained"
        call("/usr/sbin/quotaoff", "-P", self.mount)
        results["disabled_enforcement"] = self.projects["a-workspace"].availability()
        assert results["disabled_enforcement"]["state"] == "unavailable"
        results["enforcement_negative_control"] = self.actor("a", "enforcement-off")
        self.clear_files("a-workspace")
        call("/usr/sbin/quotaon", "-P", self.mount)
        assert self.projects["a-workspace"].observe() == retained
        results["missing_mount"] = self.missing_mount()
        self.state["expected"] = {key: quota.observe() for key, quota in self.projects.items()}
        self.state["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.state["results"] = results
        report = self.report("awaiting_reboot", results)
        self.state["evidence_pin"] = self.pin(report)
        (self.root / "state.json").write_text(json.dumps(self.state, sort_keys=True))
        return report

    def binding_failures(self):
        quota = self.projects["a-workspace"]
        wrong = ProjectQuota(replace(quota.binding, filesystem_uuid=str(uuid4())))
        assert wrong.availability()["state"] == "unavailable"
        leaf = quota.binding.directory / "misattributed"
        leaf.touch(mode=0o600)
        os.chown(leaf, quota.binding.uid, -1)
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            values = list(attributes(descriptor))
            values[3] = 0
            fcntl.ioctl(descriptor, SET_ATTRIBUTES, struct.pack("=5I8s", *values))
        finally:
            os.close(descriptor)
        try:
            quota.verify_tree()
        except QuotaUnavailable as error:
            assert error.code == "admin_project_descendant_invalid"
        else:
            raise AssertionError("A project-zero descendant was accepted")
        leaf.unlink()
        link = quota.binding.directory / "unsafe-symlink"
        link.symlink_to(self.root / "shared.ext4")
        try:
            quota.verify_tree()
        except QuotaUnavailable as error:
            assert error.code == "admin_project_descendant_invalid"
        else:
            raise AssertionError("A symlink was accepted")
        link.unlink()
        return {
            "wrong_uuid": "unavailable",
            "project_zero_descendant": "rejected",
            "symlink": "rejected",
        }

    def compatibility(self):
        """A real compat executable, or a measured kernel/hardware rejection."""
        source, executable = self.root / "compat.c", self.root / "compat"
        source.write_text("int main(void) { return 42; }\n")
        compiler = (
            "/usr/bin/arm-linux-gnueabihf-gcc"
            if platform.machine() == "aarch64"
            else "/usr/bin/gcc"
        )
        args = [compiler, "-static", str(source), "-o", str(executable)]
        if platform.machine() == "x86_64":
            args.insert(1, "-m32")
        call(*args)
        try:
            result = subprocess.run([str(executable)], check=False, capture_output=True, timeout=10)
        except OSError as error:
            if error.errno != 8:  # ENOEXEC is evidence; missing compiler/loader is NOT.
                raise
            return {
                "ambient": "kernel-rejected-compat-elf",
                "errno": error.errno,
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        assert result.returncode == 42
        try:
            self.actor("a", "compat", program=[str(executable)])
        except subprocess.CalledProcessError as error:
            assert error.returncode == 159, (error.returncode, error.stderr)  # SIGSYS
            return {"ambient": "executes", "sandbox": "SIGSYS", "native_only": True}
        raise AssertionError("Compatibility code executed under the native-only sandbox")

    def missing_mount(self):
        call("/usr/bin/umount", self.mount)
        try:
            result = self.projects["a-workspace"].availability()
            assert result["state"] == "unavailable"
            return result
        finally:
            call(
                "/usr/bin/mount",
                "-o",
                "loop,prjquota,nodev,nosuid,noexec",
                self.root / "shared.ext4",
                self.mount,
            )

    def after_reboot(self):
        assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() != self.state["boot_id"]
        assert self.pin(self.report("checking", {})) == self.state["evidence_pin"]
        call(
            "/usr/bin/mount",
            "-o",
            "loop,prjquota,nodev,nosuid,noexec",
            self.root / "shared.ext4",
            self.mount,
        )
        for key, quota in self.projects.items():
            assert quota.observe() == self.state["expected"][key]
            quota.verify_tree()
        self.state["results"]["reboot"] = "limits-usage-and-attribution-retained"
        # Enforcement must still actually stop an unprivileged process after reboot.
        self.projects["a-workspace"].set_limits(MIB, 512)
        self.state["results"]["post_reboot_edquot"] = self.actor("a", "bytes")
        self.clear_files("a-workspace")
        self.projects["a-workspace"].set_limits(8 * MIB, 64)
        return self.report("passed", self.state["results"])

    @staticmethod
    def pin(report):
        return {
            key: report[key]
            for key in (
                "kernel",
                "architecture",
                "e2fsprogs",
                "systemd",
                "libseccomp",
                "tools",
                "source_sha256",
                "launcher_sha256",
                "kernel_config_sha256",
            )
        }

    def report(self, status, results):
        tools = {}
        names = [
            "mkfs.ext4",
            "tune2fs",
            "quotaon",
            "quotaoff",
            "systemd-run",
            "systemctl",
            "python3",
            "gcc",
            "mount",
            "umount",
            "findmnt",
            "useradd",
            "userdel",
            "modprobe",
            "dpkg-query",
            "pkg-config",
        ]
        if platform.machine() == "aarch64":
            names.append("arm-linux-gnueabihf-gcc")
        for name in names:
            tool = Path(shutil.which(name)).resolve()
            tools[name] = {
                "sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
                "path": str(tool),
            }
        return {
            "status": status,
            "observed": time.time(),
            "root": str(self.root),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "filesystem_uuid": self.state["uuid"],
            "kernel_config_sha256": hashlib.sha256(
                Path("/boot/config-" + platform.release()).read_bytes()
            ).hexdigest(),
            "e2fsprogs": call("/usr/bin/dpkg-query", "-W", "e2fsprogs"),
            "systemd": call("/usr/bin/systemctl", "--version").splitlines()[0],
            "libseccomp": call("/usr/bin/pkg-config", "--modversion", "libseccomp"),
            "tools": tools,
            "results": results,
            "source_sha256": {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "project_quota.py",
                    "project_sandbox.py",
                    "quota_actor.py",
                    "quota_sandbox_exec.c",
                    Path(__file__).name,
                )
            },
            "launcher_sha256": hashlib.sha256(
                (self.root / "sandbox-exec").read_bytes()
            ).hexdigest(),
            "sandbox": service_properties(
                self.state["users"][0],
                {role: self.mount / ("a-" + role) for role in ("workspace", "scratch", "control")},
            ),
        }

    def cleanup(self):
        # No lazy/forced unmount: uncertain or open effects retain their identities.
        if os.path.ismount(self.mount):
            call("/usr/bin/umount", self.mount)
        for user in self.state["users"]:
            call("/usr/sbin/userdel", user)
        shutil.rmtree(self.root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("run", "after-reboot", "cleanup"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    lab = Laboratory.create() if args.phase == "run" else Laboratory(args.root)
    if args.phase == "cleanup":
        lab.cleanup()
        return
    try:
        result = lab.run() if args.phase == "run" else lab.after_reboot()
    except Exception as error:
        # Failures remain failures; retain the exact disposable tree for diagnosis.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "root": str(lab.root),
                    "error": type(error).__name__,
                    "detail": str(error),
                }
            )
        )
        raise
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
