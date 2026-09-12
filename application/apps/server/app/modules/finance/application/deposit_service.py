"""FIN-008 security-deposit workflows.

All state-changing rules deliberately run through one immediate Finance
transaction; this keeps account aggregates and audit records coherent.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.finance.application.deposit_ports import DepositUnitOfWork
from app.modules.finance.domain.deposit_models import (
    CreditCommand, DeductionCommand, DepositAccountCreateCommand,
    DepositReceiptCommand, DepositRefundCommand, SettlementCreateCommand, money, signed_money,
)
from app.modules.finance.domain.expense_models import amount_minor
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, VoidCommand


class PossibleDuplicateDepositReceiptError(FinanceConflictError):
    def __init__(self, candidates): super().__init__("A possible duplicate deposit receipt requires review."); self.candidates = candidates


class PossibleDuplicateDepositRefundError(FinanceConflictError):
    def __init__(self, candidates): super().__init__("A possible duplicate deposit refund requires review."); self.candidates = candidates


class DepositService:
    def __init__(self, unit_of_work: DepositUnitOfWork, *, now=lambda: datetime.now(UTC)):
        self.unit_of_work = unit_of_work; self.now = now

    def create_account(self, lease_id: str, command: DepositAccountCreateCommand):
        def operation(tx):
            if tx.account_for_lease(lease_id): raise FinanceConflictError("This lease already has a security-deposit account.")
            context = tx.lease_context(lease_id, command.lease_term_id)
            if context is None: raise FinanceNotFoundError("Lease or lease term was not found.")
            stamp = _stamp(self.now())
            item = {"id": str(uuid4()), "lease_id": lease_id, "lease_term_id": command.lease_term_id,
                    "property_id": context["propertyId"], "space_id": context["spaceId"],
                    "agreed_amount_minor": context["agreedSecurityDepositMinor"], "currency_code": "USD",
                    "created_at": stamp, "updated_at": stamp}
            tx.insert("account", item); self._audit(tx, "security_deposit_account", item["id"], "created", None, _account_view(item), str(uuid4()))
            return self._account_view(tx, item)
        return self.unit_of_work.write(operation)

    def account_for_lease(self, lease_id: str):
        return self.unit_of_work.read(lambda tx: self._account_view(tx, _required(tx.account_for_lease(lease_id), "Security-deposit account was not found.")))

    def account(self, account_id: str):
        return self.unit_of_work.read(lambda tx: self._account_view(tx, _required(tx.account(account_id), "Security-deposit account was not found.")))

    def receipt_history(self, account_id: str):
        def operation(tx):
            _required(tx.account(account_id), "Security-deposit account was not found.")
            return [_receipt_view({**item, "replaced_by_receipt_id": tx.receipt_replacement(item["id"])}) for item in tx.receipts(account_id)]
        return self.unit_of_work.read(operation)

    def refund_history(self, account_id: str):
        def operation(tx):
            _required(tx.account(account_id), "Security-deposit account was not found.")
            return [_refund_view({**item, "replaced_by_refund_id": tx.refund_replacement(item["id"])}) for item in tx.refunds(account_id)]
        return self.unit_of_work.read(operation)

    def list_accounts(self, *, lease_id=None, property_id=None, space_id=None, settlement_state=None, deadline_state=None, unresolved_balance=None, cursor=None, page_size=100):
        if type(page_size) is not int or not 1 <= page_size <= 500: raise FinanceError("Page size must be from 1 through 500.")
        def operation(tx):
            rows = []
            for item in tx.accounts(lease_id=lease_id, property_id=property_id, space_id=space_id):
                view = self._account_view(tx, item)
                if settlement_state is not None and view["settlementStatus"] != settlement_state: continue
                if deadline_state is not None and view["deadlineState"] != deadline_state: continue
                if unresolved_balance is not None and view["unresolvedBalance"] != unresolved_balance: continue
                rows.append(view)
            rows.sort(key=lambda value: (value["createdAt"], value["id"]), reverse=True)
            if cursor:
                try: stamp, record_id = cursor.split("|", 1)
                except ValueError as error: raise FinanceError("Cursor is invalid.") from error
                rows = [row for row in rows if (row["createdAt"], row["id"]) < (stamp, record_id)]
            page = rows[:page_size]; next_cursor = None if len(rows) <= page_size else f"{page[-1]['createdAt']}|{page[-1]['id']}"
            return {"items": page, "nextCursor": next_cursor}
        return self.unit_of_work.read(operation)

    def record_receipt(self, account_id: str, command: DepositReceiptCommand):
        def operation(tx):
            existing = tx.receipt_by_key(command.idempotency_key)
            if existing:
                if existing["account_id"] != account_id or existing["request_fingerprint"] != _aggregate_fingerprint(account_id, command.fingerprint()): raise FinanceConflictError("Idempotency key was used with a different receipt.")
                return _receipt_view(existing)
            account = _required(tx.account(account_id), "Security-deposit account was not found."); context = tx.lease_context(account["lease_id"], account["lease_term_id"])
            if date.fromisoformat(command.received_on) > self.now().astimezone(ZoneInfo(context["timeZone"])).date(): raise FinanceError("Received date cannot be in the future for the property.")
            historical = context["status"] in {"ended", "terminated", "void"}
            if historical != command.historical_entry_confirmed:
                raise FinanceConflictError("Historical receipt context requires explicit confirmation and reason.")
            payer = self._party(tx, command.received_from_party_id, "Payer", command.historical_party_confirmed) if command.received_from_party_id else None
            receiver = self._party(tx, command.received_by_party_id, "Recipient", command.historical_party_confirmed) if command.received_by_party_id else None
            active_total = sum(row["amount_minor"] for row in tx.receipts(account_id, active_only=True))
            if active_total + command.amount_minor > account["agreed_amount_minor"] and not command.overage_confirmed: raise FinanceConflictError("Deposit overage requires confirmation and reason.")
            candidates = [r for r in tx.receipts(account_id, active_only=True) if r["received_on"] == command.received_on and r["amount_minor"] == command.amount_minor and r["received_from_party_id"] == command.received_from_party_id][:10]
            if candidates and not command.duplicate_confirmed: raise PossibleDuplicateDepositReceiptError([_receipt_view(row) for row in candidates])
            if command.replaces_receipt_id:
                replaced = _required(tx.receipt(command.replaces_receipt_id), "Replacement receipt was not found.")
                if replaced["account_id"] != account_id or replaced["voided_at"] is None or tx.receipt_replacement_exists(replaced["id"]): raise FinanceConflictError("A replacement must target an unreplaced voided receipt in this account.")
            item = {"id": str(uuid4()), "account_id": account_id, "idempotency_key": command.idempotency_key, "request_fingerprint": _aggregate_fingerprint(account_id, command.fingerprint()), "received_on": command.received_on, "amount_minor": command.amount_minor, "currency_code": "USD", "received_from_party_id": command.received_from_party_id, "received_from_name": payer["display_name"] if payer else None, "received_by_kind": command.received_by_kind, "received_by_party_id": command.received_by_party_id, "received_by_name": receiver["display_name"] if receiver else None, "reference": command.reference, "notes": command.notes, "replaces_receipt_id": command.replaces_receipt_id, "voided_at": None, "void_reason": None, "created_at": _stamp(self.now())}
            audit = {**_receipt_view(item), "duplicateConfirmed": command.duplicate_confirmed, "historicalEntryConfirmed": command.historical_entry_confirmed, "historicalEntryReason": command.historical_entry_reason, "overageConfirmed": command.overage_confirmed, "overageReason": command.overage_reason, "historicalPartyConfirmed": command.historical_party_confirmed, "historicalPartyReason": command.historical_party_reason}
            tx.insert("receipt", item); self._audit(tx, "security_deposit_receipt", item["id"], "recorded", None, audit, str(uuid4())); return _receipt_view(item)
        return self.unit_of_work.write(operation)

    def void_receipt(self, receipt_id: str, command: VoidCommand):
        def operation(tx):
            old = _required(tx.receipt(receipt_id), "Security-deposit receipt was not found.")
            if old["voided_at"]: raise FinanceConflictError("Receipt is already voided.")
            if any(old["id"] in tx.settlement_receipt_ids(row["id"]) and row["status"] != "voided" for row in tx.settlements(old["account_id"])): raise FinanceConflictError("Void the settlement before voiding this captured receipt.")
            new = {**old, "voided_at": _stamp(self.now()), "void_reason": command.reason}; tx.replace("receipt", new); self._audit(tx, "security_deposit_receipt", receipt_id, "voided", _receipt_view(old), _receipt_view(new), str(uuid4())); return _receipt_view(new)
        return self.unit_of_work.write(operation)

    def create_settlement(self, account_id: str, command: SettlementCreateCommand):
        def operation(tx):
            account = _required(tx.account(account_id), "Security-deposit account was not found.")
            if any(row["status"] != "voided" for row in tx.settlements(account_id)): raise FinanceConflictError("Only one non-voided settlement is allowed.")
            if command.replaces_settlement_id is not None:
                replaced = _required(tx.settlement(command.replaces_settlement_id), "Replacement settlement was not found.")
                if replaced["account_id"] != account_id or replaced["status"] != "voided" or tx.settlement_replacement_exists(replaced["id"]): raise FinanceConflictError("A replacement must target an unreplaced voided settlement in this account.")
            context = tx.lease_context(account["lease_id"], account["lease_term_id"])
            early = context["status"] not in {"ended", "terminated", "void"} or (context["status"] != "void" and not context["actualMoveOutOn"])
            if early != command.eligibility_override_confirmed: raise FinanceConflictError("This settlement timing requires explicit eligibility confirmation and reason.")
            if context["actualMoveOutOn"] and command.settlement_due_on < context["actualMoveOutOn"] and not command.deadline_override_confirmed: raise FinanceConflictError("An early deadline requires confirmation and reason.")
            stamp = _stamp(self.now()); item = {"id": str(uuid4()), "account_id": account_id, "status": "draft", "settlement_due_on": command.settlement_due_on, "legal_rule_reference": command.legal_rule_reference, "review_notes": command.review_notes, "eligibility_override_reason": command.eligibility_override_reason, "deadline_override_reason": command.deadline_override_reason, "receipt_total_minor": None, "credit_total_minor": None, "deduction_total_minor": None, "refund_due_minor": None, "replaces_settlement_id": command.replaces_settlement_id, "approved_at": None, "completed_at": None, "voided_at": None, "void_reason": None, "created_at": stamp, "updated_at": stamp}
            tx.insert("settlement", item); self._audit(tx, "security_deposit_settlement", item["id"], "draft_created", None, _settlement_view(item), str(uuid4())); return self._settlement_view(tx, item)
        return self.unit_of_work.write(operation)

    def add_deduction(self, settlement_id: str, command: DeductionCommand):
        return self._add_line("deduction", settlement_id, command)

    def add_credit(self, settlement_id: str, command: CreditCommand):
        return self._add_line("credit", settlement_id, command)

    def update_deduction(self, deduction_id: str, command: DeductionCommand):
        return self._replace_line("deduction", deduction_id, command)

    def update_credit(self, credit_id: str, command: CreditCommand):
        return self._replace_line("credit", credit_id, command)

    def _replace_line(self, kind, record_id, command):
        def operation(tx):
            old = _required(getattr(tx, kind)(record_id), f"{kind.title()} was not found.")
            self._draft(tx, old["settlement_id"]); stamp = _stamp(self.now())
            if kind == "deduction": new = {**old, "category": command.category, "amount_minor": command.amount_minor, "description": command.description, "rationale": command.rationale, "updated_at": stamp}
            else:
                day_count = None if command.starts_on is None else (date.fromisoformat(command.ends_on) - date.fromisoformat(command.starts_on)).days
                new = {**old, "kind": command.kind, "amount_minor": command.amount_minor, "description": command.description, "calculator_principal_minor": None if command.calculator_principal is None else amount_minor(command.calculator_principal), "annual_rate_basis_points": command.annual_rate_basis_points, "starts_on": command.starts_on, "ends_on": command.ends_on, "day_count": day_count, "calculated_amount_minor": command.calculated_amount_minor, "override_reason": command.override_reason, "updated_at": stamp}
            if new == old: return _line_view(old)
            tx.replace(kind, new); self._audit(tx, f"security_deposit_{kind}", record_id, "updated", _line_view(old), _line_view(new), str(uuid4())); return _line_view(new)
        return self.unit_of_work.write(operation)

    def delete_deduction(self, deduction_id: str): return self._delete_line("deduction", deduction_id)
    def delete_credit(self, credit_id: str): return self._delete_line("credit", credit_id)
    def _delete_line(self, kind, record_id):
        def operation(tx):
            old = _required(getattr(tx, kind)(record_id), f"{kind.title()} was not found.")
            self._draft(tx, old["settlement_id"])
            if kind == "deduction":
                if any(link["archived_at"] is None for link in tx.evidence("security_deposit_deduction", record_id)):
                    raise FinanceConflictError("Archive deduction evidence before deleting its deduction.")
                for source in tx.deduction_sources(record_id):
                    tx.delete("source", source["id"])
                    self._audit(tx, "security_deposit_deduction_source", source["id"], "deleted", _source_view(source), None, str(uuid4()))
            tx.delete(kind, record_id)
            self._audit(tx, f"security_deposit_{kind}", record_id, "deleted", _line_view(old), None, str(uuid4()))
            return {"deleted": True, "id": record_id}
        return self.unit_of_work.write(operation)

    def patch_settlement(self, settlement_id: str, *, fields: frozenset[str], settlement_due_on: str | None = None, legal_rule_reference: str | None = None, review_notes: str | None = None, deadline_override_confirmed: bool | None = None, deadline_override_reason: str | None = None):
        allowed = {"settlement_due_on", "legal_rule_reference", "review_notes", "deadline_override_confirmed", "deadline_override_reason"}
        if not fields or not fields <= allowed: raise FinanceError("At least one valid settlement field is required.")
        if deadline_override_confirmed is not None and type(deadline_override_confirmed) is not bool:
            raise FinanceError("Deadline override confirmation must be boolean.")
        if "settlement_due_on" in fields:
            from app.modules.finance.domain.expense_models import local_date
            settlement_due_on = local_date(settlement_due_on, "Settlement due date")
        def operation(tx):
            old = self._draft(tx, settlement_id)
            new = {**old,
                   "settlement_due_on": settlement_due_on if "settlement_due_on" in fields else old["settlement_due_on"],
                   "legal_rule_reference": legal_rule_reference.strip() if "legal_rule_reference" in fields and legal_rule_reference else None if "legal_rule_reference" in fields else old["legal_rule_reference"],
                   "review_notes": review_notes.strip() if "review_notes" in fields and review_notes else None if "review_notes" in fields else old["review_notes"],
                   "deadline_override_reason": deadline_override_reason.strip() if "deadline_override_reason" in fields and deadline_override_reason else None if "deadline_override_reason" in fields else old["deadline_override_reason"]}
            if "deadline_override_confirmed" in fields and deadline_override_confirmed is False:
                new["deadline_override_reason"] = None
            if "deadline_override_confirmed" in fields and deadline_override_confirmed and not new["deadline_override_reason"]:
                raise FinanceError("Deadline override reason is required when confirmed.")
            if all(new[key] == old[key] for key in ("settlement_due_on", "legal_rule_reference", "review_notes", "deadline_override_reason")): return self._settlement_view(tx, old)
            account = _required(tx.account(old["account_id"]), "Security-deposit account was not found.")
            context = _required(tx.lease_context(account["lease_id"], account["lease_term_id"]), "Lease context was not found.")
            exceptional_deadline = bool(context["actualMoveOutOn"] and new["settlement_due_on"] < context["actualMoveOutOn"])
            establishes_override = exceptional_deadline and (new["settlement_due_on"] != old["settlement_due_on"] or new["deadline_override_reason"] != old["deadline_override_reason"])
            if establishes_override and deadline_override_confirmed is not True:
                raise FinanceError("An exceptional deadline requires explicit confirmation.")
            if "deadline_override_reason" in fields and new["deadline_override_reason"] is not None and deadline_override_confirmed is not True:
                raise FinanceError("Deadline override confirmation is required.")
            self._validate_settlement_timing(tx, account, new)
            new["updated_at"] = _stamp(self.now()); tx.replace("settlement", new); self._audit(tx, "security_deposit_settlement", settlement_id, "updated", _settlement_view(old), _settlement_view(new), str(uuid4())); return self._settlement_view(tx, new)
        return self.unit_of_work.write(operation)

    def _add_line(self, kind, settlement_id, command):
        def operation(tx):
            settlement = self._draft(tx, settlement_id); stamp = _stamp(self.now())
            if kind == "deduction": item = {"id": str(uuid4()), "settlement_id": settlement_id, "category": command.category, "amount_minor": command.amount_minor, "description": command.description, "rationale": command.rationale, "created_at": stamp, "updated_at": stamp}
            else:
                day_count = None if command.starts_on is None else (date.fromisoformat(command.ends_on) - date.fromisoformat(command.starts_on)).days
                item = {"id": str(uuid4()), "settlement_id": settlement_id, "kind": command.kind, "amount_minor": command.amount_minor, "description": command.description, "calculator_principal_minor": None if command.calculator_principal is None else amount_minor(command.calculator_principal), "annual_rate_basis_points": command.annual_rate_basis_points, "starts_on": command.starts_on, "ends_on": command.ends_on, "day_count": day_count, "calculated_amount_minor": command.calculated_amount_minor, "override_reason": command.override_reason, "created_at": stamp, "updated_at": stamp}
            tx.insert(kind, item); entity = f"security_deposit_{kind}"; self._audit(tx, entity, item["id"], "created", None, _line_view(item), str(uuid4())); return _line_view(item)
        return self.unit_of_work.write(operation)

    def add_deduction_source(self, deduction_id: str, source_kind: str, source_id: str, *, historical_confirmed: bool = False, historical_reason: str | None = None, duplicate_use_confirmed: bool = False):
        if source_kind not in {"inspection_comparison", "inspection_observation", "rent_expectation", "expense"}:
            raise FinanceError("Deduction source kind is invalid.")
        if type(historical_confirmed) is not bool or type(duplicate_use_confirmed) is not bool:
            raise FinanceError("Source confirmations must be boolean.")
        if (historical_reason is not None) != historical_confirmed:
            raise FinanceError("Historical source confirmation and reason must be supplied together.")
        if historical_reason is not None:
            historical_reason = historical_reason.strip()
            if not 1 <= len(historical_reason) <= 1000:
                raise FinanceError("Historical source reason must be between 1 and 1000 characters.")
        def operation(tx):
            deduction = _required(tx.deduction(deduction_id), "Deduction was not found.")
            settlement = self._draft(tx, deduction["settlement_id"]); account = _required(tx.account(settlement["account_id"]), "Security-deposit account was not found.")
            source = tx.source_context(source_kind, source_id)
            if source is None: raise FinanceNotFoundError("Deduction source was not found.")
            if source.get("leaseId") not in {None, account["lease_id"]} or source.get("propertyId") not in {None, account["property_id"]} or source.get("spaceId") not in {None, account["space_id"]}: raise FinanceConflictError("Deduction source does not belong to this lease and space.")
            if not source["active"] and not historical_confirmed:
                raise FinanceConflictError("A historical deduction source requires explicit confirmation and reason.")
            if source_kind == "expense" and tx.expense_source_used_elsewhere(source_id, deduction["id"]) and not duplicate_use_confirmed:
                raise FinanceConflictError("Duplicate expense use requires explicit confirmation.")
            if any(row["source_kind"] == source_kind and row["source_id"] == source_id for row in tx.deduction_sources(deduction_id)):
                raise FinanceConflictError("This deduction source is already attached.")
            item = {"id": str(uuid4()), "deduction_id": deduction_id, "source_kind": source_kind, "source_id": source_id, "source_summary": source["summary"], "outstanding_amount_minor": source.get("outstandingAmountMinor"), "historical_confirmed": historical_confirmed, "historical_reason": historical_reason, "duplicate_use_confirmed": duplicate_use_confirmed, "created_at": _stamp(self.now())}
            view = _source_view(item)
            tx.insert_source(item); self._audit(tx, "security_deposit_deduction_source", item["id"], "created", None, view, str(uuid4())); return view
        return self.unit_of_work.write(operation)

    def delete_deduction_source(self, source_id: str):
        def operation(tx):
            old = _required(tx.deduction_source(source_id), "Deduction source was not found.")
            deduction = _required(tx.deduction(old["deduction_id"]), "Deduction was not found.")
            self._draft(tx, deduction["settlement_id"]); tx.delete("source", source_id)
            self._audit(tx, "security_deposit_deduction_source", source_id, "deleted", _source_view(old), None, str(uuid4()))
            return {"deleted": True, "id": source_id}
        return self.unit_of_work.write(operation)

    def approve_settlement(self, settlement_id: str, confirmed: bool, *, zero_dollar_closure_confirmed: bool = False):
        if type(confirmed) is not bool or not confirmed: raise FinanceError("Approval confirmation is required.")
        if type(zero_dollar_closure_confirmed) is not bool: raise FinanceError("Zero-dollar closure confirmation must be boolean.")
        def operation(tx):
            old = self._draft(tx, settlement_id); receipts = tx.receipts(old["account_id"], active_only=True); deductions = tx.deductions(settlement_id); credits = tx.credits(settlement_id)
            account = _required(tx.account(old["account_id"]), "Security-deposit account was not found.")
            self._validate_settlement_timing(tx, account, old)
            if not receipts and not zero_dollar_closure_confirmed:
                raise FinanceConflictError("Zero-dollar closure requires explicit confirmation.")
            for deduction in deductions:
                sources = tx.deduction_sources(deduction["id"])
                if not sources and not tx.deduction_has_file_evidence(deduction["id"]):
                    raise FinanceConflictError("Every deduction requires at least one source before approval.")
                for source in sources:
                    current = tx.source_context(source["source_kind"], source["source_id"])
                    if current is None:
                        raise FinanceConflictError("A deduction source no longer exists.")
                    if current.get("leaseId") not in {None, account["lease_id"]} or current.get("propertyId") not in {None, account["property_id"]} or current.get("spaceId") not in {None, account["space_id"]}:
                        raise FinanceConflictError("A deduction source no longer belongs to this account.")
                    if source["source_kind"] == "rent_expectation":
                        refreshed = {**source, "outstanding_amount_minor": current["outstandingAmountMinor"]}
                        if refreshed != source:
                            tx.replace_source(refreshed)
                            self._audit(tx, "security_deposit_deduction_source", source["id"], "snapshotted", _source_view(source), _source_view(refreshed), str(uuid4()))
                    if not current["active"] and not source["historical_confirmed"]:
                        raise FinanceConflictError("A changed deduction source requires historical confirmation.")
                    if source["source_kind"] == "expense" and tx.expense_source_used_elsewhere(source["source_id"], deduction["id"]) and not source["duplicate_use_confirmed"]:
                        raise FinanceConflictError("Duplicate expense use requires explicit confirmation.")
            receipt_total = sum(row["amount_minor"] for row in receipts); credit_total = sum(row["amount_minor"] for row in credits); deduction_total = sum(row["amount_minor"] for row in deductions); refund_due = receipt_total + credit_total - deduction_total
            if refund_due < 0: raise FinanceConflictError("Deductions cannot exceed held receipts and credits.")
            if any(total > 9_999_999_999 for total in (receipt_total, credit_total, deduction_total, refund_due)):
                raise FinanceConflictError("Settlement totals cannot exceed 9,999,999,999 cents.")
            active_refunds = sum(row["amount_minor"] for row in tx.refunds(old["account_id"], active_only=True))
            if active_refunds > refund_due: raise FinanceConflictError("Refund due cannot be less than active refunds.")
            new = {**old, "status": "approved", "receipt_total_minor": receipt_total, "credit_total_minor": credit_total, "deduction_total_minor": deduction_total, "refund_due_minor": refund_due, "approved_at": _stamp(self.now()), "updated_at": _stamp(self.now())}; tx.replace("settlement", new)
            for receipt in receipts: tx.capture_settlement_receipt(settlement_id, receipt["id"], _stamp(self.now()))
            self._audit(tx, "security_deposit_settlement", settlement_id, "approved", _settlement_view(old), _settlement_view(new), str(uuid4())); return self._settlement_view(tx, new)
        return self.unit_of_work.write(operation)

    def record_refund(self, settlement_id: str, command: DepositRefundCommand):
        def operation(tx):
            old_key = tx.refund_by_key(command.idempotency_key)
            if old_key:
                if old_key["authorized_by_settlement_id"] != settlement_id or old_key["request_fingerprint"] != _aggregate_fingerprint(settlement_id, command.fingerprint()): raise FinanceConflictError("Idempotency key was used with a different refund.")
                return _refund_view(old_key)
            settlement = _required(tx.settlement(settlement_id), "Settlement was not found.")
            if settlement["status"] != "approved": raise FinanceConflictError("Refunds require an approved settlement.")
            account = _required(tx.account(settlement["account_id"]), "Security-deposit account was not found."); context = _required(tx.lease_context(account["lease_id"], account["lease_term_id"]), "Lease context was not found."); party = self._party(tx, command.recipient_party_id, "Refund recipient", command.historical_party_confirmed)
            if date.fromisoformat(command.paid_on) > self.now().astimezone(ZoneInfo(context["timeZone"])).date(): raise FinanceError("Paid date cannot be in the future for the property.")
            allowed = command.recipient_party_id in tx.participants(account["lease_id"]) or any(row["received_from_party_id"] == command.recipient_party_id for row in tx.receipts(account["id"], active_only=False))
            if not allowed and not command.recipient_override_confirmed: raise FinanceConflictError("An out-of-role refund recipient requires confirmation and reason.")
            total = sum(row["amount_minor"] for row in tx.refunds(account["id"], active_only=True))
            if total + command.amount_minor > settlement["refund_due_minor"]: raise FinanceConflictError("Refunds cannot exceed the approved refund due.")
            candidates = [r for r in tx.refunds(account["id"], active_only=True) if r["paid_on"] == command.paid_on and r["amount_minor"] == command.amount_minor and r["recipient_party_id"] == command.recipient_party_id][:10]
            if candidates and not command.duplicate_confirmed: raise PossibleDuplicateDepositRefundError([_refund_view(row) for row in candidates])
            if command.replaces_refund_id:
                replaced = _required(tx.refund(command.replaces_refund_id), "Replacement refund was not found.")
                if replaced["account_id"] != account["id"] or replaced["voided_at"] is None or tx.refund_replacement_exists(replaced["id"]): raise FinanceConflictError("A replacement must target an unreplaced voided refund in this account.")
            item = {"id": str(uuid4()), "account_id": account["id"], "authorized_by_settlement_id": settlement_id, "idempotency_key": command.idempotency_key, "request_fingerprint": _aggregate_fingerprint(settlement_id, command.fingerprint()), "recipient_party_id": command.recipient_party_id, "recipient_name": party["display_name"], "paid_on": command.paid_on, "amount_minor": command.amount_minor, "currency_code": "USD", "reference": command.reference, "notes": command.notes, "recipient_override_reason": command.recipient_override_reason, "replaces_refund_id": command.replaces_refund_id, "voided_at": None, "void_reason": None, "created_at": _stamp(self.now())}; audit = {**_refund_view(item), "duplicateConfirmed": command.duplicate_confirmed, "historicalPartyConfirmed": command.historical_party_confirmed, "historicalPartyReason": command.historical_party_reason}; tx.insert("refund", item); self._audit(tx, "security_deposit_refund", item["id"], "recorded", None, audit, str(uuid4())); return _refund_view(item)
        return self.unit_of_work.write(operation)

    def complete_settlement(self, settlement_id: str, zero_refund_confirmed: bool):
        def operation(tx):
            old = _required(tx.settlement(settlement_id), "Settlement was not found.")
            if old["status"] != "approved": raise FinanceConflictError("Only an approved settlement can be completed.")
            if len(tx.receipts(old["account_id"], active_only=True)) != len(tx.settlement_receipt_ids(settlement_id)): raise FinanceConflictError("New receipts require a replacement settlement.")
            paid = sum(row["amount_minor"] for row in tx.refunds(old["account_id"], active_only=True))
            if old["refund_due_minor"] == 0:
                if not zero_refund_confirmed: raise FinanceConflictError("Zero-refund completion requires confirmation.")
            elif paid != old["refund_due_minor"]: raise FinanceConflictError("Active refunds must equal the approved refund due.")
            new = {**old, "status": "completed", "completed_at": _stamp(self.now()), "updated_at": _stamp(self.now())}; tx.replace("settlement", new); self._audit(tx, "security_deposit_settlement", settlement_id, "completed", _settlement_view(old), _settlement_view(new), str(uuid4())); return self._settlement_view(tx, new)
        return self.unit_of_work.write(operation)

    def void_refund(self, refund_id: str, command: VoidCommand):
        def operation(tx):
            old = _required(tx.refund(refund_id), "Refund was not found.")
            if old["voided_at"] is not None: raise FinanceConflictError("Refund is already voided.")
            authorization = _required(tx.settlement(old["authorized_by_settlement_id"]), "Refund authorization settlement was not found.")
            if authorization["status"] == "completed":
                raise FinanceConflictError("Void and replace the completed settlement before voiding its refund.")
            new = {**old, "voided_at": _stamp(self.now()), "void_reason": command.reason}
            tx.replace("refund", new); self._audit(tx, "security_deposit_refund", refund_id, "voided", _refund_view(old), _refund_view(new), str(uuid4())); return _refund_view(new)
        return self.unit_of_work.write(operation)

    def void_settlement(self, settlement_id: str, command: VoidCommand):
        def operation(tx):
            old = _required(tx.settlement(settlement_id), "Settlement was not found.")
            if old["status"] == "voided": raise FinanceConflictError("Settlement is already voided.")
            new = {**old, "status": "voided", "voided_at": _stamp(self.now()), "void_reason": command.reason, "updated_at": _stamp(self.now())}; tx.replace("settlement", new); self._audit(tx, "security_deposit_settlement", settlement_id, "voided", _settlement_view(old), _settlement_view(new), str(uuid4())); return self._settlement_view(tx, new)
        return self.unit_of_work.write(operation)

    def settlement(self, settlement_id: str): return self.unit_of_work.read(lambda tx: self._settlement_view(tx, _required(tx.settlement(settlement_id), "Settlement was not found.")))
    def _party(self, tx, party_id, label, historical_confirmed=False):
        item = _required(tx.party(party_id), f"{label} party was not found.")
        if item["archived_at"] is not None and not historical_confirmed: raise FinanceConflictError(f"Archived {label.lower()} selection requires explicit historical confirmation and reason.")
        return item
    def _draft(self, tx, settlement_id):
        item = _required(tx.settlement(settlement_id), "Settlement was not found.")
        if item["status"] != "draft": raise FinanceConflictError("Only a draft settlement can be edited.")
        return item
    def _validate_settlement_timing(self, tx, account, settlement):
        context = _required(tx.lease_context(account["lease_id"], account["lease_term_id"]), "Lease context was not found.")
        early = context["status"] not in {"ended", "terminated", "void"} or (context["status"] != "void" and not context["actualMoveOutOn"])
        if early != (settlement["eligibility_override_reason"] is not None): raise FinanceConflictError("This settlement timing requires explicit eligibility confirmation and reason.")
        if context["actualMoveOutOn"] and settlement["settlement_due_on"] < context["actualMoveOutOn"] and settlement["deadline_override_reason"] is None: raise FinanceConflictError("An early deadline requires confirmation and reason.")
    def _account_view(self, tx, item):
        view = _account_view(item)
        receipts = tx.receipts(item["id"], active_only=True)
        refunds = tx.refunds(item["id"], active_only=True)
        settlements = [row for row in tx.settlements(item["id"]) if row["status"] != "voided"]
        settlement = settlements[0] if settlements else None
        context = _required(tx.lease_context(item["lease_id"], item["lease_term_id"]), "Lease context was not found.")
        today = self.now().astimezone(ZoneInfo(context["timeZone"])).date().isoformat()
        deadline_state = None
        if settlement is not None:
            deadline_state = (
                "complete" if settlement["status"] == "completed"
                else "overdue" if settlement["settlement_due_on"] < today
                else "due_today" if settlement["settlement_due_on"] == today
                else "due"
            )
        view.update({
            "activeReceivedAmount": money(sum(x["amount_minor"] for x in receipts)),
            "activeRefundedAmount": money(sum(x["amount_minor"] for x in refunds)),
            "varianceAmount": signed_money(sum(x["amount_minor"] for x in receipts) - item["agreed_amount_minor"]),
            "settlementId": settlement["id"] if settlement else None,
            "settlementStatus": settlement["status"] if settlement else None,
            "deadlineState": deadline_state,
            "unresolvedBalance": self._account_is_unresolved(tx, item, settlement),
        })
        return view
    def _settlement_view(self, tx, item):
        view = _settlement_view(item)
        view["replacedBySettlementId"] = tx.settlement_replacement(item["id"])
        source_warnings = []
        view["deductions"] = [
            {
                **_line_view(row),
                "sources": [_source_view(source) for source in tx.deduction_sources(row["id"])],
                "evidence": [_evidence_view(link) for link in tx.evidence("security_deposit_deduction", row["id"])],
            }
            for row in tx.deductions(item["id"])
        ]
        for deduction in view["deductions"]:
            for source in deduction["sources"]:
                current = tx.source_context(source["sourceKind"], source["sourceId"])
                if current is None:
                    source_warnings.append(f"missing_source:{source['id']}")
                elif not current["active"]:
                    source_warnings.append(f"historical_source:{source['id']}")
        view["credits"] = [_line_view(x) for x in tx.credits(item["id"])]
        view["refunds"] = [_refund_view({**x, "replaced_by_refund_id": tx.refund_replacement(x["id"])}) for x in tx.refunds(item["account_id"], active_only=False)]
        view["evidence"] = [_evidence_view(link) for link in tx.evidence("security_deposit_settlement", item["id"])]
        account = _required(tx.account(item["account_id"]), "Security-deposit account was not found.")
        view["sourceWarnings"] = source_warnings
        view["inspectionWarnings"] = tx.inspection_warnings(account["lease_id"])
        captured = tx.settlement_receipt_ids(item["id"])
        unsettled = sum(row["amount_minor"] for row in tx.receipts(item["account_id"], active_only=True) if row["id"] not in captured)
        view["unsettledReceiptAmount"] = money(unsettled)
        return view
    def _account_is_unresolved(self, tx, account, settlement):
        receipts = tx.receipts(account["id"], active_only=True)
        refunds = tx.refunds(account["id"], active_only=True)
        if settlement is None:
            return bool(receipts or refunds)
        captured = tx.settlement_receipt_ids(settlement["id"])
        if any(receipt["id"] not in captured for receipt in receipts):
            return True
        if settlement["status"] == "completed":
            return sum(refund["amount_minor"] for refund in refunds) != settlement["refund_due_minor"]
        return True
    def _audit(self, tx, entity_type, entity_id, action, before, after, correlation): tx.record_change(entity_type=entity_type, entity_id=entity_id, action=action, before=before, after=after, reason=None, correlation_id=correlation)


def _required(item, message):
    if item is None: raise FinanceNotFoundError(message)
    return item
def _stamp(value): return value.astimezone(UTC).isoformat()
def _aggregate_fingerprint(owner_id, fingerprint): return sha256(f"{owner_id}:{fingerprint}".encode()).hexdigest()
def _camel(values): return {key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value for key, value in values.items() if key not in {"request_fingerprint"}}
def _account_view(item):
    return {"id": item["id"], "leaseId": item["lease_id"], "leaseTermId": item["lease_term_id"], "propertyId": item["property_id"], "spaceId": item["space_id"], "agreedAmount": money(item["agreed_amount_minor"]), "currencyCode": item["currency_code"], "createdAt": item["created_at"], "updatedAt": item["updated_at"]}
def _receipt_view(item):
    return {"id": item["id"], "accountId": item["account_id"], "idempotencyKey": item["idempotency_key"], "receivedOn": item["received_on"], "amount": money(item["amount_minor"]), "currencyCode": item["currency_code"], "receivedFromPartyId": item["received_from_party_id"], "receivedFromName": item["received_from_name"], "receivedByKind": item["received_by_kind"], "receivedByPartyId": item["received_by_party_id"], "receivedByName": item["received_by_name"], "reference": item["reference"], "notes": item["notes"], "replacesReceiptId": item["replaces_receipt_id"], "replacedByReceiptId": item.get("replaced_by_receipt_id"), "voidedAt": item["voided_at"], "voidReason": item["void_reason"], "createdAt": item["created_at"], "lifecycleStatus": "voided" if item["voided_at"] else "active"}
def _settlement_view(item):
    return {"id": item["id"], "accountId": item["account_id"], "status": item["status"], "settlementDueOn": item["settlement_due_on"], "legalRuleReference": item["legal_rule_reference"], "reviewNotes": item["review_notes"], "eligibilityOverrideReason": item["eligibility_override_reason"], "deadlineOverrideReason": item["deadline_override_reason"], "receiptTotal": money(item["receipt_total_minor"]), "creditTotal": money(item["credit_total_minor"]), "deductionTotal": money(item["deduction_total_minor"]), "refundDue": money(item["refund_due_minor"]), "replacesSettlementId": item["replaces_settlement_id"], "approvedAt": item["approved_at"], "completedAt": item["completed_at"], "voidedAt": item["voided_at"], "voidReason": item["void_reason"], "createdAt": item["created_at"], "updatedAt": item["updated_at"]}
def _refund_view(item):
    return {"id": item["id"], "accountId": item["account_id"], "authorizedBySettlementId": item["authorized_by_settlement_id"], "idempotencyKey": item["idempotency_key"], "recipientPartyId": item["recipient_party_id"], "recipientName": item["recipient_name"], "paidOn": item["paid_on"], "amount": money(item["amount_minor"]), "currencyCode": item["currency_code"], "reference": item["reference"], "notes": item["notes"], "recipientOverrideReason": item["recipient_override_reason"], "replacesRefundId": item["replaces_refund_id"], "replacedByRefundId": item.get("replaced_by_refund_id"), "voidedAt": item["voided_at"], "voidReason": item["void_reason"], "createdAt": item["created_at"], "lifecycleStatus": "voided" if item["voided_at"] else "active"}
def _line_view(item):
    view = {
        key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value
        for key, value in item.items()
        if key not in {"amount_minor", "calculator_principal_minor", "calculated_amount_minor"}
    }
    view["amount"] = money(item["amount_minor"])
    if "calculator_principal_minor" in item:
        view["calculatorPrincipal"] = money(item["calculator_principal_minor"])
        view["calculatedAmount"] = money(item["calculated_amount_minor"])
    return view


def _source_view(item):
    view = _camel(item)
    view["outstandingAmount"] = money(item["outstanding_amount_minor"])
    view.pop("outstandingAmountMinor", None)
    return view


def _evidence_view(item):
    return {
        "fileId": item["file_id"],
        "purpose": item["purpose"],
        "createdAt": item["created_at"],
        "archivedAt": item["archived_at"],
    }
