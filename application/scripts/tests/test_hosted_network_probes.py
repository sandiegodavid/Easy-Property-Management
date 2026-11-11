"""Qualification probes retain identity isolation and fail closed at their deadline."""

from pathlib import Path
import json
import os
import runpy
import subprocess
from types import SimpleNamespace

import pytest

GATEWAY_UID, TUNNEL_UID, PROBE_TIMEOUT = 42011, 42012, 5
GATEWAY = Path(__file__).resolve().parents[2] / "deploy/hosted-mvp/gateway"


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.syspath_prepend(str(GATEWAY))
    return runpy.run_path(str(GATEWAY / "qualify_network.py"))


@pytest.mark.parametrize("allowed", [True, False])
def test_probe_uses_numeric_credentials_and_clears_inherited_groups(probes, monkeypatch, allowed):
    observed = {}

    def run(arguments, **options):
        observed.update(arguments=arguments, **options)
        return SimpleNamespace(returncode=0 if allowed else 1, stderr=b"denied")

    monkeypatch.setattr(subprocess, "run", run)
    probes["host_probe"](GATEWAY_UID, "10.249.0.2", allowed=allowed)
    assert observed["arguments"][0] == "/usr/bin/python3"
    assert observed["user"] == observed["group"] == GATEWAY_UID
    assert observed["extra_groups"] == []
    assert observed["timeout"] == PROBE_TIMEOUT


def test_denied_probe_does_not_misreport_a_process_timeout_as_network_denial(probes, monkeypatch):
    def stalled(arguments, **options):
        raise subprocess.TimeoutExpired(arguments, options["timeout"])

    monkeypatch.setattr(subprocess, "run", stalled)
    with pytest.raises(subprocess.TimeoutExpired):
        probes["host_probe"](TUNNEL_UID, "10.249.0.2", allowed=False)


def test_stream_client_drops_to_numeric_tunnel_identity(monkeypatch):
    monkeypatch.syspath_prepend(str(GATEWAY))
    stream = runpy.run_path(str(GATEWAY / "qualify_stream.py"))
    observed = {}

    def launch(arguments, **options):
        observed.update(arguments=arguments, **options)
        return "synthetic-child"

    monkeypatch.setattr(subprocess, "Popen", launch)
    assert stream["stream_client"](SimpleNamespace(tunnel_uid=TUNNEL_UID, gateway_port=18080)) == (
        "synthetic-child"
    )
    assert observed["user"] == observed["group"] == TUNNEL_UID
    assert observed["extra_groups"] == []
    assert "setpriv" not in observed["arguments"]


@pytest.mark.parametrize("same_namespace", [True, False])
def test_metadata_stall_control_never_changes_host_network(monkeypatch, same_namespace):
    driver = runpy.run_path(str(GATEWAY.parent / "gcp/qualify_principals.py"))
    monkeypatch.setenv("EPM_H02_QUALIFICATION", "1")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        os, "readlink", lambda path: "host" if same_namespace or path == "/proc/1/ns/net" else "lab"
    )
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps([{"ifname": "lo"}, {"ifname": "eth0"}]).encode(),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("The host or an externally connected namespace must never be mutated")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="private network namespace|external network interface"):
        driver["inside"]()
