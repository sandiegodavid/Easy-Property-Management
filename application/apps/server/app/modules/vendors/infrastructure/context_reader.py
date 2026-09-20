"""SQLite provider-profile facts for caller-owned transactions."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import select

from app.modules.vendors.infrastructure.sqlalchemy_models import ProviderProfileModel


class SQLiteProviderContextReader:
    def profile_context(self, connection: Any, party_id: str) -> Mapping[str, object] | None:
        return connection.execute(select(
            ProviderProfileModel.party_id, ProviderProfileModel.archived_at,
        ).where(ProviderProfileModel.party_id == party_id)).mappings().first()

    def profile_contexts(self, connection: Any, party_ids: Collection[str]) -> Mapping[str, Mapping[str, object]]:
        party_ids = set(party_ids)
        if not party_ids:
            return {}
        return {
            row["party_id"]: row
            for row in connection.execute(select(
                ProviderProfileModel.party_id, ProviderProfileModel.archived_at,
            ).where(ProviderProfileModel.party_id.in_(party_ids))).mappings()
        }
