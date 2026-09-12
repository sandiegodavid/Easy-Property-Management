"""Provider projection used inside FIN-002 transactions."""

from sqlalchemy import select

from app.modules.vendors.infrastructure.sqlalchemy_models import ProviderProfileModel


class SQLiteProviderExpenseOperations:
    def __init__(self, party_operations):
        self.party_operations = party_operations

    def expense_provider(self, connection, party_id):
        profile = connection.execute(select(
            ProviderProfileModel.archived_at,
        ).where(ProviderProfileModel.party_id == party_id)).mappings().first()
        party = self.party_operations.party(connection, party_id)
        if profile is None or party is None:
            return None
        return {
            "partyId": party_id,
            "displayName": party.display_name,
            "archived": profile["archived_at"] is not None,
        }

    def expense_providers(self, connection, party_ids):
        if not party_ids:
            return {}
        profiles = {
            row["party_id"]: row
            for row in connection.execute(
                select(
                    ProviderProfileModel.party_id,
                    ProviderProfileModel.archived_at,
                ).where(ProviderProfileModel.party_id.in_(party_ids))
            ).mappings()
        }
        parties = self.party_operations.party_map(connection, list(profiles))
        return {
            party_id: {
                "partyId": party_id,
                "displayName": party.display_name,
                "archived": profiles[party_id]["archived_at"] is not None,
            }
            for party_id, party in parties.items()
        }
