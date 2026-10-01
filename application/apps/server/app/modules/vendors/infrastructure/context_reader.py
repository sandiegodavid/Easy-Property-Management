"""SQLite provider-profile facts for caller-owned transactions."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import select

from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderCategoryAssignmentModel,
    ProviderCategoryModel,
    ProviderProfileModel,
)

MAX_PROVIDER_CONTEXTS = 200


class SQLiteProviderContextReader:
    def profile_context(self, connection: Any, party_id: str) -> Mapping[str, object] | None:
        return connection.execute(select(
            ProviderProfileModel.party_id, ProviderProfileModel.archived_at, ProviderProfileModel.selection_status,
        ).where(ProviderProfileModel.party_id == party_id)).mappings().first()

    def profile_contexts(self, connection: Any, party_ids: Collection[str]) -> Mapping[str, Mapping[str, object]]:
        party_ids = set(party_ids)
        if not party_ids:
            return {}
        _require_batch_limit(party_ids)
        return {
            row["party_id"]: row
            for row in connection.execute(select(
                ProviderProfileModel.party_id, ProviderProfileModel.archived_at, ProviderProfileModel.selection_status,
            ).where(ProviderProfileModel.party_id.in_(party_ids))).mappings()
        }

    def effective_categories(self, connection: Any, party_id: str) -> list[Mapping[str, object]]:
        return self.effective_categories_for_providers(connection, [party_id]).get(party_id, [])

    def effective_categories_for_providers(self, connection: Any, party_ids: Collection[str]) -> Mapping[str, list[Mapping[str, object]]]:
        party_ids = set(party_ids)
        if not party_ids:
            return {}
        _require_batch_limit(party_ids)
        rows = connection.execute(
            select(
                ProviderCategoryAssignmentModel.id.label("assignment_id"),
                ProviderCategoryAssignmentModel.provider_party_id,
                ProviderCategoryModel.id.label("category_id"), ProviderCategoryModel.display_name,
                ProviderCategoryModel.display_order,
            ).join(ProviderCategoryModel, ProviderCategoryModel.id == ProviderCategoryAssignmentModel.category_id).join(
                ProviderProfileModel, ProviderProfileModel.party_id == ProviderCategoryAssignmentModel.provider_party_id,
            ).where(
                ProviderCategoryAssignmentModel.provider_party_id.in_(party_ids),
                ProviderCategoryAssignmentModel.archived_at.is_(None),
                ProviderCategoryModel.archived_at.is_(None), ProviderProfileModel.archived_at.is_(None),
            ).order_by(ProviderCategoryModel.display_order, ProviderCategoryModel.normalized_name, ProviderCategoryModel.id,
                       ProviderCategoryAssignmentModel.id)
        ).mappings()
        result: dict[str, list[Mapping[str, object]]] = {party_id: [] for party_id in party_ids}
        for row in rows:
            result[row["provider_party_id"]].append(row)
        return result

    def active_category_catalog(self, connection: Any) -> list[Mapping[str, object]]:
        return list(connection.execute(select(
            ProviderCategoryModel.id, ProviderCategoryModel.display_name,
            ProviderCategoryModel.display_order,
        ).where(ProviderCategoryModel.archived_at.is_(None)).order_by(
            ProviderCategoryModel.display_order, ProviderCategoryModel.normalized_name,
            ProviderCategoryModel.id,
        )).mappings())


def _require_batch_limit(party_ids: Collection[str]) -> None:
    if len(party_ids) > MAX_PROVIDER_CONTEXTS:
        raise ValueError(f"Provider context batches cannot exceed {MAX_PROVIDER_CONTEXTS} providers.")
