"""Synthetic prior-route streaming denial; no production eligibility or business data."""

from copy import deepcopy
import json
import os
import select
import subprocess
import sys
import time
from types import SimpleNamespace

from app.modules.host_agent.application.contracts import StartContainer
from app.modules.host_agent.application.ingress import IngressRecord, IngressProjection
from app.modules.host_agent.application.dispatch import HostEffect, IngressPolicy
from app.modules.host_agent.infrastructure.gateway import (
    CaddyAdmin,
    Gateway,
    GatewaySettings,
    IngressContainment,
    closed_config,
)
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry, StopTarget
from qualify_containment import original


def verify(root, settings, target, identity, binary):
    image = DockerEngine().inspect(identity)["Config"]["Image"].removeprefix("sha256:")
    runtime = root / "caddy-run"
    runtime.mkdir(mode=0o700)
    os.chown(runtime, settings.gateway_uid, settings.gateway_uid)
    root.chmod(0o711)
    gateway_settings = GatewaySettings(
        runtime / "admin.sock", settings.gateway_uid, settings.gateway_port
    )
    start = original()
    effect = start.effect.model_copy(
        update={"binding_id": target.name[6:42], "kind": "apply_ingress_policy"}
    )
    command = HostEffect(
        effect=effect,
        access_epoch=2,
        expected_revision=1,
        payload=IngressPolicy(desired_state="blocked", expected_ingress_revision=1),
    )
    scope = effect.parent.scope
    row = IngressRecord(
        binding_id=effect.binding_id,
        operator_id=scope.operator_id,
        workspace_id=scope.workspace_id,
        resource_generation=1,
        access_epoch=2,
        operation_id=effect.child_id(),
        desired_state="blocked",
        public_origin="https://operator.example.invalid",
    )
    projection = IngressProjection(records=(row,))
    denied = closed_config(projection, gateway_settings)
    prior = deepcopy(denied)
    # Lab-only prior positive route, never emitted by the production closed generator.
    prior["apps"]["http"]["servers"]["gateway"]["routes"][0]["handle"] = [
        {
            "handler": "reverse_proxy",
            "flush_interval": -1,
            "upstreams": [{"dial": target.address4 + ":8000"}],
        }
    ]
    config = root / "prior-synthetic.json"
    config.write_text(json.dumps(prior))
    config.chmod(0o644)
    log = (root / "stream-caddy.log").open("wb")
    process = subprocess.Popen(
        [
            str(binary),
            "run",
            "--config",
            str(config),
        ],
        user=settings.gateway_uid,
        group=settings.gateway_uid,
        extra_groups=[],
        stdout=log,
        stderr=subprocess.STDOUT,
        umask=0o007,
        env=os.environ | {"XDG_DATA_HOME": str(runtime), "XDG_CONFIG_HOME": str(runtime)},
    )
    client = None
    try:
        await_admin(process, gateway_settings)
        client = stream_client(settings)
        ready, _, _ = select.select([client.stdout], [], [], 5)
        assert ready and client.stdout.readline().strip() == b"ready"
        registry_dir = root / "stops"
        registry_dir.mkdir(mode=0o700)
        registry = StopRegistry(registry_dir)
        start = start.model_copy(
            update={
                "effect": start.effect.model_copy(update={"binding_id": effect.binding_id}),
                "payload": StartContainer(binding_id=effect.binding_id),
            }
        )
        # Projection registration happened before this synthetic start in production;
        # this fixture installs only the exact already-running lab target for stop proof.
        registry.register(
            StopTarget(
                command=start,
                container_id=identity,
                image_digest=image,
                host_uid=42001,
                host_gid=42001,
            )
        )
        engine = DockerEngine()
        gateway = Gateway(
            SimpleNamespace(ingress_projection=lambda: projection),
            CaddyAdmin(gateway_settings),
            gateway_settings,
            IngressContainment(registry, engine),
        )
        allocation = SimpleNamespace(
            binding_id=effect.binding_id,
            resource_generation=1,
            container_ref=identity,
            ingress_projection_revision=2,
        )
        assert gateway.apply(command, allocation).status == "applied"
        client.wait(timeout=5)
        assert client.returncode == 0 and client.stdout.read().strip() == b"closed"
        assert engine.inspect(identity)["State"]["Running"] is False
        return {
            "existing_stream_closed": True,
            "target_stopped": True,
            "deny_config_verified": CaddyAdmin(gateway_settings).inspect() == denied,
        }
    finally:
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=5)
        process.terminate()
        process.wait(timeout=5)
        log.close()


def await_admin(process, settings):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Synthetic Caddy failed; inspect private log")
        if settings.admin_socket.exists():
            return
        time.sleep(0.05)
    raise RuntimeError("Synthetic Caddy not ready")


def stream_client(settings):
    code = (
        "import http.client,sys; "
        "c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=5); "
        "c.request('GET','/stream',headers={'Host':'operator.example.invalid',"
        "'X-Forwarded-Proto':'https'}); "
        "r=c.getresponse(); assert r.status==200; assert r.readline()==b'tick\\n'; "
        "print('ready',flush=True); "
        "\ntry:\n while r.readline(): pass"
        "\nexcept (OSError,http.client.IncompleteRead): pass"
        "\nprint('closed',flush=True)"
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(settings.gateway_port),
        ],
        user=settings.tunnel_uid,
        group=settings.tunnel_uid,
        extra_groups=[],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
