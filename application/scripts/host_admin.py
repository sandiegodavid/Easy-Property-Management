"""Root-only inventory discovery, adoption and private maintenance admission.

Install this helper and its sibling files in /opt/epm/admin before use. It has
no operator HTTP routes and never provisions, invites or grants business access.
"""

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import sqlite3
import stat
import subprocess
import sys

if __package__:
    from .host_inventory import (
        KEY,
        RESERVED_KEYS,
        MAX_INSTANCES,
        MAX_RECORD_BYTES,
        HostInventory,
        Instance,
        InventoryError,
        MaintenanceBusy,
        MaintenanceRequest,
        digest_json,
        new_identity,
    )
else:
    # -I excludes the script directory. Admit only a protected installation,
    # then make this exact sibling library importable.
    directory = Path(__file__).absolute().parent
    for candidate in (directory / "host_inventory.py", directory, *directory.parents):
        info = candidate.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise SystemExit("Admin tooling must be installed in a protected root-owned directory.")
    sys.path.insert(0, str(directory))
    from host_inventory import (
        KEY,
        RESERVED_KEYS,
        MAX_INSTANCES,
        MAX_RECORD_BYTES,
        HostInventory,
        Instance,
        InventoryError,
        MaintenanceBusy,
        MaintenanceRequest,
        digest_json,
        new_identity,
    )

WORKSPACE_BYTES = 250 * 1024 * 1024
HOSTED_ARG_COUNT = 10
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_BASELINES = 10_000
MAX_RELEASE_ARTIFACTS = 1000
PRIVATE_DIRECTORY_MODE = 0o700
COMMAND_TIMEOUT_SECONDS = 15
RELEASE = re.compile(r"release-\d{8}-\d{2,}")
RESOURCE_FIELDS = (
    "User",
    "Group",
    "MemoryHigh",
    "MemoryMax",
    "CPUQuotaPerSecUSec",
    "RequiresMountsFor",
)
UNIT_FIELDS = ("FragmentPath", "DropInPaths")
DEPLOYMENT_FIELDS = frozenset(
    {
        "deployment_mode",
        "public_origin",
        "identity_issuer",
        "identity_audience",
        "workspace_id",
        "operator_id",
        "allowed_email",
        "administrator_contact",
        "administration_database",
        "storage_volume",
        "storage_image",
        "enabled_at",
        "expires_at",
        "capabilities",
    }
)
LOCAL_FIELDS = frozenset(
    {"localWorkspacePath", "backupDestinationPath", "fileStorageProvider", "s3Bucket", "s3Prefix"}
)
MAX_DEMO_WINDOW = timedelta(days=14)
CAPABILITIES = frozenset({"records.read", "records.write", "files.read", "files.write"})
ADMIN_TOOLS = (
    "host_admin.py",
    "host_inventory.py",
    "release_cleanup.py",
    "epm-release-vm.sh",
    "epm-release-cleanup-vm.sh",
)


@dataclass(frozen=True)
class HostPaths:
    control: Path = Path("/var/lib/epm-admin")
    configs: Path = Path("/etc/epm")
    data: Path = Path("/var/lib")
    backups: Path = Path("/var/backups")
    releases: Path = Path("/opt/epm/releases")
    systemd: Path = Path("/etc/systemd/system")
    systemd_runtime: Path = Path("/run/systemd/system")
    systemd_vendor: Path = Path("/usr/lib/systemd/system")
    tools: Path = Path("/opt/epm/admin")
    mountinfo: Path = Path("/proc/self/mountinfo")
    devices: Path = Path("/sys/dev/block")
    fstab: Path = Path("/etc/fstab")
    security_root: Path = Path("/")
    owner_uid: int = 0


def protected(path, paths, uid=0, *, regular=True, private=False):
    if not path.is_absolute() or paths.security_root not in (path, *path.parents):
        raise InventoryError("Host resource is outside the trusted root.")
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or info.st_uid not in {paths.owner_uid, uid}
            or info.st_mode & 0o022
        ):
            raise InventoryError("Host resource ownership or path is unsafe.")
        if candidate == paths.security_root:
            break
    info = path.lstat()
    expected = stat.S_ISREG if regular else stat.S_ISDIR
    if not expected(info.st_mode) or (private and info.st_mode & 0o077):
        raise InventoryError("Host resource has an unsafe type or permissions.")


def read_json(path, paths, uid=0):
    protected(path, paths, uid)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise InventoryError("Host record exceeds its size bound.")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise InventoryError("Host configuration must be an object.")
    return value


def read_bounded_text(path):
    with path.open(encoding="utf-8") as stream:
        value = stream.read(MAX_RECORD_BYTES + 1)
    if len(value) > MAX_RECORD_BYTES:
        raise InventoryError("Host observation exceeds its size bound.")
    return value


