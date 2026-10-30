"""Manual edge denial cannot be replaced by an app receipt or browser assertion."""

from types import SimpleNamespace
import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.authority import SourceEffect
from app.modules.hosted_admin.infrastructure.cloudflare_setup import CloudflareSetup
from app.modules.hosted_admin.infrastructure.edge_denial import EdgeDenial
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.tests.test_onboarding import onboarding as onboarding
from app.modules.hosted_admin.tests.test_authority import command, login, request
from app.modules.hosted_admin.tests.test_provisioning import provider_transport
from app.modules.hosted_access.tests.test_source_commands import source as source
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values


def test_disable_waits_for_private_denial_and_resumes_without_another_source_write(onboarding):
    f = onboarding
    reference = {
        "instance": {"allocation_id": "fixed-allocation", "hostname": "demo.example.test"},
        "deployment_digest": "a" * 64,
    }
    cmd = command(expected_revision=1, expected_binding_revision=1)
    admitted = f.store.admit(request(login(f.store), cmd), lambda _: reference)
    payload = json.loads(admitted["payload"])
    result = {
        "operation_id": cmd.operation_id,
        "action": "disable",
        "revision": 2,
        "binding_revision": 1,
        "fence": 1,
        "generation": 1,
        "active": False,
    }
    write = Mock(return_value=result)
    provider = Mock()
    dispatch = SimpleNamespace(
        reconcile=lambda _: result if write.called else None,
        access_snapshot=lambda _: (
            {"identity_audience": "b" * 64},
            {"active": False, "admin_revision": 2},
        ),
        prepare=lambda _: reference,
    )
    denial = EdgeDenial(f.store, dispatch, f.reports, lambda: provider)
    dispatch.edge_denial = denial
    effect = SourceEffect(dispatch)
    effect.apply = lambda value, _: write(value)
    engine = OperationEngine(f.store)
    with pytest.raises(AdminError, match="app_disable_required"):
        denial.verify(cmd.operation_id)
    with pytest.raises(AdminError, match="reconciliation_required"):
        engine.run(cmd.operation_id, effect)
    assert engine.get(cmd.operation_id)["state"] == "waiting"
    assert not denial.confirmed(payload)
    denial.verify(cmd.operation_id)
    provider.verify_denial.assert_called_once_with("demo.example.test", "b" * 64)
    assert denial.confirmed(payload)
    with f.store.transaction() as connection:
        identity = dict(f.store._identity(connection))
    engine.resume(cmd.operation_id, engine.get(cmd.operation_id)["revision"], identity)
    engine.run(cmd.operation_id, effect)
    assert engine.get(cmd.operation_id)["state"] == "succeeded"
    write.assert_called_once()
    assert not denial.confirmed(payload | {"reason": "changed intent"})
    f.clock[0] += 600
    assert not denial.confirmed(payload)


@pytest.mark.parametrize(
    "mode", ["denied", "allow", "bypass", "missing", "multiple", "wrong_audience"]
)
def test_manual_edge_verification_requires_retained_exact_app_and_only_deny_everyone(mode):
    app = {
        "domain": "demo.example.test",
        "type": "self_hosted",
        "id": str(uuid4()),
        "aud": "a" * 64,
    }
    policy = {"decision": "deny", "include": [{"everyone": {}}]}
    apps = [] if mode == "missing" else [app, app] if mode == "multiple" else [app]
    if mode in {"allow", "bypass"}:
        policy["decision"] = mode
    transport = provider_transport(apps=apps, policies=[policy])
    provider = CloudflareSetup(
        "a" * 32,
        "private-read-token",
        "https://team.cloudflareaccess.com",
        lambda url, headers: (
            transport(url, headers)
            if url.startswith("https://api.cloudflare.com/")
            else (403, {"cf-ray": "private-provider-observation"}, b"")
        ),
    )
    if mode == "denied":
        assert provider.verify_denial(app["domain"], app["aud"])["application"] == app["id"]
    else:
        with pytest.raises(AdminError, match="denial_unverified"):
            provider.verify_denial(
                app["domain"], "b" * 64 if mode == "wrong_audience" else app["aud"]
            )
