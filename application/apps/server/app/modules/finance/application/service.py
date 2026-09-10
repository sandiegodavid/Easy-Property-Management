"""FIN-001 schedule, receipt, allocation, and review workflows."""
from __future__ import annotations
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from app.modules.finance.application.ports import FinanceUnitOfWork
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, RentExpectation, RentReceipt, RecordReceiptCommand, SynchronizeExpectationsCommand, TimelinessReviewCommand, VoidCommand

class FinanceService:
    def __init__(self, unit_of_work: FinanceUnitOfWork, *, now=lambda: datetime.now(UTC)): self.unit_of_work=unit_of_work; self.now=now
    def synchronize(self, lease_id, command: SynchronizeExpectationsCommand):
        def operation(tx):
            snapshot=tx.lease_term_snapshot(lease_id, command.lease_term_id)
            if snapshot is None: raise FinanceNotFoundError("Eligible lease term was not found.")
            if snapshot.currency_code != "USD": raise FinanceError("FIN-001 supports USD terms only.")
            existing = tx.expectations_for_term(snapshot.id)
            if existing:
                stored_anchor = existing[0].schedule_anchor_on
                if command.schedule_anchor_on is not None and command.schedule_anchor_on != stored_anchor:
                    raise FinanceConflictError("A term's confirmed schedule anchor cannot change after expectations exist.")
                effective_command = replace(command, schedule_anchor_on=stored_anchor)
            elif command.schedule_anchor_on is None:
                raise FinanceError("A schedule anchor is required for the first synchronization.")
            else:
                effective_command = command
            rows=_schedule(snapshot, effective_command, self.now())
            # A responsibility amendment can add a second, adjacent piece to an
            # already persisted occurrence.  Identity must include the covered
            # interval, not merely its due date, so repeating the amendment is
            # a no-op rather than an attempted duplicate insert.
            existing_intervals = {
                (item.period_starts_on, item.period_ends_on, item.due_on)
                for item in existing
            }
            new=[]
            for row in rows:
                prior = _initial_piece_for_interval(existing, row)
                if prior is None: new.append(row)
                elif _immutable_expectation(prior) != _immutable_expectation(row):
                    if not _historical_boundary_snapshot(prior):
                        raise FinanceConflictError("Stored expectation conflicts with the requested immutable schedule.")
                    furthest = _furthest_contiguous_piece(existing, row)
                    if furthest is not None and row.period_ends_on > furthest.period_ends_on:
                        supplement = _boundary_extension_piece(
                            furthest, row, snapshot.base_rent_minor,
                        )
                        identity = (
                            supplement.period_starts_on,
                            supplement.period_ends_on,
                            supplement.due_on,
                        )
                        if identity not in existing_intervals:
                            new.append(supplement)
            _reconcile_proration(new, snapshot.base_rent_minor, existing)
            if len(new)>240: raise FinanceError("Synchronization may create at most 240 expectations.")
            correlation=str(uuid4())
            for item in new:
                tx.insert_expectation(item); tx.record_change(entity_type="rent_expectation",entity_id=item.id,action="created",before=None,after=item.to_dict(),reason="Rent expectation synchronized.",correlation_id=correlation)
            return [self._expectation_view(tx, item) for item in new]
        return self.unit_of_work.write(operation)
    def list_expectations(self, *, lease_id=None, property_id=None, status=None, due_from=None, due_to=None, timeliness=None, include_voided=False, cursor=None, page_size=100):
        cursor_key = _cursor_key(cursor, "expectation") if cursor else None
        _validate_page_size(page_size)
        def operation(tx):
            # Settlement, timeliness, and property ownership are derived from
            # related records. Fetch static-filter pages from SQLite and keep
            # scanning until a response page plus a look-ahead match exists.
            scan_cursor = cursor_key
            matched = []
            context_cache = {}
            while len(matched) <= page_size:
                rows = tx.expectation_page(
                    lease_id=lease_id,
                    due_from=due_from,
                    due_to=due_to,
                    include_voided=include_voided,
                    cursor=scan_cursor,
                    limit=page_size + 1,
                )
                if not rows:
                    break
                projection = tx.expectation_projection([item.id for item in rows])
                context_cache.update(tx.historical_term_snapshots([
                    (item.lease_id, item.lease_term_id) for item in rows
                ]))
                for item in rows:
                    context = context_cache.get((item.lease_id, item.lease_term_id))
                    if context is None:
                        raise FinanceConflictError("Expectation lease context is unavailable.")
                    if property_id is not None and context.property_id != property_id:
                        continue
                    view = self._expectation_view(
                        tx, item, projection[item.id], context_cache,
                    )
                    if (status is None or view["settlementStatus"] == status) and (timeliness is None or view["timelinessStatus"] == timeliness):
                        matched.append(view)
                        if len(matched) > page_size:
                            break
                if len(matched) > page_size or len(rows) <= page_size:
                    break
                tail = rows[-1]
                scan_cursor = (tail.due_on, tail.id)
            page = matched[:page_size]
            return {"items": page, "nextCursor": f"{page[-1]['dueOn']}|{page[-1]['id']}" if len(matched) > len(page) else None}
        return self.unit_of_work.read(operation)
    def expectation(self, expectation_id):
        def operation(tx):
            row = tx.expectation(expectation_id)
            if row is None:
                raise FinanceNotFoundError("Rent expectation was not found.")
            return self._expectation_view(tx, row)
        return self.unit_of_work.read(operation)
    def record_receipt(self, command: RecordReceiptCommand):
        def operation(tx):
            old=tx.receipt_by_key(command.idempotency_key)
            if old:
                if _receipt_payload(old,tx.receipt_allocations(old.id)) != _command_payload(command): raise FinanceConflictError("Idempotency key was already used for a different receipt.")
                return self._receipt_view(old, tx.receipt_projection([old.id])[old.id])
            if command.received_by_party_id and not tx.party_exists(command.received_by_party_id): raise FinanceNotFoundError("Recipient party was not found.")
            expectations=[]
            for allocation in command.allocations:
                item=tx.expectation(allocation.expectation_id)
                if not item: raise FinanceNotFoundError("Allocated expectation was not found.")
                if item.lease_id!=command.lease_id or item.currency_code!="USD" or item.voided_at: raise FinanceConflictError("Allocation target is not eligible.")
                if tx.allocated_amount(item.id)+allocation.amount_minor>item.expected_amount_minor: raise FinanceConflictError("Allocation exceeds expected rent.")
                expectations.append(item)
            zone = tx.lease_time_zone(command.lease_id)
            if zone is None: raise FinanceConflictError("Receipt lease property is unavailable.")
            if date.fromisoformat(command.received_on) > self.now().astimezone(ZoneInfo(zone)).date(): raise FinanceError("Received date cannot be in the future.")
            if command.replaces_receipt_id:
                replaced=tx.receipt(command.replaces_receipt_id)
                if not replaced: raise FinanceNotFoundError("Replaced receipt was not found.")
                if not replaced.voided_at or replaced.lease_id!=command.lease_id or replaced.currency_code!="USD": raise FinanceConflictError("Replacement must target a voided receipt on the same lease.")
                if tx.replacement_exists(replaced.id): raise FinanceConflictError("A replacement receipt already exists.")
            created_at=_stamp(self.now()); receipt=RentReceipt(str(uuid4()),command.lease_id,command.idempotency_key,command.received_on,command.amount_minor,"USD",command.received_by_party_id,command.replaces_receipt_id,command.notes,None,None,created_at); correlation=str(uuid4()); tx.insert_receipt(receipt)
            tx.record_change(entity_type="rent_receipt",entity_id=receipt.id,action="recorded",before=None,after=receipt.to_dict(),reason="Rent receipt recorded.",correlation_id=correlation)
            for allocation in command.allocations:
                row={"id":str(uuid4()),"receipt_id":receipt.id,"expectation_id":allocation.expectation_id,"amount_minor":allocation.amount_minor,"created_at":created_at}; tx.insert_allocation(row); tx.record_change(entity_type="rent_receipt_allocation",entity_id=row["id"],action="created",before=None,after=_camel(row),reason="Receipt allocation recorded.",correlation_id=correlation)
            return self._receipt_view(receipt, tx.receipt_projection([receipt.id])[receipt.id])
        return self.unit_of_work.write(operation)
    def receipt(self, receipt_id):
        def operation(tx):
            row = tx.receipt(receipt_id)
            if not row: raise FinanceNotFoundError("Rent receipt was not found.")
            return self._receipt_view(row, tx.receipt_projection([row.id])[row.id])
        return self.unit_of_work.read(operation)
    def list_receipts(self, *, lease_id=None, received_from=None, received_to=None, received_by_party_id=None, replaces_receipt_id=None, include_voided=False, cursor=None, page_size=100):
        cursor_key = _cursor_key(cursor, "receipt") if cursor else None
        _validate_page_size(page_size)
        def operation(tx):
            if replaces_receipt_id is not None:
                try:
                    rows = tx.receipt_chain_page(
                        receipt_id=replaces_receipt_id,
                        lease_id=lease_id,
                        received_from=received_from,
                        received_to=received_to,
                        received_by_party_id=received_by_party_id,
                        include_voided=include_voided,
                        cursor=cursor_key,
                        limit=page_size + 1,
                    )
                except LookupError:
                    raise FinanceNotFoundError("Rent receipt was not found.") from None
                except ValueError as error:
                    raise FinanceConflictError(str(error)) from error
            else:
                rows = tx.receipt_page(
                    lease_id=lease_id,
                    received_from=received_from,
                    received_to=received_to,
                    received_by_party_id=received_by_party_id,
                    include_voided=include_voided,
                    cursor=cursor_key,
                    limit=page_size + 1,
                )
            projection = tx.receipt_projection([item.id for item in rows])
            views = [self._receipt_view(item, projection[item.id]) for item in rows]
            views.sort(key=lambda item: (item["receivedOn"], item["id"]))
            page = views[:page_size]
            return {"items": page, "nextCursor": f"{page[-1]['receivedOn']}|{page[-1]['id']}" if len(views) > len(page) else None}
        return self.unit_of_work.read(operation)
    def void_receipt(self, receipt_id, command: VoidCommand):
        def operation(tx):
            old=tx.receipt(receipt_id)
            if not old: raise FinanceNotFoundError("Rent receipt was not found.")
            if old.voided_at: raise FinanceConflictError("Rent receipt is already voided.")
            new=replace(old,voided_at=_stamp(self.now()),void_reason=command.reason); tx.replace_receipt(new); tx.record_change(entity_type="rent_receipt",entity_id=new.id,action="voided",before=old.to_dict(),after=new.to_dict(),reason=None,correlation_id=str(uuid4())); return self._receipt_view(new, tx.receipt_projection([new.id])[new.id])
        return self.unit_of_work.write(operation)
    def void_expectation(self, expectation_id, command: VoidCommand):
        def operation(tx):
            old=tx.expectation(expectation_id)
            if not old: raise FinanceNotFoundError("Rent expectation was not found.")
            if old.voided_at: raise FinanceConflictError("Rent expectation is already voided.")
            if tx.allocated_amount(old.id): raise FinanceConflictError("Allocated expectations cannot be voided.")
            new=replace(old,voided_at=_stamp(self.now()),void_reason=command.reason); tx.replace_expectation(new); tx.record_change(entity_type="rent_expectation",entity_id=new.id,action="voided",before=old.to_dict(),after=new.to_dict(),reason=None,correlation_id=str(uuid4())); return self._expectation_view(tx,new)
        return self.unit_of_work.write(operation)
    def review_timeliness(self, expectation_id, command: TimelinessReviewCommand):
        def operation(tx):
            item=tx.expectation(expectation_id)
            if not item: raise FinanceNotFoundError("Rent expectation was not found.")
            if item.voided_at: raise FinanceConflictError("Voided expectations cannot receive timeliness reviews.")
            received=tx.allocated_amount(item.id); now_date=self._local_date(tx, item)
            reviews=tx.reviews(item.id); missed=bool(reviews and reviews[-1]["decision"]=="mark_missed") and received==0 and not tx.receipt_activity_after(item.id, reviews[-1]["created_at"])
            if command.decision=="mark_missed" and (now_date<=date.fromisoformat(item.period_ends_on) or received): raise FinanceConflictError("Only ended unpaid expectations may be marked missed.")
            if command.decision=="clear_missed" and not missed: raise FinanceConflictError("Expectation is not currently marked missed.")
            row={"id":str(uuid4()),"expectation_id":item.id,"decision":command.decision,"reason":command.reason,"created_at":_stamp(self.now())}; tx.insert_review(row); tx.record_change(entity_type="rent_expectation_timeliness_review",entity_id=row["id"],action="recorded",before=None,after=_camel(row),reason=None,correlation_id=str(uuid4())); return self._expectation_view(tx,item)
        return self.unit_of_work.write(operation)
    def _expectation_view(self, tx, item, projection=None, context_cache=None):
        projection = projection or tx.expectation_projection([item.id])[item.id]
        summaries = projection["summaries"]
        context_cache = context_cache if context_cache is not None else {}
        context_key = (item.lease_id, item.lease_term_id)
        if context_key not in context_cache:
            context_cache[context_key] = tx.historical_term_snapshot(*context_key)
        context = context_cache[context_key]
        if context is None:
            raise FinanceConflictError("Expectation lease context is unavailable.")
        if item.voided_at:
            return {**item.to_dict(),"propertyId":context.property_id,"spaceId":context.space_id,"lifecycleStatus":"voided","settlementStatus":None,"timelinessStatus":None,"effectiveMissedReview":False,"allocationCount":len(summaries),"allocationSummaries":summaries,"receivedAmountMinor":0,"outstandingAmountMinor":0}
        timeline = projection["timeline"]
        received = sum(row["amount_minor"] for row in timeline)
        outstanding=item.expected_amount_minor-received; settlement="paid" if not outstanding else "partial" if received else "unpaid"
        today = self.now().astimezone(ZoneInfo(context.time_zone)).date()
        due=date.fromisoformat(item.due_on)
        if settlement=="paid":
            paid = 0; settled_on = due
            for allocation in timeline:
                paid += allocation["amount_minor"]
                if paid >= item.expected_amount_minor:
                    settled_on = date.fromisoformat(allocation["received_on"]); break
            timeliness="paid_on_time" if settled_on<=due else "paid_late"
        elif today<due: timeliness="upcoming"
        elif today==due: timeliness="due"
        else:
            reviews=projection["reviews"]
            missed=bool(reviews and reviews[-1]["decision"]=="mark_missed") and received==0 and today>date.fromisoformat(item.period_ends_on) and not any(value > reviews[-1]["created_at"] for value in projection["activity"])
            timeliness="missed" if missed else "late"
        return {**item.to_dict(),"propertyId":context.property_id,"spaceId":context.space_id,"lifecycleStatus":"active","settlementStatus":settlement,"timelinessStatus":timeliness,"receivedAmountMinor":received,"outstandingAmountMinor":outstanding,"effectiveMissedReview":timeliness == "missed","allocationCount":len(summaries),"allocationSummaries":summaries}
    def _receipt_view(self, item, allocations):
        return {**item.to_dict(),"allocations":allocations}
    def _local_date(self, tx, item):
        zone = tx.lease_time_zone(item.lease_id)
        if zone is None: raise FinanceConflictError("Expectation property is unavailable.")
        return self.now().astimezone(ZoneInfo(zone)).date()