def validate_nonsecret_configuration(deployment, local):
    if set(deployment) != DEPLOYMENT_FIELDS or not all(
        isinstance(value, str) for key, value in deployment.items() if key != "capabilities"
    ):
        raise InventoryError("Hosted deployment fields do not match the non-secret contract.")
    if set(local) - LOCAL_FIELDS or not all(
        value is None or isinstance(value, str) for value in local.values()
    ):
        raise InventoryError("Hosted local configuration fields are invalid.")
    if local.get("fileStorageProvider", "local") != "local" or local.get("s3Bucket"):
        raise InventoryError("Hosted demo live storage must remain local.")
    capabilities = deployment["capabilities"]
    if not isinstance(capabilities, list) or any(
        not isinstance(value, str) for value in capabilities
    ):
        raise InventoryError("Hosted capability declaration is invalid.")
    admitted = set(capabilities)
    if not {"records.read"} <= admitted <= CAPABILITIES or (
        "files.write" in admitted and not {"files.read", "records.write"} <= admitted
    ):
        raise InventoryError("Hosted capability declaration is invalid.")
    start, end = (
        datetime.fromisoformat(deployment[field]) for field in ("enabled_at", "expires_at")
    )
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= MAX_DEMO_WINDOW
    ):
        raise InventoryError("Hosted deployment dates are invalid.")


def file_digest(path, paths):
    protected(path, paths)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_ARTIFACT_BYTES:
            raise InventoryError("Release artifact exceeds its verification bound.")
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise InventoryError("Release artifact exceeds its verification bound.")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise InventoryError("Release artifact changed during observation.")
    return digest.hexdigest()


