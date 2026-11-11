"""Root-only service composition, scoped credential validation and restart inputs."""

import base64
import json
import os

import pytest
from pydantic import ValidationError

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.tunnel_credentials import (
    validate_tunnel_credential,
)
from app.modules.host_agent.infrastructure.service_config import ServiceLayout
from app.modules.host_agent.infrastructure.host_services import service_unit

ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def secret(tmp_path):
    directory = tmp_path.resolve() / "private"
    directory.mkdir(mode=0o700)
    path = directory / "tunnel.json"
    value = {
        "AccountTag": "a" * 32,
        "TunnelID": ID,
        "TunnelSecret": base64.b64encode(b"x" * 32).decode(),
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path, value


def test_tunnel_credential_is_scoped_and_never_returned(secret):
    path, _ = secret
    assert validate_tunnel_credential(path, ID, owner=os.geteuid()) is None
    with pytest.raises(HostAgentDenied) as error:
        validate_tunnel_credential(path, "00000000-0000-4000-8000-000000000002", owner=os.geteuid())
    assert "TunnelSecret" not in str(error.value) and error.value.__cause__ is None


@pytest.mark.parametrize(
    "change", ["symlink", "hardlink", "public", "large", "unexpected", "invalid"]
)
def test_unsafe_or_malformed_credential_is_not_delivered(secret, change):
    path, value = secret
    if change == "symlink":
        alias = path.with_name("alias")
        alias.symlink_to(path)
        path = alias
    elif change == "hardlink":
        os.link(path, path.with_name("alias"))
    elif change == "public":
        path.chmod(0o644)
    elif change == "large":
        path.write_bytes(b"x" * 4097)
    elif change == "unexpected":
        path.write_text(json.dumps(value | {"token": "private"}))
    else:
        path.write_text("not-json private material")
    with pytest.raises(HostAgentDenied) as error:
        validate_tunnel_credential(path, ID, owner=os.geteuid())
    assert "private material" not in str(error.value)


def test_service_runners_have_real_commands_and_credential_is_read_only_delivery():
    for component in ("network", "projection", "gateway", "tunnel"):
        unit = service_unit(component)
        assert "epm-refresh-ingress-projection" not in unit
        assert "app.modules.host_agent.infrastructure.service_runtime" in unit
        assert "ExecStopPost=" in unit and "--contain-all" in unit
    tunnel = service_unit("tunnel")
    assert "LoadCredential=tunnel.json:/etc/epm/secrets/tunnel.json" in tunnel
    assert "Environment=" not in tunnel
    assert "LoadCredential=" not in service_unit("gateway")


@pytest.mark.parametrize("value", ["/run/../etc/private", "/run//epm", "/run/x;command"])
def test_service_layout_rejects_noncanonical_or_injectable_paths(value):
    with pytest.raises(ValidationError):
        ServiceLayout(
            inventory=value, application="/opt/epm/app", stops="/var/lib/epm/stops", data="/data"
        )


def test_dns_timeout_is_unavailable_and_subprocess_reaped(monkeypatch):
    import subprocess
    from app.modules.host_agent.infrastructure import bounded_dns
    from app.modules.host_agent.application.dispatch import HostAgentUnavailable

    seen = []

    def timeout(arguments, **kwargs):
        seen.append(kwargs)
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(bounded_dns.subprocess, "run", timeout)
    with pytest.raises(HostAgentUnavailable):
        bounded_dns.resolve("registered.example.com", 443)
    assert seen[0]["timeout"] == 2 and seen[0]["close_fds"]


def test_proxy_unit_has_no_credential_grant_or_arbitrary_service_command():
    unit = service_unit("egress")
    assert "User=epm-proxy" in unit
    assert "infrastructure.egress_proxy --policy" in unit
    assert "LoadCredential=" not in unit and "Environment=" not in unit
    assert "ReadWritePaths=/run/epm-proxy" in unit
