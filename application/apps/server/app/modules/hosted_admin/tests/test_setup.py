"""Draft admission, durable effects, retries and credential-free portable control state."""

import json
from contextlib import contextmanager
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi.testclient import TestClient
import pytest

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest
from app.modules.hosted_admin.application.operations import Observation, Reservation, fingerprint
from app.modules.hosted_admin.application.setup import SetupCommand, SetupData
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.setup import SetupService, SetupWorker, invitation
from app.modules.hosted_admin.tests.test_authority import authority as authority, login


class Host:
    """An isolated resource adapter; no real host or provider calls."""

    def __init__(self):
        self.calls, self.effects = [], {}
        self.blocker = None
        self.provider_ready = False
        self.approved = False

    def options(self):
        return {"releases": ["release-20261029-01"]}

    def plan(self, identifier, data):
        key = "d-" + identifier[:8]
        ids = {
            label + "_id": str(uuid5(NAMESPACE_URL, identifier + ":" + label))
            for label in ("instance", "allocation", "operator", "workspace")
        }
        port = 8000 + int(identifier[:8], 16) % 1000
        values = {
            "email": data.email,
            "hostname": key + ".example.test",
            "port": str(port),
            "user": "epm-" + key,
            "workspace": ids["workspace_id"],
            "mount": "/synthetic/" + key + "/volume",
            "image": "/synthetic/" + key + ".ext4",
            "disk": key,
            "memory": key,
        }
        return {
            "key": key,
            **ids,
            "hostname": values["hostname"],
            "port": port,
            "profile": "synthetic-test",
            "config_hash": "a" * 64,
            "reservations": [
                Reservation(
                    kind=kind, identity=value, amount=1 if kind in {"disk", "memory"} else 0
                ).model_dump()
                for kind, value in sorted(values.items())
            ],
        }

    @contextmanager
    def admission(self, identifier, data):
        yield {"plan": self.plan(identifier, data)}

    def check(self, connection, plan, _prepared):
        if self.blocker:
            raise AdminError(self.blocker, 409)
        email = next(item["identity"] for item in plan["reservations"] if item["kind"] == "email")
        if connection.execute(
            "SELECT 1 FROM reservation WHERE kind='email' AND lower(identity)=lower(?)", (email,)
        ).fetchone():
            raise AdminError("admin_operator_email_exists", 409)

    def inspect(self, payload, step):
        if step == "provider_setup" and not self.provider_ready:
            return Observation("waiting")
        return self.effects.get((payload["operation_id"], step), Observation("absent"))

    def apply(self, payload, step):
        self.calls.append((payload["operation_id"], step))
        self.effects[payload["operation_id"], step] = Observation(
            "verified", {"verified": True}, payload["target"]
        )

    def contain(self, payload):
        self.calls.append((payload["operation_id"], "contain"))
        return True

    def enrollment(self, _instance):
        return {"approved": self.approved, "status": {"active": False}}


@pytest.fixture
def setup(authority):
    store, clock = authority
    host = Host()
    service = SetupService(store, host)
    credentials = login(store)
    return service, host, credentials, clock


def send(fixture, action="save", **changes):
    service, _, credentials, _ = fixture
    if action == "create" and "review_hash" not in changes:
        actor = identity(service)
        with service.store.transaction() as connection:
            row = service.get(connection, changes["draft_id"], actor)
            data = SetupData.model_validate_json(row["data"])
            plan = json.loads(row["plan"]) if row["plan"] else service.host.plan(row["id"], data)
        changes["review_hash"] = fingerprint({"data": data.model_dump(), "plan": plan})
    command = SetupCommand.model_validate(
        {
            "action": action,
            "draft_id": str(uuid4()),
            "expected_revision": 0,
            "data": SetupData(
                name="Operator C",
                email="c@example.test",
                support="support@example.test",
                release="release-20261029-01",
                starts=1000.0,
                expires=86400.0,
            ).model_dump()
            if action == "save"
            else None,
        }
        | changes
    )
    return service.store.handle(
        BrokerRequest(method="setup_command", setup=command, **credentials), None, setup=service
    )


def start(fixture):
    draft = send(fixture)
    return send(
        fixture,
        "create",
        draft_id=draft["id"],
        expected_revision=draft["revision"],
        operation_id=str(uuid4()),
        confirmed=True,
    )


