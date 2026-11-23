"""Fenced source access commands and immutable, scoped original outcomes."""

from dataclasses import dataclass
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import text

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.source_contracts import (
    SourceResult,
    SourceRevocation,
    require_invocation,
)
from app.modules.hosted_access.infrastructure.source_sessions import (
    check_csrf,
    session_hash,
    session_row,
)
from app.platform.hosted_contracts.operations import (
    OperationOutcome,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.values import CanonicalId

RECEIPT_KINDS = {
    "initialize_disabled": "initialize_binding",
    "apply_policy": "apply_policy",
    "claim": "claim",
    "enable": "enable",
    "disable": "disable",
    "rebind": "rebind",
    "revoke": "revoke_sessions",
    "maintenance_fence": "maintenance_fence",
    "drain": "drain",
    "verify_restore_binding": "restore_binding",
}
FREE_V1_USABLE_BYTES = 50_000_000


@dataclass(frozen=True)
class LifecycleProof:
    binding: IdentityBinding
    request_hash: str
    expires_at: int
    email_key: str


def source_meta(connection):
    row = (
        connection.execute(text("SELECT * FROM main.access_meta WHERE id=1"))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProviderDenied()
    return row


class SourceLifecycle:
    def __init__(self, engine, *, mutation, binding, clock, proof_owner=None):
        self.engine, self.mutation = engine, mutation
        self.binding, self.clock, self.proof_owner = binding, clock, proof_owner

    @staticmethod
    def _scope(meta, actor, ref):
        if (
            actor.service not in {"admin", "source", "operator_recovery"}
            or actor.deployment_id != ref.deployment_id
            or actor.scope != ref.scope
            or ref.scope.kind != "workspace"
            or (meta["deployment_id"], meta["operator_id"], meta["workspace_id"])
            != (ref.deployment_id, ref.scope.operator_id, ref.scope.workspace_id)
            or ref.kind not in RECEIPT_KINDS
            or (actor.service == "operator_recovery" and ref.kind != "verify_restore_binding")
            or (
                actor.service == "source"
                and ref.kind not in {"revoke", "maintenance_fence", "drain"}
            )
            or (actor.service == "admin" and ref.kind == "verify_restore_binding")
        ):
            raise ProviderDenied()

    @staticmethod
    def _retained(connection, reference):
        kind = RECEIPT_KINDS[reference.kind]
        rows = (
            connection.execute(
                text("""
            SELECT * FROM main.access_receipts
            WHERE operation_id=:id OR (kind=:kind AND idempotency_key=:key)
        """),
                {"id": reference.operation_id, "kind": kind, "key": reference.idempotency_key},
            )
            .mappings()
            .all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise SemanticConflict()
        row = rows[0]
        if (row["kind"], row["idempotency_key"], row["request_hash"]) != (
            kind,
            reference.idempotency_key,
            reference.request_hash,
        ):
            raise SemanticConflict()
        return OperationOutcome[SourceResult](
            operation=reference.model_copy(update={"operation_id": row["operation_id"]}),
            state=OperationState.SUCCEEDED,
            revision=row["source_revision"],
            observed_at=row["recorded_at"],
            result=SourceResult.model_validate_json(row["result_json"]),
        )

    def original(self, actor, reference):
        with self.engine.connect() as connection:
            if reference.kind == "initialize_disabled":
                if (
                    actor.service != "admin"
                    or actor.deployment_id != reference.deployment_id
                    or actor.scope != reference.scope
                    or reference.scope.kind != "workspace"
                ):
                    raise ProviderDenied()
                meta = (
                    connection.execute(text("SELECT * FROM main.access_meta WHERE id=1"))
                    .mappings()
                    .one_or_none()
                )
                if meta is None:
                    return None
                self._scope(meta, actor, reference)
                return self._retained(connection, reference)
            self._scope(source_meta(connection), actor, reference)
            return self._retained(connection, reference)

    def execute(
        self,
        actor,
        command,
        *,
        cookie=None,
        csrf=None,
        other_device=False,
        email_key=None,
    ):
        require_invocation(actor, command)
        ref = command.reference()
        intent = command.intent
        previous = (
            self.original(actor, ref)
            if (
                actor.service in {"admin", "operator_recovery"}
                or intent.kind in {"maintenance_fence", "drain"}
            )
            else None
        )
        if previous is not None:
            return previous
        binding = self.binding()
        if intent.kind == "initialize_disabled":
            return self._initialize_disabled(actor, command, binding, email_key=email_key)
        proof = None
        if intent.kind in {"claim", "enable", "rebind"}:
            # The protected owner independently verifies identity, readiness,
            # off-host evidence and the exact command before entering SQLite.
            if self.proof_owner is None:
                raise ProviderUnavailable()
            proof = self.proof_owner.verify(command, binding)
            if not isinstance(proof, LifecycleProof):
                raise ProviderDenied()
        with self.mutation() as connection:
            meta = source_meta(connection)
            self._scope(meta, actor, ref)
            previous = self._retained(connection, ref)
            if actor.service == "source" and intent.kind == "revoke":
                self._logout_actor(
                    connection, meta, command, cookie, csrf, previous, other_device=other_device
                )
            if previous is not None:
                return previous
            epoch_mismatch = (
                intent.access_epoch < binding.access_epoch
                if intent.kind == "verify_restore_binding"
                else intent.access_epoch != binding.access_epoch
            )
            if (
                self.binding() != binding
                or intent.expected_revision != meta["revision"]
                or epoch_mismatch
                or binding.deployment_id != intent.deployment_id
                or binding.scope != intent.scope
            ):
                raise ProviderDenied()
            now = self.clock()
            if proof is not None and (
                proof.binding != binding
                or proof.request_hash != ref.request_hash
                or proof.expires_at <= now
                or not 1 <= len(proof.email_key) <= 254
                or not proof.email_key.startswith(binding.issuer + ":")
                or (intent.kind != "rebind" and proof.email_key != meta["email_key"])
            ):
                raise ProviderDenied()
            if intent.kind == "revoke":
                if intent.access_epoch != meta["access_epoch"] or (
                    binding.binding_id,
                    binding.resource_generation,
                    binding.issuer,
                    binding.subject,
                ) != (
                    meta["binding_id"],
                    meta["resource_generation"],
                    meta["issuer"],
                    meta["subject"],
                ):
                    raise ProviderDenied()
                mutation, revocation = self._revoke(connection, meta, intent.payload, now)
            elif intent.kind == "drain":
                mutation, revocation = self._drain(connection, meta, intent, binding, now)
            elif intent.kind == "verify_restore_binding":
                mutation, revocation = self._verify_restore_binding(
                    connection, meta, intent, binding, now
                )
            else:
                mutation, revocation = self._changes(meta, intent, binding, now), None
                if intent.kind == "rebind":
                    mutation["email_key"] = proof.email_key
            return self._commit(connection, ref, meta, mutation, now, revocation=revocation)

    def _initialize_disabled(self, actor, command, binding, *, email_key):
        ref = command.reference()
        intent = command.intent
        payload = intent.payload
        resolved_email = email_key
        proof: LifecycleProof | None = None
        if resolved_email is None and self.proof_owner is not None:
            proof = self.proof_owner.verify(command, binding)
            if not isinstance(proof, LifecycleProof) or proof.request_hash != ref.request_hash:
                raise ProviderDenied()
            resolved_email = proof.email_key
        with self.mutation() as connection:
            previous = self._retained(connection, ref)
            if previous is not None:
                return previous
            existing = connection.execute(
                text("SELECT id FROM main.access_meta WHERE id=1")
            ).first()
            now = self.clock()
            if (
                existing is not None
                or self.binding() != binding
                or (proof is not None and (proof.binding != binding or proof.expires_at <= now))
                or intent.expected_revision != 1
                or intent.access_epoch != binding.access_epoch
                or binding.deployment_id != intent.deployment_id
                or binding.scope != intent.scope
                or binding.binding_id != payload.binding_id
                or payload.policy.usable_bytes != FREE_V1_USABLE_BYTES
                or not isinstance(resolved_email, str)
                or not 1 <= len(resolved_email) <= 254
                or not resolved_email.startswith(binding.issuer + ":")
            ):
                raise ProviderDenied()
            connection.execute(
                text("""
                INSERT INTO main.access_meta (
                    id, deployment_id, operator_id, workspace_id, binding_id,
                    resource_generation, issuer, subject, email_key, effective_access,
                    access_epoch, session_generation, not_before, effective_policy_id,
                    usable_bytes, policy_revision, maintenance_operation_id,
                    restore_generation, revision
                ) VALUES (
                    1, :deployment_id, :operator_id, :workspace_id, :binding_id,
                    :resource_generation, :issuer, NULL, :email_key, 'disabled',
                    :access_epoch, 1, :now, :policy_id,
                    :usable_bytes, :policy_revision, NULL,
                    1, 1
                )
            """),
                {
                    "deployment_id": intent.deployment_id,
                    "operator_id": intent.scope.operator_id,
                    "workspace_id": intent.scope.workspace_id,
                    "binding_id": binding.binding_id,
                    "resource_generation": binding.resource_generation,
                    "issuer": binding.issuer,
                    "email_key": resolved_email,
                    "access_epoch": intent.access_epoch,
                    "now": now,
                    "policy_id": payload.policy.policy_id,
                    "usable_bytes": payload.policy.usable_bytes,
                    "policy_revision": payload.policy.policy_revision,
                },
            )
            connection.execute(
                text("""
                INSERT INTO main.usage_state (
                    id, business_revision, committed_db_bytes, retained_file_bytes,
                    observed_at, measurement_version, revision
                ) VALUES (1, 'initial', 0, 0, :now, 'logical-v1', 1)
            """),
                {"now": now},
            )
            result = SourceResult(
                access_epoch=intent.access_epoch,
                effective_enabled=False,
                receipt_ref="source-receipt:" + ref.operation_id,
                revocation=None,
            )
            connection.execute(
                text("""
                INSERT INTO main.access_receipts
                    (operation_id, idempotency_key, request_hash, kind, access_epoch,
                     source_revision, result_json, recorded_at)
                VALUES (:id, :key, :hash, 'initialize_binding', :epoch, 1, :result, :now)
            """),
                {
                    "id": ref.operation_id,
                    "key": ref.idempotency_key,
                    "hash": ref.request_hash,
                    "epoch": intent.access_epoch,
                    "result": result.model_dump_json(),
                    "now": now,
                },
            )
            connection.execute(
                text("""
                INSERT INTO main.access_audit
                    (audit_id, operation_id, action, actor_ref, recorded_at, safe_facts_json)
                VALUES (:audit, :id, 'initialize_binding', 'identity-control', :now, '{}')
            """),
                {"audit": str(uuid4()), "id": ref.operation_id, "now": now},
            )
            return OperationOutcome[SourceResult](
                operation=ref,
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=now,
                result=result,
            )

    def _logout_actor(self, connection, meta, command, cookie, csrf, previous, *, other_device):
        if previous is None:
            row = session_row(connection, cookie, meta, self.clock(), lineage=not other_device)
        else:
            row = (
                connection.execute(
                    text("SELECT * FROM main.access_sessions WHERE session_hash=:hash"),
                    {"hash": session_hash(cookie)},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["access_epoch"] != command.intent.access_epoch:
                raise ProviderDenied()
        check_csrf(row, csrf)
        payload = command.intent.payload
        if other_device and (payload.all_devices or payload.session_reference == row["session_id"]):
            raise ProviderDenied()
        if (
            not other_device
            and not payload.all_devices
            and payload.session_reference != row["session_id"]
        ):
            raise ProviderDenied()

    def _changes(self, meta, intent, binding, now):
        kind, epoch, change = intent.kind, intent.access_epoch, intent.payload
        current = meta["access_epoch"]
        if epoch < current or (epoch > current and kind not in {"disable", "rebind"}):
            raise ProviderDenied()
        same_resource = (meta["binding_id"], meta["resource_generation"], meta["issuer"]) == (
            binding.binding_id,
            binding.resource_generation,
            binding.issuer,
        )
        if kind != "rebind" and not same_resource:
            raise ProviderDenied()
        if kind == "apply_policy":
            if (
                epoch != current
                or meta["maintenance_operation_id"] is not None
                or change.policy_revision <= meta["policy_revision"]
            ):
                raise ProviderDenied()
            return {
                "effective_policy_id": change.policy_id,
                "policy_revision": change.policy_revision,
                "usable_bytes": FREE_V1_USABLE_BYTES,
            }
        if kind == "disable":
            return self._fence(meta, now, epoch) | {"effective_access": "disabled"}
        if kind == "rebind":
            if (
                epoch <= current
                or meta["effective_access"] != "disabled"
                or meta["maintenance_operation_id"] is not None
                or change.expected_session_generation != meta["session_generation"]
                or change.assignment_revision != binding.assignment_revision
            ):
                raise ProviderDenied()
            return self._fence(meta, now, epoch) | {
                "binding_id": binding.binding_id,
                "resource_generation": binding.resource_generation,
                "issuer": binding.issuer,
                "subject": binding.subject,
            }
        if kind in {"claim", "enable"}:
            if (
                meta["maintenance_operation_id"] is not None
                or meta["effective_access"] != "disabled"
            ):
                raise ProviderDenied()
            if kind == "claim" and meta["subject"] is None:
                return {"subject": binding.subject}
            if meta["subject"] != binding.subject:
                raise ProviderDenied()
            return {"effective_access": "enabled"} if kind == "enable" else {}
        if kind == "maintenance_fence":
            if epoch != current or meta["maintenance_operation_id"] is not None:
                raise ProviderDenied()
            return {"maintenance_operation_id": change.maintenance_id}
        raise ProviderDenied()

    @staticmethod
    def _fence(meta, now, epoch):
        return {
            "access_epoch": epoch,
            "session_generation": meta["session_generation"] + 1,
            "not_before": max(meta["not_before"], now + 1),
        }

    @staticmethod
    def _revoke_live_sessions(connection, meta, now):
        connection.execute(
            text("""
            UPDATE main.access_sessions SET revoked_at=:now
            WHERE generation=:generation AND access_epoch=:epoch
                AND revoked_at IS NULL AND issued_at<=:now AND expires_at>:now
        """),
            {
                "now": now,
                "generation": meta["session_generation"],
                "epoch": meta["access_epoch"],
            },
        )

    def _drain(self, connection, meta, intent, binding, now):
        same_resource = (meta["binding_id"], meta["resource_generation"], meta["issuer"]) == (
            binding.binding_id,
            binding.resource_generation,
            binding.issuer,
        )
        if (
            not same_resource
            or intent.access_epoch != meta["access_epoch"]
            or meta["maintenance_operation_id"] != intent.payload.maintenance_id
        ):
            raise ProviderDenied()
        self._revoke_live_sessions(connection, meta, now)
        fence = self._fence(meta, now, meta["access_epoch"])
        return fence, SourceRevocation(managed_session_id=None, not_before=fence["not_before"])

    def _verify_restore_binding(self, connection, meta, intent, binding, now):
        same_resource = (meta["binding_id"], meta["resource_generation"], meta["issuer"]) == (
            binding.binding_id,
            binding.resource_generation,
            binding.issuer,
        )
        if (
            not same_resource
            or intent.access_epoch <= meta["access_epoch"]
            or meta["maintenance_operation_id"] != intent.payload.restore_operation_id
        ):
            raise ProviderDenied()
        self._revoke_live_sessions(connection, meta, now)
        fence = self._fence(meta, now, intent.access_epoch)
        mutation = fence | {
            "restore_generation": meta["restore_generation"] + 1,
            "maintenance_operation_id": None,
        }
        return mutation, SourceRevocation(managed_session_id=None, not_before=fence["not_before"])

    def _revoke(self, connection, meta, change, now):
        if change.all_devices:
            self._revoke_live_sessions(connection, meta, now)
            fence = self._fence(meta, now, meta["access_epoch"])
            return fence, SourceRevocation(managed_session_id=None, not_before=fence["not_before"])
        session_id = TypeAdapter(CanonicalId).validate_python(change.session_reference)
        matched = connection.execute(
            text("""
            UPDATE main.access_sessions SET revoked_at=coalesce(revoked_at,:now)
            WHERE session_id=:id AND generation=:generation AND access_epoch=:epoch AND issued_at<=:now
            RETURNING managed_session_id
        """),
            {
                "id": session_id,
                "now": now,
                "generation": meta["session_generation"],
                "epoch": meta["access_epoch"],
            },
        )
        managed = matched.scalar_one_or_none()
        if managed is None:
            raise ProviderDenied()
        return {}, SourceRevocation(
            session_id=session_id, managed_session_id=managed, not_before=None
        )

    def _commit(self, connection, ref, meta, mutation, now, *, revocation=None):
        revision = meta["revision"] + 1
        values = mutation | {"revision": revision}
        assignments = ", ".join(f"{key}=:{key}" for key in values)
        connection.execute(text(f"UPDATE main.access_meta SET {assignments} WHERE id=1"), values)
        result = SourceResult(
            access_epoch=mutation.get("access_epoch", meta["access_epoch"]),
            effective_enabled=mutation.get("effective_access", meta["effective_access"])
            == "enabled",
            receipt_ref="source-receipt:" + ref.operation_id,
            revocation=revocation,
        )
        kind = RECEIPT_KINDS[ref.kind]
        connection.execute(
            text("""
            INSERT INTO main.access_receipts
                (operation_id, idempotency_key, request_hash, kind, access_epoch, source_revision, result_json, recorded_at)
            VALUES (:id,:key,:hash,:kind,:epoch,:revision,:result,:now)
        """),
            {
                "id": ref.operation_id,
                "key": ref.idempotency_key,
                "hash": ref.request_hash,
                "kind": kind,
                "epoch": result.access_epoch,
                "revision": revision,
                "result": result.model_dump_json(),
                "now": now,
            },
        )
        connection.execute(
            text("""
            INSERT INTO main.access_audit (audit_id,operation_id,action,actor_ref,recorded_at,safe_facts_json)
            VALUES (:audit,:id,:kind,'identity-control',:now,'{}')
        """),
            {"audit": str(uuid4()), "id": ref.operation_id, "kind": kind, "now": now},
        )
        return OperationOutcome[SourceResult](
            operation=ref,
            state=OperationState.SUCCEEDED,
            revision=revision,
            observed_at=now,
            result=result,
        )
