"""Party-owned, read-only identity projection for caller-owned snapshots."""

from sqlalchemy import select

from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel


class SQLitePartyIdentityRelations:
    def identities(self):
        return select(
            PartyModel.id.label("party_id"),
            PartyModel.display_name,
            PartyModel.party_kind,
            PartyModel.archived_at,
        ).subquery("party_identities")