def identity(service):
    with service.store.transaction() as connection:
        return dict(service.store._identity(connection))


def test_acknowledged_draft_survives_new_session_without_resource_effects(setup):
    service, host, _, _ = setup
    saved = send(setup)
    assert saved["revision"] == 1 and not host.calls
    request = BrokerRequest(method="setup_get", draft_id=saved["id"], **login(service.store))
    assert service.store.handle(request, None, setup=service) == saved
    assert "plan" not in saved and "reservations" not in saved
    assert send(setup, draft_id=saved["id"], expected_revision=0) == saved
    with pytest.raises(AdminError, match="revision_conflict"):
        send(
            setup,
            draft_id=saved["id"],
            expected_revision=0,
            data=SetupData(name="Changed").model_dump(),
        )


def test_create_retry_returns_original_allocation_and_changed_key_conflicts(setup):
    service, host, _, _ = setup
    created = start(setup)
    assert created["state"] == "started" and not host.calls
    assert (
        send(
            setup,
            "create",
            draft_id=created["id"],
            expected_revision=1,
            operation_id=created["operation_id"],
            confirmed=True,
        )
        == created
    )
    with pytest.raises(AdminError, match="command_conflict"):
        send(
            setup,
            "create",
            draft_id=created["id"],
            expected_revision=1,
            operation_id=str(uuid4()),
            confirmed=True,
        )
    with service.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 9


@pytest.mark.parametrize(
    "blocker",
    [
        "admin_capacity_unqualified",
        "admin_provider_seats_unavailable",
        "admin_private_maintenance_pending",
    ],
)
def test_blockers_keep_acknowledged_draft_without_partial_reservations(setup, blocker):
    service, host, _, _ = setup
    saved = send(setup)
    host.blocker = blocker
    with pytest.raises(AdminError, match=blocker):
        send(
            setup,
            "create",
            draft_id=saved["id"],
            expected_revision=1,
            operation_id=str(uuid4()),
            confirmed=True,
        )
    with service.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 0
        assert connection.execute("SELECT state FROM setup_draft").fetchone()[0] == "draft"


def test_transaction_failure_rolls_back_draft_operation_and_reservations_together(setup):
    service, _, _, _ = setup
    draft = send(setup)
    with service.store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_setup BEFORE UPDATE ON setup_draft BEGIN SELECT RAISE(ABORT,'failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        send(
            setup,
            "create",
            draft_id=draft["id"],
            expected_revision=1,
            operation_id=str(uuid4()),
            confirmed=True,
        )
    with service.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 0


def test_manual_handoff_waits_and_resume_needs_exact_fresh_grant(setup):
    service, host, _, _ = setup
    created = start(setup)
    worker = SetupWorker(service)
    for _ in range(4):
        worker.tick()
    operation = service.engine.get(created["operation_id"])
    assert operation["state"] == "waiting"
    assert [step for _, step in host.calls] == ["allocate", "workspace"]
    with pytest.raises(AdminError, match="grant_invalid"):
        service.engine.resume(operation["id"], operation["revision"], identity(service))
    with service.store.transaction() as connection:
        retained = service.engine._get(connection, operation["id"])
    grant = service.store.issue(service.engine.resume_hash(retained))
    host.provider_ready = True
    service.engine.resume(operation["id"], operation["revision"], identity(service), grant)
    worker.tick()
    worker.tick()
    status = service.status(created["id"], identity(service))
    assert status["operation"]["state"] == "succeeded"
    assert status["lifecycle"] == "waiting_for_sign_in" and status["ready_instructions"] is None
    assert "pending-approval" in status["invitation"] and "UTC+0000" in status["invitation"]
    host.approved = True
    assert (
        service.status(created["id"], identity(service))["lifecycle"]
        == "identity_approved_recovery_pending"
    )
    assert len(host.calls) == 4


def test_safe_stop_retains_resources_and_started_draft_cannot_be_discarded(setup):
    service, host, _, _ = setup
    created = start(setup)
    service.engine.cancel(created["operation_id"], 1, identity(service))
    SetupWorker(service).tick()
    assert service.engine.get(created["operation_id"])["state"] == "cancelled"
    assert host.calls[-1][1] == "contain"
    with pytest.raises(AdminError, match="revision_conflict"):
        send(setup, "discard", draft_id=created["id"], expected_revision=2)
    with service.store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 9


