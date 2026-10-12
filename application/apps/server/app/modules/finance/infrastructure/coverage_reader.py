"""Grouped financial coverage hydration; single and batch reads share policy."""

from sqlalchemy import func, select, literal, union_all, case
from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    SecurityDepositAccountModel,
    SecurityDepositReceiptModel,
    SecurityDepositSettlementModel,
    SecurityDepositDeductionModel,
    SecurityDepositCreditModel,
    SecurityDepositRefundModel,
    SecurityDepositDeductionSourceModel,
)
from app.modules.audit.application.read_marker import AuditEntityReadMarker
from app.platform.coverage import CoverageFacts, bounded_subjects, evidence_revision
from app.platform.sql_coverage import json_fields, register_json_function, fact_json


class SQLiteFinanceCoverageReader:
    def __init__(self, marker: AuditEntityReadMarker):
        self.marker = marker

    def fact_relation(self, connection, contexts):
        register_json_function(connection, "coverage_finance_facts", 7, _relational_facts)
        t, a = RentExpectationModel.__table__, SecurityDepositAccountModel.__table__
        lease_id = func.json_extract(contexts.c.lease_context, "$.lease_id")
        term_id = func.json_extract(contexts.c.lease_context, "$.term_id")
        lease_ids = select(lease_id).where(contexts.c.subject_kind == "space")
        rents = (
            select(
                t.c.lease_term_id,
                func.count().label("count"),
                func.min(case((t.c.is_prorated == 0, t.c.expected_amount_minor))).label(
                    "min_amount"
                ),
                func.max(case((t.c.is_prorated == 0, t.c.expected_amount_minor))).label(
                    "max_amount"
                ),
                func.max(t.c.created_at).label("created_at"),
                func.max(t.c.period_ends_on).label("through_on"),
                func.min(t.c.currency_code).label("currency"),
                func.min(t.c.payment_frequency).label("frequency"),
            )
            .where(t.c.lease_id.in_(lease_ids), t.c.voided_at.is_(None))
            .group_by(t.c.lease_term_id)
            .subquery()
        )
        refs = union_all(
            select(
                literal("rent_expectation").label("entity_type"),
                t.c.id.label("entity_id"),
                (literal("rent:") + t.c.lease_id).label("group_id"),
            ).where(t.c.lease_id.in_(lease_ids)),
            select(*_deposit_references(lease_ids).c),
        ).subquery()
        markers = self.marker.grouped_markers(refs)
        rent_marker, deposit_marker = markers.alias("rent_marker"), markers.alias("deposit_marker")
        source = (
            contexts.outerjoin(rents, rents.c.lease_term_id == term_id)
            .outerjoin(a, a.c.lease_id == lease_id)
            .outerjoin(rent_marker, rent_marker.c.group_id == literal("rent:") + lease_id)
            .outerjoin(deposit_marker, deposit_marker.c.group_id == literal("deposit:") + lease_id)
        )
        rent = case(
            (
                rents.c.lease_term_id.is_not(None),
                json_fields(
                    rents.c, tuple(name for name in rents.c.keys() if name != "lease_term_id")
                ),
            )
        )
        account = case(
            (
                a.c.id.is_not(None),
                json_fields(a.c, ("id", "agreed_amount_minor", "lease_term_id", "updated_at")),
            )
        )
        return (
            select(
                contexts,
                func.coverage_finance_facts(
                    contexts.c.lease_context,
                    func.json_quote(contexts.c.time_zone),
                    func.json_quote(contexts.c.local_date),
                    rent,
                    account,
                    func.json_quote(func.cast(func.coalesce(rent_marker.c.marker, 0), t.c.id.type)),
                    func.json_quote(
                        func.cast(func.coalesce(deposit_marker.c.marker, 0), t.c.id.type)
                    ),
                ).label("finance_facts"),
            )
            .select_from(source)
            .cte("coverage_financial_locations")
        )

    def facts(self, connection, area, lease_context, time_zone, on):
        key = lease_context["lease_id"]
        return self.facts_for_contexts(
            connection, {key: (lease_context, time_zone, on)}, {(key, area)}
        )[(key, area)]

    def facts_for_contexts(self, connection, contexts, areas):
        bounded_subjects(contexts)
        if not contexts or not areas:
            return {}
        rent_terms = {contexts[key][0]["term_id"] for key, area in areas if area == "rent"}
        rent_leases = {contexts[key][0]["lease_id"] for key, area in areas if area == "rent"}
        deposit_leases = {contexts[key][0]["lease_id"] for key, area in areas if area == "deposit"}
        rents, accounts, refs = {}, {}, []
        if rent_terms:
            t = RentExpectationModel.__table__
            for row in connection.execute(
                select(
                    t.c.lease_term_id,
                    func.count().label("count"),
                    func.min(case((t.c.is_prorated == 0, t.c.expected_amount_minor))).label(
                        "min_amount"
                    ),
                    func.max(case((t.c.is_prorated == 0, t.c.expected_amount_minor))).label(
                        "max_amount"
                    ),
                    func.max(t.c.created_at).label("created_at"),
                    func.max(t.c.period_ends_on).label("through_on"),
                    func.min(t.c.currency_code).label("currency"),
                    func.min(t.c.payment_frequency).label("frequency"),
                )
                .where(t.c.lease_term_id.in_(rent_terms), t.c.voided_at.is_(None))
                .group_by(t.c.lease_term_id)
            ).mappings():
                rents[row["lease_term_id"]] = {
                    key: value for key, value in row.items() if key != "lease_term_id"
                }
            refs.append(
                select(
                    literal("rent_expectation").label("entity_type"),
                    t.c.id.label("entity_id"),
                    (literal("rent:") + t.c.lease_id).label("group_id"),
                ).where(t.c.lease_id.in_(rent_leases))
            )
        if deposit_leases:
            t = SecurityDepositAccountModel.__table__
            for row in connection.execute(
                select(
                    t.c.lease_id, t.c.id, t.c.agreed_amount_minor, t.c.lease_term_id, t.c.updated_at
                ).where(t.c.lease_id.in_(deposit_leases))
            ).mappings():
                accounts[row["lease_id"]] = {
                    key: value for key, value in row.items() if key != "lease_id"
                }
            refs.append(select(*_deposit_references(deposit_leases).c))
        markers = self.marker.markers_for_groups(
            connection, union_all(*refs).subquery("financial_coverage_refs")
        )
        result = {}
        for key, area in areas:
            lease, zone, on = contexts[key]
            row = (
                rents.get(lease["term_id"], _empty_rent())
                if area == "rent"
                else accounts.get(lease["lease_id"])
            )
            result[(key, area)] = _fact(
                area, lease, zone, on, row, markers.get(area + ":" + lease["lease_id"], "0")
            )
        return result


