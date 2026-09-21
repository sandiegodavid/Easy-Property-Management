from __future__ import annotations
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from json import dumps
from uuid import uuid4
from zoneinfo import ZoneInfo
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, RecordReceiptCommand, ReceiptAllocationCommand
from app.modules.owner_accounting.application.ports import OwnerRentReportUnitOfWork
from app.modules.owner_accounting.domain.models import (
    OwnerRentReport, OwnerRentReportCommand, OwnerReportConflictError, OwnerReportError,
    OwnerReportNotFoundError, RejectOwnerRentReportCommand, VerifyOwnerRentReportCommand,
)

class OwnerRentReportService:
    def __init__(self, unit_of_work: OwnerRentReportUnitOfWork, *, now=lambda: datetime.now(UTC)):
        self.unit_of_work=unit_of_work; self.now=now
    def create(self, command: OwnerRentReportCommand):
        fingerprint=_fingerprint(command.__dict__)
        def operation(tx):
            retry=tx.report_by_operation_key(command.idempotency_key)
            if retry:
                if retry["request_fingerprint"] != fingerprint: raise OwnerReportConflictError("Idempotency key was already used for a different request.")
                return self._view(tx, _required(tx.report(retry["report_id"])))
            context=self._validate_claim(tx,command)
            if command.replaces_report_id:
                prior=_required(tx.report(command.replaces_report_id))
                if prior.status == "pending": raise OwnerReportConflictError("Only terminal reports can be replaced.")
                if tx.replacement_exists(prior.id): raise OwnerReportConflictError("Report already has a replacement.")
            stamp=self.now().astimezone(UTC).isoformat(); party=tx.owner_party(command.owner_party_id)
            item=OwnerRentReport(str(uuid4()),command.lease_id,context["property_id"],context["space_id"],context["time_zone"],party.id,party.display_name,command.received_on,command.amount_minor,"USD",command.payment_method_kind,command.payment_method_label,command.masked_reference,command.other_payment_method_note,command.reported_at_utc,command.source_note,"pending",None,None,None,command.replaces_report_id,stamp,stamp)
            tx.insert_report(item); correlation=str(uuid4()); self._operation(tx,{"id":str(uuid4()),"idempotency_key":command.idempotency_key,"action":"create","report_id":item.id,"request_fingerprint":fingerprint,"result_receipt_id":None,"correlation_id":correlation,"created_at":stamp})
            tx.record_change(entity_type="owner_rent_report",entity_id=item.id,action="created",before=None,after=item.to_dict(),reason="Owner rent report recorded.",correlation_id=correlation)
            return self._view(tx,item)
        return self.unit_of_work.write(operation)
    def patch(self, report_id: str, values: dict[str, object], idempotency_key: str):
        # Patches reuse create's validation by applying a complete claim command.
        def operation(tx):
            old=_required(tx.report(report_id)); key=str(idempotency_key); fingerprint=_fingerprint({"report_id":report_id,"values":values})
            retry=tx.report_by_operation_key(key)
            if retry:
                if retry["request_fingerprint"] != fingerprint: raise OwnerReportConflictError("Idempotency key was already used for a different request.")
                return self._view(tx,_required(tx.report(retry["report_id"])))
            if old.status != "pending": raise OwnerReportConflictError("Only pending reports can be changed.")
            allowed={"owner_party_id","received_on","amount_minor","payment_method_kind","payment_method_label","masked_reference","other_payment_method_note","reported_at_utc","source_note"}
            if not set(values).issubset(allowed): raise OwnerReportError("Patch contains unsupported fields.")
            if not values:return self._view(tx,old)
            command=OwnerRentReportCommand(old.lease_id, str(values.get("owner_party_id",old.owner_party_id)),str(values.get("received_on",old.received_on)),values.get("amount_minor",old.amount_minor),str(values.get("payment_method_kind",old.payment_method_kind)),key,str(values.get("reported_at_utc",old.reported_at_utc)),values.get("payment_method_label",old.payment_method_label),values.get("masked_reference",old.masked_reference),values.get("other_payment_method_note",old.other_payment_method_note),values.get("source_note",old.source_note))
            context=self._validate_claim(tx,command); party=tx.owner_party(command.owner_party_id); stamp=self.now().astimezone(UTC).isoformat()
            item=replace(old,property_id=context["property_id"],space_id=context["space_id"],property_timezone_snapshot=context["time_zone"],owner_party_id=party.id,owner_display_name_snapshot=party.display_name,received_on=command.received_on,amount_minor=command.amount_minor,payment_method_kind=command.payment_method_kind,payment_method_label=command.payment_method_label,masked_reference=command.masked_reference,other_payment_method_note=command.other_payment_method_note,reported_at_utc=command.reported_at_utc,source_note=command.source_note,updated_at=stamp)
            tx.replace_report(item); correlation=str(uuid4()); self._operation(tx,{"id":str(uuid4()),"idempotency_key":key,"action":"patch","report_id":item.id,"request_fingerprint":fingerprint,"result_receipt_id":None,"correlation_id":correlation,"created_at":stamp}); tx.record_change(entity_type="owner_rent_report",entity_id=item.id,action="patched",before=old.to_dict(),after=item.to_dict(),reason="Pending owner rent report corrected.",correlation_id=correlation)
            return self._view(tx,item)
        return self.unit_of_work.write(operation)
    def verify(self, report_id: str, command: VerifyOwnerRentReportCommand, idempotency_key: str):
        fingerprint=_fingerprint({"report_id":report_id,**command.__dict__})
        def operation(tx):
            retry=tx.report_by_operation_key(idempotency_key)
            if retry:
                if retry["request_fingerprint"] != fingerprint: raise OwnerReportConflictError("Idempotency key was already used for a different request.")
                return self._view(tx,_required(tx.report(retry["report_id"])))
            report=_required(tx.report(report_id))
            if report.status != "pending": raise OwnerReportConflictError("Only pending reports can be verified.")
            if not tx.has_evidence(report.id): raise OwnerReportError("At least one active available evidence file is required before verification.")
            if not tx.owner_eligible(report.property_id,report.owner_party_id,report.received_on): raise OwnerReportConflictError("Owner was not a client owner on the claimed receipt date.")
            correlation=str(uuid4())
            if command.existing_receipt_id:
                receipt=tx.receipt(command.existing_receipt_id)
                if receipt is None: raise OwnerReportNotFoundError("Selected rent receipt was not found.")
                if not _compatible(report,receipt) or tx.report_for_receipt(receipt.id): raise OwnerReportConflictError("Selected receipt is not compatible with this report.")
                allocations=tx.receipt_allocations(receipt.id)
                if not allocations or sum(row["amount_minor"] for row in allocations) != report.amount_minor: raise OwnerReportConflictError("Selected receipt allocations are not valid.")
                self._validate_replacement(tx, report, receipt)
            else:
                allocations=tuple(item if isinstance(item,ReceiptAllocationCommand) else ReceiptAllocationCommand(item["expectation_id"] if isinstance(item,dict) else item.expectation_id,item["amount_minor"] if isinstance(item,dict) else item.amount_minor) for item in command.allocations)
                receipt_command=RecordReceiptCommand(report.lease_id,command.receipt_idempotency_key,report.received_on,report.amount_minor,"USD",allocations,report.payment_method_kind,report.payment_method_label,report.masked_reference,report.other_payment_method_note,report.owner_party_id,command.replaces_receipt_id,None,False,None)
                self._validate_replacement_request(tx, report, command)
                recorded=tx.record_receipt(receipt_command,now=self.now,correlation_id=correlation,audit_reason="Owner rent report verified.",duplicate_conflict=lambda candidates: OwnerReportConflictError("A matching active receipt already exists; select it or correct it first.",details={"candidateReceiptIds":[item.id for item in candidates]}))
                if not recorded.created:
                    raise OwnerReportConflictError("Receipt creation key was already used; select that receipt explicitly instead.")
                receipt=recorded.receipt
                if not _compatible(report, receipt) or tx.report_for_receipt(receipt.id):
                    raise OwnerReportConflictError("Receipt creation did not produce an active unlinked compatible receipt.")
                allocations=tx.receipt_allocations(receipt.id)
                if not allocations or sum(row["amount_minor"] for row in allocations) != report.amount_minor:
                    raise OwnerReportConflictError("Created receipt allocations are not valid.")
            stamp=self.now().astimezone(UTC).isoformat(); item=replace(report,status="verified",verified_receipt_id=receipt.id,reviewed_at=stamp,review_note=command.review_note,updated_at=stamp)
            tx.replace_report(item); self._operation(tx,{"id":str(uuid4()),"idempotency_key":idempotency_key,"action":"verify","report_id":item.id,"request_fingerprint":fingerprint,"result_receipt_id":receipt.id,"receipt_created":command.existing_receipt_id is None,"correlation_id":correlation,"created_at":stamp}); after=item.to_dict(); after["verificationEvidence"]=[{"linkId":link.id,"fileId":link.file_id,"active":True,"available":True} for link in tx.available_evidence_links(item.id)]; tx.record_change(entity_type="owner_rent_report",entity_id=item.id,action="verified",before=report.to_dict(),after=after,reason="Owner rent report verified.",correlation_id=correlation)
            return self._view(tx,item)
        return self.unit_of_work.write(operation)
    def reject(self, report_id: str, command: RejectOwnerRentReportCommand, idempotency_key: str):
        fingerprint=_fingerprint({"report_id":report_id,**command.__dict__})
        def operation(tx):
            retry=tx.report_by_operation_key(idempotency_key)
            if retry:
                if retry["request_fingerprint"] != fingerprint: raise OwnerReportConflictError("Idempotency key was already used for a different request.")
                return self._view(tx,_required(tx.report(retry["report_id"])))
            report=_required(tx.report(report_id))
            if report.status != "pending": raise OwnerReportConflictError("Only pending reports can be rejected.")
            stamp=self.now().astimezone(UTC).isoformat(); item=replace(report,status="rejected",reviewed_at=stamp,review_note=command.reason,updated_at=stamp); correlation=str(uuid4());tx.replace_report(item);self._operation(tx,{"id":str(uuid4()),"idempotency_key":idempotency_key,"action":"reject","report_id":item.id,"request_fingerprint":fingerprint,"result_receipt_id":None,"correlation_id":correlation,"created_at":stamp});tx.record_change(entity_type="owner_rent_report",entity_id=item.id,action="rejected",before=report.to_dict(),after=item.to_dict(),reason="Owner rent report rejected.",correlation_id=correlation);return self._view(tx,item)
        return self.unit_of_work.write(operation)
    def detail(self, report_id): return self.unit_of_work.read(lambda tx:self._view(tx,_required(tx.report(report_id)),detail=True))
    def list(self, *, cursor=None, page_size=100, **filters):
        if not 1 <= page_size <= 500: raise OwnerReportError("Page size must be between 1 and 500.")
        def operation(tx):
            rows=tx.report_page(cursor=cursor,limit=page_size+1,**filters); page=rows[:page_size]
            ids=[item.id for item in page]; receipt_ids=[item.verified_receipt_id for item in page if item.verified_receipt_id]
            context={"evidence":tx.evidence_counts(ids),"receipts":tx.receipts(receipt_ids),"owners":tx.owner_parties(list(dict.fromkeys(item.owner_party_id for item in page)))}
            return {"items":[self._view(tx,item,context=context) for item in page],"nextCursor":f"{page[-1].received_on}|{page[-1].id}" if len(rows)>page_size else None}
        return self.unit_of_work.read(operation)
    def _validate_claim(self,tx,command):
        context=tx.lease_context(command.lease_id)
        if context is None: raise OwnerReportNotFoundError("Lease was not found.")
        party=tx.owner_party(command.owner_party_id)
        if party is None: raise OwnerReportNotFoundError("Owner party was not found.")
        now=self.now().astimezone(ZoneInfo(context["time_zone"])); received=date.fromisoformat(command.received_on)
        if received>now.date(): raise OwnerReportError("Received date cannot be in the future.")
        reported=datetime.fromisoformat(command.reported_at_utc).astimezone(UTC)
        if reported > self.now().astimezone(UTC): raise OwnerReportError("Reported time cannot be in the future.")
        if reported.astimezone(ZoneInfo(context["time_zone"])).date()<received: raise OwnerReportError("Reported time cannot precede the claimed receipt day.")
        if not tx.owner_eligible(context["property_id"],party.id,command.received_on): raise OwnerReportConflictError("Owner was not a client owner on the claimed receipt date.")
        return context
    def _view(self,tx,item,detail=False,context=None):
        context=context or {}; receipt=(context.get("receipts",{}).get(item.verified_receipt_id) if item.verified_receipt_id else None)
        if item.verified_receipt_id and receipt is None: receipt=tx.receipt(item.verified_receipt_id)
        evidence=context.get("evidence")
        count=None if evidence is None else evidence.get(item.id,0)
        owner=(context.get("owners",{}).get(item.owner_party_id) if context else None)
        view={**item.to_dict(),"receiptLifecycleStatus":None if receipt is None else ("voided" if receipt.voided_at else "active"),"financiallyEffective":bool(item.status=="verified" and receipt and not receipt.voided_at),"evidenceCount":tx.evidence_count(item.id) if count is None else count,"currentOwnerState":None if owner is None else ("archived" if owner.archived_at else "active")}
        if detail:
            view["files"]=[link.__dict__ for link in tx.evidence_links(item.id)]
            predecessor=_required(tx.report(item.replaces_report_id)) if item.replaces_report_id else None
            successor=tx.replacement_for_report(item.id)
            view["priorReportId"]=None if predecessor is None else predecessor.id
            view["replacementReportId"]=None if successor is None else successor.id
            replacement_receipt=None if receipt is None else tx.replacement_receipt(receipt.id)
            view["replacementReceiptId"]=None if replacement_receipt is None else replacement_receipt.id
            view["receiptAllocations"]=[] if receipt is None else tx.receipt_projections([receipt.id])[receipt.id]
            party=tx.owner_party(item.owner_party_id); view["currentOwnerState"]=None if party is None else ("archived" if party.archived_at else "active")
        return view
    def _operation(self,tx,item):
        tx.insert_operation(item)
        tx.record_change(entity_type="owner_rent_report_operation",entity_id=item["id"],action="recorded",before=None,after=item,reason="Owner rent report operation recorded.",correlation_id=item["correlation_id"])
    def _validate_replacement_request(self,tx,report,command):
        if report.replaces_report_id is None:
            if command.replaces_receipt_id is not None: raise OwnerReportConflictError("Only replacement reports may replace a receipt.")
            return
        prior=_required(tx.report(report.replaces_report_id))
        if prior.status == "rejected":
            if command.replaces_receipt_id is not None: raise OwnerReportConflictError("A replacement of a rejected report cannot replace a receipt.")
            return
        if prior.status != "verified" or prior.verified_receipt_id is None: raise OwnerReportConflictError("Replacement report requires a verified predecessor.")
        prior_receipt=tx.receipt(prior.verified_receipt_id)
        if prior_receipt is None or prior_receipt.voided_at is None: raise OwnerReportConflictError("Replacement report requires its predecessor receipt to be voided.")
        if command.replaces_receipt_id != prior_receipt.id: raise OwnerReportConflictError("Replacement receipt must replace the predecessor receipt.")
    def _validate_replacement(self,tx,report,receipt):
        if report.replaces_report_id is None:
            if receipt.replaces_receipt_id is not None: raise OwnerReportConflictError("Only replacement reports may use a replacement receipt.")
            return
        prior=_required(tx.report(report.replaces_report_id))
        if prior.status == "rejected":
            if receipt.replaces_receipt_id is not None: raise OwnerReportConflictError("A replacement of a rejected report cannot use a replacement receipt.")
            return
        if prior.status != "verified" or prior.verified_receipt_id is None: raise OwnerReportConflictError("Replacement report requires a verified predecessor.")
        prior_receipt=tx.receipt(prior.verified_receipt_id)
        if prior_receipt is None or prior_receipt.voided_at is None: raise OwnerReportConflictError("Replacement report requires its predecessor receipt to be voided.")
        if receipt.replaces_receipt_id != prior_receipt.id: raise OwnerReportConflictError("Replacement receipt must replace the predecessor receipt.")

def _required(item):
    if item is None: raise OwnerReportNotFoundError("Owner rent report was not found.")
    return item
def _compatible(report,receipt):
    return receipt is not None and receipt.voided_at is None and receipt.lease_id==report.lease_id and receipt.received_on==report.received_on and receipt.amount_minor==report.amount_minor and receipt.currency_code=="USD" and receipt.received_by_party_id==report.owner_party_id and (receipt.payment_method_kind,receipt.payment_method_label,receipt.masked_reference,receipt.other_payment_method_note)==(report.payment_method_kind,report.payment_method_label,report.masked_reference,report.other_payment_method_note)
def _fingerprint(value): return sha256(dumps(value,sort_keys=True,default=str,separators=(",",":" )).encode()).hexdigest()
