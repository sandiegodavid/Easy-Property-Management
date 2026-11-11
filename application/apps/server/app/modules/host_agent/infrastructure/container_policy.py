"""Closed container policy: direct host UID, no restart loop, no writable root."""

from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import Field

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import RequestHash

MiB = 1024 * 1024


class RuntimeProfile(SemanticRequest):
    version: Literal[1] = 1
    architecture: Literal["amd64", "arm64"]
    apparmor_sha256: RequestHash
    memory_bytes: Annotated[int, Field(strict=True, ge=64 * MiB, le=16 * 1024 * MiB)]
    cpu_millicores: Annotated[int, Field(strict=True, ge=100, le=8000)]
    pids: Annotated[int, Field(strict=True, ge=16, le=512)]
    file_descriptors: Annotated[int, Field(strict=True, ge=64, le=4096)]
    log_bytes: Annotated[int, Field(strict=True, ge=MiB, le=16 * MiB)]
    log_files: Annotated[int, Field(strict=True, ge=1, le=5)]


# An independent allowlist, not default-allow plus the imported ioctl-only launcher.
# No quotactl/_fd, io_uring, mount APIs, unshare/setns, bpf, ptrace, keyctl or socketcall.
SYSCALLS = """accept accept4 access arch_prctl bind brk capget chdir chmod clock_getres
clock_gettime clock_nanosleep close close_range connect copy_file_range dup dup2 dup3
 epoll_create epoll_create1 epoll_ctl epoll_pwait epoll_pwait2 epoll_wait eventfd2
 execve exit exit_group faccessat faccessat2 fadvise64 fallocate fchdir fchmod fchmodat
 fcntl fdatasync fgetxattr flistxattr flock fork fstat fstatfs fsync ftruncate futex
 futex_waitv getcpu getcwd getdents getdents64 getegid geteuid getgid getgroups
 getitimer getpeername getpgid getpgrp getpid getppid getrandom getresgid getresuid
 getrlimit getrusage getsid getsockname getsockopt gettid gettimeofday getuid
 getxattr kill lgetxattr link linkat listen listxattr llistxattr lseek lstat madvise
 membarrier memfd_create mincore mkdir mkdirat mlock mlock2 mmap mprotect mremap
 msync munlock munmap nanosleep newfstatat open openat pause pipe pipe2 poll ppoll
 pread64 preadv preadv2 prlimit64 pselect6 pwrite64 pwritev pwritev2 read readahead
 readlink readlinkat readv recvfrom recvmmsg recvmsg rename renameat renameat2
 restart_syscall rmdir rseq rt_sigaction rt_sigpending rt_sigprocmask rt_sigqueueinfo
 rt_sigreturn rt_sigsuspend rt_sigtimedwait sched_getaffinity sched_getparam
 sched_getscheduler sched_yield select sendfile sendmmsg sendmsg sendto set_robust_list
 set_tid_address setitimer setpgid setsid setsockopt shutdown sigaltstack socket
 socketpair splice stat statfs statx symlink symlinkat sync sync_file_range syncfs
 sysinfo tee tgkill time timer_create timer_delete timer_getoverrun timer_gettime
 timer_settime timerfd_create timerfd_gettime timerfd_settime times truncate umask
 uname unlink unlinkat utime utimensat utimes vfork wait4 waitid write writev""".split()


