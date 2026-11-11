"""Cloud plans and destructive blank-device rejection have no external effects."""

from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from app.modules.host_agent.infrastructure.tunnel_credentials import validate_tunnel_credential
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.service_config import ServiceLayout

ROOT = Path(__file__).resolve().parents[2] / "deploy/hosted-mvp/gcp"


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