def test_control_recovery_preserves_setup_but_never_resumes_or_restores_authority(setup, tmp_path):
    from app.modules.hosted_admin.infrastructure.control_recovery import (
        snapshot_control,
        restore_control,
    )

    service, _, credentials, _ = setup
    created = start(setup)
    encoded = snapshot_control(service.store)
    assert credentials["token"].encode() not in encoded
    restored = AuthorityStore.initialize(
        tmp_path / "restore/authority.sqlite", identity(service)["id"]
    )
    restore_control(restored, encoded)
    AuthorityStore(restored.path)
    with restored.transaction() as connection:
        assert connection.execute("SELECT state FROM operation").fetchone()[0] == "paused"
        assert connection.execute("SELECT id FROM setup_draft").fetchone()[0] == created["id"]
    with pytest.raises(AdminError, match="revoked"):
        restored.issue()


def test_http_setup_closed_transport_authority_validation_and_safe_projection(setup):
    service, _, _, _ = setup
    browser = TestClient(
        create_admin_app(
            "http://epm-admin.localhost:8765",
            lambda value: service.store.handle(
                BrokerRequest.model_validate(value), None, setup=service
            ),
        ),
        base_url="http://epm-admin.localhost:8765",
    )
    assert browser.get("/admin-api/setup-drafts").status_code == 401
    origin = {"Origin": "http://epm-admin.localhost:8765"}
    result = browser.post("/login", headers=origin, json={"credential": service.store.issue()})
    headers = origin | {"X-Epm-Admin-Csrf": result.json()["csrf"]}
    cmd = {
        "action": "save",
        "draft_id": str(uuid4()),
        "expected_revision": 0,
        "data": {"name": "Saved operator"},
    }
    assert browser.post("/setup-command", headers=origin, json={"setup": cmd}).status_code == 403
    assert (
        browser.post(
            "/setup-command", headers=headers, json={"setup": cmd | {"shell": "touch /tmp/bad"}}
        ).status_code
        == 422
    )
    response = browser.post("/setup-command", headers=headers, json={"setup": cmd})
    assert response.status_code == 200
    assert "paths" not in response.text
    assert browser.get(f"/setups/{cmd['draft_id']}").status_code == 200


def test_invitation_names_zone_offsets_start_pending_and_final_return_steps():
    data = SetupData(
        name="Test",
        email="test@example.test",
        support="help@example.test",
        starts=1793437200.0,
        expires=1793696400.0,
        timezone="America/New_York",
    ).model_dump()
    text = invitation(data, "demo.example.test")
    assert "America/New_York" in text and "UTC-0400" in text and "UTC-0500" in text
    assert "return at the start time" in text and "setup is complete" in text


def test_retained_setup_tampering_and_unknown_fields_are_rejected(setup):
    service, _, _, _ = setup
    send(setup)
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE setup_draft SET data=?", (json.dumps({"private_payload": "undeclared"}),)
        )
    with pytest.raises(ValueError):
        AuthorityStore(service.store.path)


def test_admission_observes_outside_transaction_and_rechecks_revision(setup):
    service, host, _, _ = setup
    saved = send(setup)

    @contextmanager
    def admission(identifier, data):
        # A concurrent editor can commit while host observations are collected.
        # This would lock/time out if the admission held a control transaction.
        with service.store.transaction() as connection:
            connection.execute(
                "UPDATE setup_draft SET revision=revision+1 WHERE id=?", (identifier,)
            )
        yield {"plan": host.plan(identifier, data)}

    host.admission = admission
    with pytest.raises(AdminError, match="revision_conflict"):
        send(
            setup,
            "create",
            draft_id=saved["id"],
            expected_revision=1,
            operation_id=str(uuid4()),
            confirmed=True,
        )
    assert not host.calls


def test_changed_reviewed_assignment_cannot_be_admitted_under_same_intent(setup):
    saved = send(setup)
    with pytest.raises(AdminError, match="revision_conflict"):
        send(
            setup,
            "create",
            draft_id=saved["id"],
            expected_revision=1,
            operation_id=str(uuid4()),
            confirmed=True,
            review_hash="0" * 64,
        )
