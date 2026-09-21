"""Composition-side neutral source facts for OWNER-004."""
from datetime import datetime
from typing import Any
from sqlalchemy import func, select
from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationLinkModel, CommunicationModel, CommunicationParticipantModel
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseParticipantModel
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, PropertyOwnershipModel, SpaceAvailabilityModel, SpaceModel, SpaceOccupancyPeriodModel
from app.modules.tasks.application.service import TaskCreateCommand
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel

class SQLiteOwnerConcernContext:
    def __init__(self, task_operations): self.task_operations=task_operations
    def context(self, connection: Any, *, owner_party_id, property_id, space_id, lease_id, tenant_party_id, raised_on, historical):
        prop=connection.execute(select(PropertyModel.__table__).where(PropertyModel.id==property_id)).mappings().first()
        owner=connection.execute(select(PartyModel.__table__).where(PartyModel.id==owner_party_id)).mappings().first()
        if not prop or not owner: raise ValueError("Selected owner or property was not found.")
        if prop["status"] != "active" and not historical: raise ValueError("Current concerns require an active property.")
        zone=prop["time_zone"]
        if not raised_on: return {"time_zone": zone}
        owned=connection.execute(select(PropertyOwnershipModel.id).where(PropertyOwnershipModel.property_id==property_id,PropertyOwnershipModel.party_id==owner_party_id,PropertyOwnershipModel.owner_kind=="client_owner",PropertyOwnershipModel.starts_on<=raised_on,(PropertyOwnershipModel.ends_on.is_(None)|(PropertyOwnershipModel.ends_on>raised_on)))).first()
        if not owned: raise ValueError("Selected party was not a client owner on the raised local date.")
        if owner["archived_at"] is not None and not historical: raise ValueError("Current concerns require an active owner party.")
        space=None
        if space_id:
            space=connection.execute(select(SpaceModel.__table__).where(SpaceModel.id==space_id)).mappings().first()
            if not space or space["property_id"]!=property_id: raise ValueError("Selected space does not belong to the property.")
            if space["status"]!="active" and not historical: raise ValueError("Current concerns require an active space.")
        lease=None
        if lease_id:
            lease=connection.execute(select(LeaseModel.__table__).where(LeaseModel.id==lease_id)).mappings().first()
            if not lease or not space or lease["space_id"]!=space_id: raise ValueError("Selected lease does not match the property and space.")
        tenant=None
        if tenant_party_id:
            tenant=connection.execute(select(PartyModel.__table__).where(PartyModel.id==tenant_party_id)).mappings().first()
            participant=connection.execute(select(LeaseParticipantModel.id).where(LeaseParticipantModel.lease_id==lease_id,LeaseParticipantModel.tenant_party_id==tenant_party_id,LeaseParticipantModel.starts_on<=raised_on,(LeaseParticipantModel.ends_on.is_(None)|(LeaseParticipantModel.ends_on>raised_on)))).first()
            if not tenant or not participant: raise ValueError("Selected tenant was not an effective lease participant on the raised local date.")
        occupancy=availability=None
        if space_id:
            occupancy=connection.execute(select(SpaceOccupancyPeriodModel.occupancy_status).where(SpaceOccupancyPeriodModel.space_id==space_id,SpaceOccupancyPeriodModel.record_state=="valid",SpaceOccupancyPeriodModel.starts_on<=raised_on,(SpaceOccupancyPeriodModel.ends_on.is_(None)|(SpaceOccupancyPeriodModel.ends_on>raised_on)))).scalar_one_or_none()
            availability=connection.execute(select(SpaceAvailabilityModel.__table__).where(SpaceAvailabilityModel.space_id==space_id)).mappings().first()
        return {"time_zone":zone,"owner_display_name":owner["display_name"],"property_display_name":prop["display_name"],"space_display_name":None if not space else space["display_name"],"lease_display":None if not lease else f"Lease {lease['contract_starts_on']}","tenant_display_name":None if not tenant else tenant["display_name"],"occupancy_status":occupancy,"availability_status":None if not availability else availability["availability_status"],"available_on":None if not availability else availability["available_on"]}
    def originating_communication(self,connection, communication_id, owner_party_id, property_id):
        row=connection.execute(select(CommunicationModel.id).where(CommunicationModel.id==communication_id,CommunicationModel.status=="recorded",CommunicationModel.direction=="inbound")).first()
        reporter=connection.execute(select(CommunicationParticipantModel.id).where(CommunicationParticipantModel.communication_id==communication_id,CommunicationParticipantModel.party_id==owner_party_id,CommunicationParticipantModel.role.in_(("sender","reporter")))).first()
        link=connection.execute(select(CommunicationLinkModel.id).where(CommunicationLinkModel.communication_id==communication_id,CommunicationLinkModel.entity_type=="property",CommunicationLinkModel.entity_id==property_id)).first()
        return bool(row and reporter and link)
    def create_task(self,connection,values,correlation_id,record_change):
        task_values = {
            "title": values["title"], "notes": values.get("notes"), "priority": values.get("priority", "normal"),
            "dueAtUtc": values.get("due_at_utc"), "dueTimezone": values.get("due_timezone"),
            "isAllDay": values.get("is_all_day", False), "relatedEntityType": values["related_entity_type"],
            "relatedEntityId": values["related_entity_id"], "relatedLabel": values["related_label"],
        }
        return self.task_operations.create_task(connection,TaskCreateCommand.from_mapping(task_values),correlation_id=correlation_id,record_change=record_change)
    def task_views(self,connection,concern_ids):
        rows=connection.execute(select(TaskModel.__table__).where(TaskModel.related_entity_type=="owner_concern",TaskModel.related_entity_id.in_(concern_ids))).mappings()
        result={item:[] for item in concern_ids}
        for row in rows: result[row["related_entity_id"]].append({"id":row["id"],"status":row["status"],"title":row["title"],"dueAtUtc":row["due_at_utc"]})
        return result
    def communication_counts(self,connection,concern_ids):
        rows=connection.execute(select(CommunicationLinkModel.entity_id,func.count()).where(CommunicationLinkModel.entity_type=="owner_concern",CommunicationLinkModel.entity_id.in_(concern_ids)).group_by(CommunicationLinkModel.entity_id)).all()
        return {row[0]:row[1] for row in rows}