class HostDiscovery:
    def __init__(self, paths=HostPaths(), *, run=subprocess.run):
        self.paths, self.run = paths, run

    def systemctl(self, *arguments):
        result = self.run(
            ["/usr/bin/systemctl", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).stdout
        if len(result) > MAX_RECORD_BYTES:
            raise InventoryError("Systemd observation exceeds its size bound.")
        return result

    def keys(self):
        keys = self._unit_keys() | self._file_keys() | self._fstab_keys() | self._data_keys()
        if len(keys) > MAX_INSTANCES:
            raise InventoryError("Host discovery exceeds its instance bound.")
        return sorted(keys)

    def _unit_keys(self):
        keys = set()
        for command in ("list-units", "list-unit-files"):
            output = self.systemctl(
                command, "--all", "--plain", "--no-legend", "epm-hosted@*.service"
            )
            for line in output.splitlines():
                fields = line.split()
                if not fields:
                    continue
                unit = fields[1] if fields[0] == "●" and len(fields) > 1 else fields[0]
                match = re.fullmatch(r"epm-hosted@([a-z0-9][a-z0-9-]{0,31})\.service", unit)
                if match:
                    keys.add(match[1])
                elif unit != "epm-hosted@.service":
                    raise InventoryError("Hosted service discovery returned an unknown unit name.")
        return keys

    def _file_keys(self):
        keys = set()
        for path in self.paths.configs.glob("hosted-*.json"):
            key = path.name.removeprefix("hosted-").removesuffix(".json")
            if not KEY.fullmatch(key):
                raise InventoryError("Hosted configuration has an invalid instance name.")
            keys.add(key)
        for directory in (
            self.paths.systemd,
            self.paths.systemd_runtime,
            self.paths.systemd_vendor,
        ):
            keys |= self._dropin_keys(directory)
        return keys

    @staticmethod
    def _dropin_keys(directory):
        keys = set()
        for path in directory.glob("epm-hosted@*.service*"):
            match = re.fullmatch(
                r"epm-hosted@([a-z0-9][a-z0-9-]{0,31})\.service(?:\.d)?", path.name
            )
            if match:
                keys.add(match[1])
        return keys

    def _data_keys(self):
        keys = set()
        for path in self.paths.data.glob("epm-*"):
            key = path.name.removeprefix("epm-")
            if KEY.fullmatch(key) and key not in RESERVED_KEYS:
                keys.add(key)
        for path in (self.paths.data / "epm-volumes").glob("epm-*.ext4"):
            key = path.name.removeprefix("epm-").removesuffix(".ext4")
            if not KEY.fullmatch(key) or key in RESERVED_KEYS:
                raise InventoryError("Unrecognized retained volume allocation.")
            keys.add(key)
        for path in (self.paths.data / "epm-recovery").glob("*"):
            if KEY.fullmatch(path.name) and path.name not in RESERVED_KEYS:
                keys.add(path.name)
        return keys

    def _fstab_keys(self):
        keys = set()
        protected(self.paths.fstab, self.paths)
        for line in read_bounded_text(self.paths.fstab).splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            for field in line.split()[:2]:
                match = re.search(
                    re.escape(str(self.paths.data)) + r"/epm-([a-z0-9][a-z0-9-]{0,31})(?:/|$)",
                    field,
                )
                if match and match[1] not in RESERVED_KEYS:
                    keys.add(match[1])
                image = re.search(r"/epm-volumes/epm-([a-z0-9][a-z0-9-]{0,31})\.ext4$", field)
                if image:
                    keys.add(image[1])
        return keys

    def observe(self, key):
        if not KEY.fullmatch(key):
            raise InventoryError("Invalid instance key.")
        paths = self.paths
        deployment_path = paths.configs / f"hosted-{key}.json"
        deployment = read_json(deployment_path, paths)
        if (
            set(deployment) != DEPLOYMENT_FIELDS
            or deployment.get("deployment_mode") != "hosted_demo"
        ):
            raise InventoryError("Only synthetic hosted demo deployments can be adopted.")
        service, argv, release, identity, local_path = self._service(key)
        user = f"epm-{key}"
        local = read_json(local_path, paths)
        validate_nonsecret_configuration(deployment, local)
        workspace = Path(local["localWorkspacePath"])
        manifest = read_json(workspace / "workspace.json", paths, identity.pw_uid)
        if manifest.get("workspaceId") != deployment.get("workspace_id"):
            raise InventoryError("Workspace and deployment identities differ.")
        volume, image = Path(deployment["storage_volume"]), Path(deployment["storage_image"])
        if volume != paths.data / user / "volume" or volume not in workspace.parents:
            raise InventoryError("Workspace is outside the allocated instance volume.")
        protected(image, paths, private=True)
        info = image.stat()
        if info.st_size != WORKSPACE_BYTES or info.st_blocks * 512 < info.st_size:
            raise InventoryError("Backing image is not a fully allocated 250 MiB volume.")
        protected(volume, paths, identity.pw_uid, regular=False)
        if str(volume) not in shlex.split(service["RequiresMountsFor"]):
            raise InventoryError("Effective service does not require its allocated mount.")
        mount = self._mount(volume, image)
        database, binding_reference = self._binding(deployment, user, identity.pw_uid)
        release_evidence = self._release(release)
        resource_values = {field: service.get(field, "") for field in RESOURCE_FIELDS}
        if not all(resource_values.values()):
            raise InventoryError("Effective resource profile is incomplete.")
        facts = {
            "deployment": deployment,
            "local": local,
            "release": release_evidence,
            "resources": resource_values,
            "mount": mount,
            "binding_reference": binding_reference,
            "service_files": self._service_files(service),
            "admin_tools": {name: file_digest(paths.tools / name, paths) for name in ADMIN_TOOLS},
            "tunnel": self._tunnel(),
            "provider_references": {
                "issuer": deployment["identity_issuer"],
                "audience": deployment.get("identity_audience"),
                "hostname": deployment["public_origin"],
                "provider_verification": "not_performed",
            },
        }
        fields = {
            "key": key,
            "operator_id": deployment["operator_id"],
            "workspace_id": deployment["workspace_id"],
            "email": deployment["allowed_email"],
            "hostname": deployment["public_origin"].removeprefix("https://"),
            "port": int(argv[9]),
            "user": user,
            "mount": str(volume),
            "image": str(image),
            "release": release.name,
            "profile": "observed-" + digest_json(resource_values)[:16],
            "template": "unknown",
            "config_digest": digest_json(facts),
            "local_config": str(local_path),
            "access_database": str(database),
            "workspace": str(workspace),
        }
        return {
            "fields": fields,
            "facts": facts,
            "digest": digest_json(facts),
            "checked_at": datetime.now(UTC).isoformat(),
            "recovery_status": "unverified",
            "rollback_acceptance": "not_recorded",
        }

    def source_command_ready(self, instance):
        """Grant-side checks; containment does not depend on a working business volume."""
        service, argv, release, _, local_path = self._service(instance.key)
        profile = (
            "observed-"
            + digest_json({field: service.get(field, "") for field in RESOURCE_FIELDS})[:16]
        )
        if (
            release.name != instance.release
            or str(local_path) != instance.local_config
            or int(argv[9]) != instance.port
            or profile != instance.profile
            or self.systemctl("is-active", f"epm-hosted@{instance.key}.service").strip() != "active"
        ):
            raise InventoryError("Registered source runtime is not ready.")
        self._release(release)

    def _service(self, key):
        paths = self.paths
        deployment_path = paths.configs / f"hosted-{key}.json"
        output = self.systemctl(
            "show",
            f"epm-hosted@{key}.service",
            "--no-pager",
            "-p",
            "ExecStart",
            *[part for field in (*RESOURCE_FIELDS, *UNIT_FIELDS) for part in ("-p", field)],
        )
        service = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        executable = re.fullmatch(
            r"\{ path=([^ ;]+) ; argv\[\]=([^;]+) ;.*\}", service.get("ExecStart", "")
        )
        if executable is None:
            raise InventoryError("Effective service command cannot be identified safely.")
        argv = shlex.split(executable[2].strip())
        if (
            len(argv) != HOSTED_ARG_COUNT
            or argv[1:4] != ["-m", "app", "--config"]
            or argv[5:7] != ["serve-hosted", "--deployment"]
            or argv[8] != "--port"
            or argv[0] != executable[1]
        ):
            raise InventoryError("Effective service command is not the supported hosted command.")
        interpreter = Path(argv[0])
        release = interpreter.parent.parent.parent
        if (
            release.parent != paths.releases
            or not RELEASE.fullmatch(release.name)
            or interpreter != release / "venv/bin/python"
        ):
            raise InventoryError("Effective service does not select a fixed installed release.")
        user = f"epm-{key}"
        identity = pwd.getpwnam(user)
        if service.get("User") != user or service.get("Group") != user:
            raise InventoryError("Effective service identity differs from the allocated user.")
        local_path = Path(argv[4])
        if local_path.parent != paths.data / user or Path(argv[7]) != deployment_path:
            raise InventoryError("Service configuration paths differ from the allocated instance.")
        return service, argv, release, identity, local_path

    def _service_files(self, service):
        fragment = service.get("FragmentPath")
        if not fragment:
            raise InventoryError("Effective service fragment is unknown.")
        files = [fragment, *shlex.split(service.get("DropInPaths", ""))]
        return {value: file_digest(Path(value), self.paths) for value in files}

    def _tunnel(self):
        output = self.systemctl(
            "show",
            "epm-cloudflared.service",
            "--no-pager",
            "-p",
            "ExecStart",
            "-p",
            "UnitFileState",
        )
        fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        command = re.fullmatch(
            r"\{ path=([^ ;]+) ; argv\[\]=([^;]+) ;.*\}", fields.get("ExecStart", "")
        )
        if command is None:
            raise InventoryError("Effective tunnel configuration is unknown.")
        argv = shlex.split(command[2])
        if (
            any(value.startswith(("--token", "--credentials-contents")) for value in argv)
            or "--config" not in argv
            or argv.index("--config") + 1 >= len(argv)
        ):
            raise InventoryError(
                "Tunnel requires a protected configuration file, without token arguments."
            )
        config = Path(argv[argv.index("--config") + 1])
        return {
            "configuration_digest": file_digest(config, self.paths),
            "boot_policy": fields.get("UnitFileState", "unknown"),
            "provider_verification": "not_performed",
        }

    def _binding(self, deployment, user, uid):
        paths = self.paths
        database = Path(deployment["administration_database"])
        if database.parent != paths.data / user / "access":
            raise InventoryError(
                "Access store is outside the allocated instance authority directory."
            )
        protected(database, paths, uid, private=True)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            binding = connection.execute(
                "SELECT id, workspace_id, issuer, email, subject FROM hosted_operator"
            ).fetchall()
        expected = (
            deployment["operator_id"],
            deployment["workspace_id"],
            deployment["identity_issuer"],
            deployment["allowed_email"],
        )
        if len(binding) != 1 or binding[0][:4] != expected:
            raise InventoryError("Retained access binding differs from the deployment.")
        # Session/token tables are deliberately never read or copied.
        binding_reference = digest_json({"binding": binding[0]})
        return database, binding_reference

    def _mount(self, volume, image):
        matches = []
        for line in read_bounded_text(self.paths.mountinfo).splitlines():
            fields = line.split()
            separator = fields.index("-")
            if fields[4] == str(volume):
                matches.append((fields, separator))
        if len(matches) != 1:
            raise InventoryError("Allocated volume is not one dedicated mount.")
        fields, separator = matches[0]
        if (
            fields[3] != "/"
            or fields[separator + 1] != "ext4"
            or not {"rw", "nodev", "nosuid", "noexec"}.issubset(fields[5].split(","))
            or not re.fullmatch(r"\d+:\d+", fields[2])
        ):
            raise InventoryError("Allocated mount identity or options are unsafe.")
        device = self.paths.devices / fields[2]
        if (device / "size").read_text().strip() != str(WORKSPACE_BYTES // 512) or (
            device / "loop/backing_file"
        ).read_text().strip() != str(image):
            raise InventoryError("Mount block device differs from the allocated backing image.")
        return {
            "volume": str(volume),
            "image": str(image),
            "filesystem": "ext4",
            "options": sorted(fields[5].split(",")),
        }

    def _release(self, release):
        manifest = release / "SHA256SUMS"
        protected(manifest, self.paths)
        if manifest.stat().st_size > MAX_RECORD_BYTES:
            raise InventoryError("Release manifest exceeds its bound.")
        count = 0
        for line in read_bounded_text(manifest).splitlines():
            match = re.fullmatch(r"([a-f0-9]{64}) [ *](.+)", line)
            if not match:
                raise InventoryError("Installed release manifest is invalid.")
            relative = Path(match[2])
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or file_digest(release / relative, self.paths) != match[1]
            ):
                raise InventoryError("Installed release does not match its manifest.")
            count += 1
            if count > MAX_RELEASE_ARTIFACTS:
                raise InventoryError("Release manifest exceeds its artifact bound.")
        if not count:
            raise InventoryError("Installed release manifest is empty.")
        return {
            "release": release.name,
            "manifest_digest": file_digest(manifest, self.paths),
            "source_digest": file_digest(release / "SOURCE_COMMIT.txt", self.paths),
        }

    def report(self, registered):
        by_key = {item.key: item for item in registered}
        observed, problems = {}, []
        keys = sorted(set(self.keys()) | set(by_key))
        for key in keys:
            try:
                item = self.observe(key)
                observed[key] = item
                if key not in by_key:
                    problems.append({"key": key, "kind": "unmanaged"})
                else:
                    expected = asdict(by_key[key])
                    changed = [
                        name
                        for name, value in item["fields"].items()
                        if name != "template" and expected[name] != value
                    ]
                    if changed:
                        problems.append({"key": key, "kind": "changed", "fields": changed})
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                IndexError,
                sqlite3.Error,
                subprocess.SubprocessError,
            ) as error:
                # A malformed observation remains unavailable without exposing
                # submitted values or aborting other instance observations.
                detail = (
                    str(error)
                    if isinstance(error, InventoryError)
                    else "Host observation is malformed or inaccessible."
                )
                problems.append({"key": key, "kind": "unverifiable", "detail": detail})
        return {
            "observed": observed,
            "discrepancies": problems,
            "checked_at": datetime.now(UTC).isoformat(),
            "digest": digest_json({key: value["digest"] for key, value in observed.items()}),
        }


