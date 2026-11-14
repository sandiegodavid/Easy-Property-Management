"""Cloud plans and destructive blank-device rejection have no external effects."""

from copy import deepcopy
from contextlib import nullcontext
import base64
import json
import os
from pathlib import Path
import runpy
import stat
import struct
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from app.modules.host_agent.infrastructure.tunnel_credentials import validate_tunnel_credential
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.service_config import ServiceLayout
from app.modules.hosted_admin.infrastructure import project_quota
from app.modules.hosted_admin.infrastructure.project_quota import QuotaUnavailable

ROOT = Path(__file__).resolve().parents[2] / "deploy/hosted-mvp/gcp"
Q_GETINFO = 0x800005
Q_XGETQSTATV = 0x5808


def target():
    return dict(
        project="synthetic-project",
        region="us-west1",
        zone="us-west1-b",
        instance="epm-h02-host",
        network="epm-h02-network",
        subnet="epm-h02-subnet",
        subnet_cidr="10.80.0.0/24",
        repository="epm-h02-candidates",
        service_account="epm-h02-host",
        image="ubuntu-2404-noble-amd64-v20261105",
        tunnel_id="00000000-0000-4000-8000-000000000001",
    )


def test_plan_has_explicit_identity_private_ingress_and_retained_data():
    module = runpy.run_path(str(ROOT / "cloud_plan.py"))
    value = module["Target"](**target())
    commands = module["plan"](value, Path("/private/startup.sh"))
    assert all("--project=synthetic-project" in command for command in commands)
    vm = commands[-1]
    assert "--machine-type=e2-standard-2" in vm
    assert "--boot-disk-size=20GB" in vm
    assert any("device-name=epm-h02-data" in arg and "auto-delete=no" in arg for arg in vm)
    assert not any("family" in arg or "gce-container" in arg for arg in vm)
    assert "--source-ranges=35.235.240.0/20" in commands[3]
    assert "--rules=tcp:22" in commands[3]
    assert "--service-account=epm-h02-host@synthetic-project.iam.gserviceaccount.com" in vm
    assert not any("delete" in command for command in commands)


@pytest.mark.parametrize(
    "change",
    [
        {"instance": "bad;touch file"},
        {"project": "--project=other"},
        {"zone": "us-east1-b"},
        {"subnet_cidr": "10.246.0.0/24"},
        {"subnet_cidr": "0.0.0.0/24"},
        {"machine": "e2-medium"},
    ],
)
def test_wrong_cloud_target_rejects_before_commands(change):
    model = runpy.run_path(str(ROOT / "cloud_plan.py"))["Target"]
    with pytest.raises(ValidationError):
        model(**(target() | change))


def test_only_empty_whole_expected_size_disk_passes_gate():
    module = runpy.run_path(str(ROOT / "guest_disk.py"))
    check = module["require_blank"]
    tree = {"blockdevices": [dict(type="disk", size=module["SIZE"], mountpoints=[None])]}
    check(tree, {"signatures": []})
    for change in [
        dict(type="part"),
        dict(size=1),
        dict(mountpoints=["/"]),
        dict(children=[dict(type="part")]),
    ]:
        changed = deepcopy(tree)
        changed["blockdevices"][0].update(change)
        with pytest.raises(ValueError):
            check(changed, {"signatures": []})
    with pytest.raises(ValueError):
        check(tree, {"signatures": [dict(type="ext4")]})
    with pytest.raises(ValueError):
        check({"blockdevices": []}, {"signatures": []})


def test_rendered_startup_verifies_closed_packages_and_no_moving_install():
    render = runpy.run_path(str(ROOT / "render_startup.py"))["render"]
    pins = [
        dict(
            package=name,
            url="https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/"
            + name
            + ".deb",
            sha256="a" * 64,
        )
        for name in ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin")
    ]
    script = render("@@PINNED_DOCKER_PACKAGES@@", pins)
    assert script.count("sha256sum -c -") == len(pins)
    assert "apt-mark hold" in script and "apt-get install" in script
    assert "curl |" not in script
    pins[0]["url"] = "https://attacker.invalid/package.deb"
    with pytest.raises(ValueError):
        render("@@PINNED_DOCKER_PACKAGES@@", pins)


