"""A ceiling of two cannot be raised by a declaration, failed test or stale evidence."""

import hashlib
import hmac
import json
import socket
import sqlite3
import threading
from uuid import uuid4

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical, OperationIntent, Reservation
from app.modules.hosted_admin.application.qualification import (
    CapacitySnapshot,
    QualificationPlan,
    QualificationCommand,
    QualificationEvidence,
    REQUIRED_EVIDENCE,
)
from app.modules.hosted_admin.infrastructure.broker import Broker, send, receive
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.infrastructure.qualification import QualificationService
from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations
from app.modules.hosted_admin.infrastructure.verified_reports import VerifiedReports
from app.modules.hosted_admin.tests.test_authority import authority as authority
from app.modules.hosted_admin.tests.test_operations import identity


@pytest.fixture
def qualification(authority):
    store, clock = authority
    snapshot = CapacitySnapshot(
        environment_hash="a" * 64,
        release="release-20261028-01",
        profile="qualified-profile",
        observed=clock[0],
        memory_total=10000,
        memory_committed=1000,
        disk_total=100000,
        disk_free=80000,
        disk_committed=1000,
        recovery_staging=10000,
        active_count=2,
        inventory_clear=True,
        baseline_restored=True,
        test_resources_retired=True,
    )
    reports = {}
    service = QualificationService(store, lambda: snapshot, reports.__getitem__)
    service.initialize_capacity(2, snapshot)
    plan = QualificationPlan(
        id=str(uuid4()),
        release=snapshot.release,
        profile=snapshot.profile,
        environment_hash=snapshot.environment_hash,
        target=3,
        browsers=6,
        identities=[
            {"email": f"tester{i}@example.test", "hostname": f"test{i}.example.test"}
            for i in range(3)
        ],
        starts=clock[0],
        expires=clock[0] + 1000.0,
        evidence_directory_id=str(uuid4()),
        maintenance_reference="maintenance-1",
        rollback_reference="rollback-1",
        workload_digest="b" * 64,
        memory_bytes=5000,
        disk_bytes=20000,
    )
    return service, store, clock, snapshot, reports, plan


def action(service, store, plan, name, **changes):
    with store.transaction() as connection:
        capacity = connection.execute("SELECT revision FROM capacity").fetchone()[0]
    return QualificationCommand(
        operation_id=str(uuid4()),
        qualification_id=plan.id,
        action=name,
        expected_revision=service.status(plan.id)["revision"],
        expected_capacity_revision=capacity,
        reason="Controlled private qualification",
        confirmed=True,
    ).model_copy(update=changes)


def evidence(service, store, reports, plan, kinds=REQUIRED_EVIDENCE, **changes):
    for kind in kinds:
        value = QualificationEvidence(
            id=str(uuid4()),
            qualification_id=plan.id,
            kind=kind,
            artifact_digest="d" * 64,
            environment_hash=plan.environment_hash,
            observed=store.clock(),
            expires=plan.expires,
            passed=True,
        ).model_copy(update=changes)
        reports[value.id] = value
        service.register(value.id, identity(store))


def allocation(plan, index=0):
    target = f"test-{index}"
    return [
        Reservation(kind=kind, identity=value, amount=amount)
        for kind, value, amount in (
            ("email", plan.identities[index].email, 0),
            ("hostname", plan.identities[index].hostname, 0),
            ("port", str(8100 + index), 0),
            ("user", target, 0),
            ("workspace", str(uuid4()), 0),
            ("image", f"/test/{target}.img", 0),
            ("mount", f"/test/{target}", 0),
            ("memory", target, 1000),
            ("disk", target, 5000),
        )
    ]


def test_registered_provision_reservations_are_not_counted_twice(qualification):
    service, store, _, snapshot, _, plan = qualification
    first = OperationIntent(
        operation_id=str(uuid4()),
        kind="provision",
        target="test-0",
        expected_revision=0,
        reason="Retained provision",
    )
    OperationEngine(store).reserve(
        first, allocation(plan, 0), identity(store), admit_check=lambda *_: None
    )
    current = snapshot.model_copy(
        update={"retained_hostnames": [plan.identities[0].hostname], "memory_committed": 6500}
    )
    second = first.model_copy(update={"operation_id": str(uuid4()), "target": "test-1"})
    with store.transaction() as connection:
        connection.execute("UPDATE capacity SET ceiling=3")
        service.admission_check(connection, second, allocation(plan, 1), snapshot=current)
        with pytest.raises(AdminError, match="capacity_unqualified"):
            service.admission_check(
                connection,
                second,
                allocation(plan, 1),
                snapshot=current.model_copy(update={"retained_hostnames": []}),
            )


