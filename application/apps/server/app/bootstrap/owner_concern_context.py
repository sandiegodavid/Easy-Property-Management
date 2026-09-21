"""Composition-side neutral source facts for OWNER-004."""
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo
from sqlalchemy import func, select, union_all
from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationLinkModel, CommunicationModel, CommunicationParticipantModel
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseParticipantModel
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, PropertyOwnershipModel, SpaceAvailabilityModel, SpaceModel, SpaceOccupancyPeriodModel
from app.modules.finance.infrastructure.sqlalchemy_models import RentExpectationModel
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel
from app.modules.owner_management.infrastructure.sqlalchemy_models import OwnerConcernModel
from app.modules.tenants.infrastructure.sqlalchemy_models import TenantProfileModel
from app.modules.tasks.application.service import TaskCreateCommand
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel

class SQLiteOwnerConcernContext:
    def __init__(self, task_operations): self.task_operations=task_operations
    def context(self, connection: Any, *, owner_party_id, property_id, space_id, lease_id, tenant_party_id, raised_on, historical, concern_type):
        prop=connection.execute(select(PropertyModel.__table__).where(PropertyModel.id==property_id)).mappings().first()
        owner=connection.execute(select(PartyModel.__table__).where(PartyModel.id==owner_party_id)).mappings().first()
        if not prop: raise KeyError("Selected property was not found.")
        if not owner: raise KeyError("Selected owner party was not found.")
        if prop["status"] != "active": raise ValueError("Concerns require an active property.")
        zone=prop["time_zone"]
        if not raised_on: return {"time_zone": zone}
        owned=connection.execute(select(PropertyOwnershipModel.id).where(PropertyOwnershipModel.property_id==property_id,PropertyOwnershipModel.party_id==owner_party_id,PropertyOwnershipModel.owner_kind=="client_owner",PropertyOwnershipModel.starts_on<=raised_on,(PropertyOwnershipModel.ends_on.is_(None)|(PropertyOwnershipModel.ends_on>raised_on)))).first()
        if not owned: raise ValueError("Selected party was not a client owner on the raised local date.")
        if owner["archived_at"] is not None and not historical: raise ValueError("Current concerns require an active owner party.")
        space=None
        if space_id:
            space=connection.execute(select(SpaceModel.__table__).where(SpaceModel.id==space_id)).mappings().first()
            if not space: raise KeyError("Selected space was not found.")
            if space["property_id"]!=property_id: raise ValueError("Selected space does not belong to the property.")
            if space["status"]!="active": raise ValueError("Concerns require an active space.")
        lease=None
        if lease_id:
            lease=connection.execute(select(LeaseModel.__table__).where(LeaseModel.id==lease_id)).mappings().first()
            if not lease: raise KeyError("Selected lease was not found.")
            if not space or lease["space_id"]!=space_id: raise ValueError("Selected lease does not match the property and space.")
        tenant=None
        if tenant_party_id:
            tenant=connection.execute(select(PartyModel.__table__).where(PartyModel.id==tenant_party_id)).mappings().first()
            participant=connection.execute(select(LeaseParticipantModel.id).where(LeaseParticipantModel.lease_id==lease_id,LeaseParticipantModel.tenant_party_id==tenant_party_id,LeaseParticipantModel.starts_on<=raised_on,(LeaseParticipantModel.ends_on.is_(None)|(LeaseParticipantModel.ends_on>raised_on)))).first()
            if not tenant: raise KeyError("Selected tenant was not found.")
            if not participant: raise ValueError("Selected tenant was not an effective lease participant on the raised local date.")
        occupancy=availability=None
        if space_id and concern_type == "vacancy":
            occupancy=connection.execute(select(SpaceOccupancyPeriodModel.occupancy_status).where(SpaceOccupancyPeriodModel.space_id==space_id,SpaceOccupancyPeriodModel.record_state=="valid",SpaceOccupancyPeriodModel.starts_on<=raised_on,(SpaceOccupancyPeriodModel.ends_on.is_(None)|(SpaceOccupancyPeriodModel.ends_on>raised_on)))).scalar_one_or_none()
            availability=connection.execute(select(SpaceAvailabilityModel.__table__).where(SpaceAvailabilityModel.space_id==space_id)).mappings().first()
        return {"time_zone":zone,"owner_display_name":owner["display_name"],"property_display_name":prop["display_name"],"space_display_name":None if not space else space["display_name"],"lease_display":None if not lease else f"Lease {lease['contract_starts_on']}","tenant_display_name":None if not tenant else tenant["display_name"],"occupancy_status":occupancy,"availability_status":None if not availability else availability["availability_status"],"available_on":None if not availability else availability["available_on"]}
    def active_property(self, connection: Any, property_id: str) -> None:
        status=connection.execute(select(PropertyModel.status).where(PropertyModel.id==property_id)).scalar_one_or_none()
        if status is None: raise KeyError("Selected property was not found.")
        if status != "active": raise ValueError("Reopening requires an active property.")
    def originating_communication(self,connection, communication_id, owner_party_id, property_id):
        row=connection.execute(select(CommunicationModel.id).where(CommunicationModel.id==communication_id,CommunicationModel.status=="recorded",CommunicationModel.direction=="inbound")).first()
        reporter=connection.execute(select(CommunicationParticipantModel.id).where(CommunicationParticipantModel.communication_id==communication_id,CommunicationParticipantModel.party_id==owner_party_id,CommunicationParticipantModel.role.in_(("sender","reporter")))).first()
        return bool(row and reporter and property_id in self._linked_property_ids(connection,communication_id))
    def _linked_property_ids(self, connection, communication_id):
        links = select(CommunicationLinkModel.entity_type, CommunicationLinkModel.entity_id).where(CommunicationLinkModel.communication_id == communication_id).subquery()
        property_ids = union_all(
            select(links.c.entity_id.label("property_id")).where(links.c.entity_type == "property"),
            select(SpaceModel.property_id.label("property_id")).join(links, (links.c.entity_type == "space") & (links.c.entity_id == SpaceModel.id)),
            select(SpaceModel.property_id.label("property_id")).select_from(LeaseModel).join(SpaceModel, SpaceModel.id == LeaseModel.space_id).join(links, (links.c.entity_type == "lease") & (links.c.entity_id == LeaseModel.id)),
            select(SpaceModel.property_id.label("property_id")).select_from(RentExpectationModel).join(LeaseModel, LeaseModel.id == RentExpectationModel.lease_id).join(SpaceModel, SpaceModel.id == LeaseModel.space_id).join(links, (links.c.entity_type == "rent_expectation") & (links.c.entity_id == RentExpectationModel.id)),
            select(MaintenanceIssueModel.property_id.label("property_id")).join(links, (links.c.entity_type == "maintenance_issue") & (links.c.entity_id == MaintenanceIssueModel.id)),
            select(OwnerConcernModel.property_id.label("property_id")).join(links, (links.c.entity_type == "owner_concern") & (links.c.entity_id == OwnerConcernModel.id)),
        ).subquery()
        return set(connection.execute(select(property_ids.c.property_id).distinct()).scalars())
    def apply_concern_filters(self,connection,query,filters,concern_model):
        if filters.get("linked_communication") is not None:
            linked=select(CommunicationLinkModel.id).where(CommunicationLinkModel.entity_type=="owner_concern",CommunicationLinkModel.entity_id==concern_model.id).exists()
            query=query.where(linked if filters["linked_communication"] else ~linked)
        if filters.get("active_task") is not None:
            active=select(TaskModel.id).where(TaskModel.related_entity_type=="owner_concern",TaskModel.related_entity_id==concern_model.id,TaskModel.status.in_(("open","in_progress"))).exists()
            query=query.where(active if filters["active_task"] else ~active)
        return query
    def create_task(self,connection,values,correlation_id,record_change):
        task_values = {
            "title": values["title"], "notes": values.get("notes"), "priority": values.get("priority", "normal"),
            "dueAtUtc": values.get("due_at_utc"), "dueTimezone": values.get("due_timezone"),
            "isAllDay": values.get("is_all_day", False), "relatedEntityType": values["related_entity_type"],
            "relatedEntityId": values["related_entity_id"], "relatedLabel": values["related_label"],
        }
        return self.task_operations.create_task(connection,TaskCreateCommand.from_mapping(task_values),correlation_id=correlation_id,record_change=record_change)
    def task_views(self,connection,concern_ids):
        # Detail exposes a bounded recent summary; TASK-001 owns full history.
        task_rank=func.row_number().over(partition_by=TaskModel.related_entity_id,order_by=(TaskModel.updated_at_utc.desc(),TaskModel.id.desc())).label("task_rank")
        ranked=select(TaskModel.related_entity_id,TaskModel.id,TaskModel.status,TaskModel.title,TaskModel.due_at_utc,task_rank).where(TaskModel.related_entity_type=="owner_concern",TaskModel.related_entity_id.in_(concern_ids)).subquery()
        rows=connection.execute(select(ranked).where(ranked.c.task_rank<=20).order_by(ranked.c.related_entity_id,ranked.c.task_rank)).mappings()
        result={item:[] for item in concern_ids}
        for row in rows: result[row["related_entity_id"]].append({"id":row["id"],"status":row["status"],"title":row["title"],"dueAtUtc":row["due_at_utc"]})
        return result
    def active_task_counts(self, connection, concern_ids):
        rows = connection.execute(
            select(TaskModel.related_entity_id, func.count())
            .where(
                TaskModel.related_entity_type == "owner_concern",
                TaskModel.related_entity_id.in_(concern_ids),
                TaskModel.status.in_(("open", "in_progress")),
            )
            .group_by(TaskModel.related_entity_id)
        ).all()
        return {row[0]: row[1] for row in rows}
    def communication_counts(self,connection,concern_ids):
        rows=connection.execute(select(CommunicationLinkModel.entity_id,func.count()).where(CommunicationLinkModel.entity_type=="owner_concern",CommunicationLinkModel.entity_id.in_(concern_ids)).group_by(CommunicationLinkModel.entity_id)).all()
        return {row[0]:row[1] for row in rows}
    def detail_projection(self,connection,concern):
        predecessor=None; successor=None
        if concern.replaces_concern_id:
            predecessor=connection.execute(select(OwnerConcernModel.id,OwnerConcernModel.status,OwnerConcernModel.summary).where(OwnerConcernModel.id==concern.replaces_concern_id)).mappings().first()
        successor=connection.execute(select(OwnerConcernModel.id,OwnerConcernModel.status,OwnerConcernModel.summary).where(OwnerConcernModel.replaces_concern_id==concern.id)).mappings().first()
        source=None
        if concern.originating_communication_id:
            source=connection.execute(select(CommunicationModel.id,CommunicationModel.status,CommunicationModel.superseded_by_communication_id).where(CommunicationModel.id==concern.originating_communication_id)).mappings().first()
        rows=connection.execute(select(CommunicationModel.id,CommunicationModel.subject,CommunicationModel.occurred_at_utc,CommunicationModel.status).join(CommunicationLinkModel).where(CommunicationLinkModel.entity_type=="owner_concern",CommunicationLinkModel.entity_id==concern.id).order_by(CommunicationModel.occurred_at_utc.desc()).limit(20)).mappings()
        property_row = connection.execute(select(PropertyModel.__table__).where(PropertyModel.id == concern.property_id)).mappings().first()
        owner_row = connection.execute(select(PartyModel.__table__).where(PartyModel.id == concern.owner_party_id)).mappings().first()
        space_row = None if concern.space_id is None else connection.execute(select(SpaceModel.__table__).where(SpaceModel.id == concern.space_id)).mappings().first()
        lease_row = None if concern.lease_id is None else connection.execute(select(LeaseModel.__table__).where(LeaseModel.id == concern.lease_id)).mappings().first()
        tenant_row = None if concern.tenant_party_id is None else connection.execute(select(PartyModel.__table__).where(PartyModel.id == concern.tenant_party_id)).mappings().first()
        tenant_profile = None if concern.tenant_party_id is None else connection.execute(select(TenantProfileModel.__table__).where(TenantProfileModel.party_id == concern.tenant_party_id)).mappings().first()
        today = datetime.now(UTC).astimezone(ZoneInfo(property_row["time_zone"])).date().isoformat() if property_row else None
        participation = None
        if concern.lease_id and concern.tenant_party_id and today:
            participation = connection.execute(select(LeaseParticipantModel.id).where(LeaseParticipantModel.lease_id == concern.lease_id, LeaseParticipantModel.tenant_party_id == concern.tenant_party_id, LeaseParticipantModel.starts_on <= today, (LeaseParticipantModel.ends_on.is_(None) | (LeaseParticipantModel.ends_on > today)))).first() is not None
        occupancy = None
        availability = None
        if concern.space_id and today:
            occupancy = connection.execute(select(SpaceOccupancyPeriodModel.occupancy_status).where(SpaceOccupancyPeriodModel.space_id == concern.space_id, SpaceOccupancyPeriodModel.record_state == "valid", SpaceOccupancyPeriodModel.starts_on <= today, (SpaceOccupancyPeriodModel.ends_on.is_(None) | (SpaceOccupancyPeriodModel.ends_on > today)))).scalar_one_or_none()
            availability = connection.execute(select(SpaceAvailabilityModel.__table__).where(SpaceAvailabilityModel.space_id == concern.space_id)).mappings().first()
        return {"predecessor":None if predecessor is None else {"id":predecessor["id"],"status":predecessor["status"],"summary":predecessor["summary"]},"successor":None if successor is None else {"id":successor["id"],"status":successor["status"],"summary":successor["summary"]},"originatingCommunicationState":None if source is None else {"id":source["id"],"status":source["status"],"supersededByCommunicationId":source["superseded_by_communication_id"]},"currentSourceState":{"propertyStatus":None if property_row is None else property_row["status"],"propertyDisplayName":None if property_row is None else property_row["display_name"],"ownerArchived":owner_row is not None and owner_row["archived_at"] is not None,"ownerDisplayName":None if owner_row is None else owner_row["display_name"],"spaceStatus":None if space_row is None else space_row["status"],"spaceDisplayName":None if space_row is None else space_row["display_name"],"leaseStatus":None if lease_row is None else lease_row["status"],"leaseActualMoveOutOn":None if lease_row is None else lease_row["actual_move_out_on"],"tenantArchived":tenant_row is not None and tenant_row["archived_at"] is not None,"tenantDisplayName":None if tenant_row is None else tenant_row["display_name"],"tenantProfileActive":tenant_profile is not None and tenant_profile["archived_at"] is None,"tenantParticipationActive":participation,"occupancyStatus":occupancy,"availabilityStatus":None if availability is None else availability["availability_status"],"availableOn":None if availability is None else availability["available_on"]},"recentCommunications":[{"id":row["id"],"subject":row["subject"],"occurredAtUtc":row["occurred_at_utc"],"status":row["status"]} for row in rows]}
