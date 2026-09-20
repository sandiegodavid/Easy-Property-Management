"""SQLite persistence for MAINT-001.

Cross-module facts are provided by owner-owned, transaction-aware readers.  This
adapter deliberately knows only maintenance tables.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Callable
from sqlalchemy import and_, create_engine, desc, exists, select
from app.modules.audit.application.recorder import AuditRecorder
from app.platform.sqlite_engine import immediate_transaction
from .sqlalchemy_models import *

MODELS={"issue":MaintenanceIssueModel,"appointment":MaintenanceAppointmentModel,"cost":MaintenanceCostContextModel,"expense_link":MaintenanceIssueExpenseLinkModel,"follow_up_operation":MaintenanceFollowUpOperationModel}
class SQLiteMaintenanceTransaction:
    def __init__(self, connection, recorder, portfolio, finance, tasks, task_operations, files, parties=None, leases=None, communications=None):
        self.connection,self.recorder=connection,recorder
        self.portfolio,self.finance,self.tasks,self.task_operations,self.files=portfolio,finance,tasks,task_operations,files
        self.parties,self.leases,self.communications=parties,leases,communications
    def _get(self, kind, item_id):
        model=MODELS[kind]
        row=self.connection.execute(select(model).where(model.id==item_id)).mappings().first(); return dict(row) if row else None
    def _by_idempotency_key(self, kind, key):
        model=MODELS[kind]
        row=self.connection.execute(select(model).where(model.idempotency_key==key)).mappings().first()
        return None if row is None else dict(row)
    def _insert(self, kind, values): self.connection.execute(MODELS[kind].__table__.insert().values(**values))
    def _replace(self, kind, item_id, values): self.connection.execute(MODELS[kind].__table__.update().where(MODELS[kind].id==item_id).values(**values))
    def issue(self, item_id): return self._get("issue", item_id)
    def appointment(self, item_id): return self._get("appointment", item_id)
    def cost_context(self, item_id): return self._get("cost", item_id)
    def expense_link(self, item_id): return self._get("expense_link", item_id)
    def issue_by_key(self, key): return self._by_idempotency_key("issue", key)
    def appointment_by_key(self, key): return self._by_idempotency_key("appointment", key)
    def cost_context_by_key(self, key): return self._by_idempotency_key("cost", key)
    def expense_link_by_key(self, key): return self._by_idempotency_key("expense_link", key)
    def follow_up_by_key(self, key): return self._by_idempotency_key("follow_up_operation", key)
    def insert_issue(self, values): self._insert("issue", values)
    def replace_issue(self, item_id, values): self._replace("issue", item_id, values)
    def insert_appointment(self, values): self._insert("appointment", values)
    def replace_appointment(self, item_id, values): self._replace("appointment", item_id, values)
    def insert_cost_context(self, values): self._insert("cost", values)
    def replace_cost_context(self, item_id, values): self._replace("cost", item_id, values)
    def insert_expense_link(self, values): self._insert("expense_link", values)
    def replace_expense_link(self, item_id, values): self._replace("expense_link", item_id, values)
    def insert_follow_up_operation(self, values): self._insert("follow_up_operation", values)
    def appointments_for_issue(self, issue_id):
        return [dict(row) for row in self.connection.execute(select(MaintenanceAppointmentModel).where(MaintenanceAppointmentModel.issue_id==issue_id)).mappings()]
    def issue_context(self, property_id, space_id):
        context=self.portfolio.context_for_property_space(self.connection,property_id,space_id)
        if context is None:return None
        return {"property":{"id":context["property_id"],"display_name":context["property_display_name"],"status":context["property_status"],"time_zone":context["time_zone"]},"space":None if space_id is None else {"id":context["space_id"],"display_name":context["space_display_name"],"status":context["space_status"]}}
    def reporter_party(self, party_id): return self.parties.party(self.connection, party_id) if self.parties else None
    def reporter_party_states(self, party_ids):
        if not party_ids or not self.parties:return {}
        return {party_id: ("archived" if party.archived_at else "active") for party_id,party in self.parties.party_map(self.connection, party_ids).items()}
    def reporter_is_owner(self, property_id, party_id, on):
        subjects=self.portfolio.ownership_subject_kinds_on(self.connection, property_id, on)
        return (("local_operator", None) in subjects) if party_id is None else (("client_owner", party_id) in subjects)
    def reporter_is_tenant(self, property_id, space_id, party_id, on):
        return bool(self.leases and self.leases.participant_active_for_property(self.connection, party_id, property_id, space_id, on))
    def expense(self, expense_id):
        return self.finance.expense_context(self.connection, expense_id)
    def active_expense_link(self, expense_id):
        return self.connection.execute(
            select(MaintenanceIssueExpenseLinkModel.id).where(
                MaintenanceIssueExpenseLinkModel.expense_id == expense_id,
                MaintenanceIssueExpenseLinkModel.archived_at.is_(None),
            )
        ).first() is not None
    def issues_page(self, *, property_id=None, space_id=None, category=None, priority=None, status=None, reporter_role=None, reporter_party_id=None, reporter_subject_kind=None, reported_from=None, reported_to=None, appointment_from=None, appointment_to=None, has_evidence=None, has_linked_expense=None, has_active_task=None, cursor=None, limit=101):
        query=select(MaintenanceIssueModel)
        conditions=[]
        for column,value in ((MaintenanceIssueModel.property_id,property_id),(MaintenanceIssueModel.space_id,space_id),(MaintenanceIssueModel.category,category),(MaintenanceIssueModel.priority,priority),(MaintenanceIssueModel.status,status),(MaintenanceIssueModel.reporter_role,reporter_role),(MaintenanceIssueModel.reporter_party_id,reporter_party_id),(MaintenanceIssueModel.reporter_subject_kind,reporter_subject_kind)):
            if value is not None:conditions.append(column==value)
        if reported_from: conditions.append(MaintenanceIssueModel.reported_at_utc>=reported_from)
        if reported_to: conditions.append(MaintenanceIssueModel.reported_at_utc<=reported_to)
        if appointment_from or appointment_to:
            appointment_conditions=[MaintenanceAppointmentModel.issue_id==MaintenanceIssueModel.id]
            if appointment_from: appointment_conditions.append(MaintenanceAppointmentModel.starts_at_utc>=appointment_from)
            if appointment_to: appointment_conditions.append(MaintenanceAppointmentModel.starts_at_utc<=appointment_to)
            conditions.append(exists(select(MaintenanceAppointmentModel.id).where(*appointment_conditions)))
        if has_linked_expense is not None:
            linked=exists(select(MaintenanceIssueExpenseLinkModel.id).where(MaintenanceIssueExpenseLinkModel.issue_id==MaintenanceIssueModel.id,MaintenanceIssueExpenseLinkModel.archived_at.is_(None)))
            conditions.append(linked if has_linked_expense else ~linked)
        if cursor:
            priority_value,reported,item_id=cursor
            # Cursor retains the exact stable tuple used by this ordered projection.
            rank={"urgent":4,"high":3,"normal":2,"low":1}[priority_value]
            rank_expr=__import__("sqlalchemy").case({"urgent":4,"high":3,"normal":2,"low":1},value=MaintenanceIssueModel.priority)
            conditions.append((rank_expr<rank)|and_(rank_expr==rank,MaintenanceIssueModel.reported_at_utc<reported)|and_(rank_expr==rank,MaintenanceIssueModel.reported_at_utc==reported,MaintenanceIssueModel.id<item_id))
        rank_expr=__import__("sqlalchemy").case({"urgent":4,"high":3,"normal":2,"low":1},value=MaintenanceIssueModel.priority)
        # Cross-module predicates are evaluated in bounded database chunks.
        # A selective filter never materializes every file/task identifier in
        # the workspace, and an exhausted scan returns a resumable cursor.
        dynamic_filter = has_evidence is not None or has_active_task is not None
        chunk_size = min(max(limit * 2, 100), 500)
        max_scanned = 2_000
        scanned = 0
        scan_cursor = cursor
        accepted = []
        exhausted = False

        def candidate_rows(after):
            candidate_conditions = list(conditions)
            if after:
                priority_value, reported, item_id = after
                rank = {"urgent": 4, "high": 3, "normal": 2, "low": 1}[priority_value]
                candidate_conditions.append(
                    (rank_expr < rank)
                    | and_(rank_expr == rank, MaintenanceIssueModel.reported_at_utc < reported)
                    | and_(
                        rank_expr == rank,
                        MaintenanceIssueModel.reported_at_utc == reported,
                        MaintenanceIssueModel.id < item_id,
                    )
                )
            return [
                dict(row)
                for row in self.connection.execute(
                    query.where(*candidate_conditions)
                    .order_by(desc(rank_expr), desc(MaintenanceIssueModel.reported_at_utc), desc(MaintenanceIssueModel.id))
                    .limit(chunk_size if dynamic_filter else limit)
                ).mappings()
            ]

        while True:
            rows = candidate_rows(scan_cursor)
            if not rows:
                exhausted = True
                break
            candidate_count = len(rows)
            scanned += len(rows)
            last = rows[-1]
            scan_cursor = (last["priority"], last["reported_at_utc"], last["id"])
            identifiers = [row["id"] for row in rows]
            if has_evidence is not None and self.files:
                evidence_ids = self.files.active_linked_entity_ids(self.connection, "maintenance_issue", identifiers)
                appointments = [
                    dict(row)
                    for row in self.connection.execute(
                        select(MaintenanceAppointmentModel.id, MaintenanceAppointmentModel.issue_id).where(
                            MaintenanceAppointmentModel.issue_id.in_(identifiers)
                        )
                    ).mappings()
                ]
                costs = [
                    dict(row)
                    for row in self.connection.execute(
                        select(MaintenanceCostContextModel.id, MaintenanceCostContextModel.issue_id).where(
                            MaintenanceCostContextModel.issue_id.in_(identifiers)
                        )
                    ).mappings()
                ]
                appointment_by_id = {item["id"]: item["issue_id"] for item in appointments}
                cost_by_id = {item["id"]: item["issue_id"] for item in costs}
                evidence_ids.update(
                    appointment_by_id[item]
                    for item in self.files.active_linked_entity_ids(
                        self.connection, "maintenance_appointment", list(appointment_by_id)
                    )
                    if item in appointment_by_id
                )
                evidence_ids.update(
                    cost_by_id[item]
                    for item in self.files.active_linked_entity_ids(
                        self.connection, "maintenance_cost_context", list(cost_by_id)
                    )
                    if item in cost_by_id
                )
                rows = [row for row in rows if (row["id"] in evidence_ids) == has_evidence]
            if has_active_task is not None:
                active_ids = self.tasks.active_related_entity_ids(
                    self.connection, "maintenance_issue", [row["id"] for row in rows]
                )
                rows = [row for row in rows if (row["id"] in active_ids) == has_active_task]
            accepted.extend(rows)
            if not dynamic_filter or len(accepted) >= limit or candidate_count < chunk_size or scanned >= max_scanned:
                exhausted = not dynamic_filter or candidate_count < chunk_size
                break

        # If the bounded dynamic scan stopped before source exhaustion, callers
        # resume from the last scanned issue even when the page is empty.
        resume = None if exhausted or len(accepted) >= limit else scan_cursor
        return accepted[:limit], resume
    def task(self, task_id):
        return self.tasks.task(self.connection, task_id)
    def tasks_for_issues(self, issue_ids):
        return self.tasks.tasks_for_related_entities(self.connection,"maintenance_issue",list(issue_ids))
    def create_task(self, command, *, correlation_id):
        return self.task_operations.create_task(self.connection,command,correlation_id=correlation_id,record_change=self.record_change)
    def projection(self, issue_ids, *, include_detail=True):
        """Return a fixed-query MAINT-001 read projection for one page/detail."""
        issue_ids=list(dict.fromkeys(issue_ids))
        if not issue_ids:return {}
        issues={row["id"]:dict(row) for row in self.connection.execute(select(MaintenanceIssueModel).where(MaintenanceIssueModel.id.in_(issue_ids))).mappings()}
        appointments={issue_id:[] for issue_id in issues}; costs={issue_id:[] for issue_id in issues}; links={issue_id:[] for issue_id in issues}
        for row in self.connection.execute(select(MaintenanceAppointmentModel).where(MaintenanceAppointmentModel.issue_id.in_(issue_ids)).order_by(MaintenanceAppointmentModel.starts_at_utc.desc(),MaintenanceAppointmentModel.id.desc())).mappings(): appointments[row["issue_id"]].append(dict(row))
        for row in self.connection.execute(select(MaintenanceCostContextModel).where(MaintenanceCostContextModel.issue_id.in_(issue_ids)).order_by(MaintenanceCostContextModel.created_at.desc(),MaintenanceCostContextModel.id.desc())).mappings(): costs[row["issue_id"]].append(dict(row))
        for row in self.connection.execute(select(MaintenanceIssueExpenseLinkModel).where(MaintenanceIssueExpenseLinkModel.issue_id.in_(issue_ids)).order_by(MaintenanceIssueExpenseLinkModel.created_at.desc(),MaintenanceIssueExpenseLinkModel.id.desc())).mappings(): links[row["issue_id"]].append(dict(row))
        contexts=self.portfolio.contexts_for_property_spaces(self.connection,[(row["property_id"],row["space_id"]) for row in issues.values()])
        tasks=self.tasks.tasks_for_related_entities(self.connection,"maintenance_issue",issue_ids)
        expenses=self.finance.expense_contexts(self.connection,[row["expense_id"] for values in links.values() for row in values])
        issue_files=self.files.links_for_entities(self.connection,"maintenance_issue",issue_ids) if self.files else {}
        appointment_files=self.files.links_for_entities(self.connection,"maintenance_appointment",[row["id"] for values in appointments.values() for row in values]) if self.files else {}
        cost_files=self.files.links_for_entities(self.connection,"maintenance_cost_context",[row["id"] for values in costs.values() for row in values]) if self.files else {}
        party_states=(
            self.reporter_party_states([row["reporter_party_id"] for row in issues.values() if row["reporter_party_id"]])
            if include_detail else {}
        )
        communications=(
            self.communications.summaries_for_entities(self.connection,"maintenance_issue",issue_ids)
            if include_detail and self.communications else {}
        )
        return {issue_id:{"issue":issue,"appointments":appointments[issue_id],"costs":costs[issue_id],"links":links[issue_id],"context":contexts.get((issue["property_id"],issue["space_id"])),"tasks":tasks.get(issue_id,[]),"expenses":expenses,"files":issue_files.get(issue_id,[]),"appointment_files":appointment_files,"cost_files":cost_files,"party_states":party_states,"communications":communications.get(issue_id,[])} for issue_id,issue in issues.items()}
    def record_change(self, **kwargs): self.recorder.record_change(self.connection.connection.driver_connection, **kwargs)

class SQLiteMaintenanceUnitOfWork:
    def __init__(self,database,recorder:AuditRecorder,portfolio,finance,tasks,task_operations,files=None,parties=None,leases=None,communications=None):
        self.database,self.recorder=database,recorder
        self.portfolio,self.finance,self.tasks,self.task_operations,self.files=portfolio,finance,tasks,task_operations,files
        self.parties,self.leases,self.communications=parties,leases,communications
    def write(self, operation):
        engine=create_engine(f"sqlite:///{self.database}")
        try:
            with immediate_transaction(engine) as connection:return operation(SQLiteMaintenanceTransaction(connection,self.recorder,self.portfolio,self.finance,self.tasks,self.task_operations,self.files,self.parties,self.leases,self.communications))
        finally:engine.dispose()
    def read(self, operation):
        engine=create_engine(f"sqlite:///{self.database}")
        try:
            with engine.connect() as connection:return operation(SQLiteMaintenanceTransaction(connection,self.recorder,self.portfolio,self.finance,self.tasks,self.task_operations,self.files,self.parties,self.leases,self.communications))
        finally:engine.dispose()
