"""Disposable systemd root/credential/restart proof with real synthetic owning inventory."""

import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from app.modules.host_agent.infrastructure.host_services import service_unit, TunnelSettings
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings
from app.modules.host_agent.infrastructure.service_config import ServiceInputs, ServiceLayout
from service_fixture import initialize

UNITS = {
    "network": "epm-network-policy.service",
    "projection": "epm-ingress-projection.service",
    "gateway": "epm-gateway.service",
    "egress": "epm-egress.service",
}


def call(*args, check=True):
    return subprocess.run(
        [str(arg) for arg in args], capture_output=True, text=True, timeout=30, check=check
    )


def account(name):
    try:
        return pwd.getpwnam(name)
    except KeyError:
        call(
            "/usr/sbin/useradd",
            "--system",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            name,
        )
        return pwd.getpwnam(name)


def setup(root, caddy):
    identities = [account(name) for name in ("epm-caddy", "epm-tunnel", "epm-proxy")]
    source = Path(__file__).resolve().parents[3]
    application = root / "application"
    shutil.copytree(
        source / "apps", application / "apps", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        source / "database", application / "database", ignore=shutil.ignore_patterns("__pycache__")
    )
    inventory, metadata, principals, projects = initialize(root, application)
    for name in ("data", "stops", "config", "secrets"):
        (root / name).mkdir(mode=0o700)
    for name, identity in zip(("caddy", "tunnel", "proxy"), identities, strict=True):
        directory = root / (name + "-run")
        directory.mkdir(mode=0o700)
        os.chown(directory, identity.pw_uid, identity.pw_gid)
        projection = root / (name + "-projection")
        projection.mkdir(mode=0o750)
        os.chown(projection, 0, identity.pw_gid)
    tools = root / "tools"
    tools.mkdir(mode=0o755)
    shutil.copyfile(caddy, tools / "caddy")
    (tools / "caddy").chmod(0o755)
    layout = ServiceLayout(
        inventory=str(inventory),
        application=str(application),
        stops=str(root / "stops"),
        data=str(root / "data"),
        gateway_runtime=str(root / "caddy-run"),
        gateway_projection=str(root / "caddy-projection"),
        proxy_runtime=str(root / "proxy-run"),
        proxy_projection=str(root / "proxy-projection"),
        tunnel_runtime=str(root / "tunnel-run"),
        tunnel_projection=str(root / "tunnel-projection"),
        tunnel_secret=str(root / "secrets/tunnel.json"),
        installation=str(Path(sys.executable).parent.parent),
        tools=str(tools),
        config=str(root / "config/service.json"),
    )
    network = NetworkSettings(
        ipv4_pool="10.248.0.0/16",
        ipv6_pool="fd47:6570:6f00::/48",
        first_project=1,
        gateway_uid=identities[0].pw_uid,
        tunnel_uid=identities[1].pw_uid,
        proxy_uid=identities[2].pw_uid,
        gateway_port=18080,
    )
    tunnel = TunnelSettings(tunnel_id=str(uuid4()), gateway_port=18080)
    inputs = ServiceInputs(
        layout=layout,
        metadata=metadata,
        uids=principals,
        gids=principals,
        projects=projects,
        public_domain="example.invalid",
        network=network,
        tunnel=tunnel,
    )
    Path(layout.config).write_text(inputs.model_dump_json())
    Path(layout.config).chmod(0o600)
    secret = {
        "AccountTag": "a" * 32,
        "TunnelID": tunnel.tunnel_id,
        "TunnelSecret": base64.b64encode(
            b"synthetic-tunnel-secret-material!".ljust(32, b"x")[:32]
        ).decode(),
    }
    Path(layout.tunnel_secret).write_text(json.dumps(secret))
    Path(layout.tunnel_secret).chmod(0o600)
    return inputs


def install(inputs):
    python_path = str(Path(inputs.layout.application) / "apps/server")
    for component, name in UNITS.items():
        path = Path("/run/systemd/system") / name
        if path.exists():
            raise RuntimeError("Existing service path; no takeover")
        text = service_unit(component, inputs.layout)
        text += "\n[Service]\nEnvironment=PYTHONPATH=" + python_path + "\n"
        # Explicit non-secret lab import path; production uses the installed agent.
        text += "Environment=XDG_DATA_HOME=" + inputs.layout.gateway_runtime + "\n"
        text += "Environment=XDG_CONFIG_HOME=" + inputs.layout.gateway_runtime + "\n"
        path.write_text(text)
    call("/usr/bin/systemctl", "daemon-reload")


def request(inputs):
    code = (
        "import http.client; c=http.client.HTTPConnection('127.0.0.1',18080,timeout=2); "
        "c.request('GET','/',headers={'Host':'operator.example.invalid',"
        "'X-Forwarded-Proto':'https'}); "
        "print(c.getresponse().status)"
    )
    return call(
        "/usr/bin/setpriv",
        f"--reuid={inputs.network.tunnel_uid}",
        f"--regid={inputs.network.tunnel_uid}",
        "--clear-groups",
        "/usr/bin/python3",
        "-c",
        code,
    ).stdout.strip()