def publish_baseline(store, observation):
    data = (json.dumps(observation, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > MAX_RECORD_BYTES:
        raise InventoryError("Baseline exceeds its size bound.")
    digest = hashlib.sha256(data).hexdigest()
    directory = store.path.parent / "baselines"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != store.owner_uid or info.st_mode & 0o077:
        raise InventoryError("Baseline directory is unsafe.")
    target = directory / f"{digest}.json"
    try:
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != data:
            raise InventoryError("Retained baseline does not match its digest.") from None
        return digest
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return digest


def protected_releases(store):
    registered = store.list()
    releases = {item.release for item in registered} | set(store.upgrade_releases())
    expected = {item.baseline_digest for item in registered}
    found = set()
    directory = store.path.parent / "baselines"
    if not directory.exists():
        if releases:
            raise InventoryError("Registered baseline evidence is missing.")
        return []
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != store.owner_uid or info.st_mode & 0o077:
        raise InventoryError("Baseline directory is unsafe.")
    for index, path in enumerate(directory.iterdir()):
        if index >= MAX_BASELINES:
            raise InventoryError("Retained baselines exceed their inspection bound.")
        name = baseline_release(path, store)
        releases.add(name)
        found.add(path.stem)
    if expected - found:
        raise InventoryError("Registered baseline evidence is missing.")
    return sorted(releases)


def baseline_release(path, store):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != store.owner_uid
        or info.st_mode & 0o077
        or info.st_size > MAX_RECORD_BYTES
    ):
        raise InventoryError("Retained baseline is unsafe.")
    data = path.read_bytes()
    if path.name != hashlib.sha256(data).hexdigest() + ".json":
        raise InventoryError("Retained baseline digest differs.")
    observation = json.loads(data)
    if observation["digest"] != digest_json(observation["facts"]):
        raise InventoryError("Retained baseline observation differs from its facts.")
    name = observation["facts"]["release"]["release"]
    if not RELEASE.fullmatch(name):
        raise InventoryError("Retained baseline release is invalid.")
    return name


def adopt(store, discovery, key, expected_digest):
    protected_releases(store)
    observation = discovery.observe(key)
    if observation["digest"] != expected_digest:
        raise InventoryError("Host observation changed; review discovery again before adoption.")
    existing = [item for item in store.list() if item.key == key]
    if existing:
        protected_releases(store)
        if existing[0].config_digest == observation["fields"]["config_digest"]:
            return existing[0]
        raise InventoryError(
            "Registered instance differs; use explicit maintenance reconciliation."
        )
    identifier, allocation = new_identity()
    record = Instance(
        **observation["fields"],
        instance_id=identifier,
        allocation_id=allocation,
        baseline_digest=publish_baseline(store, observation),
    )
    store.register(record)
    return record


def lock_host(store):
    store._check_directory()
    path = store.path.parent / "maintenance.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != store.owner_uid or info.st_mode & 0o077:
        os.close(descriptor)
        raise InventoryError("Maintenance lock is unsafe.")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise MaintenanceBusy("Another host maintenance operation is running.") from error
    mark_lock(descriptor, None)
    return descriptor


def mark_lock(descriptor, identifier):
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, json.dumps({"operation_id": identifier, "pid": os.getpid()}).encode())
    os.fsync(descriptor)