def test_three_test_plan_can_run_without_raising_ordinary_ceiling(qualification):
    service, store, _, _, _, plan = qualification
    created = service.create(plan, identity(store))
    assert service.create(plan, identity(store)) == created
    command = action(service, store, plan, "start")
    assert service.command(command, identity(store))["ceiling"] == 2
    engine = OperationEngine(store)
    ordinary = OperationIntent(
        operation_id=str(uuid4()),
        target="ordinary-c",
        kind="provision",
        expected_revision=0,
        reason="Not yet qualified",
    )
    with pytest.raises(AdminError, match="unqualified"):
        engine.reserve(
            ordinary, allocation(plan), identity(store), admit_check=service.admission_check
        )
    test = ordinary.model_copy(
        update={
            "operation_id": str(uuid4()),
            "kind": "qualification_test",
            "qualification_id": plan.id,
            "target": "test-c",
        }
    )
    reservations = allocation(plan)
    assert (
        engine.reserve(test, reservations, identity(store), admit_check=service.admission_check)[
            "state"
        ]
        == "queued"
    )
    with pytest.raises(AdminError, match="identity_conflict"):
        engine.reserve(
            test.model_copy(update={"operation_id": str(uuid4()), "target": "wrong"}),
            [
                item.model_copy(update={"identity": "unknown@example.test"})
                if item.kind == "email"
                else item
                for item in allocation(plan)
            ],
            identity(store),
            admit_check=service.admission_check,
        )


def test_promotion_requires_all_immutable_evidence_restoration_and_one_use_authorization(
    qualification,
):
    service, store, _, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    evidence(service, store, reports, plan)
    service.command(action(service, store, plan, "retire"), identity(store))
    promote = action(service, store, plan, "promote")
    with pytest.raises(AdminError, match="grant_invalid"):
        service.command(promote, identity(store))
    credential = store.issue(promote.fingerprint())
    result = service.command(promote, identity(store), credential)
    assert result["ceiling"] == 3 and result["state"] == "promoted"
    # A lost response returns the original receipt without another grant.
    assert service.command(promote, identity(store)) == result
    with pytest.raises(AdminError, match="conflict"):
        service.command(promote.model_copy(update={"reason": "Different intent"}), identity(store))
    with store.transaction() as connection:
        assert connection.execute("SELECT ceiling,revision FROM capacity").fetchone()[:] == (3, 2)
        for sql in (
            "DELETE FROM qualification_evidence",
            "UPDATE qualification_receipt SET result='{}'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"memory_committed": 3000}, "memory_reservation"),
        ({"disk_free": 30000}, "disk_reservation"),
        ({"inventory_clear": False}, "observation_unavailable"),
        ({"observed": 0.0}, "observation_unavailable"),
        ({"environment_hash": "c" * 64}, "environment_changed"),
        ({"retained_emails": ["tester0@example.test"]}, "identity_conflict"),
    ],
)
def test_capacity_and_identity_blockers_never_create_plan(qualification, change, code):
    service, store, _, snapshot, _, plan = qualification
    service.snapshot = lambda: snapshot.model_copy(update=change)
    with pytest.raises(AdminError, match=code):
        service.create(plan, identity(store))
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM qualification").fetchone()[0] == 0
        assert connection.execute("SELECT ceiling FROM capacity").fetchone()[0] == 2


