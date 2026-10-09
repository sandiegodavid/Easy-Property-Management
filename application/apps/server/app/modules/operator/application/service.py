"""Readiness, durable preferences and incomplete-form recovery use cases."""

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError

from app.modules.operator.application.ports import OperatorUnitOfWork
from app.modules.operator.application.cursors import ReadCursor, decode_cursor, read_revision
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.domain.models import (
    MAX_ACTIVE_RECOVERY,
    OperatorConflict,
    OperatorError,
    OperatorNotFound,
    OperatorStorageFailure,
    OperatorUnavailable,
    Preferences,
    canonical,
    concurrency,
    fingerprint,
    identifier,
    source_identifier,
    audit_metadata,
)


class OperatorService:
    def __init__(
        self,
        unit_of_work: OperatorUnitOfWork,
        *,
        runtime,
        now=lambda: datetime.now(UTC),
        capabilities=(),
    ):
        self.unit_of_work, self.runtime, self.now = unit_of_work, runtime, now
        self.capabilities = tuple(capabilities)

    def instant(self):
        value = self.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise OperatorUnavailable("Operator clock is unavailable.")
        return value.astimezone(UTC)

    def ready(self, write=False):
        identity = self.runtime()
        if identity.state != "ready" or (write and not identity.can_write):
            raise OperatorUnavailable("Open and validate the workspace before this operation.")
        return identity

    def bootstrap(self):
        identity = self.runtime()
        state, reason_code = identity.state, identity.reason_code
        preferences = None
        recovery_actions = []
        if state == "ready":
            try:
                preferences = self.preferences()
            except OperatorUnavailable:
                state, reason_code = "busy", "workspace_busy"
            except OperatorStorageFailure:
                state, reason_code = "unavailable", "operator_storage_failure"
            if state != "ready":
                recovery_actions = [
                    {
                        "kind": "api_operation",
                        "action": "getOperatorBootstrap",
                        "label": "Retry the workspace readiness check.",
                    }
                ]
        else:
            recovery_actions = [
                {
                    "kind": "setup_guidance",
                    "action": "workspace_setup",
                    "label": "Use the local workspace setup command.",
                }
            ]
        ready = state == "ready"
        return {
            "contractVersion": 1,
            "state": state,
            "workspaceId": identity.workspace_id if identity.state == "ready" else None,
            "runtimeEpoch": identity.epoch,
            "canWrite": ready and identity.can_write,
            "reasonCode": reason_code,
            "capabilities": list(self.capabilities) if ready else [],
            "capabilityVersion": 1,
            "preferencesState": "available" if ready else "unavailable",
            "preferences": preferences,
            "recoveryActions": recovery_actions,
        }

    def preferences(self):
        self.ready()
        return self.unit_of_work.read(lambda tx: preference_view(tx.preferences()))

    def update_preferences(
        self,
        *,
        appearance,
        destination_order,
        hidden_destination_ids,
        expected_revision,
        idempotency_key,
    ):
        self.ready(True)
        concurrency(expected_revision, idempotency_key)
        try:
            requested = Preferences(
                appearance=appearance,
                destination_order=destination_order,
                hidden_destination_ids=hidden_destination_ids,
            )
        except ValidationError as error:
            raise OperatorError("Navigation or appearance preferences are invalid.") from error
        request = {
            "kind": "preferences",
            "value": requested.model_dump(mode="json"),
            "expectedRevision": expected_revision,
        }
        instant = self.instant()

        def write(tx):
            replay = replay_operation(tx, idempotency_key, request)
            if replay is not None:
                return replay
            current = tx.preferences()
            check_revision(current.revision, expected_revision)
            updated = requested.model_copy(
                update={"revision": current.revision + 1, "updated_at": instant.isoformat()}
            )
            tx.save_preferences(updated)
            result = preference_view(updated)
            return record_operation(
                tx,
                idempotency_key,
                request,
                "operator_preferences",
                "workspace",
                "updated",
                expected_revision,
                result,
                preference_view(current),
                instant,
            )

        return self.unit_of_work.write(write)

    def save_recovery(
        self,
        record_id,
        *,
        form_key,
        schema_version,
        payload,
        expected_revision,
        idempotency_key,
        source_kind=None,
        source_id=None,
        base_source_revision=None,
    ):
        self.ready(True)
        identifier(record_id)
        concurrency(expected_revision, idempotency_key)
        payload = validate_payload(form_key, schema_version, payload)
        if (source_kind is None) != (source_id is None) or (
            source_kind is None and base_source_revision is not None
        ):
            raise OperatorError("Related source kind and ID must be supplied together.")
        if source_id is not None:
            source_identifier(source_kind, source_id)
        if base_source_revision is not None and (
            not isinstance(base_source_revision, str) or not 1 <= len(base_source_revision) <= 100
        ):
            raise OperatorError("Invalid base source revision.")
        request = {
            "kind": "recovery_save",
            "id": record_id,
            "formKey": form_key,
            "schemaVersion": schema_version,
            "payload": payload,
            "expectedRevision": expected_revision,
            "sourceKind": source_kind,
            "sourceId": source_id,
            "baseSourceRevision": base_source_revision,
        }
        instant = self.instant()

        def write(tx):
            replay = replay_operation(tx, idempotency_key, request)
            if replay is not None:
                return replay
            current = tx.recovery(record_id)
            check_revision(current["revision"] if current else 0, expected_revision)
            if current and (current["form_key"] != form_key or current["status"] != "active"):
                raise OperatorConflict("This recovery record cannot be overwritten.")
            if current is None and tx.active_recovery_count() >= MAX_ACTIVE_RECOVERY:
                raise OperatorConflict(
                    "Recovery capacity is exhausted; reconcile or discard saved forms first."
                )
            value = {
                "id": record_id,
                "form_key": form_key,
                "schema_version": schema_version,
                "payload_json": canonical(payload),
                "revision": expected_revision + 1,
                "status": "active",
                "source_kind": source_kind,
                "source_id": source_id,
                "base_source_revision": base_source_revision,
                "attempt_key": None,
                "request_fingerprint": None,
                "receipt_json": None,
                "saved_at": instant.isoformat(),
                "expires_at": (instant + timedelta(days=30)).isoformat(),
            }
            state = tx.validate_recovery(value)
            if state != "available":
                raise OperatorConflict(
                    "The source is unavailable, changed, or has an official draft."
                )
            tx.save_recovery(value)
            return record_operation(
                tx,
                idempotency_key,
                request,
                "operator_recovery",
                record_id,
                "saved",
                expected_revision,
                recovery_view(value, instant, state),
                recovery_metadata(current),
                instant,
            )

        return self.unit_of_work.write(write)

    def recovery(self, record_id):
        self.ready()
        identifier(record_id)
        instant = self.instant()

        def read(tx):
            value = require_recovery(tx, record_id)
            compatible = value["schema_version"] == 1
            state = tx.validate_recovery(value) if compatible else "schema_incompatible"
            return recovery_view(value, instant, state)

        return self.unit_of_work.read(read)

    def recovery_page(self, *, limit=50, cursor=None):
        runtime = self.ready()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise OperatorError("Recovery page size must be 1–100.")
        instant = self.instant()

        def read(tx):
            identity = (runtime.workspace_id, runtime.epoch)
            source_revision = read_revision(identity, tx.source_marker())
            filters = {"limit": limit}
            continuation = (
                decode_cursor(
                    cursor,
                    endpoint="recovery",
                    filters=filters,
                    identity=identity,
                    source_revision=source_revision,
                    now=instant,
                )
                if cursor
                else None
            )
            after = continuation.last if continuation else None
            as_of = continuation.as_of if continuation else instant.isoformat()
            total, rows = tx.recovery_page(limit=limit, after=after)
            selected = rows[:limit]
            # Lists contain metadata only; source revalidation occurs on load.
            return {
                "items": [recovery_metadata(row) for row in selected],
                "matchingTotal": total,
                "nextCursor": ReadCursor(
                    "recovery",
                    filters,
                    identity,
                    source_revision,
                    as_of,
                    (selected[-1]["saved_at"], selected[-1]["id"]),
                ).encode()
                if len(rows) > limit
                else None,
                "asOf": as_of,
                "sourceRevision": source_revision,
            }

        return self.unit_of_work.read(read)

    def discard_recovery(self, record_id, *, expected_revision, idempotency_key):
        return self._recovery_transition(record_id, "discarded", expected_revision, idempotency_key)

    def reconcile_recovery(self, record_id, *, expected_revision, idempotency_key):
        return self._recovery_transition(
            record_id, "reconciled", expected_revision, idempotency_key
        )

    def prepare_attempt(
        self,
        record_id,
        *,
        attempt_key,
        request_fingerprint=None,
        expected_revision,
        idempotency_key,
    ):
        self.ready(True)
        identifier(record_id)
        identifier(attempt_key)
        concurrency(expected_revision, idempotency_key)
        if request_fingerprint is not None and (
            not isinstance(request_fingerprint, str)
            or not re.fullmatch("[0-9a-f]{64}", request_fingerprint)
        ):
            raise OperatorError("The owning command fingerprint must be lowercase SHA-256.")
        request = {
            "kind": "recovery_attempt",
            "id": record_id,
            "attemptKey": attempt_key,
            "requestFingerprint": request_fingerprint,
            "expectedRevision": expected_revision,
        }
        instant = self.instant()

        def write(tx):
            replay = replay_operation(tx, idempotency_key, request)
            if replay is not None:
                return replay
            current = require_recovery(tx, record_id)
            check_revision(current["revision"], expected_revision)
            if current["status"] != "active":
                raise OperatorConflict("This form cannot begin a recoverable command attempt.")
            if (
                current["expires_at"] <= instant.isoformat()
                or tx.validate_recovery(current) != "available"
            ):
                raise OperatorConflict("Refresh this form before starting an attempt.")
            from app.modules.operator.application.command_forms import COMMAND_SCHEMAS

            if current["form_key"] in COMMAND_SCHEMAS:
                calculated = tx.attempt_fingerprint(current, attempt_key)
                if request_fingerprint is not None and calculated != request_fingerprint:
                    raise OperatorConflict("The attempted command does not match the saved form.")
            else:
                if request_fingerprint is None:
                    raise OperatorError("The owning command fingerprint is required.")
                calculated = request_fingerprint
            value = {
                **current,
                "revision": expected_revision + 1,
                "status": "outcome_unknown",
                "attempt_key": attempt_key,
                "request_fingerprint": calculated,
            }
            tx.save_recovery(value)
            return record_operation(
                tx,
                idempotency_key,
                request,
                "operator_recovery",
                record_id,
                "saved",
                expected_revision,
                recovery_view(value, instant, "outcome_unknown"),
                recovery_metadata(current),
                instant,
            )

        return self.unit_of_work.write(write)

    def expire_recovery(self, *, limit=100):
        self.ready(True)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise OperatorError("Expiry batch must contain 1–100 records.")
        instant = self.instant()

        def write(tx):
            rows = tx.expired_recovery(instant.isoformat(), limit)
            for current in rows:
                value = {**current, "status": "expired", "revision": current["revision"] + 1}
                tx.save_recovery(value)
                request = {
                    "kind": "recovery_expire",
                    "id": value["id"],
                    "expectedRevision": current["revision"],
                }
                record_operation(
                    tx,
                    str(uuid4()),
                    request,
                    "operator_recovery",
                    value["id"],
                    "expired",
                    current["revision"],
                    recovery_view(value, instant, "expired"),
                    recovery_metadata(current),
                    instant,
                )
            return {
                "expiredCount": len(rows),
                "asOf": instant.isoformat(),
                "mayHaveMore": len(rows) == limit,
            }

        return self.unit_of_work.write(write)

    def _recovery_transition(self, record_id, action, expected_revision, idempotency_key):
        self.ready(True)
        identifier(record_id)
        concurrency(expected_revision, idempotency_key)
        instant = self.instant()
        request = {
            "kind": "recovery_" + action,
            "id": record_id,
            "expectedRevision": expected_revision,
        }

        def write(tx):
            replay = replay_operation(tx, idempotency_key, request)
            if replay is not None:
                return replay
            current = require_recovery(tx, record_id)
            check_revision(current["revision"], expected_revision)
            if current["status"] in {"discarded", "expired"}:
                raise OperatorConflict("This recovery record is terminal.")
            value = dict(current)
            if action == "reconciled":
                if current["status"] != "outcome_unknown":
                    raise OperatorConflict("Only unresolved attempts need reconciliation.")
                receipt = tx.resolve_attempt(current)
                if receipt is None:
                    raise OperatorConflict("The owning command outcome is still unknown.")
                value["receipt_json"] = canonical(receipt)
            elif current["status"] == "outcome_unknown":
                raise OperatorConflict("An unresolved command cannot be discarded.")
            value.update(status=action, revision=expected_revision + 1)
            tx.save_recovery(value)
            return record_operation(
                tx,
                idempotency_key,
                request,
                "operator_recovery",
                record_id,
                action,
                expected_revision,
                recovery_view(value, instant, "not_reusable"),
                recovery_metadata(current),
                instant,
            )

        return self.unit_of_work.write(write)

    def operation(self, key):
        self.ready()
        identifier(key)

        def read(tx):
            value = tx.operation(key)
            if value is None:
                raise OperatorNotFound("Operator operation was not found.")
            return json.loads(value["result_json"])

        return self.unit_of_work.read(read)


