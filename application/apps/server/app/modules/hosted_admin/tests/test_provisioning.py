"""Trusted admission and provider observations; no Linux/Cloudflare mutation."""

from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import fingerprint
from app.modules.hosted_admin.application.setup import SetupData
from app.modules.hosted_admin.infrastructure.cloudflare_setup import CloudflareSetup
from app.modules.hosted_admin.infrastructure.provisioning import (
    ProvisioningConfig,
    ProvisioningDependencies,
    ProvisioningHost,
)
from app.modules.hosted_admin.tests.test_qualification import qualification as qualification
from app.modules.hosted_admin.tests.test_authority import authority as authority


@pytest.fixture
def provisioner(qualification, tmp_path):
    qualifier, store, clock, snapshot, _, _ = qualification
    snapshot = snapshot.model_copy(
        update={"memory_total": 10**12, "disk_total": 10**13, "disk_free": 8 * 10**12}
    )
    qualifier.snapshot = lambda: snapshot
    config = ProvisioningConfig(
        deployment_kind="synthetic_demo",
        hostname_suffix="example.test",
        release=snapshot.release,
        release_digest="a" * 64,
        profile=snapshot.profile,
        template_digest="b" * 64,
        memory_bytes=10**8,
        disk_bytes=10**9,
        port_start=8000,
        issuer="https://team.cloudflareaccess.com",
        account="a" * 32,
        readiness_report=str(uuid4()),
    )
    platform = Mock()
    platform.configuration.return_value = config.model_dump()
    platform.paths_for.side_effect = lambda key: {
        "volume": tmp_path / key / "volume",
        "image": tmp_path / (key + ".ext4"),
    }
    source = Mock()
    source.inventory.list.return_value = []
    discovery = Mock()
    discovery.keys.return_value = []
    reports = Mock()
    reports.report.return_value = {
        "release": config.release,
        "profile": config.profile,
        "release_digest": config.release_digest,
        "configuration_hash": fingerprint(config.model_dump()),
        "template_digest": config.template_digest,
        "qualified": True,
        "observed": clock[0],
        "expires": clock[0] + 1000,
        "remaining_seats": 10,
    }
    host = ProvisioningHost(
        ProvisioningDependencies(store, source, discovery, qualifier, reports, platform)
    )
    return host, store, clock, config


def prepared(host):
    return {
        "config": host.config(),
        "report": host.d.reports.report.return_value,
        "registered": host.d.source.inventory.list(),
        "discovered": host.d.discovery.keys(),
        "snapshot": host.d.qualification.snapshot(),
    }


def test_server_assigns_stable_distinct_identities_and_bounded_ports(provisioner):
    host, _, _, config = provisioner
    data = SetupData(release=config.release, email="c@example.test")
    identifier = str(uuid4())
    one = host.plan(identifier, data)
    assert host.plan(identifier, data) == one
    assert (
        len({one[key] for key in ("instance_id", "allocation_id", "operator_id", "workspace_id")})
        == 4
    )
    assert 8000 <= one["port"] < 9000
    assert one["hostname"].endswith(".example.test")
    assert {item["kind"] for item in one["reservations"]} == {
        "hostname",
        "port",
        "user",
        "workspace",
        "email",
        "mount",
        "image",
        "disk",
        "memory",
    }
    assert host.plan(str(uuid4()), data) != one


def test_two_operator_ceiling_blocks_ordinary_third_before_effects(provisioner):
    host, store, _, config = provisioner
    plan = host.plan(str(uuid4()), SetupData(release=config.release, email="c@example.test"))
    with store.transaction() as connection:
        with pytest.raises(AdminError, match="capacity_unqualified"):
            host.check(connection, plan, prepared(host))
    host.d.platform.apply.assert_not_called()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"remaining_seats": 0}, "seats_unavailable"),
        ({"qualified": False}, "readiness_unverified"),
        ({"template_digest": "c" * 64}, "readiness_unverified"),
        ({"observed": 0}, "readiness_unverified"),
    ],
)
def test_unverified_quota_template_and_stale_evidence_block_admission(provisioner, change, code):
    host, store, _, config = provisioner
    host.d.reports.report.return_value |= change
    plan = host.plan(str(uuid4()), SetupData(release=config.release, email="c@example.test"))
    with store.transaction() as connection:
        with pytest.raises(AdminError, match=code):
            host.check(connection, plan, prepared(host))


def test_duplicate_email_is_casefolded_without_provider_specific_rewriting(provisioner):
    host, store, _, config = provisioner
    host.d.source.inventory.list.return_value = [
        SimpleNamespace(email="C+Exact@example.test", key="a")
    ]
    plan = host.plan(str(uuid4()), SetupData(release=config.release, email="c+exact@example.test"))
    with store.transaction() as connection:
        with pytest.raises(AdminError, match="email_exists"):
            host.check(connection, plan, prepared(host))


def test_tampered_or_changed_plan_cannot_reach_platform_effect(provisioner):
    host, _, _, config = provisioner
    draft_id = str(uuid4())
    data = SetupData(release=config.release, email="c@example.test").model_dump()
    payload = {"target": "arbitrary", "setup": {"draft_id": draft_id, "data": data, "plan": {}}}
    with pytest.raises(AdminError, match="configuration_changed"):
        host.apply(payload, "allocate")
    host.d.platform.apply.assert_not_called()


