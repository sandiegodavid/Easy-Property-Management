"""Tenant identity metadata only; excludes contacts, notes and applicant evidence."""

from sqlalchemy import literal, select, or_

from app.modules.parties.application.identity_relations import PartyIdentityRelations
from app.modules.tenants.infrastructure.sqlalchemy_models import TenantProfileModel
from app.platform.sql_metadata_search import metadata_page


class SQLiteTenantSearchReader:
    def __init__(self, parties: PartyIdentityRelations):
        self.parties = parties

    def search(self, connection, term, window):
        tenant, party = TenantProfileModel.__table__, self.parties.identities()
        selection = select(
            tenant.c.party_id.label("id"),
            party.c.display_name.label("label"),
            literal("Tenant").label("context"),
            or_(tenant.c.archived_at.is_not(None), party.c.archived_at.is_not(None)).label(
                "archived"
            ),
            literal("tenant").label("entity_type"),
        ).join(party, tenant.c.party_id == party.c.party_id)
        return metadata_page(connection, selection, term, window)
