"""Provider-owned transaction-aware state and original receipt metadata."""

from sqlalchemy import func, select

from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderCategoryAssignmentModel,
    ProviderCategoryCommandOperationModel,
    ProviderCategoryModel,
    ProviderCommandOperationModel,
    ProviderProfileModel,
    ProviderReferenceModel,
    ProviderReputationLinkModel,
    ProviderServiceAreaModel,
    ProviderServiceModel,
    ProviderWorkHistoryModel,
)
from app.platform.command_recovery import CommandOutcome, CommandRecoveryReader, CommandResult


CHILD_MODELS = {
    "service": ProviderServiceModel,
    "area": ProviderServiceAreaModel,
    "work": ProviderWorkHistoryModel,
    "reference": ProviderReferenceModel,
    "reputation": ProviderReputationLinkModel,
    "assignment": ProviderCategoryAssignmentModel,
}


class SQLiteProviderRecoveryReader:
    def __init__(self, parties: CommandRecoveryReader, *, designate=False, category=False):
        self.parties, self.designate, self.category = parties, designate, category

    def creation_state(self, connection, payload):
        identifiers = set(payload.get("categoryIds") or ())
        if not identifiers:
            return "available"
        model = ProviderCategoryModel
        existing = set(
            connection.execute(
                select(model.id).where(model.id.in_(identifiers), model.archived_at.is_(None))
            ).scalars()
        )
        return "available" if existing == identifiers else "source_unavailable"

    def state(self, connection, source_id):
        model = ProviderCategoryModel if self.category else ProviderProfileModel
        identity = model.id if self.category else model.party_id
        row = (
            connection.execute(
                select(model.revision, model.archived_at).where(identity == source_id)
            )
            .mappings()
            .first()
        )
        party = None if self.category else self.parties.state(connection, source_id)
        if row is None:
            return (
                {"revision": 0, "status": "eligible"}
                if self.designate and party is not None and party["status"] == "active"
                else None
            )
        return {
            "revision": row["revision"],
            "status": "archived" if row["archived_at"] else "active",
            "party_status": party["status"] if party else None,
        }

    def related_state(self, connection, kind, target):
        if kind == "category":
            model = ProviderCategoryModel
            columns = (model.id.label("source_id"), model.revision, model.archived_at)
        else:
            model = CHILD_MODELS[kind]
            owner = model.provider_party_id if kind == "assignment" else model.party_id
            columns = (owner.label("source_id"), model.archived_at)
            if kind == "assignment":
                columns += (model.category_id,)
        row = connection.execute(select(*columns).where(model.id == target)).mappings().first()
        return {**row, "status": "archived" if row["archived_at"] else "active"} if row else None

    def outcome(self, connection, key, *, family):
        if family not in {"provider", "provider_category"}:
            raise ValueError("Unsupported Provider command family.")
        category = family == "provider_category"
        model = ProviderCategoryCommandOperationModel if category else ProviderCommandOperationModel
        owner = model.category_id if category else model.party_id
        path = "$.category" if category else "$.item"
        row = (
            connection.execute(
                select(
                    model.id,
                    owner.label("source_id"),
                    model.action,
                    model.request_fingerprint,
                    model.resulting_revision,
                    func.json_extract(model.result_json, path + ".id").label("target_id"),
                    func.json_extract(model.result_json, path + ".archivedAt").label("archived_at"),
                    func.json_extract(model.result_json, "$.profile.archivedAt").label(
                        "profile_archived"
                    ),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        archived = row["archived_at"] if row["target_id"] else row["profile_archived"]
        return CommandOutcome(
            row["id"],
            row["action"],
            row["source_id"],
            row["request_fingerprint"],
            CommandResult(
                row["target_id"] or row["source_id"],
                row["resulting_revision"],
                "archived" if archived else "active",
            ),
        )
