"""Disposable exact-ID Docker containment check; no network or production start proof."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import re
from types import SimpleNamespace
from uuid import uuid4

from app.modules.host_agent.application.contracts import StartContainer
from app.modules.host_agent.application.dispatch import HostEffect
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import IngressContainment
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry, StopTarget
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.values import WorkspaceScope


def original():
    binding = str(uuid4())
    parent = OperationReference(
        deployment_id=str(uuid4()),
        scope=WorkspaceScope(operator_id=str(uuid4()), workspace_id=str(uuid4())),
        kind="provision",
        operation_id=str(uuid4()),
        idempotency_key="isolated-ingress-containment",
        request_hash="a" * 64,
    )
    return HostEffect(
        effect=EffectIdentity(
            parent=parent,
            binding_id=binding,
            resource_generation=1,
            kind="start_container",
            slot="native_check",
        ),
        access_epoch=1,
        expected_revision=1,
        payload=StartContainer(binding_id=binding),
    )


def create(engine, registry, image):
    command = original()
    identity = engine.create(
        command,
        {
            "Image": "sha256:" + image,
            "User": "42001:42001",
            "Cmd": ["python", "-c", "import time; time.sleep(120)"],
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true"],
                "Memory": 64 * 1024 * 1024,
                "MemorySwap": 64 * 1024 * 1024,
                "NanoCpus": 250000000,
                "PidsLimit": 16,
                "LogConfig": {"Type": "local", "Config": {"max-size": "1m", "max-file": "2"}},
            },
        },
    )
    try:
        with registry.lock("gate.lock", wait=True):
            registry.register(
                StopTarget(
                    command=command,
                    container_id=identity,
                    image_digest=image,
                    host_uid=42001,
                    host_gid=42001,
                )
            )
            engine.start(identity)
        assert engine.inspect(identity)["State"]["Running"]
    except Exception:
        engine.stop(identity)
        engine.remove_stopped(identity)
        raise
    return command, identity


def run(image):
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in is required.")
    if not re.fullmatch(r"[a-f0-9]{64}", image):
        raise ValueError("An already-present exact image digest is required.")
    root = Path(tempfile.mkdtemp(prefix="epm-ingress-containment-", dir="/var/lib"))
    registry = StopRegistry(root)
    engine, targets = DockerEngine(), []
    results = {"status": "failed", "image": image, "lab": str(root), "cases": {}}
    try:
        for _ in range(2):
            targets.append(create(engine, registry, image))
        command, identity = targets[0]
        allocation = SimpleNamespace(
            binding_id=command.effect.binding_id,
            resource_generation=1,
            container_ref=None,
        )
        # Simulate a started container whose ID has not yet committed to inventory.
        IngressContainment(registry, engine)(command, allocation)
        assert engine.inspect(identity)["State"]["Running"] is False
        assert engine.inspect(targets[1][1])["State"]["Running"] is True
        IngressContainment(registry, engine)(command, allocation)
        results["cases"] = {
            "uncommitted_runtime_stopped_by_exact_projection": True,
            "sibling_remains_running": True,
            "repeated_containment_is_safe": True,
        }
        results["source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
        results["status"] = "scoped_containment_pass"
    finally:
        for _, identity in targets:
            engine.stop(identity)
            engine.remove_stopped(identity)
        (root / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    run(parser.parse_args().image)