def _empty_rent():
    return {
        "count": 0,
        "min_amount": None,
        "max_amount": None,
        "created_at": None,
        "through_on": None,
        "currency": None,
        "frequency": None,
    }


def _relational_facts(lease, zone, on, rent, account, rent_marker, deposit_marker):
    if lease is None or lease["ambiguous"] or lease["term_id"] is None:
        return {}
    return {
        "rent": fact_json(_fact("rent", lease, zone, on, rent or _empty_rent(), rent_marker)),
        "deposit": fact_json(_fact("deposit", lease, zone, on, account, deposit_marker)),
    }


def _fact(area, lease, zone, on, row, marker):
    if area == "rent":
        missing = ("rent_expectations_missing",) if not row["count"] else ()
        changed = row["count"] and (
            row["currency"] != lease["currency_code"]
            or row["frequency"] != lease["payment_frequency"]
            or row["max_amount"] is not None
            and row["max_amount"] != lease["base_rent_minor"]
            or row["min_amount"] is not None
            and row["min_amount"] != lease["base_rent_minor"]
            or row["through_on"] <= on
        )
        needs = ("rent_synchronization_required",) if changed else ()
        reason = None
    else:
        reason = (
            "no_deposit_terms"
            if lease["agreed_security_deposit_minor"] == 0 and row is None
            else None
        )
        missing = ("deposit_account_missing",) if row is None and reason is None else ()
        needs = (
            ("deposit_terms_changed",)
            if row
            and (
                row["lease_term_id"] != lease["term_id"]
                or row["agreed_amount_minor"] != lease["agreed_security_deposit_minor"]
            )
            else ()
        )
    revision = evidence_revision(
        {"lease": dict(lease), "facts": row, "marker": marker, "needs": needs, "zone": zone}
    )
    return CoverageFacts(area, revision, zone, missing, needs, reason, lease_id=lease["lease_id"])


def _deposit_references(lease_ids):
    account = SecurityDepositAccountModel.__table__
    settlement = SecurityDepositSettlementModel.__table__
    group = (literal("deposit:") + account.c.lease_id).label("group_id")
    selections = [
        select(
            literal("security_deposit_account").label("entity_type"),
            account.c.id.label("entity_id"),
            group,
        ).where(account.c.lease_id.in_(lease_ids))
    ]
    for kind, model in (
        ("receipt", SecurityDepositReceiptModel),
        ("settlement", SecurityDepositSettlementModel),
        ("deduction", SecurityDepositDeductionModel),
        ("credit", SecurityDepositCreditModel),
        ("refund", SecurityDepositRefundModel),
    ):
        t = model.__table__
        parent = (
            t.join(account, t.c.account_id == account.c.id)
            if kind in ("receipt", "settlement", "refund")
            else (
                t.join(settlement, t.c.settlement_id == settlement.c.id).join(
                    account, settlement.c.account_id == account.c.id
                )
            )
        )
        selections.append(
            select(literal("security_deposit_" + kind), t.c.id, group)
            .select_from(parent)
            .where(account.c.lease_id.in_(lease_ids))
        )
    source, deduction = (
        SecurityDepositDeductionSourceModel.__table__,
        SecurityDepositDeductionModel.__table__,
    )
    parent = (
        source.join(deduction, source.c.deduction_id == deduction.c.id)
        .join(settlement, deduction.c.settlement_id == settlement.c.id)
        .join(account, settlement.c.account_id == account.c.id)
    )
    selections.append(
        select(literal("security_deposit_deduction_source"), source.c.id, group)
        .select_from(parent)
        .where(account.c.lease_id.in_(lease_ids))
    )
    return union_all(*selections).subquery("deposit_coverage_references")
