"""Tenant-owned independent revisions and immutable command metadata."""

from sqlalchemy import select, func, case

from app.modules.tenants.infrastructure.sqlalchemy_models import (
    TenantProfileModel,
    TenantCommandOperationModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult, CommandRecoveryReader


class SQLiteTenantRecoveryReader:
    def __init__(self, parties: CommandRecoveryReader, *, designate=False):
        self.parties, self.designate = parties, designate

    def state(self, connection, source_id):
        party = self.parties.state(connection, source_id)
        if party is None:
            return None
        model = TenantProfileModel
        row = (
            connection.execute(
                select(model.revision, model.archived_at).where(model.party_id == source_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            return (
                {
                    "revision": 0,
                    "status": "eligible" if party["status"] == "active" else "unavailable",
                }
                if self.designate
                else None
            )
        return {
            "revision": row["revision"],
            "status": "archived" if row["archived_at"] else "active",
            "party_status": party["status"],
        }

    def outcome(self, connection, key, *, family):
        if family != "tenant":
            raise ValueError("Unsupported Tenant command family.")
        model = TenantCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.party_id,
                    model.action,
                    model.request_fingerprint,
                    model.resulting_revision,
                    case(
                        (
                            func.json_type(model.result_json, "$.profile") == "object",
                            func.json_extract(model.result_json, "$.profile.archivedAt"),
                        ),
                        else_=func.json_extract(model.result_json, "$.archivedAt"),
                    ).label("archived_at"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["party_id"],
            row["request_fingerprint"],
            CommandResult(
                row["party_id"],
                row["resulting_revision"],
                "archived" if row["archived_at"] else "active",
            ),
        )
