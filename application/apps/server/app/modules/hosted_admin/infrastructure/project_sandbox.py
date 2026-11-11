"""Candidate service boundary, qualified by the root Linux harness before adoption."""

import re

from app.modules.hosted_admin.infrastructure.project_quota import QuotaUnavailable


def service_properties(user, directories, *, workload="primitive"):
    if workload not in {"primitive", "seed"}:
        raise QuotaUnavailable("admin_project_sandbox_workload_invalid")
    if not re.fullmatch(r"epm-qtest-[a-z0-9]+", user) or set(directories) != {
        "workspace",
        "scratch",
        "control",
    }:
        raise QuotaUnavailable("admin_project_sandbox_binding_invalid")
    paths = [str(directories[key]) for key in ("workspace", "scratch", "control")]
    if any(
        not path.startswith("/var/lib/") or any(c.isspace() for c in path) or ":" in path
        for path in paths
    ):
        raise QuotaUnavailable("admin_project_sandbox_binding_invalid")
    if len(set(paths)) != 3 or any(".." in directories[key].parts for key in directories):
        raise QuotaUnavailable("admin_project_sandbox_binding_invalid")
    return [
        f"User={user}",
        "UMask=0077",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "RestrictSUIDSGID=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateDevices=yes",
        "ProtectKernelTunables=yes",
        "ProtectKernelModules=yes",
        "ProtectControlGroups=yes",
        "RestrictNamespaces=yes",
        "LockPersonality=yes",
        "SystemCallArchitectures=native",
        "SystemCallFilter=@system-service",
        "SystemCallFilter=~quotactl quotactl_fd @mount @privileged @resources",
        "SystemCallErrorNumber=EPERM",
        "ReadWritePaths=" + " ".join(paths),
        f"Environment=TMPDIR={paths[1]}",
        f"BindPaths={paths[1]}:/tmp {paths[1]}:/var/tmp",
        "TemporaryFileSystem=/dev/shm:ro /run:ro",
        "ProtectProc=invisible",
        "TasksMax=32",
        "MemoryMax=512M" if workload == "seed" else "MemoryMax=128M",
        "RuntimeMaxSec=180" if workload == "seed" else "RuntimeMaxSec=30",
    ]