def require_maintenance(store, identifier):
    operation = store.maintenance(identifier)
    if operation["state"] != "running":
        raise InventoryError("Maintenance operation is not running.")
    try:
        descriptor = lock_host(store)
    except MaintenanceBusy as error:
        path = store.path.parent / "maintenance.lock"
        metadata = json.loads(read_bounded_text(path))
        if metadata.get("operation_id") != identifier:
            raise InventoryError("Maintenance lock belongs to a different operation.") from error
        return operation
    else:
        os.close(descriptor)
        raise InventoryError("Maintenance holder is no longer running; explicitly resume it.")


def run_maintenance(store, discovery, kind, action, request=None):
    request = request or MaintenanceRequest()
    key, release, resume = request.key, request.release, request.resume
    if kind not in {"release", "cleanup"}:
        raise InventoryError("Unsupported executable maintenance kind.")
    descriptor = lock_host(store)
    try:
        registered = store.list()
        protected_releases(store)
        if not registered:
            raise InventoryError("Adopt existing instances before private maintenance.")
        report = discovery.report(registered)
        registered_keys = {item.key for item in registered}
        if any(problem["key"] not in registered_keys for problem in report["discrepancies"]) or (
            report["discrepancies"] and not resume
        ):
            raise InventoryError("Host inventory discrepancies block private maintenance.")
        script = discovery.paths.tools / (
            "epm-release-vm.sh" if kind == "release" else "epm-release-cleanup-vm.sh"
        )
        protected(script, discovery.paths)
        login = os.environ.get("SUDO_USER", "")
        account = pwd.getpwnam(login)
        if account.pw_uid == 0 or login.startswith("epm-"):
            raise InventoryError("Run private maintenance from the administrator login account.")
        if resume:
            operation = store.maintenance(resume)
            intent = store.maintenance_intent(resume)
            check_intent_observation(intent, report, operation["kind"], operation["action"])
        elif (kind == "release" and not key) or (action != "backup" and not release):
            raise InventoryError("Select the instance and intended release before maintenance.")
        identifier = store.begin_maintenance(
            kind,
            action,
            report["digest"],
            request=MaintenanceRequest(resume=resume, key=key, release=release),
        )
        intent = store.maintenance_intent(identifier)
        mark_lock(descriptor, identifier)
        environment = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "TERM": os.environ.get("TERM", "dumb"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "EPM_HOST_MAINTENANCE_ID": identifier,
            "EPM_ACTION": action,
            "EPM_INSTANCE": intent["key"] or "",
            "EPM_RELEASE": intent["release"] or "",
            "EPM_DEPLOY_RECORD": intent["checkpoint"] or "",
        }
        print(
            f"Maintenance {identifier} started; keep this ID for explicit resume/reconciliation.",
            flush=True,
        )
        result_code = 1
        try:
            result = subprocess.run(
                ["/usr/sbin/runuser", "-u", login, "--", "/bin/bash", str(script)],
                env=environment,
                check=False,
                pass_fds=(descriptor,),
            )
            result_code = result.returncode
        except BaseException as error:
            try:
                store.finish_maintenance(identifier, result_code)
            except (OSError, sqlite3.Error, InventoryError) as journal_error:
                error.add_note(
                    f"Maintenance {identifier} needs journal reconciliation: "
                    f"{type(journal_error).__name__}."
                )
            raise
        else:
            store.finish_maintenance(identifier, result_code)
            return identifier, result_code
    finally:
        os.close(descriptor)