@contextmanager
def unlocked():
    yield


def provider_transport(*, policies=None, apps=None, challenge=True, pages=1):
    def request(url, headers):
        if url.startswith("https://api.cloudflare.com/"):
            assert headers["Authorization"] == "Bearer private-read-token"
            result = policies if "/policies?" in url else apps
            return (
                200,
                {},
                json.dumps(
                    {"success": True, "result": result, "result_info": {"total_pages": pages}}
                ).encode(),
            )
        assert headers == {}  # Never send the private token to the public origin.
        return (
            (302 if challenge else 200),
            {
                "Location": "https://team.cloudflareaccess.com/cdn-cgi/access/login/demo.example.test"
            },
            b"",
        )

    return request


def test_provider_verification_requires_exact_app_policy_and_public_challenge():
    app = {
        "domain": "demo.example.test",
        "type": "self_hosted",
        "id": str(uuid4()),
        "aud": "a" * 64,
    }
    policies = [{"decision": "allow", "include": [{"email": {"email": "c@example.test"}}]}]
    provider = CloudflareSetup(
        "a" * 32,
        "private-read-token",
        "https://team.cloudflareaccess.com",
        provider_transport(apps=[app], policies=policies),
    )
    assert provider.verify("demo.example.test", "c@example.test") == {
        "application": app["id"],
        "audience": app["aud"],
    }
    for changes in (
        {"policies": [{"decision": "bypass", "include": [{"everyone": {}}]}]},
        {"apps": [app, app]},
        {"challenge": False},
        {"pages": 2},
    ):
        provider.request = provider_transport(**({"apps": [app], "policies": policies} | changes))
        with pytest.raises(AdminError):
            provider.verify("demo.example.test", "c@example.test")


def test_readiness_waits_for_current_independently_verified_pre_enrollment_archive(provisioner):
    host, _, clock, config = provisioner
    data = SetupData(release=config.release, email="c@example.test")
    draft_id = str(uuid4())
    plan = host.plan(draft_id, data)
    payload = {
        "operation_id": str(uuid4()),
        "target": plan["key"],
        "setup": {"data": data.model_dump(), "draft_id": draft_id, "plan": plan},
    }
    from app.modules.hosted_admin.application.operations import Observation

    host.d.platform.lock.side_effect = unlocked
    host.d.platform.readiness.return_value = Observation("verified", {"verified": True})
    host.d.platform.deployment_digest.return_value = "f" * 64
    host.provider = Mock(return_value=Mock(verify=Mock(return_value={"audience": "c" * 64})))
    host.d.reports.report.side_effect = FileNotFoundError
    assert host.inspect(payload, "readiness").state == "waiting"
    host.d.reports.report.side_effect = None
    host.d.reports.report.return_value = {
        "operation_id": payload["operation_id"],
        "workspace_id": plan["workspace_id"],
        "configuration_digest": "f" * 64,
        "encrypted_archive": True,
        "independent_readback": True,
        "workspace_validated": True,
        "observed": clock[0],
        "expires": clock[0] + 3600,
    }
    assert host.inspect(payload, "readiness").state == "verified"
    host.d.reports.report.return_value["workspace_id"] = str(uuid4())
    with pytest.raises(AdminError, match="recovery_unverified"):
        host.inspect(payload, "readiness")


def test_linux_publication_refuses_symlinks_and_unowned_populated_destination(tmp_path):
    from scripts.host_admin import HostPaths, protected, read_json
    from app.modules.hosted_admin.infrastructure.linux_provisioning import LinuxProvisioning
    import os

    paths = HostPaths(
        control=tmp_path / "control",
        data=tmp_path / "data",
        security_root=tmp_path,
        owner_uid=os.getuid(),
    )
    paths.control.mkdir(mode=0o700)
    (paths.control / "provisioning").mkdir(mode=0o700)
    paths.data.mkdir(mode=0o700)
    platform = LinuxProvisioning(
        SimpleNamespace(paths=paths, protected=protected, read_json=read_json), Mock()
    )
    target = paths.control / "symlink"
    target.symlink_to(paths.control / "missing")
    with pytest.raises(ValueError):
        platform.publish(target, b"do not follow")
    (paths.data / "epm-d-test").mkdir(mode=0o700)
    payload = {"operation_id": str(uuid4()), "setup": {"plan": {"key": "d-test"}}}
    with pytest.raises(AdminError, match="allocation_conflict"):
        platform.owned(payload, create=True)
    platform.run.assert_not_called()


def test_workspace_reserved_identity_is_validated_without_rewriting_existing_data(tmp_path):
    from app.modules.workspace.application.service import WorkspaceService, WorkspaceError

    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    service = WorkspaceService.from_local_config(config)
    reserved = str(uuid4())
    assert service.initialize(workspace_id=reserved).workspace_id == reserved
    assert service.initialize(workspace_id=reserved).workspace_id == reserved
    with pytest.raises(WorkspaceError, match="differs"):
        service.initialize(workspace_id=str(uuid4()))
