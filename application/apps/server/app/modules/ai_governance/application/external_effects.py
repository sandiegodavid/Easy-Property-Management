"""Durable intent recovery for non-transactional, device-local AI effects.

An attempt key identifies an intent, never a credential value. Reusing it does
not apply a new secret. Unknown attempts are not dispatched again.
"""

from datetime import UTC, datetime
from hashlib import sha256
import json
from collections.abc import Callable, Mapping
from uuid import uuid4
from threading import Lock

from app.modules.ai_governance.application.commands import command_json
from app.modules.ai_governance.application.ports import (
    AiGovernanceUnitOfWork,
    AiProviderPort,
    AiTransportCredentialStore,
)
from app.modules.ai_governance.domain.models import (
    AiConflictError,
    AiNotFoundError,
    AiValidationError,
    validate_provider_metadata,
    validate_uuid,
    canonical_json,
)


EXTERNAL_ACTIONS = frozenset({"credential_set", "credential_delete", "connection_probe"})


def external_request(action, connection_id, expected_revision):
    if action not in EXTERNAL_ACTIONS:
        raise AiValidationError("Unsupported AI external operation.")
    if validate_uuid(connection_id, "connectionId") != connection_id:
        raise AiValidationError("connectionId must be a canonical UUID.")
    if type(expected_revision) is not int or expected_revision < 1:
        raise AiValidationError("expectedRevision must be an exact positive integer.")
    return command_json(
        {"action": action, "connectionId": connection_id, "expectedRevision": expected_revision}
    )


def external_fingerprint(action, connection_id, expected_revision):
    return sha256(external_request(action, connection_id, expected_revision).encode()).hexdigest()


def external_view(row):
    result = None if row["result_json"] is None else json.loads(row["result_json"])
    return {
        "operationId": row["id"],
        "idempotencyKey": row["idempotency_key"],
        "connectionId": row["connection_id"],
        "action": row["action"],
        "revision": row["revision"],
        "updatedAt": row["created_at"],
        "status": "outcome_unknown" if result is None else result["status"],
        "result": result,
        "createdAt": row["created_at"],
        "completedAt": row["completed_at"],
        # Portable history is never evidence of present-device readiness.
        "requiresDeviceValidation": True,
    }