def tunnel_document():
    return {
        "AccountTag": "a" * 32,
        "TunnelID": "00000000-0000-4000-8000-000000000001",
        "TunnelSecret": base64.b64encode(b"synthetic".ljust(32, b"x")).decode(),
    }


def test_provider_empty_endpoint_is_removed_without_weakening_runtime_contract():
    canonical = runpy.run_path(str(ROOT / "install_services.py"))["canonical_credential"]
    value = tunnel_document()
    assert json.loads(canonical(json.dumps(value | {"Endpoint": ""}))) == value
    assert json.loads(canonical(json.dumps(value))) == value
    for invalid in (value | {"Endpoint": "https://other.invalid"}, value | {"extra": ""}, []):
        with pytest.raises(HostAgentDenied, match="protected host request"):
            canonical(json.dumps(invalid))


def test_invalid_secret_never_publishes_and_retry_preserves_existing_identity(
    tmp_path, monkeypatch
):
    publish = runpy.run_path(str(ROOT / "install_services.py"))["publish_credential"]

    def private_directory(path, mode):
        path.mkdir(mode=mode, parents=True, exist_ok=True)

    monkeypatch.setitem(publish.__globals__, "directory", private_directory)
    monkeypatch.setitem(
        publish.__globals__,
        "validate_tunnel_credential",
        lambda path, identity: validate_tunnel_credential(path, identity, owner=os.getuid()),
    )
    destination = tmp_path / "secrets/tunnel.json"
    value = tunnel_document()
    with pytest.raises(HostAgentDenied):
        publish(destination, json.dumps(value | {"TunnelSecret": "invalid"}), value["TunnelID"])
    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []
    publish(destination, json.dumps(value | {"Endpoint": ""}), value["TunnelID"])
    original = destination.read_bytes()
    inode = destination.stat().st_ino
    assert stat.S_IMODE(destination.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    assert destination.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        publish(destination, json.dumps(value), value["TunnelID"])
    assert destination.read_bytes() == original and destination.stat().st_ino == inode


def test_installed_services_serialize_projection_refresh_on_boot():
    render = runpy.run_path(str(ROOT / "install_services.py"))["installation_unit"]
    layout = ServiceLayout(
        inventory="/srv/epm/data/host/inventory/inventory.sqlite",
        application="/opt/epm/app",
        stops="/srv/epm/data/host/stops",
        data="/srv/epm/data",
    )
    tunnel = render("tunnel", layout)
    assert "After=epm-egress.service\n" in tunnel
    assert "After=epm-gateway.service\n" in render("egress", layout)
    for component in ("network", "projection", "gateway", "egress", "tunnel"):
        assert "Requires=srv-epm-data.mount\n" in render(component, layout)
    assert "LoadCredential=tunnel.json:" in tunnel
    assert "ExecStartPre=+" in tunnel and " refresh --config " in tunnel


def test_post_reboot_lock_is_acquired_as_the_retained_operator(monkeypatch, tmp_path):
    verify = runpy.run_path(str(ROOT / "qualify_host.py"))["verify_writer_lock"]
    owner = SimpleNamespace(host_uid=42001, host_gid=42002)
    observed = {}

    def run(arguments, **options):
        observed.update(arguments=arguments, **options)

    monkeypatch.setattr(subprocess, "run", run)
    lock = tmp_path / "writer.lock"
    verify(lock, owner)
    assert observed["user"] == owner.host_uid and observed["group"] == owner.host_gid
    assert observed["extra_groups"] == []
    assert observed["check"] is True
    assert observed["arguments"][-1] == str(lock)


@pytest.fixture
def live_installation(tmp_path, monkeypatch):
    """Retained ready metadata is deliberately not proof of a live mounted disk."""
    install = runpy.run_path(str(ROOT / "install_services.py"))["install"]
    mount = tmp_path / "data"
    mount.mkdir()
    ready = tmp_path / "data.json"
    identity = "00000000-0000-4000-8000-000000000001"
    ready.write_text(json.dumps(dict(phase="ready", uuid=identity)))
    original_path = Path
    monkeypatch.setitem(
        install.__globals__,
        "Path",
        lambda path: ready if str(path) == "/etc/epm/bootstrap/data.json" else original_path(path),
    )
    monkeypatch.setitem(install.__globals__, "ROOT", mount / "host")
    monkeypatch.setenv("EPM_H02_QUALIFICATION", "1")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(project_quota.sys, "platform", "linux")
    monkeypatch.setattr(project_quota, "protected_directory", lambda _: nullcontext())
    observed = dict(
        row=dict(
            target=str(mount),
            source="/dev/epm-test",
            fstype="ext4",
            uuid=identity,
            options="rw,prjquota,nodev,nosuid,noexec",
        ),
        features="Filesystem features: project quota\nInode size: 256\n",
        flags=0x30,
        calls=[],
    )
    original_stat = Path.stat

    def device_stat(path, *args, **kwargs):
        if str(path) == "/dev/epm-test":
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=mount.stat().st_dev)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", device_stat)

    def run(arguments, **options):
        observed["calls"].append(arguments[0])
        if arguments[0] == "/usr/bin/findmnt":
            assert options["check"] and str(mount) in arguments
            if observed.get("inspection_error"):
                raise subprocess.CalledProcessError(1, arguments)
            return SimpleNamespace(stdout=json.dumps(dict(filesystems=observed["rows"])))
        assert arguments[0] == "/usr/sbin/tune2fs"
        return SimpleNamespace(stdout=observed["features"])

    def control(device, command, value):
        observed["calls"].append(command)
        if command == Q_XGETQSTATV:
            struct.pack_into("=H", value, 2, observed["flags"])

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(project_quota, "_quota_control", control)
    observed["rows"] = [observed["row"]]
    mutation = Mock(side_effect=AssertionError("First mutation reached"))
    monkeypatch.setitem(install.__globals__, "directory", mutation)
    return SimpleNamespace(
        install=install,
        mount=mount,
        ready=ready,
        original=ready.read_bytes(),
        observed=observed,
        mutation=mutation,
    )


