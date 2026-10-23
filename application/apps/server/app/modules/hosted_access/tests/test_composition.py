"""The real domain composition is protected, not merely a synthetic test endpoint."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
import secrets
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.bootstrap.api import create_app
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.storage_budget import HostedStorageBudget, StorageFacts
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.service import WorkspaceService
from app.platform.browser_transport import BrowserTransportPolicy
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption


@pytest.fixture
def hosted_app(tmp_path, deployment_values, monkeypatch, request):
    # This macOS-compatible composition suite tests admission using synthetic disk
    # facts. Real Linux mount/capacity qualification is a separate deployment gate.
    monkeypatch.setattr(
        "app.bootstrap.hosted_access.build_storage_budget",
        lambda *_args: HostedStorageBudget(
            lambda: StorageFacts(250 * 1024**2, 220 * 1024**2, 30 * 1024**3, 20 * 1024**3, 10000)
        ),
    )
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    manifest = WorkspaceService.from_local_config(config).initialize()
    deployment = HostedDeployment.model_validate(
        {
            **deployment_values,
            "workspace_id": manifest.workspace_id,
            "capabilities": getattr(request, "param", deployment_values["capabilities"]),
        }
    )
    SQLiteHostedSessionStore.initialize(deployment)
    store = SQLiteHostedSessionStore(deployment)
    now = datetime.now(UTC)
    proof = VerifiedIdentity(
        deployment.identity_issuer,
        "verified-subject",
        deployment.allowed_email,
        now,
        now + timedelta(hours=1),
        sha256(b"real-composition-proof").hexdigest(),
    )

    def verify(assertion):
        if assertion != "valid-assertion":
            raise HostedAccessError("hosted_identity_rejected", "Identity rejected.")
        return proof

    monkeypatch.setattr("app.bootstrap.api.load_hosted_deployment", lambda _path: deployment)
    monkeypatch.setattr(
        "app.bootstrap.hosted_access.CloudflareIdentityVerifier",
        lambda _deployment: Mock(verify=verify),
    )
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><head><title>Demo</title></head><body>App</body></html>")
    (web / "assets").mkdir()
    (web / "assets" / "app-aaaaaaaa.js").write_text("// compiled fixture")
    app = create_app(config, hosted_deployment_path=tmp_path / "protected.json", web_build_path=web)
    with TestClient(app, base_url=deployment.public_origin, client=("127.0.0.1", 123)) as client:
        client.headers.update(
            {
                "cf-access-jwt-assertion": "valid-assertion",
                "origin": deployment.public_origin,
            }
        )
        yield app, client, store, deployment
    store.engine.dispose()


def enroll(client, store):
    assert client.post("/api/hosted/session").status_code == 403
    store.activate("verified-subject")
    response = client.post("/api/hosted/session")
    assert response.status_code == 200
    client.headers["x-epm-csrf"] = response.json()["csrfToken"]


def test_identity_redirect_navigation_serves_only_public_sign_in_shell(hosted_app):
    _app, client, _store, _deployment = hosted_app
    del client.headers["origin"]
    del client.headers["cf-access-jwt-assertion"]
    headers = {
        "accept": "text/html",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document",
    }
    response = client.get("/sign-in", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "<html>" in response.text
    denied = client.get("/api/operator/bootstrap", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "hosted_origin_rejected"


def test_real_bootstrap_file_recovery_and_receipts_require_authorization(hosted_app):
    _app, client, store, deployment = hosted_app
    paths = [
        "/api/operator/bootstrap",
        "/api/operator/recovery",
        "/api/audit/events",
        f"/api/files/{uuid4()}/content",
        f"/api/tasks/creation-operations/{uuid4()}",
    ]
    for path in paths:
        assert client.get(path).status_code == 401
    enroll(client, store)
    bootstrap = client.get(paths[0])
    assert bootstrap.status_code == 200
    assert bootstrap.json()["workspaceId"] == str(deployment.workspace_id)
    assert bootstrap.headers["cache-control"] == "no-store"
    command = {"title": "Hosted task", "expectedRevision": 0, "idempotencyKey": str(uuid4())}
    created = client.post("/api/tasks", json=command)
    assert created.status_code == 201, created.text
    assert client.post("/api/tasks", json=command).json() == created.json()
    receipt_path = f"/api/tasks/creation-operations/{command['idempotencyKey']}"
    assert client.get(receipt_path).json() == created.json()
    store.disable(datetime.now(UTC))
    for path in [*paths, receipt_path]:
        assert client.get(path).status_code == 401


def test_runtime_binding_and_host_administration_are_fenced(hosted_app):
    app, client, store, _deployment = hosted_app
    enroll(client, store)
    for method, path in [
        ("GET", "/api/workspace/status"),
        ("POST", "/api/workspace/initialize"),
        ("GET", "/api/files/integrity-attention"),
        ("POST", "/api/files/verify"),
        ("GET", "/api/ai/settings"),
        ("GET", "/health"),
        ("GET", "/openapi.json"),
    ]:
        assert client.request(method, path).status_code == 403
    app.state.workspace_runtime.workspace_id = str(uuid4())
    response = client.get("/api/operator/bootstrap")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "hosted_workspace_unavailable"
    assert client.get("/api/hosted/session").status_code == 200


def test_quota_and_host_maintenance_precede_domain_work_without_blocking_logout(hosted_app):
    app, client, store, _deployment = hosted_app
    enroll(client, store)
    original = app.state.hosted_storage_budget.facts
    state = original()
    from dataclasses import replace

    app.state.hosted_storage_budget.facts = lambda: replace(state, available_bytes=1024)
    body = {"title": "Must not be created", "expectedRevision": 0, "idempotencyKey": str(uuid4())}
    response = client.post("/api/tasks", json=body)
    assert response.status_code == 507
    assert response.json()["detail"]["code"] == "hosted_storage_quota_exceeded"
    assert response.headers["cache-control"] == "no-store"
    assert app.state.hosted_storage_budget.reserved_bytes == 0
    # Keep the authenticated non-business shell available to explain API failure.
    assert client.get("/tasks", headers={"accept": "text/html"}).status_code == 200
    assert client.get("/api/operator/bootstrap").status_code == 507
    app.state.hosted_storage_budget.facts = original
    assert client.get(f"/api/tasks/creation-operations/{body['idempotencyKey']}").status_code == 404
    app.state.hosted_storage_budget.facts = lambda: replace(
        state, host_available_bytes=state.host_total_bytes // 10
    )
    paused = client.post("/api/tasks", json=body)
    assert paused.status_code == 503
    assert paused.json()["detail"]["code"] == "hosted_write_maintenance"
    assert client.get("/api/operator/bootstrap").status_code == 200
    assert client.delete("/api/hosted/session").status_code == 204


def test_hosted_mode_cannot_combine_local_transport(hosted_app, tmp_path):
    _app, _client, _store, _deployment = hosted_app
    with pytest.raises(ValueError, match="cannot be combined"):
        create_app(
            tmp_path / "local.json",
            hosted_deployment_path=tmp_path / "protected.json",
            transport_policy=BrowserTransportPolicy(),
        )


@pytest.mark.parametrize("hosted_app", [["records.read"]], indirect=True)
def test_read_only_capabilities_reject_writes_and_file_reads(hosted_app):
    _app, client, store, _deployment = hosted_app
    enroll(client, store)
    bootstrap = client.get("/api/operator/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["canWrite"] is False
    assert client.post("/api/tasks", json={}).status_code == 403
    assert client.get(f"/api/files/{uuid4()}/content").status_code == 403


def test_every_registered_business_path_is_guarded_before_dispatch(hosted_app, monkeypatch):
    app, client, _store, _deployment = hosted_app
    monkeypatch.setattr("app.modules.hosted_access.api.middleware.MAX_REQUESTS_PER_MINUTE", 10000)
    for template, operations in app.openapi()["paths"].items():
        if template.startswith("/api/hosted/"):
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid4()), template)
        method = next(
            verb for verb in operations if verb in {"get", "post", "put", "delete", "patch"}
        )
        response = client.request(method, path)
        assert response.status_code in {401, 403}, (method, template, response.text)
        assert response.headers["cache-control"] == "no-store"


def test_public_sign_in_shell_and_deep_link_do_not_disclose_workspace_data(hosted_app):
    _app, client, store, deployment = hosted_app
    response = client.get("/maintenance", headers={"accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in?next=%2Fmaintenance"
    deep_link = client.get(
        "/tasks?workflow=task.create", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert deep_link.headers["location"] == "/sign-in?next=%2Ftasks%3Fworkflow%3Dtask.create"
    shell = client.get("/sign-in", headers={"accept": "text/html"})
    assert shell.status_code == 200
    assert 'name="epm-deployment" content="hosted_demo"' in shell.text
    assert str(deployment.workspace_id) not in shell.text
    assert deployment.identity_audience not in shell.text
    assert str(deployment.administration_database) not in shell.text
    assert shell.headers["cache-control"] == "no-store"
    asset = client.get("/assets/app-aaaaaaaa.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    # HTML Accept does not turn a protected API into a public sign-in shell.
    assert client.get("/api/operator/bootstrap", headers={"accept": "text/html"}).status_code == 401
    enroll(client, store)
    assert client.get("/maintenance", headers={"accept": "text/html"}).status_code == 200


def test_recovery_mutation_requires_current_lease_even_for_original_key_replay(hosted_app):
    _app, client, store, _deployment = hosted_app
    enroll(client, store)
    record_id = str(uuid4())
    path = f"/api/operator/recovery/{record_id}"
    claim_path = f"/api/hosted/drafts/{record_id}/lease"
    body = {
        "formKey": "task.create",
        "schemaVersion": 1,
        "payload": {"title": "Private draft"},
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
    }
    assert client.put(path, json=body).status_code == 409
    first, second = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    assert client.post(claim_path, json={"token": first, "expectedRevision": 0}).status_code == 200
    client.headers["x-epm-draft-lease"] = first
    saved = client.put(path, json=body)
    assert saved.status_code == 200, saved.text
    assert client.put(path, json=body).json() == saved.json()
    assert client.post(claim_path, json={"token": second, "expectedRevision": 1}).status_code == 409
    takeover = client.post(
        claim_path, json={"token": second, "expectedRevision": 1, "takeover": True}
    )
    assert takeover.status_code == 200, takeover.text
    # Even a recorded replay cannot bypass the current edit authority.
    assert client.put(path, json=body).status_code == 409
    assert client.get(path).json()["revision"] == 1
    client.headers["x-epm-draft-lease"] = second
    updated = client.put(path, json={**body, "expectedRevision": 1, "idempotencyKey": str(uuid4())})
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2


def test_verified_actor_survives_replay_sensitive_reads_and_portable_restore(hosted_app, tmp_path):
    app, client, store, deployment = hosted_app
    enroll(client, store)
    runtime = app.state.workspace_runtime
    repository = SQLiteAuditRepository(runtime.service.paths.database)
    command = {"title": "Audited task", "expectedRevision": 0, "idempotencyKey": str(uuid4())}
    response = client.post("/api/tasks", json=command)
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    original = repository.history("task", task_id)
    assert original and all(event.actor_kind == "hosted_operator" for event in original)
    assert {event.actor_reference for event in original} == {str(deployment.operator_id)}
    client.headers["x-actor-reference"] = str(uuid4())
    assert client.post("/api/tasks", json=command).json() == response.json()
    assert repository.history("task", task_id) == original

    source = {
        "sourceKind": "operator_note",
        "channel": "internal",
        "body": "Synthetic source",
        "occurredAtUtc": datetime.now(UTC).isoformat(),
        "originSystem": "manual",
        "idempotencyKey": str(uuid4()),
    }
    admitted = client.post(
        "/api/intake/sources/import",
        data={"metadata": json.dumps(source)},
        files=[("files", ("evidence.txt", b"synthetic evidence", "text/plain"))],
    )
    assert admitted.status_code == 200, admitted.text
    source_id = admitted.json()["sourceId"]
    assert client.get(f"/api/intake/sources/{source_id}").status_code == 200
    events = repository.history("intake_source", source_id)
    assert any(event.action == "evidence_read" for event in events)
    assert all(
        event.actor_kind == "hosted_operator"
        and event.actor_reference == str(deployment.operator_id)
        for event in events
    )
    # Includes source-owned retained validators, not merely the generic Audit check.
    runtime.service.open(integrity_check=True)
    runtime.stop()
    backups = app.state.backup_service
    with fast_backup_encryption():
        archive = backups.create_backup(
            "synthetic test passphrase", output_path=tmp_path / "copy.epm-backup"
        )
        contents = backups.validate_archive(archive.archive_path, "synthetic test passphrase")
        restored = backups.restore(
            archive.archive_path, "synthetic test passphrase", tmp_path / "restored"
        )
    assert contents.file_count > 0
    restored_config = tmp_path / "restored.json"
    restored_config.write_text(json.dumps({"localWorkspacePath": str(restored.workspace_path)}))
    restored_workspace = WorkspaceService.from_local_config(restored_config)
    assert restored_workspace.open().workspace_id == str(deployment.workspace_id)
    restored_history = SQLiteAuditRepository(restored_workspace.paths.database).history(
        "task", task_id
    )
    assert restored_history == original
    assert not (restored.workspace_path / deployment.administration_database.name).exists()
    old_cookie = client.cookies.get("__Host-epm_session")
    # The same administrative store must notice a new restore event and invalidate enrollment.
    restored_app = create_app(restored_config, hosted_deployment_path=tmp_path / "protected.json")
    with TestClient(
        restored_app, base_url=deployment.public_origin, client=("127.0.0.1", 124)
    ) as other:
        other.headers.update(client.headers)
        other.cookies.set("__Host-epm_session", old_cookie)
        assert other.get("/api/operator/bootstrap").status_code == 401
        assert other.post("/api/hosted/session").status_code == 403
        assert store.enrollments()[0]["subject"] == "verified-subject"