def preference_view(value):
    return {
        "appearance": value.appearance,
        "destinationOrder": list(value.destination_order),
        "hiddenDestinationIds": list(value.hidden_destination_ids),
        "revision": value.revision,
        "updatedAt": value.updated_at,
    }


def recovery_metadata(value):
    if value is None:
        return None
    return {
        "id": value["id"],
        "formKey": value["form_key"],
        "schemaVersion": value["schema_version"],
        "revision": value["revision"],
        "status": value["status"],
        "savedAt": value["saved_at"],
        "expiresAt": value["expires_at"],
        "sourceKind": value["source_kind"],
        "sourceId": value["source_id"],
        "baseSourceRevision": value["base_source_revision"],
    }


def recovery_view(value, instant, state):
    expired = value["status"] != "outcome_unknown" and value["expires_at"] <= instant.isoformat()
    if value["status"] == "outcome_unknown":
        state = "outcome_unknown"
    elif value["status"] != "active":
        state = "not_reusable"
    return {
        **recovery_metadata(value),
        "payload": json.loads(value["payload_json"]),
        "attemptKey": value["attempt_key"],
        "requestFingerprint": value["request_fingerprint"],
        "receipt": json.loads(value["receipt_json"]) if value["receipt_json"] else None,
        "reuseState": "expired" if expired else state,
        "asOf": instant.isoformat(),
    }