@pytest.mark.parametrize("failed", [True, False])
def test_failed_or_expired_evidence_cannot_retire_or_promote(qualification, failed):
    service, store, clock, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    evidence(service, store, reports, plan, passed=not failed)
    if not failed:
        clock[0] = plan.expires
    with pytest.raises(AdminError, match="observation_unavailable|evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))


def test_abort_retains_reservations_and_generation_revocation_requires_new_grant(qualification):
    service, store, _, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    store.revoke_identity()
    store.restore_identity()
    resume = action(service, store, plan, "resume")
    with pytest.raises(AdminError, match="grant_invalid"):
        service.command(resume, identity(store))
    service.command(resume, identity(store), store.issue(resume.fingerprint()))
    service.command(action(service, store, plan, "abort"), identity(store))
    assert service.status(plan.id)["state"] == "aborted"
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    evidence(service, store, reports, plan, {"retirement", "restoration"})
    assert (
        service.command(action(service, store, plan, "retire"), identity(store))["state"]
        == "retired"
    )


def test_promotion_failure_rolls_back_authorization_capacity_receipt_and_audit(qualification):
    service, store, _, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    evidence(service, store, reports, plan)
    service.command(action(service, store, plan, "retire"), identity(store))
    promote = action(service, store, plan, "promote")
    credential = store.issue(promote.fingerprint())
    with store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_promotion BEFORE INSERT ON audit WHEN NEW.action='qualification_promoted' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        service.command(promote, identity(store), credential)
    with store.transaction() as connection:
        assert connection.execute("SELECT ceiling FROM capacity").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT used FROM grant WHERE request_hash=?", (promote.fingerprint(),)
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER fail_promotion")
    assert service.command(promote, identity(store), credential)["ceiling"] == 3


def test_private_qualification_rpc_is_denied_to_http_and_operator_peers(qualification):
    service, store, _, _, _, plan = qualification
    operations = PrivateOperations(store, service, None)
    for peer in (12345, 23456, 0):
        left, right = socket.socketpair()
        broker = Broker(store, 12345, None, peer=lambda _: peer, operations=operations)
        thread = threading.Thread(target=broker.handle, args=(left,))
        thread.start()
        try:
            send(
                right,
                {
                    "method": "private_operations",
                    "request": {"action": "qualification-create", "plan": plan.model_dump()},
                },
            )
            response = receive(right)
            assert ("result" in response) == (peer == 0)
        finally:
            thread.join(timeout=5)
            left.close()
            right.close()


def test_protected_evidence_requires_signature_pinned_verifier_and_exact_artifact(tmp_path):
    directory = tmp_path / "reports"
    directory.mkdir(mode=0o700)
    key = b"k" * 32
    inventory_digest = "b" * 64
    report = QualificationEvidence(
        id=str(uuid4()),
        qualification_id=str(uuid4()),
        kind="load",
        artifact_digest=hashlib.sha256(b"verified measurements").hexdigest(),
        environment_hash="a" * 64,
        observed=1000.0,
        expires=2000.0,
        passed=True,
    )
    unsigned = {
        "payload": report.model_dump(),
        "verifier_digest": "c" * 64,
        "inventory_digest": inventory_digest,
    }
    envelope = unsigned | {
        "signature": hmac.digest(key, canonical(unsigned).encode(), "sha256").hex()
    }
    files = {
        "verifier.key": key,
        "verifier.json": json.dumps({"verifier_digest": "c" * 64}).encode(),
        f"{report.id}.json": json.dumps(envelope).encode(),
        f"{report.id}.evidence": b"verified measurements",
    }
    for name, content in files.items():
        path = directory / name
        path.write_bytes(content)
        path.chmod(0o600)
    reader = VerifiedReports(directory, lambda: inventory_digest)
    assert reader.evidence(report.id) == report
    (directory / f"{report.id}.evidence").write_bytes(b"changed")
    with pytest.raises(AdminError, match="artifact_changed"):
        reader.evidence(report.id)
    envelope["payload"]["passed"] = False
    (directory / f"{report.id}.json").write_text(json.dumps(envelope))
    with pytest.raises(AdminError, match="signature_invalid"):
        reader.evidence(report.id)
    with pytest.raises(AdminError, match="identity_invalid"):
        reader.evidence("../outside")


def test_promotion_revalidates_registered_artifacts_and_current_physical_capacity(qualification):
    service, store, _, snapshot, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    evidence(service, store, reports, plan)
    service.command(action(service, store, plan, "retire"), identity(store))
    promote = action(service, store, plan, "promote")
    credential = store.issue(promote.fingerprint())
    service.snapshot = lambda: snapshot.model_copy(update={"memory_committed": 9000})
    with pytest.raises(AdminError, match="physical_capacity_blocked"):
        service.command(promote, identity(store), credential)
    service.snapshot = lambda: snapshot
    identifier = next(iter(reports))
    reports[identifier] = reports[identifier].model_copy(update={"artifact_digest": "f" * 64})
    with pytest.raises(AdminError, match="evidence_changed"):
        service.command(promote, identity(store), credential)


def test_start_cannot_be_reused_to_bypass_resume_authorization(qualification):
    service, store, _, _, _, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    with pytest.raises(AdminError, match="transition_invalid"):
        service.command(action(service, store, plan, "start"), identity(store))
    resume = action(service, store, plan, "resume")
    with pytest.raises(AdminError, match="grant_invalid"):
        service.command(resume, identity(store))
    assert (
        service.command(resume, identity(store), store.issue(resume.fingerprint()))["state"]
        == "running"
    )


@pytest.mark.parametrize("abort", [True, False])
def test_expired_plan_can_retire_with_fresh_cleanup_but_cannot_promote(qualification, abort):
    service, store, clock, snapshot, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    evidence(service, store, reports, plan)
    original_reports = dict(reports)
    clock[0] = plan.expires + 1
    service.snapshot = lambda: snapshot.model_copy(update={"observed": clock[0]})
    with pytest.raises(AdminError, match="window_invalid"):
        service.command(action(service, store, plan, "resume"), identity(store))
    intent = OperationIntent(
        operation_id=str(uuid4()),
        target="expired-test",
        kind="qualification_test",
        qualification_id=plan.id,
        expected_revision=0,
        reason="Expired test must stay blocked",
    )
    with pytest.raises(AdminError, match="not_running"):
        OperationEngine(store).reserve(
            intent, allocation(plan), identity(store), admit_check=service.admission_check
        )
    if abort:
        service.command(action(service, store, plan, "abort"), identity(store))
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    evidence(service, store, reports, plan, {"retirement"}, expires=clock[0] + 300)
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    evidence(service, store, reports, plan, {"restoration"}, expires=clock[0] + 300, passed=False)
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    clock[0] += 1
    evidence(service, store, reports, plan, {"restoration"}, expires=clock[0] + 300)
    retire = action(service, store, plan, "retire")
    result = service.command(retire, identity(store))
    assert result["state"] == "retired" and result["ceiling"] == 2
    assert service.command(retire, identity(store)) == result
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "promote"), identity(store))
    assert all(reports[key] == value for key, value in original_reports.items())
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM qualification_evidence").fetchone()[0] == (
            len(REQUIRED_EVIDENCE) + 3
        )
        assert connection.execute("SELECT ceiling,revision FROM capacity").fetchone()[:] == (2, 1)