@pytest.mark.parametrize(
    "failure",
    [
        "unmounted",
        "missing_mount",
        "inspection_error",
        "replaced",
        "wrong_type",
        "read_only",
        "missing_prjquota",
        "missing_nodev",
        "missing_nosuid",
        "missing_noexec",
        "quota_off",
        "accounting_off",
        "no_features",
    ],
)
def test_ready_bootstrap_cannot_create_authority_on_wrong_or_unenforced_mount(
    live_installation, failure
):
    fixture = live_installation
    observation = fixture.observed
    if failure == "unmounted":
        observation["row"]["target"] = "/"
    elif failure == "missing_mount":
        observation["rows"] = []
    elif failure == "inspection_error":
        observation["inspection_error"] = True
    elif failure == "replaced":
        observation["row"]["uuid"] = "00000000-0000-4000-8000-000000000002"
    elif failure == "wrong_type":
        observation["row"]["fstype"] = "tmpfs"
    elif failure == "read_only":
        observation["row"]["options"] = observation["row"]["options"].replace("rw", "ro")
    elif failure.startswith("missing_"):
        observation["row"]["options"] = ",".join(
            x
            for x in observation["row"]["options"].split(",")
            if x != failure.removeprefix("missing_")
        )
    elif failure == "quota_off":
        observation["flags"] = 0x10
    elif failure == "accounting_off":
        observation["flags"] = 0x20
    else:
        observation["features"] = "Filesystem features: extent\nInode size: 256\n"
    with pytest.raises((QuotaUnavailable, subprocess.CalledProcessError)):
        fixture.install("synthetic-project", "example.com", tunnel_document()["TunnelID"])
    fixture.mutation.assert_not_called()
    assert list(fixture.mount.iterdir()) == []
    assert fixture.ready.read_bytes() == fixture.original
    assert fixture.observed["calls"][0] == "/usr/bin/findmnt"


def test_installation_proves_live_accounting_and_enforcement_before_first_mutation(
    live_installation,
):
    fixture = live_installation
    with pytest.raises(AssertionError, match="First mutation reached"):
        fixture.install("synthetic-project", "example.com", tunnel_document()["TunnelID"])
    assert fixture.observed["calls"] == [
        "/usr/bin/findmnt",
        "/usr/sbin/tune2fs",
        Q_GETINFO,
        Q_XGETQSTATV,
    ]
    fixture.mutation.assert_called_once_with(fixture.mount / "host", 0o700)


