"""Offline exact-host cloudflared config check; no credentials or Tunnel connection."""

import argparse
from app.modules.host_agent.infrastructure import host_services
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from app.modules.host_agent.application.ingress import IngressRecord, IngressProjection
from app.modules.host_agent.infrastructure.host_services import TunnelSettings, tunnel_config


def run(binary):
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in required")
    root = Path(tempfile.mkdtemp(prefix="epm-tunnel-qualification-", dir="/var/lib"))
    row = IngressRecord(
        operator_id=str(uuid4()),
        workspace_id=str(uuid4()),
        binding_id=str(uuid4()),
        resource_generation=1,
        access_epoch=1,
        desired_state="held",
        operation_id=str(uuid4()),
        public_origin="https://operator.example.invalid",
    )
    config = root / "config.json"
    config.write_text(
        json.dumps(
            tunnel_config(IngressProjection(records=(row,)), TunnelSettings(tunnel_id=str(uuid4())))
        )
    )
    result = {
        "status": "failed",
        "binary_sha256": sha256(binary.read_bytes()).hexdigest(),
        "host_services_sha256": sha256(Path(host_services.__file__).read_bytes()).hexdigest(),
    }
    try:
        command = [
            "/usr/bin/unshare",
            "--net",
            str(binary),
            "tunnel",
            "--config",
            str(config),
            "ingress",
        ]
        validate = subprocess.run(
            [*command, "validate"], capture_output=True, check=True, timeout=10
        )
        (root / "validate.log").write_bytes(validate.stdout + validate.stderr)
        for host, expected in (
            ("operator.example.invalid", "http://127.0.0.1:8080"),
            ("unknown.example.invalid", "http_status:403"),
            ("admin.example.invalid", "http_status:403"),
        ):
            match = subprocess.run(
                [*command, "rule", "https://" + host], capture_output=True, check=True, timeout=10
            )
            output = (match.stdout + match.stderr).decode()
            assert expected in output, output
            (root / (host + ".log")).write_text(output)
        result.update(
            status="offline_tunnel_config_pass",
            cases=[
                "registered exact host targets private gateway",
                "unknown and reserved hosts deny",
                "validated in empty network namespace without credentials",
            ],
            source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        )
    finally:
        (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudflared", type=Path, required=True)
    run(parser.parse_args().cloudflared)