@pytest.mark.parametrize("kind", sorted(REQUIRED_EVIDENCE - {"retirement", "restoration"}))
def test_expired_plan_cannot_register_new_test_evidence(qualification, kind):
    service, store, clock, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    clock[0] = plan.expires + 1
    with pytest.raises(AdminError, match="evidence_stale"):
        evidence(service, store, reports, plan, {kind}, expires=clock[0] + 300)


def test_latest_cleanup_failure_blocks_older_pass_and_reports_remain_immutable(qualification):
    service, store, clock, _, reports, plan = qualification
    service.create(plan, identity(store))
    service.command(action(service, store, plan, "start"), identity(store))
    evidence(service, store, reports, plan, {"retirement", "restoration"})
    clock[0] += 1
    evidence(service, store, reports, plan, {"retirement"}, passed=False)
    with pytest.raises(AdminError, match="evidence_incomplete"):
        service.command(action(service, store, plan, "retire"), identity(store))
    latest = next(reversed(reports.values()))
    assert service.register(latest.id, identity(store))["registered"]
    reports[latest.id] = latest.model_copy(update={"passed": True})
    with pytest.raises(AdminError, match="evidence_conflict"):
        service.register(latest.id, identity(store))
    with store.transaction() as connection:
        for sql in (
            "DELETE FROM qualification_evidence",
            "UPDATE qualification_evidence SET passed=1",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)