def _schedule(s,c,now):
    start = date.fromisoformat(s.effective_on)
    horizon = date.fromisoformat(c.through_on)
    if horizon > start + timedelta(days=366 * 25):
        raise FinanceError("Synchronization horizon is too far in the future.")
    # A responsibility agreement takes precedence; otherwise physical move-out is
    # the default lease responsibility boundary. A term can only narrow either.
    responsibility = c.responsibility_ends_on_override or s.responsibility_ends_on
    boundary = date.fromisoformat(responsibility) if responsibility else (date.fromisoformat(s.actual_move_out_on) - timedelta(days=1) if s.actual_move_out_on else None)
    if s.ends_on:
        term_boundary = date.fromisoformat(s.ends_on) - timedelta(days=1)
        boundary = min(boundary, term_boundary) if boundary else term_boundary
    generation_end = boundary or horizon
    if generation_end < start: return []
    anchor = date.fromisoformat(c.schedule_anchor_on)
    if s.payment_frequency == "monthly":
        if s.payment_due_day is None or anchor.day != min(s.payment_due_day, _month_days(anchor.year, anchor.month)):
            raise FinanceError("Monthly anchor must match the configured due day.")
        cursor = date(start.year, start.month, min(s.payment_due_day, _month_days(start.year, start.month)))
        if cursor < start: cursor = _next(cursor, "monthly", s.payment_due_day)
        regular = []
        while cursor <= max(generation_end, horizon) or not regular:
            regular.append(cursor); cursor = _next(cursor, "monthly", s.payment_due_day)
    else:
        if anchor < start: raise FinanceError("Weekly anchor must be on or after the term start.")
        cursor = anchor
        while cursor - timedelta(days=7) >= start: cursor -= timedelta(days=7)
        regular=[]
        while cursor <= max(generation_end, horizon) or not regular:
            regular.append(cursor); cursor += timedelta(days=7)
    rows=[]; now=_stamp(now); boundary_text=boundary.isoformat() if boundary else None
    first = regular[0]
    if start < first:
        stub_end = first - timedelta(days=1)
        # A responsibility boundary can shorten the first notional period.  The
        # synchronization horizon cannot: it only decides whether a complete
        # period is eligible for creation.
        if boundary is not None:
            stub_end = min(stub_end, boundary)
        if stub_end <= horizon:
            rows.append(_expectation(s,start,stub_end,start,c,True,now,boundary_text,first-_previous(first,s.payment_frequency)))
    for index, due in enumerate(regular):
        next_due = regular[index + 1] if index + 1 < len(regular) else _next(due,s.payment_frequency,s.payment_due_day)
        full_end = next_due - timedelta(days=1)
        if boundary is not None and due > boundary: continue
        actual_end = min(full_end, boundary) if boundary else full_end
        # throughOn selects only complete periods; it must never shorten one.
        if actual_end > horizon or due > horizon: continue
        prorated = actual_end < full_end
        rows.append(_expectation(s,due,actual_end,due,c,prorated,now,boundary_text,next_due-due))
    for row in rows:
        if (date.fromisoformat(row.period_ends_on)-date.fromisoformat(row.period_starts_on)).days<1: raise FinanceError("A rent period must cover at least two calendar dates.")
    _reconcile_proration(rows, s.base_rent_minor, ())
    return rows