def seccomp(architecture):
    native = {"amd64": "SCMP_ARCH_X86_64", "arm64": "SCMP_ARCH_AARCH64"}.get(architecture)
    if native is None:
        raise HostAgentDenied()
    rules = [{"names": sorted(SYSCALLS), "action": "SCMP_ACT_ALLOW"}]
    # clone3's argument structure cannot be inspected by seccomp. Return ENOSYS so
    # libc falls back to clone; namespace-bearing clone arguments are still denied.
    rules.append({"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38})
    rules.append(
        {
            "names": ["clone"],
            "action": "SCMP_ACT_ALLOW",
            "args": [{"index": 0, "value": 0x7E020080, "valueTwo": 0, "op": "SCMP_CMP_MASKED_EQ"}],
        }
    )
    for request in (0x5451, 0x5401, 0x5421):  # FIOCLEX, TCGETS, FIONBIO only.
        rules.append(
            {
                "names": ["ioctl"],
                "action": "SCMP_ACT_ALLOW",
                "args": [{"index": 1, "value": request, "op": "SCMP_CMP_EQ"}],
            }
        )
    return {
        "defaultAction": "SCMP_ACT_ERRNO",
        "defaultErrnoRet": 1,
        "architectures": [native],
        "syscalls": rules,
    }


def policy_hash(profile):
    document = {
        "profile": profile.model_dump(),
        "seccomp": seccomp(profile.architecture),
        "apparmor": "epm-h02-operator-v1",
    }
    return sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def container_spec(command, allocation, targets, profile, *, network=None):
    if allocation.limits is None:
        raise HostAgentDenied()
    bindings = targets.bindings(allocation)
    roots = dict(
        zip(
            ("workspace", "control", "scratch"),
            (str(binding.directory) for binding in bindings),
            strict=True,
        )
    )
    mounts = []
    for role, target in (
        ("workspace", "/workspace"),
        ("control", "/control"),
        ("scratch", "/scratch"),
        ("scratch", "/tmp"),
        ("scratch", "/var/tmp"),
    ):
        mounts.append(
            {
                "Type": "bind",
                "Source": roots[role],
                "Target": target,
                "ReadOnly": role == "control",
                "BindOptions": {"Propagation": "rprivate"},
            }
        )
    mounts.append(
        {
            "Type": "bind",
            "Source": roots["control"] + "/data",
            "Target": "/control/data",
            "ReadOnly": False,
            "BindOptions": {"Propagation": "rprivate"},
        }
    )
    spec = {
        "Image": "sha256:" + allocation.image_digest,
        "User": f"{allocation.host_uid}:{allocation.host_gid}",
        "Env": ["PYTHONDONTWRITEBYTECODE=1", "TMPDIR=/scratch", "HOME=/scratch"],
        "Labels": {
            "epm.binding": allocation.binding_id,
            "epm.generation": str(allocation.resource_generation),
            "epm.effect": command.effect.child_id(),
            "epm.policy": policy_hash(profile),
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "AutoRemove": False,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "Privileged": False,
            "SecurityOpt": [
                "no-new-privileges=true",
                "apparmor=epm-h02-operator-v1",
                "seccomp=" + json.dumps(seccomp(profile.architecture)),
            ],
            "NetworkMode": "none",
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "host",
            "CgroupnsMode": "private",
            "PublishAllPorts": False,
            "PortBindings": {},
            "Binds": [],
            "VolumesFrom": [],
            "Links": [],
            "GroupAdd": [],
            "Devices": [],
            "DeviceRequests": [],
            "Mounts": mounts,
            "Memory": profile.memory_bytes,
            "MemorySwap": profile.memory_bytes,
            "NanoCpus": profile.cpu_millicores * 1000000,
            "PidsLimit": profile.pids,
            "ShmSize": MiB,
            "Tmpfs": {"/dev/shm": "ro,noexec,nosuid,nodev,size=1048576"},
            "Ulimits": [
                {"Name": "core", "Soft": 0, "Hard": 0},
                {
                    "Name": "nofile",
                    "Soft": profile.file_descriptors,
                    "Hard": profile.file_descriptors,
                },
            ],
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": str(profile.log_bytes), "max-file": str(profile.log_files)},
            },
        },
    }

    if network is not None:
        spec["Env"].append(f"HTTPS_PROXY=http://{network.gateway4}:{network.proxy_port}")
        spec["HostConfig"].update(NetworkMode=network.name, Dns=["127.0.0.1"], DnsSearch=["."])
        spec["NetworkingConfig"] = {"EndpointsConfig": network.endpoint()}
    return spec