def require_recovery(tx, record_id):
    value = tx.recovery(record_id)
    if value is None:
        raise OperatorNotFound("Recovery record was not found.")
    return value


def check_revision(current, expected):
    if current != expected:
        raise OperatorConflict(
            "The record changed. Reload before saving.", current_revision=current
        )


def replay_operation(tx, key, request):
    operation = tx.operation(key)
    if operation is None:
        return None
    if operation["request_fingerprint"] != fingerprint(request):
        raise OperatorConflict("This idempotency key was used for a different request.")
    return json.loads(operation["result_json"])


def record_operation(
    tx, key, request, entity_type, entity_id, action, expected, result, before, instant
):
    operation_id, correlation = str(uuid4()), str(uuid4())
    result = {**result, "operationId": operation_id}
    metadata = audit_metadata(result)
    tx.record_change(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before=before,
        after=metadata,
        correlation_id=correlation,
        occurred_at=instant,
    )
    operation = {
        "id": operation_id,
        "idempotency_key": key,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "request_fingerprint": fingerprint(request),
        "request_json": canonical(request),
        "expected_revision": expected,
        "resulting_revision": expected + 1,
        "result_json": canonical(result),
        "correlation_id": correlation,
        "created_at": instant.isoformat(),
        "recovery_id": entity_id if entity_type == "operator_recovery" else None,
    }
    tx.insert_operation(operation)
    tx.record_change(
        entity_type="operator_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after={
            "entityType": entity_type,
            "entityId": entity_id,
            "action": action,
            "revision": expected + 1,
        },
        correlation_id=correlation,
        occurred_at=instant,
    )
    return result