def reconcile(store, discovery, identifier, expected_digest):
    descriptor = lock_host(store)
    try:
        registered = store.list()
        report = discovery.report(registered)
        if (
            report["digest"] != expected_digest
            or set(report["observed"]) != {item.key for item in registered}
            or any(problem["kind"] != "changed" for problem in report["discrepancies"])
        ):
            raise InventoryError(
                "Observed inventory is incomplete or changed; review discovery again."
            )
        operation = store.maintenance(identifier)
        check_intent_observation(
            store.maintenance_intent(identifier), report, operation["kind"], operation["action"]
        )
        if operation["state"] == "running":
            # We hold the exclusive lock, so no admitted wizard remains alive.
            # Reconciliation observes a crashed holder; it does not rerun it.
            store.finish_maintenance(identifier, -1)
        allowed = {"release", "config_digest", "profile"}
        if operation["action"] in {"reset-demo", "resume-reset", "rollback-reset"}:
            allowed |= {"workspace_id", "workspace", "access_database"}
        replacements = []
        for old in registered:
            observation = report["observed"][old.key]
            fields = {
                key: value for key, value in observation["fields"].items() if key != "template"
            }
            changed = {key for key, value in fields.items() if getattr(old, key) != value}
            if changed - allowed:
                raise InventoryError(
                    "Observed allocation or authority changed outside this maintenance action."
                )
            if changed:
                replacements.append(
                    (
                        old,
                        replace(
                            old,
                            **fields,
                            revision=old.revision + 1,
                            baseline_digest=publish_baseline(store, observation),
                        ),
                    )
                )
        store.reconcile(identifier, replacements, report["digest"])
    finally:
        os.close(descriptor)