@pytest.fixture
def reboot_continuation(tmp_path, monkeypatch):
    module = runpy.run_path(str(ROOT / "qualify_host.py"))
    after = module["after"]
    boot = tmp_path / "boot"
    boot.mkdir()
    image = boot / "vmlinuz-recorded-kernel"
    image.write_bytes(b"original verified kernel")
    boot_id = tmp_path / "boot-id"
    boot_id.write_text("new-boot")
    root = tmp_path / "lab"
    root.mkdir()
    data = tmp_path / "data"
    physical = data / "qualification/lab"
    locks = []
    owners = [dict(host_uid=42001, host_gid=42001), dict(host_uid=42002, host_gid=42002)]
    for index in range(len(owners)):
        control = physical / "control" / str(index)
        control.mkdir(parents=True)
        lock = control / "writer.lock"
        lock.touch()
        locks.append(lock)
    projects = [
        {
            role: dict(hard_bytes=8192, allocated_bytes=4096)
            for role in ("workspace", "control", "scratch")
        }
        for _ in owners
    ]
    state = dict(
        boot_id="old-boot",
        kernel="recorded-kernel",
        machine="x86_64",
        kernel_sha256=module["sha256"](image.read_bytes()).hexdigest(),
        filesystem_uuid="00000000-0000-4000-8000-000000000001",
        physical_roots=str(physical),
        owners=owners,
        expected_projects=projects,
        lock_inodes=[p.stat().st_ino for p in locks],
    )
    (root / "h02-gcp-before.json").write_text(json.dumps(state))
    monkeypatch.setitem(after.__globals__, "guard", lambda: None)
    original_path = Path

    def path(value):
        if str(value) == "/boot":
            return boot
        if str(value) == "/proc/sys/kernel/random/boot_id":
            return boot_id
        return original_path(value)

    monkeypatch.setitem(after.__globals__, "Path", path)
    monkeypatch.setitem(after.__globals__, "DATA", data)
    monkeypatch.setattr(module["platform"], "release", lambda: state["kernel"])
    monkeypatch.setattr(module["platform"], "machine", lambda: state["machine"])
    call = Mock(return_value=json.dumps(dict(filesystems=[dict(uuid=state["filesystem_uuid"])])))
    monkeypatch.setitem(after.__globals__, "call", call)
    storage = SimpleNamespace(
        verify=lambda owner: projects[owner.host_uid - owners[0]["host_uid"]],
        projects=lambda owner: [
            None,
            SimpleNamespace(
                binding=SimpleNamespace(
                    directory=locks[owner.host_uid - owners[0]["host_uid"]].parent
                )
            ),
        ],
    )
    monkeypatch.setitem(after.__globals__, "PrivateStorage", lambda _: storage)
    monkeypatch.setitem(after.__globals__, "Allocation", SimpleNamespace)
    writer = Mock()
    monkeypatch.setitem(after.__globals__, "verify_writer_lock", writer)
    return SimpleNamespace(
        after=after, state=state, root=root, module=module, image=image, call=call, writer=writer
    )


@pytest.mark.parametrize("changed", ["kernel", "architecture", "image_bytes"])
def test_reboot_proof_rejects_changed_running_platform_with_old_kernel_still_present(
    reboot_continuation, monkeypatch, changed
):
    fixture = reboot_continuation
    if changed == "kernel":
        monkeypatch.setattr(fixture.module["platform"], "release", lambda: "different-kernel")
    elif changed == "architecture":
        monkeypatch.setattr(fixture.module["platform"], "machine", lambda: "aarch64")
    else:
        fixture.image.write_bytes(b"changed running kernel bytes")
    if changed != "image_bytes":
        assert fixture.image.read_bytes() == b"original verified kernel"
    with pytest.raises(ValueError, match="[Kk]ernel|architecture"):
        fixture.after(fixture.root)
    fixture.call.assert_not_called()
    fixture.writer.assert_not_called()
    assert not (fixture.root / "h02-gcp-after.json").exists()


def test_matching_running_kernel_and_architecture_can_complete_retained_reboot_proof(
    reboot_continuation,
):
    fixture = reboot_continuation
    fixture.after(fixture.root)
    result = json.loads((fixture.root / "h02-gcp-after.json").read_text())
    assert result["phase"] == "passed"
    assert result["after_kernel"] == fixture.state["kernel"]
    assert result["after_machine"] == fixture.state["machine"]
    assert result["after_kernel_sha256"] == fixture.state["kernel_sha256"]
    assert fixture.writer.call_count == len(fixture.state["owners"])
