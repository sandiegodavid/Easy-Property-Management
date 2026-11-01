"""Atomic source mutations, receipts and privacy-safe audit; no business DB access."""

from datetime import UTC, datetime
import json
import hashlib
import math
import re
from uuid import uuid4

from sqlalchemy import MetaData, Table, select, update, func

from app.modules.hosted_access.application.admin_commands import (
    MAX_ENROLLMENTS,
    AccessCommand,
    AccessResult,
    AccessStatus,
    deployment_fingerprint,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.sqlite_engine import immediate_transaction


def denied(code="hosted_admin_conflict"):
    return HostedAccessError(
        code, "Administration requires current authority and source state.", 409
    )


def state(row):
    return {
        key: row[key]
        for key in ("admin_revision", "binding_revision", "admin_fence", "generation", "active")
    }


class AccessCommands:
    def __init__(self, store, activation_check=None):
        self.store = store
        # Later onboarding supplies a trusted recovery/acceptance checker, never a browser boolean.
        self.activation_check = activation_check
        metadata = MetaData()
        self.receipts = Table("hosted_admin_receipt", metadata, autoload_with=store.engine)
        self.audit = Table("hosted_admin_audit", metadata, autoload_with=store.engine)

    def status(self):
        with self.store.engine.connect() as connection:
            row = connection.execute(select(self.store.operator)).mappings().one()
            return state(row)

    def administrative_status(self) -> AccessStatus:
        with self.store.engine.connect() as connection:
            approval = (
                select(func.max(self.audit.c.recorded_at))
                .where(self.audit.c.action.in_(("approve", "rebind", "renew")))
                .scalar_subquery()
            )
            row = (
                connection.execute(select(self.store.operator, approval.label("approved_at")))
                .mappings()
                .one()
            )
            candidates = connection.execute(
                select(self.store.enrollment.c.subject, self.store.enrollment.c.received_at)
                .order_by(self.store.enrollment.c.received_at, self.store.enrollment.c.subject)
                .limit(MAX_ENROLLMENTS)
            ).mappings()
            return AccessStatus(
                **state(row),
                identity_approved=row["subject"] is not None,
                approved_subject=row["subject"],
                approved_at=row["approved_at"],
                binding_matches_configuration=(
                    row["binding_digest"] == deployment_fingerprint(self.store.deployment)
                ),
                enrollments=[dict(candidate) for candidate in candidates],
            )

    def receipt(self, command: AccessCommand) -> AccessResult | None:
        with self.store.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.receipts).where(
                        self.receipts.c.operation_id == command.operation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row and row["semantic_hash"] != command.fingerprint():
                raise denied("hosted_admin_identity_conflict")
            return AccessResult.model_validate_json(row["result_json"]) if row else None

    def execute(self, command: AccessCommand, now=None) -> AccessResult:
        now = now or datetime.now(UTC)
        with immediate_transaction(self.store.engine) as connection:
            receipt = (
                connection.execute(
                    select(self.receipts).where(
                        self.receipts.c.operation_id == command.operation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt:
                if receipt["semantic_hash"] != command.fingerprint():
                    raise denied("hosted_admin_identity_conflict")
                return AccessResult.model_validate_json(receipt["result_json"])
            row = connection.execute(select(self.store.operator)).mappings().one()
            self._validate(connection, row, command, now)
            values = {"admin_revision": row["admin_revision"] + 1}
            if command.action in {"approve", "rebind"}:
                values.update(
                    subject=command.subject,
                    active=False,
                    binding_revision=row["binding_revision"] + 1,
                )
            if command.action in {"enable", "complete_onboarding"}:
                values["active"] = True
            if command.action in {"renew", "replace_email"}:
                replacement = self.replacement(command)
                values.update(
                    active=False,
                    binding_revision=row["binding_revision"] + 1,
                    binding_digest=deployment_fingerprint(replacement),
                    email=replacement.allowed_email,
                )
                if command.action == "replace_email":
                    values["subject"] = None
                    connection.execute(self.store.enrollment.delete())
            if command.action in {"disable", "revoke", "rebind", "renew", "replace_email"}:
                values.update(
                    generation=row["generation"] + 1,
                    not_before=now.timestamp(),
                    admin_fence=row["admin_fence"] + 1,
                )
            if command.action == "disable":
                values["active"] = False
            connection.execute(update(self.store.operator).values(**values))
            after = dict(row) | values
            return self._record(connection, row, after, command, now)

    def _record(self, connection, row, after, command, now):
        result = AccessResult(
            operation_id=command.operation_id,
            action=command.action,
            revision=after["admin_revision"],
            binding_revision=after["binding_revision"],
            fence=after["admin_fence"],
            generation=after["generation"],
            active=after["active"],
        )
        connection.execute(
            self.receipts.insert().values(
                operation_id=command.operation_id,
                semantic_hash=command.fingerprint(),
                result_json=result.model_dump_json(),
            )
        )
        connection.execute(
            self.audit.insert().values(
                operation_id=command.operation_id,
                action=command.action,
                authority_reference=command.authority_reference,
                recorded_at=now.timestamp(),
                before_json=json.dumps(state(row), sort_keys=True),
                after_json=json.dumps(state(after), sort_keys=True),
            )
        )
        return result

    def record_restore(self, connection, row, after, now):
        # A restored business history invalidates binding and sessions atomically.
        # The technical marker is private and not copied into the safe audit.
        from types import SimpleNamespace

        fingerprint = hashlib.sha256(json.dumps(state(after), sort_keys=True).encode()).hexdigest()
        command = SimpleNamespace(
            operation_id=str(uuid4()),
            action="restore_reset",
            authority_reference="workspace-restore",
            fingerprint=lambda: fingerprint,
        )
        self._record(connection, row, after, command, now)

    def _validate(self, connection, row, command, now):
        if (
            row["admin_revision"] != command.expected_revision
            or row["binding_revision"] != command.expected_binding_revision
            or row["admin_fence"] != command.fence
        ):
            raise denied()
        if command.action in {"disable", "revoke"}:
            return  # Containment remains possible with expired/broken business data.
        self.store.maintenance.require_open(connection)
        deployment = self.store.deployment
        if (
            command.action not in {"renew", "replace_email"}
            and not deployment.enabled_at <= now < deployment.expires_at
        ):
            raise denied("hosted_admin_window_invalid")
        if row["binding_digest"] != deployment_fingerprint(deployment):
            raise denied("hosted_admin_binding_changed")
        if command.action in {"renew", "replace_email"}:
            replacement = self.replacement(command)
            if replacement.expires_at <= now:
                raise denied("hosted_admin_window_invalid")
            if command.action == "replace_email" and (
                row["active"] or replacement.allowed_email == deployment.allowed_email
            ):
                raise denied("hosted_replacement_requires_disabled_access")
        if command.action in {"approve", "rebind"}:
            candidate = (
                connection.execute(
                    select(self.store.enrollment).where(
                        self.store.enrollment.c.subject == command.subject
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                not candidate
                or candidate["email"] != deployment.allowed_email
                or candidate["received_at"] != command.enrollment_received_at
            ):
                raise denied("hosted_enrollment_missing")
            if row["active"] or (
                command.action == "approve" and row["subject"] not in {None, command.subject}
            ):
                raise denied()
        if command.action in {"enable", "complete_onboarding"}:
            if row["subject"] is None:
                raise denied("hosted_recovery_required")
            if command.activation is not None:
                self._activation(connection, row, command, now)
            elif self.activation_check is not None:
                self.activation_check(connection, row, command, now)
            else:
                raise denied("hosted_recovery_required")

    def _activation(self, connection, row, command, now):
        proof = command.activation
        approved = connection.scalar(
            select(func.max(self.audit.c.recorded_at)).where(
                self.audit.c.action.in_(("approve", "rebind", "renew"))
            )
        )
        if (
            proof.evidence_id != command.evidence_id
            or proof.acceptance_id != command.acceptance_id
            or proof.workspace_id != row["workspace_id"]
            or proof.binding_revision != row["binding_revision"]
            or proof.subject != row["subject"]
            or proof.deployment_digest != row["binding_digest"]
            or approved is None
            or proof.verified_at < approved
            or not 0 <= now.timestamp() - proof.verified_at < 86400
            or proof.expires <= now.timestamp()
        ):
            raise denied("hosted_recovery_required")

    def replacement(self, command):
        from app.modules.hosted_access.application.configuration import HostedDeployment

        values = self.store.deployment.model_dump(mode="json")
        if command.action == "renew":
            values.update(
                enabled_at=datetime.fromtimestamp(command.starts, UTC).isoformat(),
                expires_at=datetime.fromtimestamp(command.expires, UTC).isoformat(),
            )
        else:
            values["allowed_email"] = command.replacement_email
        return HostedDeployment.model_validate(values)

    def validate_retained(self):
        """Reconstruct every audited authorization transition and match the retained tip."""
        try:
            with self.store.engine.connect() as connection:
                receipts = {
                    row["operation_id"]: row
                    for row in connection.execute(select(self.receipts)).mappings()
                }
                audits = list(connection.execute(select(self.audit)).mappings())
                operator = connection.execute(select(self.store.operator)).mappings().one()
            if len(receipts) != len(audits):
                raise ValueError()
            ordered = sorted(
                audits, key=lambda event: json.loads(event["after_json"])["admin_revision"]
            )
            prior = {
                "admin_revision": 0,
                "binding_revision": 0,
                "admin_fence": 0,
                "generation": 0,
                "active": False,
            }
            for event in ordered:
                receipt = receipts[event["operation_id"]]
                result = AccessResult.model_validate_json(receipt["result_json"])
                before, after = json.loads(event["before_json"]), json.loads(event["after_json"])
                self._validate_event(event, receipt, result, before, after)
                # Operator-initiated all-device sign-out may advance generation independently.
                if before["generation"] < prior["generation"] or {
                    key: value for key, value in before.items() if key != "generation"
                } != {key: value for key, value in prior.items() if key != "generation"}:
                    raise ValueError()
                prior = after
            current = state(operator)
            if (
                current["generation"] < prior["generation"]
                or any(current[key] != prior[key] for key in current if key != "generation")
                or not re.fullmatch(r"[a-f0-9]{64}", operator["binding_digest"])
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            raise denied("hosted_admin_history_invalid") from error

    @staticmethod
    def _validate_event(event, receipt, result, before, after):
        expected_keys = {
            "admin_revision",
            "binding_revision",
            "admin_fence",
            "generation",
            "active",
        }
        for snapshot in (before, after):
            if (
                set(snapshot) != expected_keys
                or type(snapshot["active"]) is not bool
                or any(
                    type(snapshot[key]) is not int or snapshot[key] < 0
                    for key in expected_keys - {"active"}
                )
            ):
                raise ValueError()
        action = result.action
        if (
            result.operation_id != receipt["operation_id"]
            or action != event["action"]
            or not re.fullmatch(r"[a-f0-9]{64}", receipt["semantic_hash"])
            or not math.isfinite(event["recorded_at"])
            or event["recorded_at"] < 0
            or not 1 <= len(event["authority_reference"]) <= 128
            or result.model_dump_json() != receipt["result_json"]
            or after
            != {
                "admin_revision": result.revision,
                "binding_revision": result.binding_revision,
                "admin_fence": result.fence,
                "generation": result.generation,
                "active": result.active,
            }
        ):
            raise ValueError()
        fenced = action in {
            "disable",
            "revoke",
            "rebind",
            "restore_reset",
            "renew",
            "replace_email",
        }
        bound = action in {"approve", "rebind", "restore_reset", "renew", "replace_email"}
        active = (
            True
            if action in {"enable", "complete_onboarding"}
            else False
            if action != "revoke"
            else before["active"]
        )
        if after != {
            "admin_revision": before["admin_revision"] + 1,
            "binding_revision": before["binding_revision"] + int(bound),
            "admin_fence": before["admin_fence"] + int(fenced),
            "generation": before["generation"] + int(fenced),
            "active": active,
        }:
            raise ValueError()