def check_intent_observation(intent, report, kind, action):
    """Keep unrelated sources unchanged, even when a target cutover is incomplete."""
    if set(report["observed"]) != set(intent["sources"]):
        raise InventoryError("Observed inventory differs from the maintenance sources.")
    for key, source in intent["sources"].items():
        observed = report["observed"][key]["fields"]
        if kind == "reconciliation":
            continue
        if intent["scope"] == "instance" and key == intent["key"]:
            allowed = {"release", "config_digest", "profile", "template"}
            if action == "backup":
                allowed = {"template"}
            if action == "reset-demo":
                allowed |= {"workspace_id", "workspace", "access_database"}
            if any(
                value != source[field] for field, value in observed.items() if field not in allowed
            ):
                raise InventoryError(
                    "Observed allocation or authority differs from maintenance intent."
                )
            if observed["release"] not in {source["release"], intent["release"]}:
                raise InventoryError("Observed release differs from maintenance intent.")
        elif observed["config_digest"] != source["config_digest"]:
            raise InventoryError("Changes are outside the maintenance target.")


def private_directory(path, paths, identity):
    """Create a fixed derived directory without following a substituted target."""
    protected(path.parent, paths, identity.pw_uid, regular=False)
    created = False
    try:
        path.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        expected_owner = paths.owner_uid if created else identity.pw_uid
        if info.st_uid != expected_owner or stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
            raise InventoryError("Recovery directory has unexpected ownership or permissions.")
        if created:
            os.fchown(descriptor, identity.pw_uid, identity.pw_gid)
    finally:
        os.close(descriptor)


def prepare_backup(args, store, paths):
    operation = require_maintenance(store, args.maintenance_id)
    if operation["kind"] != "release" or operation["action"] != "backup":
        raise InventoryError("Backup staging requires its admitted maintenance action.")
    require_target(store, args.maintenance_id, args.key)
    item = store.get(args.key)
    identity = pwd.getpwnam(item.user)
    directory = paths.backups / item.user
    private_directory(directory, paths, identity)
    private_directory(directory / "staging", paths, identity)
    root_identity = pwd.getpwuid(paths.owner_uid)
    root = paths.data / "epm-recovery"
    for path in (root, root / item.key, root / item.key / "staging"):
        private_directory(path, paths, root_identity)