class AiExternalEffectService:
    """External calls occur strictly between intent and result transactions."""

    def __init__(
        self,
        unit_of_work: AiGovernanceUnitOfWork,
        *,
        workspace_id: str,
        adapters,
        credentials: AiTransportCredentialStore | None,
        providers: Mapping[str, AiProviderPort],
        now: Callable[[], datetime] | None = None,
    ):
        self.unit_of_work = unit_of_work
        self.workspace_id = workspace_id
        self.adapters = adapters
        self.credentials = credentials
        self.providers = dict(providers)
        self.clock = now or (lambda: datetime.now(UTC))
        self._active = set()
        self._guard = Lock()

    def _stamp(self):
        instant = self.clock()
        if instant.tzinfo is None:
            raise AiValidationError("AI clock must be timezone aware.")
        return instant.astimezone(UTC).isoformat()

    def receipt(self, *, operation_id=None, key=None):
        if (operation_id is None) == (key is None):
            raise AiValidationError("Supply one external-operation identifier.")
        validate_uuid(operation_id or key, "operationId")
        row = self.unit_of_work.external_row(operation_id=operation_id, key=key)
        if row is None:
            raise AiNotFoundError("AI external operation was not found.")
        return external_view(row)

    def execute(
        self, action, connection_id, *, expected_revision, idempotency_key, credential=None
    ):
        external_request(action, connection_id, expected_revision)
        if validate_uuid(idempotency_key, "idempotencyKey") != idempotency_key:
            raise AiValidationError("idempotencyKey must be a canonical UUID.")
        # Acknowledgement cannot release an intent while this writer is still
        # executing it. Workspace writer ownership excludes other processes.
        with self._guard:
            if idempotency_key in self._active:
                raise AiConflictError("ai_external_in_progress")
            self._active.add(idempotency_key)
        try:
            return self._execute(
                action,
                connection_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                credential=credential,
            )
        finally:
            with self._guard:
                self._active.discard(idempotency_key)

    def _execute(self, action, connection_id, *, expected_revision, idempotency_key, credential):
        request = external_request(action, connection_id, expected_revision)
        if validate_uuid(idempotency_key, "idempotencyKey") != idempotency_key:
            raise AiValidationError("idempotencyKey must be a canonical UUID.")
        if action == "credential_set" and (
            not isinstance(credential, str) or not 1 <= len(credential) <= 8192
        ):
            raise AiValidationError("A bounded credential is required.")
        stamp = self._stamp()

        def reserve(tx):
            prior = tx.external_by_key(idempotency_key)
            if prior is not None:
                if prior["request_json"] != request:
                    raise AiConflictError("ai_idempotency_conflict")
                return prior, False
            connection = tx.model_connection(connection_id)
            if connection is None:
                raise AiNotFoundError("AI model connection was not found.")
            if connection["revision"] != expected_revision:
                error = AiConflictError("ai_revision_conflict")
                error.current = {"id": connection_id, "revision": connection["revision"]}
                error.revision = connection["revision"]
                raise error
            if tx.pending_external(connection_id):
                raise AiConflictError("ai_external_outcome_unknown")
            row = {
                "id": str(uuid4()),
                "idempotency_key": idempotency_key,
                "connection_id": connection_id,
                "action": action,
                "expected_revision": expected_revision,
                "revision": expected_revision + 1,
                "request_json": request,
                "request_fingerprint": sha256(request.encode()).hexdigest(),
                "correlation_id": str(uuid4()),
                "created_at": stamp,
                "result_json": None,
                "completed_at": None,
            }
            tx.insert_external(row)
            revised = {**connection, "revision": row["revision"], "updated_at": stamp}
            tx.replace_connection(connection_id, {"revision": row["revision"], "updated_at": stamp})
            tx.record_audit(
                entity_type="ai_model_connection",
                entity_id=connection_id,
                action="external_reserved",
                before=connection,
                after=revised,
                correlation_id=row["correlation_id"],
                actor="local_operator",
                reason="ai_external_reserved",
                event_id=row["id"],
            )
            self._audit(tx, row, "intent_recorded", None, external_view(row))
            return row, True

        row, dispatch = self.unit_of_work.write(reserve)
        if not dispatch:
            return external_view(row)
        try:
            current = self.unit_of_work.connection_row(connection_id)
            if current is None or current["revision"] != row["revision"]:
                return external_view(row)
            result = self._perform(action, current, credential)
        except Exception:
            # Transport and keyring errors can occur after the effect. Neither
            # retry nor compensation can safely establish the original outcome.
            return external_view(row)
        completed = self._stamp()

        def finish(tx):
            retained = tx.external_by_key(idempotency_key)
            if retained["result_json"] is not None:
                return external_view(retained)
            after = {**retained, "result_json": command_json(result), "completed_at": completed}
            tx.complete_external(row["id"], after["result_json"], completed)
            self._audit(tx, after, "completed", external_view(retained), external_view(after))
            if action != "connection_probe":
                tx.record_audit(
                    entity_type="ai_model_connection",
                    entity_id=connection_id,
                    action=result["credentialAction"],
                    before={"id": connection_id, "credentialPresent": result["beforePresent"]},
                    after={"id": connection_id, "credentialPresent": result["afterPresent"]},
                    correlation_id=row["correlation_id"],
                    actor="local_operator",
                    reason="ai_credential_changed",
                )
            return external_view(after)

        # If this commit fails the intent remains unknown. Do not rerun effect.
        return self.unit_of_work.write(finish)

    def acknowledge_unknown(self, operation_id):
        """Explicitly close uncertainty, without asserting success or repeating it."""
        if validate_uuid(operation_id, "operationId") != operation_id:
            raise AiValidationError("operationId must be a canonical UUID.")
        stamp = self._stamp()

        def operation(tx):
            row = tx.external_operation(operation_id)
            if row is None:
                raise AiNotFoundError("AI external operation was not found.")
            with self._guard:
                if row["idempotency_key"] in self._active:
                    raise AiConflictError("ai_external_in_progress")
            if row["result_json"] is not None:
                if json.loads(row["result_json"])["status"] != "abandoned":
                    raise AiConflictError("ai_external_already_completed")
                return external_view(row)
            result = command_json({"status": "abandoned"})
            after = {**row, "result_json": result, "completed_at": stamp}
            tx.complete_external(operation_id, result, stamp)
            self._audit(tx, after, "abandoned", external_view(row), external_view(after))
            return external_view(after)

        return self.unit_of_work.write(operation)

    def _perform(self, action, connection, credential):
        if action != "connection_probe":
            if self.credentials is None:
                raise AiValidationError("AI credential storage is unavailable.")
            before = (
                self.credentials.get_credential(self.workspace_id, connection["id"]) is not None
            )
            if action == "credential_set":
                self.credentials.set_credential(self.workspace_id, connection["id"], credential)
            else:
                self.credentials.delete_credential(self.workspace_id, connection["id"])
            return {
                "status": "completed",
                "beforePresent": before,
                "afterPresent": action == "credential_set",
                "credentialAction": "credential_deleted"
                if action == "credential_delete"
                else "credential_replaced"
                if before
                else "credential_set",
            }
        adapter = self.adapters.require(connection["adapter_id"], connection["adapter_version"])
        if not connection["enabled"]:
            return {"status": "completed", "ready": False, "reason": "connection_disabled"}
        if adapter.requires_credential and (
            self.credentials is None
            or self.credentials.get_credential(self.workspace_id, connection["id"]) is None
        ):
            return {"status": "completed", "ready": False, "reason": "credential_unavailable"}
        provider = self.providers.get(connection["adapter_id"])
        if provider is None:
            return {"status": "completed", "ready": False, "reason": "provider_unavailable"}
        probe = provider.probe(
            {"kind": "connection_probe", "input": "health check"},
            connection["model_identifier"],
            adapter.timeout_seconds,
        )
        if not isinstance(probe.payload, Mapping) or probe.payload != {"status": "ok"}:
            raise AiValidationError("Invalid synthetic probe result.")
        canonical_json(probe.payload, maximum_bytes=1024)
        validate_provider_metadata(
            probe.prompt_tokens, probe.completion_tokens, probe.provider_request_id
        )
        return {"status": "completed", "ready": True, "reason": None}

    @staticmethod
    def _audit(tx, row, action, before, after):
        tx.record_audit(
            entity_type="ai_external_operation",
            entity_id=row["id"],
            action=action,
            before=before,
            after=after,
            correlation_id=row["correlation_id"],
            actor="local_operator",
            reason="ai_external_" + action,
        )
