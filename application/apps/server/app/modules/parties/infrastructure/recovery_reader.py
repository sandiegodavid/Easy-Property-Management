"""Party-owned, transaction-aware identity/contact command recovery."""

from sqlalchemy import select, func, case

from app.modules.parties.infrastructure.sqlalchemy_models import (
    PartyModel,
    PartyCommandOperationModel,
    PartyContactMethodModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLitePartyRecoveryReader:
    def state(self, connection, source_id):
        return (
            connection.execute(
                select(
                    PartyModel.revision,
                    case((PartyModel.archived_at.is_(None), "active"), else_="archived").label(
                        "status"
                    ),
                ).where(PartyModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def related_state(self, connection, kind, target_id):
        if kind != "contact":
            raise ValueError("Unsupported Party related source.")
        model = PartyContactMethodModel
        return (
            connection.execute(
                select(
                    model.party_id.label("source_id"),
                    model.status,
                ).where(model.id == target_id)
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        if family != "party":
            raise ValueError("Unsupported Party command family.")
        model = PartyCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.party_id,
                    model.action,
                    model.request_fingerprint,
                    model.resulting_revision,
                    func.json_extract(model.result_json, "$.id").label("target_id"),
                    func.json_extract(model.result_json, "$.status").label("contact_status"),
                    func.json_extract(model.result_json, "$.archivedAt").label("archived_at"),
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
                row["target_id"],
                row["resulting_revision"],
                row["contact_status"] or ("archived" if row["archived_at"] else "active"),
            ),
        )