def _expectation(s,start,end,due,c,prorated,now,boundary,notional):
    days=(end-start).days+1; denom=notional.days
    amount=s.base_rent_minor if not prorated else int((Decimal(s.base_rent_minor)*Decimal(days)/Decimal(denom)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    return RentExpectation(str(uuid4()),s.lease_id,s.id,start.isoformat(),end.isoformat(),due.isoformat(),amount,"USD",s.payment_frequency,c.schedule_anchor_on,prorated,days if prorated else None,denom if prorated else None,boundary,c.override_reason,None,None,now)
def _boundary_extension_piece(prior, scheduled, full_recurring_amount):
    start = date.fromisoformat(prior.period_ends_on) + timedelta(days=1)
    end = date.fromisoformat(scheduled.period_ends_on)
    denominator = scheduled.proration_denominator_days or (date.fromisoformat(scheduled.period_ends_on) - date.fromisoformat(scheduled.period_starts_on)).days + 1
    days = (end - start).days + 1
    amount = int((Decimal(full_recurring_amount) * Decimal(days) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return replace(scheduled, id=str(uuid4()), period_starts_on=start.isoformat(), period_ends_on=end.isoformat(), due_on=start.isoformat(), is_prorated=True, proration_numerator_days=days, proration_denominator_days=denominator, expected_amount_minor=amount)

def _reconcile_proration(rows, full_amount, historical):
    # Only adjacent pieces that cover the same notional interval reconcile. The
    # denominator alone is not identity: unrelated months often share it.
    all_pieces = [*historical, *rows]
    for later in rows:
        if not later.is_prorated:
            continue
        preceding = []
        cursor = date.fromisoformat(later.period_starts_on)
        while True:
            candidates = [
                item for item in all_pieces
                if item is not later
                and item.is_prorated
                and item.proration_denominator_days == later.proration_denominator_days
                and date.fromisoformat(item.period_ends_on) + timedelta(days=1) == cursor
            ]
            if not candidates:
                break
            previous = max(candidates, key=lambda item: item.period_starts_on)
            preceding.append(previous)
            cursor = date.fromisoformat(previous.period_starts_on)
        if preceding and sum(item.proration_numerator_days for item in preceding) + later.proration_numerator_days == later.proration_denominator_days:
            corrected = full_amount - sum(item.expected_amount_minor for item in preceding)
            rows[rows.index(later)] = replace(later, expected_amount_minor=corrected)
def _month_days(y,m): return (_add_month(date(y,m,1))-timedelta(days=1)).day
def _add_month(d): return date(d.year+(d.month==12),1 if d.month==12 else d.month+1,1)
def _next(d,freq,due_day=None): return _add_month(date(d.year,d.month,1)).replace(day=min(due_day,_month_days(_add_month(date(d.year,d.month,1)).year,_add_month(date(d.year,d.month,1)).month))) if freq=="monthly" else d+timedelta(days=7)
def _previous(d,freq):
    if freq != "monthly": return d-timedelta(days=7)
    year, month = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return date(year, month, min(d.day, _month_days(year, month)))
def _stamp(value): return value.astimezone(UTC).isoformat()
def _camel(row): return {key.split("_")[0]+"".join(x.title() for x in key.split("_")[1:]):value for key,value in row.items()}
def _command_payload(c): return (c.lease_id,c.received_on,c.amount_minor,c.currency_code,c.received_by_party_id,c.replaces_receipt_id,c.notes,tuple(sorted((a.expectation_id,a.amount_minor) for a in c.allocations)))
def _receipt_payload(r,allocations): return (r.lease_id,r.received_on,r.amount_minor,r.currency_code,r.received_by_party_id,r.replaces_receipt_id,r.notes,tuple(sorted((x["expectation_id"],x["amount_minor"]) for x in allocations)))
def _immutable_expectation(item):
    # Boundary evidence is historical context, not schedule identity. Later
    # responsibility amendments may generate new occurrences without rewriting it.
    return (item.lease_id,item.lease_term_id,item.period_starts_on,item.period_ends_on,item.due_on,item.expected_amount_minor,item.currency_code,item.payment_frequency,item.schedule_anchor_on,item.is_prorated,item.proration_numerator_days,item.proration_denominator_days)
def _historical_boundary_snapshot(item):
    return item.responsibility_boundary_on is not None and item.is_prorated

def _initial_piece_for_interval(existing, scheduled):
    start = scheduled.period_starts_on
    candidates = [
        item for item in existing
        if item.period_starts_on == start
        and item.lease_term_id == scheduled.lease_term_id
        and item.payment_frequency == scheduled.payment_frequency
        and item.schedule_anchor_on == scheduled.schedule_anchor_on
    ]
    return max(candidates, key=lambda item: item.period_ends_on, default=None)

def _furthest_contiguous_piece(existing, scheduled):
    """Return the last persisted piece covering this recurring occurrence.

    Boundary extensions retain the original shortened expectation and append
    suffixes.  Walk those contiguous suffixes so a later extension starts only
    after the already covered date, never from the original row again.
    """
    start = date.fromisoformat(scheduled.period_starts_on)
    end = date.fromisoformat(scheduled.period_ends_on)
    pieces = sorted(
        (
            item for item in existing
            if item.lease_term_id == scheduled.lease_term_id
            and item.payment_frequency == scheduled.payment_frequency
            and item.schedule_anchor_on == scheduled.schedule_anchor_on
            and start <= date.fromisoformat(item.period_starts_on) <= end
        ),
        key=lambda item: (item.period_starts_on, item.period_ends_on),
    )
    furthest = None
    covered_through = start - timedelta(days=1)
    for item in pieces:
        item_start = date.fromisoformat(item.period_starts_on)
        item_end = date.fromisoformat(item.period_ends_on)
        if item_start > covered_through + timedelta(days=1):
            break
        if item_end > covered_through:
            covered_through = item_end
            furthest = item
    return furthest

def _cursor_key(cursor, kind):
    try:
        value, record_id = cursor.split("|", 1)
        date.fromisoformat(value)
        record_id = str(UUID(record_id))
    except (AttributeError, TypeError, ValueError):
        raise FinanceError(f"Invalid {kind} cursor.") from None
    return value, record_id

def _validate_page_size(page_size):
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise FinanceError("Page size must be between 1 and 500.")