def verify_credentials(inputs):
    path = Path("/run/systemd/system/epm-tunnel.service")
    if path.exists():
        raise RuntimeError("Existing Tunnel unit; no takeover")
    layout = inputs.layout
    source_probe = Path(__file__).resolve().parent / "credential_probe.py"
    probe = Path(layout.data).parent / "credential_probe.py"
    shutil.copyfile(source_probe, probe)
    probe.chmod(0o644)
    outcome = Path(layout.tunnel_runtime) / "credential-result.json"
    unit = service_unit("tunnel", layout)
    lines = []
    for original_line in unit.splitlines():
        line = original_line
        if line.startswith("ExecStart="):
            line = (
                "ExecStart="
                + layout.installation
                + "/bin/python -B "
                + str(probe)
                + " "
                + inputs.tunnel.tunnel_id
                + " "
                + str(outcome)
                + " "
                + layout.tunnel_secret
                + " "
                + layout.inventory
                + " /run/docker.sock"
            )
        elif line.startswith("Type="):
            line = "Type=simple"
        elif line.startswith("Restart="):
            line = "Restart=no"
        lines.append(line)
    lines += [
        "",
        "[Service]",
        "RemainAfterExit=yes",
        "Environment=PYTHONPATH=" + str(Path(layout.application) / "apps/server"),
    ]
    try:
        path.write_text("\n".join(lines) + "\n")
        call("/usr/bin/systemctl", "daemon-reload")
        call("/usr/bin/systemctl", "start", "epm-tunnel.service")
        for _ in range(30):
            if outcome.exists():
                break
            time.sleep(0.1)
        assert outcome.exists(), "Credential consumer did not become ready"
        for uid in (inputs.network.gateway_uid, 100000):
            attempted = call(
                "/usr/bin/setpriv",
                f"--reuid={uid}",
                f"--regid={uid}",
                "--clear-groups",
                "/usr/bin/python3",
                "-c",
                "from pathlib import Path; "
                "Path('/run/credentials/epm-tunnel.service/tunnel.json').read_bytes()",
                check=False,
            )
            assert attempted.returncode != 0
        return json.loads(outcome.read_text())
    finally:
        journal = call(
            "/usr/bin/journalctl", "-u", "epm-tunnel.service", "-n", "60", "--no-pager", check=False
        )
        (Path(layout.data).parent / "credential-unit.log").write_text(journal.stdout)
        call("/usr/bin/systemctl", "stop", "epm-tunnel.service", check=False)
        path.unlink(missing_ok=True)
        call("/usr/bin/systemctl", "daemon-reload")


def verify(inputs):
    call("/usr/bin/systemctl", "start", UNITS["gateway"])
    assert request(inputs) == "503"
    call("/usr/bin/systemctl", "start", UNITS["egress"])
    assert call("/usr/bin/systemctl", "is-active", UNITS["egress"]).stdout.strip() == "active"
    credentials = verify_credentials(inputs)
    before = call(
        "/usr/bin/systemctl", "show", UNITS["gateway"], "--property=MainPID", "--value"
    ).stdout.strip()
    call("/usr/bin/systemctl", "kill", "--kill-whom=main", "--signal=KILL", UNITS["gateway"])
    for _ in range(100):
        time.sleep(0.1)
        current = call(
            "/usr/bin/systemctl", "show", UNITS["gateway"], "--property=MainPID", "--value"
        ).stdout.strip()
        active = call(
            "/usr/bin/systemctl", "is-active", UNITS["gateway"], check=False
        ).stdout.strip()
        if current not in {"0", before} and active == "active":
            assert request(inputs) == "503"
            break
    else:
        raise AssertionError("Gateway did not restart held closed")
    call("/usr/bin/systemctl", "stop", UNITS["gateway"])
    config = Path(inputs.layout.gateway_projection) / "config.json"
    config.write_text('{"apps":{}}')
    call("/usr/bin/systemctl", "start", UNITS["gateway"])
    assert request(inputs) == "503"  # Pre-start replaced a tampered stale file.
    call("/usr/bin/systemctl", "stop", UNITS["gateway"])
    inventory = Path(inputs.layout.inventory)
    saved = inventory.with_suffix(".held")
    inventory.rename(saved)
    for phase in ("missing", "corrupt"):
        call("/usr/bin/systemctl", "reset-failed", UNITS["gateway"])
        assert call("/usr/bin/systemctl", "start", UNITS["gateway"], check=False).returncode != 0
        assert (
            call(
                "/usr/bin/systemctl", "show", UNITS["gateway"], "--property=Result", "--value"
            ).stdout.strip()
            == "exit-code"
        )
        assert (
            call("/usr/bin/systemctl", "is-active", UNITS["gateway"], check=False).returncode != 0
        )
        call("/usr/bin/systemctl", "stop", UNITS["gateway"])
        if phase == "missing":
            saved.rename(inventory)
            inventory.write_bytes(b"corrupt synthetic inventory")
    return {
        "held_after_process_death": True,
        "stale_projection_rebuilt": True,
        "missing_inventory_prevents_start": True,
        "corrupt_inventory_prevents_start": True,
        "admin_service_not_required": True,
        "credentials": credentials,
    }


def run(caddy):
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in required")
    if any((Path("/run/systemd/system") / name).exists() for name in UNITS.values()):
        raise RuntimeError("Existing service units; no takeover")
    root = Path(tempfile.mkdtemp(prefix="epm-service-qualification-", dir="/var/lib"))
    root.chmod(0o711)
    result = {"status": "failed", "root": str(root)}
    print(root, flush=True)
    try:
        inputs = setup(root, caddy)
        install(inputs)
        result["cases"] = verify(inputs)
        result["status"] = "scoped_service_pass"
    finally:
        for name in UNITS.values():
            log = call("/usr/bin/journalctl", "-u", name, "--no-pager", "-n", "80", check=False)
            (root / (name + ".log")).write_text(log.stdout)
            call("/usr/bin/systemctl", "stop", name, check=False)
            (Path("/run/systemd/system") / name).unlink(missing_ok=True)
        call("/usr/bin/systemctl", "daemon-reload")
        (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", type=Path, required=True)
    run(parser.parse_args().caddy)
