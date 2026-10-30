"""Target-only Linux orchestration with real inventory and source receipts."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from scripts.admin_lifecycle import AccessCutover
from scripts.tests.test_host_inventory import instance, inventory as inventory
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values
from app.modules.hosted_access.tests.test_source_commands import source as source, approved_source
from app.modules.hosted_access.application.admin_commands import AccessCommand
from app.modules.hosted_access.application.configuration import HostedDeployment


@pytest.mark.parametrize("action", ["renew", "replace_email"])
def test_cutover_resumes_after_config_publication_without_second_source_mutation(
    source, inventory, tmp_path, monkeypatch, action
):
    store, commands, now = approved_source(source)
    configs = tmp_path / "configs"
    configs.mkdir()
    path = configs / "hosted-c.json"
    path.write_text(store.deployment.model_dump_json())
    item = replace(
        instance("c"),
        workspace_id=str(store.deployment.workspace_id),
        operator_id=str(store.deployment.operator_id),
        email=store.deployment.allowed_email,
        config_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    inventory.register(item)
    reference = {
        "instance": asdict(item),
        "deployment": store.deployment.model_dump(mode="json"),
        "deployment_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    cmd = AccessCommand(
        operation_id=str(uuid4()),
        action=action,
        expected_revision=1,
        expected_binding_revision=1,
        fence=0,
        authority_reference="owner:1",
        reason="Explicit new demo window",
        **(
            {"starts": now.timestamp(), "expires": now.timestamp() + 14 * 86400}
            if action == "renew"
            else {"replacement_email": "replacement@example.test"}
        ),
    )
    payload = cmd.model_dump() | {"instance": "c", "confirmed": True, "source_reference": reference}
    transport = Mock()

    def invoke(_instance, raw):
        store.deployment = HostedDeployment.model_validate_json(path.read_bytes())
        if raw.get("query") == "receipt":
            result = commands.receipt(AccessCommand.model_validate(raw["command"]))
            return {"found": result is not None, "result": result.model_dump() if result else None}
        return commands.execute(AccessCommand.model_validate(raw), now).model_dump()

    transport.side_effect = invoke
    platform = Mock()
    platform.lock.side_effect = nullcontext
    platform.service_state.return_value = "inactive"
    platform.publish.side_effect = lambda file, raw, _gid: file.write_bytes(raw)
    platform.h.save_baseline.return_value = "f" * 64
    provider = Mock()
    provider.verify.return_value = {"audience": store.deployment.identity_audience}
    monkeypatch.setattr("scripts.admin_lifecycle.CloudflareSetup", lambda *_: provider)
    platform.configuration.return_value = {"account": "fixed", "issuer": "https://issuer.test"}
    desired_fields = dict(
        workspace_id=item.workspace_id,
        operator_id=item.operator_id,
        email=item.email if action == "renew" else "replacement@example.test",
        port=item.port,
        release=item.release,
    )
    platform.h.discovery.observe.side_effect = [
        OSError("lost runtime observation"),
        {"fields": desired_fields},
    ]
    runner = SimpleNamespace(
        paths=SimpleNamespace(configs=configs),
        inventory=inventory,
        _transport=transport,
        _command=lambda _: cmd,
    )
    platform.h.read_json.side_effect = lambda file, _: json.loads(file.read_bytes())
    monkeypatch.setattr("scripts.admin_lifecycle.pwd.getpwnam", lambda _: SimpleNamespace(pw_gid=1))
    cutover = AccessCutover(runner, platform)
    if action == "replace_email":
        provider.verify.return_value = None
        with pytest.raises(ValueError, match="replacement_provider_setup_required"):
            cutover(payload)
        assert commands.status()["admin_revision"] == 1
        platform.call.assert_not_called()
        provider.verify.return_value = {"audience": store.deployment.identity_audience}
    with pytest.raises(OSError):
        cutover(payload)
    assert not commands.status()["active"] and commands.status()["admin_revision"] == 2
    assert inventory.get("c").revision == 1
    assert cutover.lookup(payload) is None
    result = cutover(payload)
    assert result["revision"] == 2 and not result["active"]
    assert inventory.get("c").revision == 2
    assert cutover.lookup(payload) == result
    commands.validate_retained()
    assert all(call.args[0][-1] == "epm-hosted@c.service" for call in platform.call.call_args_list)
    with inventory.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM inventory_audit WHERE action='access_cutover'"
            ).fetchone()[0]
            == 1
        )
    if action == "renew":
        assert datetime.fromtimestamp(payload["starts"], UTC) < datetime.fromtimestamp(
            payload["expires"], UTC
        )
    else:
        assert not commands.administrative_status().identity_approved
        assert inventory.get("c").email == "replacement@example.test"
