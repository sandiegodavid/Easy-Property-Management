"""Explicit disposable root-Linux Caddy proof. No Tunnel/cloud credentials or live routes."""

import argparse
from copy import deepcopy
from hashlib import sha256
from http import HTTPStatus
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import pwd
import socket
import sys
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

import app.modules.host_agent.infrastructure.gateway as gateway_module
from app.modules.host_agent.application.ingress import IngressRecord, IngressProjection
from app.modules.host_agent.infrastructure.gateway import CaddyAdmin, GatewaySettings, closed_config


def request(port, host, headers=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "GET", "/", headers={"Host": host, "X-Forwarded-Proto": "https", **(headers or {})}
        )
        response = connection.getresponse()
        return {
            "status": response.status,
            "body": response.read(4096).decode(),
            "cache": response.getheader("Cache-Control"),
        }
    finally:
        connection.close()


def verify_private_admin(settings, results):
    # A different unprivileged host account cannot traverse the private socket dir.
    probe = (
        "import socket,sys; s=socket.socket(socket.AF_UNIX); "
        "\ntry: s.connect(sys.argv[1])"
        "\nexcept PermissionError: sys.exit(0)"
        "\nelse: sys.exit(1)"
    )
    subprocess.run(
        [
            "/usr/bin/setpriv",
            "--reuid=65534",
            "--regid=65534",
            "--clear-groups",
            "/usr/bin/python3",
            "-c",
            probe,
            str(settings.admin_socket),
        ],
        check=True,
    )
    for address in (("127.0.0.1", 2019), ("::1", settings.port)):
        try:
            with socket.create_connection(address, timeout=1):
                raise AssertionError("Unexpected public/default admin listener")
        except ConnectionRefusedError:
            pass
    results["cases"]["other_uid_admin_denied_and_no_tcp_admin"] = True


def verify_routes(admin, config, row, settings, results):
    assert admin.inspect() == config
    verify_private_admin(settings, results)
    normal = request(settings.port, "operator.example.invalid")
    assert normal["status"] == HTTPStatus.SERVICE_UNAVAILABLE and normal["cache"] == "no-store"
    results["cases"]["registered_held"] = normal
    for host in (
        "unknown.example.invalid",
        "admin.example.invalid",
        "operator.example.invalid:443",
        "operator.example.invalid.",
        "127.0.0.1",
    ):
        assert request(settings.port, host)["status"] == HTTPStatus.FORBIDDEN
    for headers in (
        {"X-Forwarded-Host": "evil.example.invalid"},
        {"Forwarded": "host=operator.example.invalid"},
        {"X-Forwarded-Proto": "http"},
    ):
        assert (
            request(settings.port, "operator.example.invalid", headers)["status"]
            == HTTPStatus.FORBIDDEN
        )
    results["cases"]["unknown_and_forged_hosts"] = "denied"
    invalid = deepcopy(config)
    invalid["apps"]["http"]["servers"]["gateway"]["listen"] = ["not a listener"]
    try:
        admin.load(invalid)
    except Exception:
        pass
    else:
        raise AssertionError("Invalid reload unexpectedly accepted")
    assert admin.inspect() == config
    results["cases"]["failed_load_keeps_previous_config"] = True
    verify_new_fence(admin, row, settings, results)


def verify_new_fence(admin, row, settings, results):
    changed = closed_config(
        IngressProjection(
            records=(
                row.model_copy(
                    update={
                        "desired_state": "blocked",
                        "access_epoch": 2,
                        "operation_id": str(uuid4()),
                    }
                ),
            )
        ),
        settings,
    )
    admin.load(changed)
    assert admin.inspect() == changed
    assert (
        request(settings.port, "operator.example.invalid")["status"]
        == HTTPStatus.SERVICE_UNAVAILABLE
    )
    results["cases"]["new_fence_loaded_and_verified"] = True


def start(binary):
    root = Path(tempfile.mkdtemp(prefix="epm-gateway-qualification-", dir="/var/lib"))
    root.chmod(0o711)
    installed = root / "caddy"
    shutil.copyfile(binary, installed)
    installed.chmod(0o755)
    user = "epm-gw-" + uuid4().hex[:8]
    subprocess.run(
        ["/usr/sbin/useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user],
        check=True,
    )
    identity = pwd.getpwnam(user)
    runtime = root / "run"
    runtime.mkdir(mode=0o700)
    os.chown(runtime, identity.pw_uid, identity.pw_gid)
    settings = GatewaySettings(runtime / "admin.sock", identity.pw_uid, port=18080)
    row = IngressRecord(
        operator_id=str(uuid4()),
        workspace_id=str(uuid4()),
        binding_id=str(uuid4()),
        resource_generation=1,
        public_origin="https://operator.example.invalid",
        access_epoch=1,
        desired_state="held",
        operation_id=str(uuid4()),
    )
    projection = IngressProjection(records=(row,))
    config = closed_config(projection, settings)
    file = root / "candidate.json"
    file.write_text(json.dumps(config))
    file.chmod(0o644)
    log = (root / "caddy.log").open("wb")
    command = [
        "/usr/bin/setpriv",
        f"--reuid={identity.pw_uid}",
        f"--regid={identity.pw_gid}",
        "--clear-groups",
        "/usr/bin/env",
        "XDG_CONFIG_HOME=" + str(runtime),
        "XDG_DATA_HOME=" + str(runtime),
        str(installed),
        "run",
        "--config",
        str(file),
    ]
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, umask=0o007)
    return root, installed, identity, settings, row, config, file, log, process


def run(binary):
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in is required.")
    root, installed, identity, settings, row, config, file, log, process = start(binary)
    results = {
        "root": str(root),
        "uid": identity.pw_uid,
        "binary_sha256": sha256(installed.read_bytes()).hexdigest(),
        "python": sys.version,
        "kernel": os.uname().release,
        "source_sha256": {
            "gateway.py": sha256(Path(gateway_module.__file__).read_bytes()).hexdigest(),
            "qualify_gateway.py": sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "config_sha256": sha256(file.read_bytes()).hexdigest(),
        "cases": {},
    }
    print(root, flush=True)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Caddy startup failed; inspect private log.")
            if settings.admin_socket.exists():
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Caddy admin socket did not become ready.")
        verify_routes(CaddyAdmin(settings), config, row, settings, results)
        results["status"] = "scoped_gateway_pass"
    except Exception:
        results["status"] = "failed"
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        (root / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", type=Path, required=True)
    run(parser.parse_args().caddy)