def record_breakglass(args, store, discovery):
    """Acknowledge an observed root intervention without executing or granting anything."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", args.incident):
        raise InventoryError("A bounded private incident reference is required.")
    descriptor = lock_host(store)
    try:
        report = discovery.report(store.list())
        if report["digest"] != args.observed_digest or any(
            problem["kind"] != "changed" for problem in report["discrepancies"]
        ):
            raise InventoryError(
                "Break-glass observation is incomplete or changed; review discovery again."
            )
        identifier = store.begin_maintenance(
            "reconciliation",
            "breakglass",
            report["digest"],
            request=MaintenanceRequest(incident=args.incident),
        )
        store.finish_maintenance(identifier, -1)
    finally:
        os.close(descriptor)
    # The usual allocation/authority restrictions and current observation checks
    # still apply; a root declaration cannot adopt unknown resources here.
    reconcile(store, discovery, identifier, args.observed_digest)
    print(f"Recorded root intervention {args.incident}: {identifier}.")


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "discover", "export-checked", "cleanup-inventory", "maintenance-status"):
        commands.add_parser(name)
    keys = commands.add_parser("keys")
    keys.add_argument("--maintenance-id")
    unused = commands.add_parser("release-unused")
    unused.add_argument("--release", required=True)
    register = commands.add_parser("adopt")
    register.add_argument("--key", required=True)
    register.add_argument("--observed-digest", required=True)
    register.add_argument("--confirm", action="store_true", required=True)
    selection = commands.add_parser("select")
    selection.add_argument("--key", required=True)
    selection.add_argument("--maintenance-id", required=True)
    selection.add_argument("--format", choices=("json", "tsv"), default="json")
    maintenance = commands.add_parser("maintenance")
    maintenance.add_argument("--kind", choices=("release", "cleanup"), required=True)
    maintenance.add_argument("--action", required=True)
    maintenance.add_argument("--resume")
    maintenance.add_argument("--key")
    maintenance.add_argument("--release")
    check = commands.add_parser("assert-maintenance")
    check.add_argument("--maintenance-id", required=True)
    check.add_argument("--key")
    check.add_argument("--release")
    check.add_argument("--checkpoint")
    check.add_argument("--kind")
    check.add_argument("--action")
    allocations = commands.add_parser("allocations")
    allocations.add_argument("--maintenance-id", required=True)
    backup = commands.add_parser("prepare-backup")
    backup.add_argument("--maintenance-id", required=True)
    backup.add_argument("--key", required=True)
    breakglass = commands.add_parser("record-breakglass")
    breakglass.add_argument("--incident", required=True)
    breakglass.add_argument("--observed-digest", required=True)
    breakglass.add_argument("--confirm", action="store_true", required=True)
    complete = commands.add_parser("reconcile")
    complete.add_argument("--maintenance-id", required=True)
    complete.add_argument("--observed-digest", required=True)
    complete.add_argument("--confirm", action="store_true", required=True)
    return parser


def main():
    args = argument_parser().parse_args()
    if os.geteuid() != 0:
        raise InventoryError("Host inventory commands require the private root administrator path.")
    paths = HostPaths()
    store = HostInventory(paths.control / "inventory.sqlite")
    discovery = HostDiscovery(paths)
    handlers = {
        "init": store.initialize,
        "maintenance-status": lambda: print(
            json.dumps(store.maintenance_history(), sort_keys=True, indent=2)
        ),
        "discover": lambda: print(
            json.dumps(discovery.report(store.list()), sort_keys=True, indent=2)
        ),
        "adopt": lambda: adopt_command(args, store, discovery),
        "maintenance": lambda: maintenance_command(args, store, discovery),
        "assert-maintenance": lambda: assert_intent(args, store),
        "allocations": lambda: allocations_command(args, store),
        "select": lambda: select_command(args, store, paths),
        "reconcile": lambda: reconcile(store, discovery, args.maintenance_id, args.observed_digest),
        "prepare-backup": lambda: prepare_backup(args, store, paths),
        "record-breakglass": lambda: record_breakglass(args, store, discovery),
    }
    if args.command == "keys" and args.maintenance_id:
        require_maintenance(store, args.maintenance_id)
        print("\n".join(item.key for item in store.list()))
    elif args.command in handlers:
        handlers[args.command]()
    else:
        checked_export(args, store, discovery)


def adopt_command(args, store, discovery):
    descriptor = lock_host(store)
    try:
        print(
            json.dumps(
                asdict(adopt(store, discovery, args.key, args.observed_digest)), sort_keys=True
            )
        )
    finally:
        os.close(descriptor)


def maintenance_command(args, store, discovery):
    identifier, code = run_maintenance(
        store,
        discovery,
        args.kind,
        args.action,
        MaintenanceRequest(key=args.key, release=args.release, resume=args.resume),
    )
    print(f"Maintenance {identifier}: exit {code}; explicit discovery/reconciliation is required.")
    raise SystemExit(code)


def allocations_command(args, store):
    require_maintenance(store, args.maintenance_id)
    print(json.dumps([asdict(item) for item in store.list()], sort_keys=True))


def select_command(args, store, paths):
    require_maintenance(store, args.maintenance_id)
    require_target(store, args.maintenance_id, args.key)
    item = store.get(args.key)
    if args.format == "tsv":
        print(
            "\t".join(
                (
                    str(item.port),
                    item.user,
                    item.local_config,
                    str(paths.configs / f"hosted-{item.key}.json"),
                    item.mount,
                )
            )
        )
    else:
        print(json.dumps(asdict(item), sort_keys=True))


def require_target(store, identifier, key):
    if store.maintenance_intent(identifier)["key"] != key:
        raise InventoryError("Instance differs from the original maintenance target.")


def assert_intent(args, store):
    operation = require_maintenance(store, args.maintenance_id)
    intent = store.maintenance_intent(args.maintenance_id)
    for argument, field in (("key", "key"), ("release", "release"), ("checkpoint", "checkpoint")):
        supplied = getattr(args, argument, None)
        if supplied is not None and supplied != intent[field]:
            raise InventoryError("Selection differs from the original maintenance intent.")
    for field in ("kind", "action"):
        supplied = getattr(args, field, None)
        if supplied is not None and supplied != operation[field]:
            raise InventoryError("Command differs from the admitted maintenance action.")


def checked_export(args, store, discovery):
    registered = store.list()
    retained = protected_releases(store)
    report = discovery.report(registered)
    if not registered or report["discrepancies"]:
        raise InventoryError("Host inventory has unresolved discrepancies.")
    if args.command == "release-unused":
        if not RELEASE.fullmatch(args.release) or args.release in {
            item.release for item in registered
        }:
            raise InventoryError("Release is selected by a registered instance.")
    elif args.command == "keys":
        print("\n".join(item.key for item in registered))
    elif args.command == "cleanup-inventory":
        print(
            json.dumps(
                {
                    "instances": [asdict(item) for item in registered],
                    "protected_releases": retained,
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps([asdict(item) for item in registered], sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (
        InventoryError,
        OSError,
        ValueError,
        KeyError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"Host administration stopped: {type(error).__name__}: {error}") from error
