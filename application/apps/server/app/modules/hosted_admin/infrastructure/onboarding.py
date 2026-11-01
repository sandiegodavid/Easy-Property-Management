"""Persistent recovery checklist; root-registered evidence gates source activation."""

import json
import sqlite3
from uuid import uuid4

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical
from app.modules.hosted_admin.application.recovery import RecoveryBinding, RecoveryReport


class OnboardingRecovery:
    def __init__(self, store, source, reports):
        self.store, self.source, self.reports = store, source, reports

    def binding(self, instance):
        deployment, status = self.source.access_snapshot(instance)
        if not status.get("identity_approved") or not status["binding_matches_configuration"]:
            raise AdminError("admin_approved_binding_required", 409)
        reference = self.source.prepare(instance)
        return RecoveryBinding(
            instance=instance,
            workspace_id=deployment["workspace_id"],
            binding_revision=status["binding_revision"],
            subject=status["approved_subject"],
            configuration_digest=reference["deployment_digest"],
            approved_at=status["approved_at"],
            release=reference["instance"]["release"],
        ), status

    def handoff(self, instance, identity):
        binding, status = self.binding(instance)
        identifier = self.ensure(binding, identity)
        return self.view(identifier, status["admin_revision"], binding)

    def ensure(self, binding, identity):
        instance = binding.instance
        encoded = canonical(binding.model_dump())
        with self.store.transaction() as connection:
            current = self.store._identity(connection)
            if current["id"] != identity["id"] or current["generation"] != identity["generation"]:
                raise AdminError("admin_authority_fenced", 409)
            row = connection.execute(
                "SELECT * FROM recovery_handoff WHERE instance=? AND binding=? AND generation=?",
                (instance, encoded, identity["generation"]),
            ).fetchone()
            if row is None:
                identifier = str(uuid4())
                connection.execute(
                    "INSERT INTO recovery_handoff VALUES (?,?,?,?,?,?)",
                    (
                        identifier,
                        instance,
                        encoded,
                        self.store.clock(),
                        identity["id"],
                        identity["generation"],
                    ),
                )
                self.store._audit(connection, "recovery_handoff_created", identifier)
            else:
                identifier = row["id"]
        return identifier

    def _get(self, connection, identifier):
        row = connection.execute(
            "SELECT * FROM recovery_handoff WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise AdminError("admin_recovery_handoff_not_found", 404)
        return dict(row)

    def register(self, identifier, report_id):
        """Root-only broker vocabulary reads a protected signed report by ID."""
        report = RecoveryReport.model_validate(self.reports.report(report_id))
        with self.store.transaction() as connection:
            current = self.store._identity(connection)
            handoff = self._get(connection, identifier)
            if (
                report.id != report_id
                or report.handoff_id != identifier
                or canonical(report.binding.model_dump()) != handoff["binding"]
                or handoff["generation"] != current["generation"]
            ):
                raise AdminError("admin_recovery_report_conflict", 409)
            encoded = canonical(report.model_dump())
            prior = connection.execute(
                "SELECT payload FROM recovery_report WHERE id=?", (report_id,)
            ).fetchone()
            if prior:
                if prior[0] != encoded:
                    raise AdminError("admin_recovery_report_conflict", 409)
            else:
                connection.execute(
                    "INSERT INTO recovery_report VALUES (?,?,?,?)",
                    (
                        report_id,
                        identifier,
                        encoded,
                        self.store.clock(),
                    ),
                )
                self.store._audit(connection, "recovery_report_registered", report_id)
        self.refresh(identifier)
        return {"registered": True, "report_id": report_id}

    def refresh(self, identifier, current=None):
        with self.store.transaction() as connection:
            handoff = self._get(connection, identifier)
            current_identity = self.store._identity(connection)
            row = connection.execute(
                "SELECT payload FROM recovery_report WHERE handoff_id=? ORDER BY registered DESC,rowid DESC LIMIT 1",
                (identifier,),
            ).fetchone()
        binding = RecoveryBinding.model_validate_json(handoff["binding"])
        report = RecoveryReport.model_validate_json(row[0]) if row else None
        now = self.store.clock()
        age = now - (report.completed.readback or report.observed) if report else None
        if handoff["generation"] != current_identity["generation"] or (
            current is not None and current != binding
        ):
            state = "stale"
        elif report is None:
            state = "unknown"
        elif not self.current_report(report):
            state = "stale"
        elif report.state == "failed":
            state = "failed"
        elif age < 0 or age >= 86400 or report.expires <= now:
            state = "overdue"
        elif age >= 72000:
            state = "warning"
        else:
            state = "verified"
        with self.store.transaction() as connection:
            previous = connection.execute(
                "SELECT state FROM recovery_attention WHERE handoff_id=?", (identifier,)
            ).fetchone()
            connection.execute(
                "INSERT INTO recovery_attention VALUES (?,?,?,NULL) ON CONFLICT(handoff_id) DO UPDATE SET state=excluded.state,checked=excluded.checked,acknowledged=CASE WHEN recovery_attention.state=excluded.state THEN recovery_attention.acknowledged ELSE NULL END",
                (identifier, state, now),
            )
            if previous is None or previous[0] != state:
                self.store._audit(connection, "recovery_" + state, identifier)
        return state, report

    def current_report(self, report):
        """Retained history is not proof under a changed or unavailable verifier."""
        try:
            protected = RecoveryReport.model_validate(self.reports.report(report.id))
        except OSError, ValueError:
            return False
        return protected == report

    def view(self, identifier, revision, binding):
        state, report = self.refresh(identifier, binding)
        with self.store.transaction() as connection:
            row = self._get(connection, identifier)
            attention = connection.execute(
                "SELECT acknowledged FROM recovery_attention WHERE handoff_id=?", (identifier,)
            ).fetchone()
            completed = connection.execute(
                "SELECT operation_id FROM onboarding_completion WHERE handoff_id=? ORDER BY completed DESC LIMIT 1",
                (identifier,),
            ).fetchone()
            if completed is None:
                completed = connection.execute(
                    "SELECT l.operation_id FROM upgrade_onboarding l JOIN operation o ON o.id=l.operation_id WHERE l.handoff_id=? AND o.state='succeeded' ORDER BY l.rowid DESC LIMIT 1",
                    (identifier,),
                ).fetchone()
        return {
            "id": identifier,
            "instance": row["instance"],
            "binding": json.loads(row["binding"]),
            "expected_revision": revision,
            "state": state,
            "acknowledged": attention is not None and attention[0] is not None,
            "report": report.model_dump() if report else None,
            "completion": completed[0] if completed else None,
            "private_command": f"sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py verify-onboarding --handoff {identifier}",
        }

    def check(self, request):
        with self.store.transaction() as connection:
            row = self._get(connection, request.handoff_id)
        binding, status = self.binding(row["instance"])
        if status["admin_revision"] != request.expected_revision:
            raise AdminError("admin_source_revision_conflict", 409)
        return self.view(request.handoff_id, status["admin_revision"], binding)

    def activation(self, payload):
        """Resolve proof before the host lock; the source rechecks it atomically."""
        report_id = payload.get("evidence_id")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT handoff_id FROM recovery_report WHERE id=?", (report_id,)
            ).fetchone()
        if not row or payload.get("acceptance_id") != report_id:
            raise AdminError("admin_recovery_verification_required", 409)
        binding, status = self.binding(payload["instance"])
        view = self.view(row[0], status["admin_revision"], binding)
        report = view["report"]
        if (
            view["state"] not in {"verified", "warning"}
            or not report
            or report["id"] != report_id
            or view["binding"] != binding.model_dump()
        ):
            raise AdminError("admin_recovery_verification_required", 409)
        if payload["action"] == "enable" and not view["completion"]:
            raise AdminError("admin_onboarding_completion_required", 409)
        from app.modules.hosted_access.application.configuration import HostedDeployment
        from app.modules.hosted_access.application.admin_commands import deployment_fingerprint

        deployment, _ = self.source.access_snapshot(payload["instance"])
        return {
            "evidence_id": report_id,
            "acceptance_id": report_id,
            "workspace_id": binding.workspace_id,
            "binding_revision": binding.binding_revision,
            "subject": binding.subject,
            "deployment_digest": deployment_fingerprint(
                HostedDeployment.model_validate(deployment)
            ),
            "verified_at": report["completed"]["readback"],
            "expires": report["expires"],
        }

    def completed(self, payload, result):
        if payload["action"] != "complete_onboarding" or not result.get("active"):
            return
        with self.store.transaction() as connection:
            report = connection.execute(
                "SELECT handoff_id FROM recovery_report WHERE id=?", (payload["evidence_id"],)
            ).fetchone()
            if report is None:
                raise AdminError("admin_recovery_verification_required", 409)
            inserted = connection.execute(
                "INSERT OR IGNORE INTO onboarding_completion VALUES (?,?,?,?)",
                (
                    payload["operation_id"],
                    report[0],
                    payload["evidence_id"],
                    self.store.clock(),
                ),
            )
            if inserted.rowcount:
                self.store._audit(connection, "onboarding_completed", payload["operation_id"])

    def acknowledge(self, request):
        value = self.check(request)
        with self.store.transaction() as connection:
            updated = connection.execute(
                "UPDATE recovery_attention SET acknowledged=? WHERE handoff_id=? AND state=?",
                (self.store.clock(), request.handoff_id, value["state"]),
            )
            if not updated.rowcount:
                raise AdminError("admin_recovery_attention_changed", 409)
            self.store._audit(connection, "recovery_attention_acknowledged", request.handoff_id)
        return value | {"acknowledged": True}

    def observe_all(self):
        # Called by the private worker independently of any console page. Access
        # expiry/late backups never trigger automatic activation or disablement.
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT id,instance FROM recovery_handoff h WHERE rowid=(SELECT max(rowid) FROM recovery_handoff WHERE instance=h.instance) ORDER BY created DESC LIMIT 1000"
            ).fetchall()
        for row in rows:
            try:
                current, _ = self.binding(row["instance"])
                self.refresh(row["id"], current)
            except OSError, ValueError, sqlite3.Error:
                with self.store.transaction() as connection:
                    previous = connection.execute(
                        "SELECT state FROM recovery_attention WHERE handoff_id=?", (row["id"],)
                    ).fetchone()
                    connection.execute(
                        "INSERT INTO recovery_attention VALUES (?,'unknown',?,NULL) ON CONFLICT(handoff_id) DO UPDATE SET state='unknown',checked=excluded.checked,acknowledged=CASE WHEN recovery_attention.state='unknown' THEN recovery_attention.acknowledged ELSE NULL END",
                        (row["id"], self.store.clock()),
                    )
                    if previous is None or previous[0] != "unknown":
                        self.store._audit(connection, "recovery_unknown", row["id"])

    def observation(self, instance):
        from app.modules.hosted_admin.application.console import RecoveryObservation

        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT h.id,a.state,a.acknowledged FROM recovery_handoff h LEFT JOIN recovery_attention a ON a.handoff_id=h.id WHERE h.instance=? ORDER BY h.created DESC,h.rowid DESC LIMIT 1",
                (instance,),
            ).fetchone()
            report_row = (
                connection.execute(
                    "SELECT payload FROM recovery_report WHERE handoff_id=? ORDER BY registered DESC,rowid DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if row
                else None
            )
            verified_row = (
                connection.execute(
                    "SELECT payload FROM recovery_report WHERE handoff_id=? AND json_extract(payload,'$.state')='verified' ORDER BY registered DESC,rowid DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if row
                else None
            )
        if not row or not report_row:
            return RecoveryObservation()
        report = RecoveryReport.model_validate_json(report_row[0])
        verified = RecoveryReport.model_validate_json(verified_row[0]) if verified_row else None
        return RecoveryObservation(
            local_archive=verified.completed.archive if verified else None,
            off_host_readback=verified.completed.readback if verified else None,
            restore_drill=verified.completed.restore if verified else None,
            approved_binding=verified.completed.approved_binding if verified else None,
            policy_state=row["state"] or "unknown",
            snapshot_marker=verified.snapshot_marker if verified else None,
            attempted=report.observed,
            acknowledged=row["acknowledged"] is not None,
        )
