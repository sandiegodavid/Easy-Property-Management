"""Explicit reconciliation/retirement receipts and serialized quota effects."""

import json
import fcntl
import os
from contextlib import contextmanager
from app.modules.hosted_admin.infrastructure.storage_queries import PENDING_STORAGE

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.storage import (
    StorageProof,
    RegisteredQuotaPort,
    canonical_storage,
    verify_storage_proof,
)


@contextmanager
def storage_worker(store):
    # One host storage worker; generations are checked again after slow effects.
    path = store.path.parent / "storage-worker.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AdminError("admin_storage_busy", 409) from error
        yield
    finally:
        os.close(fd)


class StorageLifecycle:
    def __init__(self, allocations, effects: RegisteredQuotaPort):
        self.allocations, self.store, self.effects = allocations, allocations.store, effects

    def command(self, command, identity, credential):
        with storage_worker(self.store):
            with self.store.transaction() as connection:
                self.allocations.authority(connection, identity)
                prior = self.receipt(connection, command, identity)
                if prior is not None:
                    return prior
                row = self.get(connection, command.operation_id)
                self.allowed(command, row, connection)
                attempt = connection.execute(
                    "SELECT * FROM storage_attempt WHERE id=?", (command.id,)
                ).fetchone()
                if attempt:
                    if attempt["request"] != canonical_storage(command.model_dump()) or (
                        attempt["identity"],
                        attempt["generation"],
                    ) != (identity["id"], identity["generation"]):
                        raise AdminError("admin_authority_fenced", 409)
                else:
                    if connection.execute(
                        "SELECT 1 FROM (" + PENDING_STORAGE + ") WHERE operation_id=? LIMIT 1",
                        (command.operation_id,),
                    ).fetchone() and command.action not in {"reconcile", "finish_retirement"}:
                        raise AdminError("admin_storage_reconciliation_required", 409)
                    if (
                        connection.execute("SELECT count(*) FROM storage_attempt").fetchone()[0]
                        >= 10000
                    ):
                        raise AdminError("admin_storage_action_capacity", 409)
                    self.store._consume(connection, credential, "action", command.fingerprint())
                    # Durable action admission survives an uncertain effect/reply;
                    # retries use the same command and original expected revision.
                    connection.execute(
                        "INSERT INTO storage_attempt VALUES (?,?,?,?,?,?)",
                        (
                            command.id,
                            command.operation_id,
                            canonical_storage(command.model_dump()),
                            identity["id"],
                            identity["generation"],
                            self.store.clock(),
                        ),
                    )
                    self.store._audit(connection, "storage_action_admitted", command.id)
            return self.finish(command, identity)

    def finish(self, command, identity):
        with self.store.transaction() as connection:
            self.allocations.authority(connection, identity)
            row = self.get(connection, command.operation_id)
            request = json.loads(row["request"])
        # The owning adapter revalidates the exact source/inventory binding and
        # profile before each mutation. It never changes allowance or access.
        if command.action == "retire":
            proof = None
        else:
            proof = StorageProof.model_validate(self.effects(command, request))
        with self.store.transaction() as connection:
            self.allocations.authority(connection, identity)
            current = self.get(connection, command.operation_id)
            self.allowed(command, current, connection)
            now = self.store.clock()
            if proof is not None:
                self.check_proof(command, current, proof)
            state = {
                "apply": "active",
                "reconcile": "active",
                "retire": "retiring",
                "finish_retirement": "retired",
            }[command.action]
            connection.execute(
                "UPDATE storage_allocation SET state=?,revision=revision+1,updated=? WHERE operation_id=?",
                (state, now, command.operation_id),
            )
            if proof is not None:
                for usage in proof.projects:
                    connection.execute(
                        "UPDATE storage_project SET allocated_bytes=?,allocated_inodes=?,observed=?,enforcement=? WHERE operation_id=? AND project_id=?",
                        (
                            usage.allocated_bytes,
                            usage.allocated_inodes,
                            proof.observed,
                            int(usage.enforcement),
                            command.operation_id,
                            usage.project_id,
                        ),
                    )
            result = self.allocations.view(self.get(connection, command.operation_id))
            encoded = canonical_storage(command.model_dump())
            evidence = canonical_storage(proof.model_dump() if proof else {})
            connection.execute(
                "INSERT INTO storage_command VALUES (?,?,?,?,?,?,?,?)",
                (
                    command.id,
                    command.operation_id,
                    encoded,
                    canonical_storage(result),
                    identity["id"],
                    identity["generation"],
                    evidence,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO storage_event VALUES (?,?,?,?,?,?,?)",
                (
                    command.operation_id,
                    result["revision"],
                    command.action,
                    encoded,
                    identity["id"],
                    identity["generation"],
                    now,
                ),
            )
            self.store._audit(connection, "storage_" + command.action, command.id)
            return result

    def allowed(self, command, row, connection):
        if row["revision"] != command.expected_revision:
            raise AdminError("admin_storage_revision_conflict", 409)
        valid = {
            "apply": {"reserved"},
            "reconcile": {"reserved", "active"},
            "retire": {"reserved", "active"},
            "finish_retirement": {"retiring"},
        }
        if row["state"] not in valid[command.action]:
            raise AdminError("admin_storage_lifecycle_conflict", 409)
        if connection.execute(
            "SELECT 1 FROM operation WHERE target=? AND kind IN ('upgrade','upgrade_rollback') AND state NOT IN ('succeeded','cancelled')",
            (row["instance"],),
        ).fetchone():
            raise AdminError("admin_storage_upgrade_conflict", 409)

    def check_proof(self, command, row, proof):
        try:
            verify_storage_proof(
                command, json.loads(row["request"])["policy"], proof, self.store.clock()
            )
        except ValueError as error:
            raise AdminError("admin_storage_proof_invalid", 409) from error

    @staticmethod
    def get(connection, operation):
        row = connection.execute(
            "SELECT * FROM storage_allocation WHERE operation_id=?", (operation,)
        ).fetchone()
        if row is None:
            raise AdminError("admin_storage_not_found", 404)
        return dict(row)

    @staticmethod
    def receipt(connection, command, identity):
        prior = connection.execute(
            "SELECT * FROM storage_command WHERE id=?", (command.id,)
        ).fetchone()
        if prior:
            if prior["request"] != canonical_storage(command.model_dump()) or (
                prior["identity"],
                prior["generation"],
            ) != (identity["id"], identity["generation"]):
                raise AdminError("admin_storage_intent_conflict", 409)
            return json.loads(prior["result"])
        return None
