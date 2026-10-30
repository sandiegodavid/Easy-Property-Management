"""Private verification of manual provider denial after the owning app fence."""

import json
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import fingerprint


class EdgeDenialReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_revision: int = Field(ge=0)
    configuration_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed: float = Field(ge=0, allow_inf_nan=False)


class EdgeDenial:
    def __init__(self, store, source, reports, provider):
        self.store, self.source, self.reports, self.provider = store, source, reports, provider

    def current(self, payload):
        deployment, status = self.source.access_snapshot(payload["instance"])
        reference = self.source.prepare(payload["instance"])
        if (
            status["active"]
            or any(
                reference["instance"].get(field)
                != payload["source_reference"]["instance"].get(field)
                for field in (
                    "allocation_id",
                    "instance_id",
                    "workspace_id",
                    "operator_id",
                    "hostname",
                )
            )
            or reference["deployment_digest"] != payload["source_reference"]["deployment_digest"]
        ):
            raise AdminError("admin_provider_denial_unverified", 409)
        return deployment, status, reference

    def verify(self, identifier):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM operation WHERE id=? AND kind='source'", (identifier,)
            ).fetchone()
        if row is None:
            raise AdminError("admin_operation_not_found", 404)
        payload = json.loads(row[0])
        if payload["action"] != "disable" or self.source.reconcile(payload) is None:
            raise AdminError("admin_app_disable_required", 409)
        deployment, status, reference = self.current(payload)
        self.provider().verify_denial(
            reference["instance"]["hostname"], deployment["identity_audience"]
        )
        if self.current(payload) != (deployment, status, reference):
            raise AdminError("admin_source_binding_changed", 409)
        report = EdgeDenialReport(
            operation_id=identifier,
            request_digest=fingerprint(payload),
            source_revision=status["admin_revision"],
            configuration_digest=reference["deployment_digest"],
            observed=self.store.clock(),
        )
        report_id = str(uuid4())
        self.reports.publish(report_id, report.model_dump())
        with self.store.transaction() as connection:
            self.store._audit(connection, "edge_denial_verified", identifier + ":" + report_id)
        return {"verified": True, "operation_id": identifier, "report_id": report_id}

    def confirmed(self, payload):
        try:
            with self.store.transaction() as connection:
                audited = connection.execute(
                    "SELECT reference FROM audit WHERE action='edge_denial_verified' AND reference LIKE ? ORDER BY sequence DESC LIMIT 1",
                    (payload["operation_id"] + ":%",),
                ).fetchone()
            if audited is None:
                return False
            report = EdgeDenialReport.model_validate(
                self.reports.report(audited[0].split(":", 1)[1])
            )
            _, status, reference = self.current(payload)
            return bool(
                audited
                and report.operation_id == payload["operation_id"]
                and report.request_digest == fingerprint(payload)
                and report.source_revision == status["admin_revision"]
                and report.configuration_digest == reference["deployment_digest"]
                and 0 <= self.store.clock() - report.observed < 600
            )
        except OSError, ValueError:
            return False
