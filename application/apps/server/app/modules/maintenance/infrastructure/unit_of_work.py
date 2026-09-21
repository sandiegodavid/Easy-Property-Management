"""SQLite persistence for MAINT-001.

Cross-module facts are provided by owner-owned, transaction-aware readers.  This
adapter deliberately knows only maintenance tables.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Callable
from zoneinfo import ZoneInfo
from sqlalchemy import and_, case, create_engine, desc, exists, func, select
from sqlalchemy.exc import IntegrityError
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.maintenance.domain.models import MaintenanceConflictError
from app.platform.sqlite_engine import immediate_transaction
from .sqlalchemy_models import *

MODELS={"issue":MaintenanceIssueModel,"appointment":MaintenanceAppointmentModel,"cost":MaintenanceCostContextModel,"expense_link":MaintenanceIssueExpenseLinkModel,"follow_up_operation":MaintenanceFollowUpOperationModel,"quote":MaintenanceQuoteModel,"assignment":MaintenanceAssignmentModel,"work_journal":MaintenanceWorkJournalEntryModel}
class SQLiteMaintenanceTransaction:
    def __init__(self, connection, recorder, portfolio, finance, tasks, task_operations, files, parties=None, leases=None, communications=None, providers=None):
        self.connection,self.recorder=connection,recorder
        self.portfolio,self.finance,self.tasks,self.task_operations,self.files=portfolio,finance,tasks,task_operations,files
        self.parties,self.leases,self.communications,self.providers=parties,leases,communications,providers
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
    def quote(self, item_id): return self._get("quote", item_id)
    def assignment(self, item_id): return self._get("assignment", item_id)
    def work_journal(self, item_id): return self._get("work_journal", item_id)
    def issue_by_key(self, key): return self._by_idempotency_key("issue", key)
    def appointment_by_key(self, key): return self._by_idempotency_key("appointment", key)
    def cost_context_by_key(self, key): return self._by_idempotency_key("cost", key)
    def expense_link_by_key(self, key): return self._by_idempotency_key("expense_link", key)
    def quote_by_key(self, key): return self._by_idempotency_key("quote", key)
    def quote_replacement(self, quote_id):
        row=self.connection.execute(select(MaintenanceQuoteModel).where(MaintenanceQuoteModel.replaces_quote_id==quote_id)).mappings().first()
        return None if row is None else dict(row)
    def assignment_by_key(self, key): return self._by_idempotency_key("assignment", key)
    def work_journal_by_key(self, key): return self._by_idempotency_key("work_journal", key)
    def work_journal_correction(self, entry_id):
        row=self.connection.execute(select(MaintenanceWorkJournalEntryModel).where(MaintenanceWorkJournalEntryModel.corrects_entry_id==entry_id)).mappings().first()
        return None if row is None else dict(row)
    def follow_up_by_key(self, key): return self._by_idempotency_key("follow_up_operation", key)
    def insert_issue(self, values): self._insert("issue", values)
    def replace_issue(self, item_id, values): self._replace("issue", item_id, values)
    def insert_appointment(self, values): self._insert("appointment", values)
    def replace_appointment(self, item_id, values): self._replace("appointment", item_id, values)
    def insert_cost_context(self, values): self._insert("cost", values)
    def replace_cost_context(self, item_id, values): self._replace("cost", item_id, values)
    def insert_expense_link(self, values): self._insert("expense_link", values)
    def replace_expense_link(self, item_id, values): self._replace("expense_link", item_id, values)
    def insert_quote(self, values):
        try:self._insert("quote", values)
        except IntegrityError as error:
            if "maintenance_quotes.replaces_quote_id" in str(error.orig): raise MaintenanceConflictError("Quote already has a replacement.","quote_replaced") from error
            raise
    def replace_quote(self, item_id, values): self._replace("quote", item_id, values)
    def insert_assignment(self, values): self._insert("assignment", values)
    def replace_assignment(self, item_id, values): self._replace("assignment", item_id, values)
    def insert_work_journal(self, values):
        try:self._insert("work_journal", values)
        except IntegrityError as error:
            if "corrects_entry_id" in str(error.orig): raise MaintenanceConflictError("Journal entry already has a correction.","correction_exists") from error
            raise
    def insert_follow_up_operation(self, values): self._insert("follow_up_operation", values)
    def appointments_for_issue(self, issue_id):
        return [dict(row) for row in self.connection.execute(select(MaintenanceAppointmentModel).where(MaintenanceAppointmentModel.issue_id==issue_id)).mappings()]
    def current_assignment(self, issue_id):
        row=self.connection.execute(select(MaintenanceAssignmentModel).where(MaintenanceAssignmentModel.issue_id==issue_id,MaintenanceAssignmentModel.ended_at.is_(None))).mappings().first()
        return None if row is None else dict(row)
    def issue_context(self, property_id, space_id):
        context=self.portfolio.context_for_property_space(self.connection,property_id,space_id)
        if context is None:return None
        return {"property":{"id":context["property_id"],"display_name":context["property_display_name"],"status":context["property_status"],"time_zone":context["time_zone"]},"space":None if space_id is None else {"id":context["space_id"],"display_name":context["space_display_name"],"status":context["space_status"]}}
    def reporter_party(self, party_id): return self.parties.party(self.connection, party_id) if self.parties else None
    def reporter_party_states(self, party_ids):
        if not party_ids or not self.parties:return {}
        return {party_id: ("archived" if party.archived_at else "active") for party_id,party in self.parties.party_map(self.connection, party_ids).items()}
    def provider_context(self, party_id):
        if not self.parties or not self.providers: return None
        party=self.parties.party(self.connection, party_id)
        profile=self.providers.profile_context(self.connection, party_id)
        if party is None or profile is None:return None
        return {"display_name":party.display_name,"party_archived_at":party.archived_at,**dict(profile)}
    def provider_states(self, party_ids):
        party_ids=list(dict.fromkeys(party_ids))
        if not party_ids or not self.parties or not self.providers:return {}
        parties=self.parties.party_map(self.connection,party_ids)
        profiles=self.providers.profile_contexts(self.connection,party_ids)
        return {party_id:{"currentPartyState":"archived" if party.archived_at else "active","currentProviderProfileState":None if party_id not in profiles else ("archived" if profiles[party_id]["archived_at"] else "active")} for party_id,party in parties.items()}
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
    def work_journal_page(self, *, issue_id, provider_party_id, cursor, limit, descending):
        # Both issue and provider journals expose the same immutable context.
        # Keep the joins outer: operator observations legitimately have no
        # assignment or quote.
        query=(
            select(MaintenanceWorkJournalEntryModel)
            .join(MaintenanceIssueModel,MaintenanceIssueModel.id==MaintenanceWorkJournalEntryModel.issue_id)
            .outerjoin(MaintenanceAssignmentModel,MaintenanceAssignmentModel.id==MaintenanceWorkJournalEntryModel.assignment_id)
            .outerjoin(MaintenanceQuoteModel,MaintenanceQuoteModel.id==MaintenanceAssignmentModel.quote_id)
            .add_columns(
                MaintenanceIssueModel.summary.label("issue_summary"),
                MaintenanceIssueModel.property_id.label("property_id"),
                MaintenanceIssueModel.space_id.label("space_id"),
                MaintenanceAssignmentModel.provider_party_id.label("provider_party_id"),
                MaintenanceAssignmentModel.provider_display_name_snapshot.label("provider_display_name_snapshot"),
                MaintenanceAssignmentModel.assigned_at.label("assigned_at"),
                MaintenanceAssignmentModel.quote_id.label("quote_id"),
                MaintenanceQuoteModel.earliest_work_start_on.label("quoted_earliest_work_start_on"),
                MaintenanceQuoteModel.estimated_work_finish_on.label("quoted_estimated_work_finish_on"),
            )
        )
        if provider_party_id is not None:
            query=query.where(MaintenanceAssignmentModel.provider_party_id==provider_party_id)
        if issue_id is not None: query=query.where(MaintenanceWorkJournalEntryModel.issue_id==issue_id)
        if cursor:
            occurred, recorded, item_id=cursor
            if descending:
                query=query.where((MaintenanceWorkJournalEntryModel.occurred_at_utc<occurred)|and_(MaintenanceWorkJournalEntryModel.occurred_at_utc==occurred,MaintenanceWorkJournalEntryModel.recorded_at_utc<recorded)|and_(MaintenanceWorkJournalEntryModel.occurred_at_utc==occurred,MaintenanceWorkJournalEntryModel.recorded_at_utc==recorded,MaintenanceWorkJournalEntryModel.id<item_id))
            else:
                query=query.where((MaintenanceWorkJournalEntryModel.occurred_at_utc>occurred)|and_(MaintenanceWorkJournalEntryModel.occurred_at_utc==occurred,MaintenanceWorkJournalEntryModel.recorded_at_utc>recorded)|and_(MaintenanceWorkJournalEntryModel.occurred_at_utc==occurred,MaintenanceWorkJournalEntryModel.recorded_at_utc==recorded,MaintenanceWorkJournalEntryModel.id>item_id))
        ordering=(desc(MaintenanceWorkJournalEntryModel.occurred_at_utc),desc(MaintenanceWorkJournalEntryModel.recorded_at_utc),desc(MaintenanceWorkJournalEntryModel.id)) if descending else (MaintenanceWorkJournalEntryModel.occurred_at_utc,MaintenanceWorkJournalEntryModel.recorded_at_utc,MaintenanceWorkJournalEntryModel.id)
        return [dict(row) for row in self.connection.execute(query.order_by(*ordering).limit(limit)).mappings()]
    def work_journal_corrected_ids(self, entry_ids):
        if not entry_ids:return set()
        return set(self.connection.execute(select(MaintenanceWorkJournalEntryModel.corrects_entry_id).where(MaintenanceWorkJournalEntryModel.corrects_entry_id.in_(entry_ids))).scalars())
    def work_journal_files(self, entry_ids):
        if not entry_ids or not self.files:
            return {}
        return self.files.links_for_entities(self.connection, "maintenance_work_journal_entry", entry_ids)
    def work_journal_assignment_start_seconds(self, assignment_ids):
        """Return the earliest effective work-start duration for each assignment."""
        assignment_ids=list(dict.fromkeys(item for item in assignment_ids if item is not None))
        if not assignment_ids:
            return {}
        correction=MaintenanceWorkJournalEntryModel.__table__.alias("journal_correction")
        effective=~exists(select(correction.c.id).where(correction.c.corrects_entry_id==MaintenanceWorkJournalEntryModel.id))
        effective_kind=case(
            (MaintenanceWorkJournalEntryModel.entry_kind=="correction", MaintenanceWorkJournalEntryModel.corrected_entry_kind),
            else_=MaintenanceWorkJournalEntryModel.entry_kind,
        )
        rows=self.connection.execute(
            select(
                MaintenanceWorkJournalEntryModel.assignment_id,
                MaintenanceAssignmentModel.assigned_at,
                func.min(MaintenanceWorkJournalEntryModel.occurred_at_utc).label("started_at"),
            ).join(MaintenanceAssignmentModel, MaintenanceAssignmentModel.id==MaintenanceWorkJournalEntryModel.assignment_id)
            .where(MaintenanceWorkJournalEntryModel.assignment_id.in_(assignment_ids), effective, effective_kind=="work_started")
            .group_by(MaintenanceWorkJournalEntryModel.assignment_id, MaintenanceAssignmentModel.assigned_at)
        ).mappings()
        result={}
        for row in rows:
            started=datetime.fromisoformat(row["started_at"])
            assigned=datetime.fromisoformat(row["assigned_at"])
            result[row["assignment_id"]]=None if started < assigned else int((started-assigned).total_seconds())
        return result
    def issues_page(self, *, property_id=None, space_id=None, category=None, priority=None, status=None, reporter_role=None, reporter_party_id=None, reporter_subject_kind=None, provider_party_id=None, has_active_quote=None, has_current_assignment=None, reported_from=None, reported_to=None, appointment_from=None,appointment_to=None,has_evidence=None,has_linked_expense=None,has_active_task=None,cursor=None,limit=101):
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
        if provider_party_id is not None:
            conditions.append(exists(select(MaintenanceAssignmentModel.id).where(MaintenanceAssignmentModel.issue_id==MaintenanceIssueModel.id,MaintenanceAssignmentModel.provider_party_id==provider_party_id)))
        if has_active_quote is not None:
            quote=exists(select(MaintenanceQuoteModel.id).where(MaintenanceQuoteModel.issue_id==MaintenanceIssueModel.id,MaintenanceQuoteModel.withdrawn_at.is_(None)))
            conditions.append(quote if has_active_quote else ~quote)
        if has_current_assignment is not None:
            assignment=exists(select(MaintenanceAssignmentModel.id).where(MaintenanceAssignmentModel.issue_id==MaintenanceIssueModel.id,MaintenanceAssignmentModel.ended_at.is_(None)))
            conditions.append(assignment if has_current_assignment else ~assignment)
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
        appointments={issue_id:[] for issue_id in issues}; costs={issue_id:[] for issue_id in issues}; links={issue_id:[] for issue_id in issues}; quotes={issue_id:[] for issue_id in issues}; assignments={issue_id:[] for issue_id in issues}; journals={issue_id:[] for issue_id in issues}; journal_counts={issue_id:0 for issue_id in issues}
        appointment_columns=(MaintenanceAppointmentModel,) if include_detail else (MaintenanceAppointmentModel.id,MaintenanceAppointmentModel.issue_id,MaintenanceAppointmentModel.starts_at_utc,MaintenanceAppointmentModel.ends_at_utc,MaintenanceAppointmentModel.status)
        cost_columns=(MaintenanceCostContextModel,) if include_detail else (MaintenanceCostContextModel.id,MaintenanceCostContextModel.issue_id)
        link_columns=(MaintenanceIssueExpenseLinkModel,) if include_detail else (MaintenanceIssueExpenseLinkModel.issue_id,MaintenanceIssueExpenseLinkModel.archived_at)
        for row in self.connection.execute(select(*appointment_columns).where(MaintenanceAppointmentModel.issue_id.in_(issue_ids)).order_by(MaintenanceAppointmentModel.starts_at_utc.desc(),MaintenanceAppointmentModel.id.desc())).mappings(): appointments[row["issue_id"]].append(dict(row))
        for row in self.connection.execute(select(*cost_columns).where(MaintenanceCostContextModel.issue_id.in_(issue_ids)).order_by(MaintenanceCostContextModel.created_at.desc(),MaintenanceCostContextModel.id.desc())).mappings(): costs[row["issue_id"]].append(dict(row))
        for row in self.connection.execute(select(*link_columns).where(MaintenanceIssueExpenseLinkModel.issue_id.in_(issue_ids)).order_by(MaintenanceIssueExpenseLinkModel.created_at.desc(),MaintenanceIssueExpenseLinkModel.id.desc())).mappings(): links[row["issue_id"]].append(dict(row))
        quote_columns=(MaintenanceQuoteModel.id,MaintenanceQuoteModel.issue_id,MaintenanceQuoteModel.withdrawn_at) if not include_detail else (MaintenanceQuoteModel,)
        assignment_columns=(MaintenanceAssignmentModel.issue_id,MaintenanceAssignmentModel.provider_display_name_snapshot,MaintenanceAssignmentModel.ended_at) if not include_detail else (MaintenanceAssignmentModel,)
        for row in self.connection.execute(select(*quote_columns).where(MaintenanceQuoteModel.issue_id.in_(issue_ids))).mappings(): quotes[row["issue_id"]].append(dict(row))
        for row in self.connection.execute(select(*assignment_columns).where(MaintenanceAssignmentModel.issue_id.in_(issue_ids))).mappings(): assignments[row["issue_id"]].append(dict(row))
        journal_summaries={issue_id:{"actual_work_started":None,"actual_work_completed":None} for issue_id in issues}
        journal_evidence_counts={issue_id:0 for issue_id in issues}
        if include_detail:
            # A windowed query retains only the ten newest entries per issue;
            # detail therefore never pulls an unbounded history collection.
            ranked=select(
                MaintenanceWorkJournalEntryModel,
                func.row_number().over(
                    partition_by=MaintenanceWorkJournalEntryModel.issue_id,
                    order_by=(MaintenanceWorkJournalEntryModel.occurred_at_utc.desc(),MaintenanceWorkJournalEntryModel.recorded_at_utc.desc(),MaintenanceWorkJournalEntryModel.id.desc()),
                ).label("rank"),
            ).where(MaintenanceWorkJournalEntryModel.issue_id.in_(issue_ids)).subquery()
            for row in self.connection.execute(select(ranked).where(ranked.c.rank<=10)).mappings():
                item={key:value for key,value in row.items() if key!="rank"}
                journals[item["issue_id"]].append(item)
            for issue_id in journals:
                journals[issue_id].sort(key=lambda item:(item["occurred_at_utc"],item["recorded_at_utc"],item["id"]),reverse=True)
            for row in self.connection.execute(
                select(MaintenanceWorkJournalEntryModel.issue_id,func.count().label("count"))
                .where(MaintenanceWorkJournalEntryModel.issue_id.in_(issue_ids))
                .group_by(MaintenanceWorkJournalEntryModel.issue_id)
            ).mappings(): journal_counts[row["issue_id"]]=row["count"]
            child=MaintenanceWorkJournalEntryModel.__table__.alias("journal_correction")
            effective=~exists(select(child.c.id).where(child.c.corrects_entry_id==MaintenanceWorkJournalEntryModel.id))
            kind=case((MaintenanceWorkJournalEntryModel.entry_kind=="correction",MaintenanceWorkJournalEntryModel.corrected_entry_kind),else_=MaintenanceWorkJournalEntryModel.entry_kind)
            effective_rows=self.connection.execute(
                select(MaintenanceWorkJournalEntryModel,kind.label("effective_kind"))
                .where(MaintenanceWorkJournalEntryModel.issue_id.in_(issue_ids),effective)
                .order_by(MaintenanceWorkJournalEntryModel.issue_id,MaintenanceWorkJournalEntryModel.occurred_at_utc,MaintenanceWorkJournalEntryModel.recorded_at_utc,MaintenanceWorkJournalEntryModel.id)
            ).mappings()
            for row in effective_rows:
                item=dict(row); summary=journal_summaries[item["issue_id"]]
                if item["effective_kind"]=="work_started" and summary["actual_work_started"] is None:
                    summary["actual_work_started"]=item
                if item["effective_kind"]=="work_completed" and item["operator_verified"] and item["outcome_status"]=="completed" and summary["actual_work_completed"] is None:
                    summary["actual_work_completed"]=item
            if self.files:
                journal_owner = {
                    row["id"]: row["issue_id"]
                    for row in self.connection.execute(
                        select(MaintenanceWorkJournalEntryModel.id, MaintenanceWorkJournalEntryModel.issue_id)
                        .where(MaintenanceWorkJournalEntryModel.issue_id.in_(issue_ids))
                    ).mappings()
                }
                active = self.files.active_link_counts_for_entities(
                    self.connection, "maintenance_work_journal_entry", list(journal_owner),
                )
                for entry_id, count in active.items():
                    journal_evidence_counts[journal_owner[entry_id]] += count
        contexts=self.portfolio.contexts_for_property_spaces(self.connection,[(row["property_id"],row["space_id"]) for row in issues.values()])
        if include_detail:
            for issue_id, values in quotes.items():
                today=datetime.now(ZoneInfo(contexts[(issues[issue_id]["property_id"],issues[issue_id]["space_id"])]["time_zone"])).date().isoformat()
                values.sort(key=lambda item:(item["withdrawn_at"] is not None,item["valid_through"] is not None and item["valid_through"] < today,item["amount_minor"],-date.fromisoformat(item["received_on"]).toordinal(),item["id"]))
            for values in assignments.values(): values.sort(key=lambda item:(item["assigned_at"],item["id"]),reverse=True)
        tasks=self.tasks.tasks_for_related_entities(self.connection,"maintenance_issue",issue_ids)
        expenses=self.finance.expense_contexts(self.connection,[row["expense_id"] for values in links.values() for row in values]) if include_detail else {}
        issue_files=self.files.links_for_entities(self.connection,"maintenance_issue",issue_ids) if include_detail and self.files else {}
        appointment_files=self.files.links_for_entities(self.connection,"maintenance_appointment",[row["id"] for values in appointments.values() for row in values]) if include_detail and self.files else {}
        cost_files=self.files.links_for_entities(self.connection,"maintenance_cost_context",[row["id"] for values in costs.values() for row in values]) if include_detail and self.files else {}
        quote_files=self.files.links_for_entities(self.connection,"maintenance_quote",[row["id"] for values in quotes.values() for row in values]) if include_detail and self.files else {}
        assignment_files=self.files.links_for_entities(self.connection,"maintenance_assignment",[row["id"] for values in assignments.values() for row in values]) if include_detail and self.files else {}
        journal_files=self.files.links_for_entities(self.connection,"maintenance_work_journal_entry",[row["id"] for values in journals.values() for row in values]) if include_detail and self.files else {}
        party_states=(
            self.reporter_party_states([row["reporter_party_id"] for row in issues.values() if row["reporter_party_id"]])
            if include_detail else {}
        )
        provider_states=self.provider_states([row["provider_party_id"] for values in quotes.values() for row in values]+[row["provider_party_id"] for values in assignments.values() for row in values]) if include_detail else {}
        evidence_counts={} if include_detail or not self.files else self.files.active_link_counts_for_entity_groups(self.connection,{"maintenance_issue":issue_ids,"maintenance_appointment":[row["id"] for values in appointments.values() for row in values],"maintenance_cost_context":[row["id"] for values in costs.values() for row in values]})
        communications=(
            self.communications.summaries_for_entities(self.connection,"maintenance_issue",issue_ids)
            if include_detail and self.communications else {}
        )
        corrected_ids=self.work_journal_corrected_ids([row["id"] for values in journals.values() for row in values]) if include_detail else set()
        return {issue_id:{"issue":issue,"appointments":appointments[issue_id],"costs":costs[issue_id],"links":links[issue_id],"quotes":quotes[issue_id],"assignments":assignments[issue_id],"journals":journals[issue_id],"journal_count":journal_counts[issue_id],"journal_corrected_ids":corrected_ids,"journal_summary":journal_summaries[issue_id],"journal_evidence_count":journal_evidence_counts[issue_id],"context":contexts.get((issue["property_id"],issue["space_id"])),"tasks":tasks.get(issue_id,[]),"expenses":expenses,"files":issue_files.get(issue_id,[]),"appointment_files":appointment_files,"cost_files":cost_files,"quote_files":quote_files,"assignment_files":assignment_files,"journal_files":journal_files,"party_states":party_states,"provider_states":provider_states,"evidence_count":None if include_detail else sum(evidence_counts.get((entity_type,item_id),0) for entity_type,item_id in [("maintenance_issue",issue_id)]+[("maintenance_appointment",item["id"]) for item in appointments[issue_id]]+[("maintenance_cost_context",item["id"]) for item in costs[issue_id]]),"communications":communications.get(issue_id,[])} for issue_id,issue in issues.items()}
    def comparison_projection(self, issue_id):
        issue=self.connection.execute(select(MaintenanceIssueModel.id,MaintenanceIssueModel.reported_timezone).where(MaintenanceIssueModel.id==issue_id)).mappings().first()
        if issue is None:return {}
        issue=dict(issue); today=datetime.now(ZoneInfo(issue["reported_timezone"])).date().isoformat()
        quotes=[dict(row) for row in self.connection.execute(select(MaintenanceQuoteModel).where(MaintenanceQuoteModel.issue_id==issue_id)).mappings()]
        quotes.sort(key=lambda item:(item["withdrawn_at"] is not None,item["valid_through"] is not None and item["valid_through"] < today,item["amount_minor"],-date.fromisoformat(item["received_on"]).toordinal(),item["id"]))
        assignments=[dict(row) for row in self.connection.execute(select(MaintenanceAssignmentModel.quote_id,MaintenanceAssignmentModel.ended_at).where(MaintenanceAssignmentModel.issue_id==issue_id)).mappings()]
        quote_ids=[item["id"] for item in quotes]
        return {issue_id:{"issue":issue,"quotes":quotes,"assignments":assignments,"quote_document_counts":self.files.active_link_counts_for_entities(self.connection,"maintenance_quote",quote_ids) if self.files else {},"provider_states":self.provider_states([item["provider_party_id"] for item in quotes])}}
    def record_change(self, **kwargs): self.recorder.record_change(self.connection.connection.driver_connection, **kwargs)

class SQLiteMaintenanceUnitOfWork:
    def __init__(self,database,recorder:AuditRecorder,portfolio,finance,tasks,task_operations,files=None,parties=None,leases=None,communications=None,providers=None):
        self.database,self.recorder=database,recorder
        self.portfolio,self.finance,self.tasks,self.task_operations,self.files=portfolio,finance,tasks,task_operations,files
        self.parties,self.leases,self.communications,self.providers=parties,leases,communications,providers
    def write(self, operation):
        engine=create_engine(f"sqlite:///{self.database}")
        try:
            with immediate_transaction(engine) as connection:return operation(SQLiteMaintenanceTransaction(connection,self.recorder,self.portfolio,self.finance,self.tasks,self.task_operations,self.files,self.parties,self.leases,self.communications,self.providers))
        finally:engine.dispose()
    def read(self, operation):
        engine=create_engine(f"sqlite:///{self.database}")
        try:
            with engine.connect() as connection:return operation(SQLiteMaintenanceTransaction(connection,self.recorder,self.portfolio,self.finance,self.tasks,self.task_operations,self.files,self.parties,self.leases,self.communications,self.providers))
        finally:engine.dispose()
