"""Closed Tunnel routing and per-resource bootstrap permission candidates."""

import pytest
from pydantic import ValidationError

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.host_services import (
    TunnelSettings,
    tunnel_config,
    service_unit,
)
from app.modules.host_agent.infrastructure.scoped_iam import BootstrapGrants
from app.modules.host_agent.tests.test_agent import setup as setup, ready, ID


def test_tunnel_uses_only_registered_hosts_and_preserves_original_origin(setup):
    ready(setup)
    value = tunnel_config(setup.inventory.ingress_projection(), TunnelSettings(tunnel_id=ID))
    assert value["ingress"] == [
        {"hostname": "synthetic-0001.example.invalid", "service": "http://127.0.0.1:8080"},
        {"service": "http_status:403"},
    ]
    assert "httpHostHeader" not in str(value) and "*" not in str(value)
    assert value["credentials-file"] == "/run/credentials/epm-tunnel.service/tunnel.json"
    assert "token" not in str(value)


@pytest.mark.parametrize("component", ["gateway", "tunnel"])
def test_service_has_own_unprivileged_identity_and_no_data_or_docker_access(component):
    value = service_unit(component)
    assert "User=epm-" in value and "User=root" not in value
    assert "CapabilityBoundingSet=\n" in value and "NoNewPrivileges=yes" in value
    assert "InaccessiblePaths=" in value and "/run/docker.sock" in value and "/var/lib/epm" in value
    assert "epm-ingress-projection.service" in value and "epm-network-policy.service" in value
    assert "--resume" not in value and "Environment=" not in value
    assert "ProtectSystem=strict" in value and "TasksMax=64" in value


def test_no_arbitrary_service_command_or_credentials_path():
    with pytest.raises(HostAgentDenied):
        service_unit("operator")
    with pytest.raises(ValidationError):
        TunnelSettings(tunnel_id=ID, credential_path="/other")


def test_bootstrap_permissions_are_only_on_exact_repository_and_tunnel_secret():
    grants = BootstrapGrants(
        project="synthetic-epm",
        region="us-central1",
        repository="candidates",
        host_service_account="epm-host",
        tunnel_id=ID,
    )
    repository, secret = grants.resource_policies()
    assert (
        repository["resource"]
        == "projects/synthetic-epm/locations/us-central1/repositories/candidates"
    )
    assert secret["resource"] == "projects/synthetic-epm/secrets/epm-tunnel-" + ID
    for item in (repository, secret):
        text = str(item)
        assert "*" not in text and "roles/owner" not in text and "roles/editor" not in text
        assert "operator" not in text and "secretmanager.admin" not in text
        assert item["policy"]["bindings"][0]["members"] == [
            "serviceAccount:epm-host@synthetic-epm.iam.gserviceaccount.com",
        ]


@pytest.mark.parametrize(
    "updates",
    [
        {"repository": "*"},
        {"project": "other/path"},
        {"host_service_account": "operator@example.com"},
    ],
)
def test_invalid_resource_scope_rejects(updates):
    with pytest.raises(ValidationError):
        BootstrapGrants(
            **(
                dict(
                    project="synthetic-epm",
                    region="us-central1",
                    repository="candidates",
                    host_service_account="epm-host",
                    tunnel_id=ID,
                )
                | updates
            )
        )


def test_bootstrap_reconstructs_snapshot_without_admin_and_contains_on_failure(setup):
    from types import SimpleNamespace
    from pathlib import Path
    from app.modules.host_agent.infrastructure.gateway import GatewaySettings
    from app.modules.host_agent.infrastructure.ingress_bootstrap import IngressBootstrap

    ready(setup)
    writes, stops = [], []
    files = SimpleNamespace(publish=lambda value: writes.append(value))
    value = IngressBootstrap(
        setup.inventory,
        GatewaySettings(Path("/run/epm-caddy/admin.sock"), 800),
        TunnelSettings(tunnel_id=ID),
        files,
        files,
        contain_all=lambda: stops.append("stop"),
    )
    value.refresh()
    assert len(writes) == 2 and not stops
    # A fresh service start regenerates from inventory; no Admin contact or autosave read.
    value.refresh()
    assert writes[:2] == writes[2:]

    def unavailable(*args):
        raise OSError("projection publication unavailable")

    files.publish = unavailable
    with pytest.raises(OSError):
        value.refresh()
    assert stops == ["stop"]


def test_bootstrap_preserves_both_publication_and_containment_failures(setup):
    from types import SimpleNamespace
    from pathlib import Path
    from app.modules.host_agent.infrastructure.gateway import GatewaySettings
    from app.modules.host_agent.infrastructure.ingress_bootstrap import IngressBootstrap

    def fail(*args):
        raise OSError("unavailable")

    ready(setup)
    value = IngressBootstrap(
        setup.inventory,
        GatewaySettings(Path("/run/epm-caddy/admin.sock"), 800),
        TunnelSettings(tunnel_id=ID),
        SimpleNamespace(publish=fail),
        SimpleNamespace(publish=fail),
        contain_all=fail,
    )
    with pytest.raises(ExceptionGroup) as caught:
        value.refresh()
    assert len(caught.value.exceptions) == 2


def test_projection_files_are_private_atomic_and_refuse_replaced_directory(tmp_path):
    import os
    import stat
    import json
    from app.modules.host_agent.infrastructure.ingress_bootstrap import ProjectionPublisher

    directory = tmp_path.resolve() / "protected"
    directory.mkdir(mode=0o750)
    os.chown(directory, -1, os.getgid())
    files = ProjectionPublisher(directory, reader_gid=os.getgid())
    files.publish({"first": True})
    files.publish({"second": True})
    assert json.loads((directory / "config.json").read_text()) == {"second": True}
    assert stat.S_IMODE((directory / "config.json").stat().st_mode) == 0o640
    assert [item.name for item in directory.iterdir()] == ["config.json"]
    directory.rename(directory.with_name("old"))
    directory.mkdir(mode=0o750)
    with pytest.raises(HostAgentDenied):
        files.publish({"third": True})
    assert not list(directory.iterdir())
