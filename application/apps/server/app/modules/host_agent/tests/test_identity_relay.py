"""Scoped relay tests use real Unix sockets and synthetic owning handlers."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace

import pytest

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.identity_relay import (
    IdentityRelayCall,
    handle_identity,
    invoke_identity,
    open_relay_socket,
    serve_identity,
)
from app.modules.host_agent.infrastructure.endpoint_policy import identity_provider_policy
from app.modules.host_agent.infrastructure import service_runtime
from app.modules.hosted_access.application.source_contracts import (
    Claim,
    SourceCommand,
    SourceResult,
)
from app.platform.hosted_contracts.operations import OperationOutcome, OperationState
from app.platform.hosted_contracts.semantic import semantic_hash

ID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def call(method="execute"):
    payload = Claim(invitation_id=ID, verified_identity_ref="verified", readiness_proof_ref="ready")
    intent = {
        "deployment_id": ID,
        "scope": {"kind": "workspace", "operator_id": ID, "workspace_id": OTHER},
        "kind": "claim",
        "expected_revision": 1,
        "access_epoch": 2,
        "payload": payload,
        "component": None,
    }
    # Compute the hash from the validated semantic intent, including its defaults.
    intent_type = SourceCommand.model_fields["intent"].annotation
    intent = intent_type.model_validate(intent)
    return IdentityRelayCall(
        method=method,
        command=SourceCommand(
            operation_id=ID,
            idempotency_key="claim-original",
            intent=intent,
            request_hash=semantic_hash(intent),
        ),
    )


def test_relay_runtime_resolves_current_scope_and_retains_original_outcome(monkeypatch):
    class Registry:
        def resolve_identity_control(self, deployment, scope, epoch, *, original):
            assert (deployment, scope.workspace_id, epoch) == (ID, OTHER, 2)
            return SimpleNamespace(path=source_path, uid=os.getuid())

    calls = []

    def source_dispatch(request, *, deadline):
        calls.append(request)
        return OperationOutcome[SourceResult](
            operation=request.command.reference(),
            state=OperationState.SUCCEEDED,
            revision=1,
            observed_at=2,
            result=SourceResult(
                access_epoch=2, effective_enabled=False, receipt_ref="source-original"
            ),
        )

    with TemporaryDirectory(dir="/tmp") as directory:
        base = Path(directory).resolve()
        source_path, relay_path = base / "s.sock", base / "relay.sock"
        base.chmod(0o750)
        (base / "stops").mkdir(mode=0o700)
        monkeypatch.setattr(service_runtime, "IDENTITY_RELAY_DIRECTORY", base)
        runtime = service_runtime.ServiceRuntime(
            SimpleNamespace(
                layout=SimpleNamespace(stops=str(base / "stops")),
                network=None,
                identity_relay=SimpleNamespace(
                    central_gid=base.stat().st_gid,
                    central_uid=os.getuid(),
                    source_return_directory=None,
                ),
            )
        )
        monkeypatch.setattr(runtime, "inventory", lambda: "protected-inventory")

        def registration(inventory):
            assert inventory == "protected-inventory"
            return Registry()

        monkeypatch.setattr(runtime, "registered_sources", registration)
        listening = Event()

        def serve_relay(listener, dispatch, **kwargs):
            listening.set()
            serve_identity(listener, dispatch, **kwargs)

        monkeypatch.setattr(service_runtime, "serve_identity", serve_relay)
        with socket.socket(socket.AF_UNIX) as source:
            source.bind(str(source_path))
            source.listen(1)
            stop = Event()
            with ThreadPoolExecutor(max_workers=2) as workers:
                source_task = workers.submit(
                    serve_identity,
                    source,
                    source_dispatch,
                    allowed_uid=os.getuid(),
                    stopping=stop,
                    workers=1,
                )
                relay_task = workers.submit(runtime.serve_relay, stop)
                try:
                    assert listening.wait(5)
                    assert relay_path.stat().st_mode & 0o777 == 0o660
                    for method in ("execute", "original"):
                        result = invoke_identity(relay_path, call(method), expected_uid=os.getuid())
                        assert result.result.receipt_ref == "source-original"
                        assert not result.result.effective_enabled
                finally:
                    stop.set()
                source_task.result(timeout=5)
                relay_task.result(timeout=5)
            assert not relay_path.exists()
    assert [item.method for item in calls] == ["execute", "original"]


def test_relay_socket_denies_writable_directory_and_preserves_existing_path():
    with TemporaryDirectory(dir="/tmp") as directory:
        base = Path(directory).resolve()
        gid = base.stat().st_gid
        base.chmod(0o770)
        with pytest.raises(HostAgentDenied), open_relay_socket(base, central_gid=gid):
            pytest.fail("writable directory admitted")
        base.chmod(0o750)
        path = base / "relay.sock"
        path.touch()
        with pytest.raises(OSError), open_relay_socket(base, central_gid=gid):
            pytest.fail("existing path replaced")
        assert path.is_file()


def test_peer_denial_happens_before_parsing():
    from app.modules.host_agent.infrastructure.identity_relay import _receive
    from time import monotonic

    server, client = socket.socketpair()
    with server, client:
        handle_identity(server, lambda *_: pytest.fail("dispatched"), allowed_uid=os.getuid() + 1)
        assert _receive(client, monotonic() + 1) == {"error": "denied"}


def test_expired_relay_budget_and_scoped_egress():
    from time import monotonic

    with pytest.raises(HostAgentUnavailable):
        invoke_identity(
            Path("/tmp").resolve() / "absent.sock",
            call(),
            expected_uid=os.getuid(),
            deadline=monotonic(),
        )
    provider = identity_provider_policy("central_identity")
    assert provider.hosts == ("identitytoolkit.googleapis.com", "www.googleapis.com")
    with pytest.raises(HostAgentDenied):
        identity_provider_policy("operator")
    with pytest.raises(HostAgentDenied):
        provider.resolve("unregistered.example:443")


def test_source_return_checks_owning_scope_before_opening_central_socket(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from app.modules.host_agent.infrastructure import identity_relay
    from app.modules.hosted_access.application.handoff_channel import (
        ReadContinuation,
        HandoffAccepted,
    )
    from app.modules.hosted_access.application.identity_evidence import IdentityBinding

    deployment = "00000000-0000-4000-8000-000000000001"
    workspace = "00000000-0000-4000-8000-000000000002"
    operator = "00000000-0000-4000-8000-000000000003"
    origin = "https://owner.example.invalid"
    binding = IdentityBinding(
        deployment_id=deployment,
        scope={"operator_id": operator, "workspace_id": workspace},
        binding_id=deployment,
        resource_generation=1,
        access_epoch=1,
        assignment_revision=1,
        registered_origin_id=deployment,
        target_origin=origin,
        issuer="realm",
        subject="synthetic",
    )
    source = Mock()
    invoke = Mock(return_value=HandoffAccepted())
    monkeypatch.setattr(identity_relay, "invoke_identity", invoke)
    relay = identity_relay.SourceReturnRelay(
        source,
        {
            "operator_id": operator,
            "workspace_id": workspace,
            "binding_id": deployment,
            "resource_generation": 1,
            "public_origin": origin,
        },
        tmp_path,
        65532,
    )
    command = ReadContinuation(binding=binding, continuation_id=deployment)
    relay(command, deadline=123)
    source.resolve_identity_source.assert_called_once_with(deployment, binding.scope, 1)
    invoke.assert_called_once_with(
        tmp_path / (operator + ".sock"), command, expected_uid=65532, deadline=123
    )
    with pytest.raises(HostAgentDenied):
        relay(
            command.model_copy(
                update={
                    "binding": binding.model_copy(
                        update={"target_origin": "https://other.example.invalid"}
                    )
                }
            ),
            deadline=123,
        )
    assert invoke.call_count == 1


def test_central_proxy_stays_on_the_exact_private_peer_and_project():
    from app.modules.host_agent.infrastructure.identity_egress import CentralProxy, EgressInputs

    inputs = EgressInputs.model_validate_json(
        '{"address":"10.3.0.1","central_address":"10.3.0.3","port":1080,'
        '"firebase_project":"synthetic-project-123"}'
    )
    assert str(inputs.central_address) == "10.3.0.3"
    proxy = object.__new__(CentralProxy)
    proxy.central_address = str(inputs.central_address)
    assert proxy.verify_request(None, ("10.3.0.3", 12345))
    assert not proxy.verify_request(None, ("10.3.0.4", 12345))
    policy = identity_provider_policy("central_identity", firebase_project=inputs.firebase_project)
    assert "synthetic-project-123.firebaseapp.com" in policy.hosts
    assert "other-project-123.firebaseapp.com" not in policy.hosts
    with pytest.raises(HostAgentDenied):
        identity_provider_policy("operator", firebase_project=inputs.firebase_project)
