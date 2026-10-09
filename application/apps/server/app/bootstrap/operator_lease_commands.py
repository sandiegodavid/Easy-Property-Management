"""Fingerprints OPS lease forms with the owning Lease command contract."""

from dataclasses import asdict
from app.modules.leases.application.commands import LeaseCommandIdentity, fingerprint
from app.modules.leases.application.service import (
    LeaseCreateCommand,
    LeasePatchCommand,
    ParticipantCommand,
    RenewalCommand,
    RenewalPatchCommand,
    TermCommand,
    TerminationCaseCommand,
    TerminationProposalCommand,
    normalize_renewal_decision_notes,
)
from app.modules.operator.domain.models import OperatorError
from app.modules.leases.domain.models import termination_end_reason


def termination_completion_payload(reader, connection, lease_id, payload):
    reason = reader.termination_case_reason(connection, lease_id, payload["caseId"])
    if reason is None:
        raise OperatorError("Select a termination case belonging to this Lease.")
    return {**payload, "endReason": termination_end_reason(reason)}


def lease_request(action, source_id, payload, key):
    expected = payload.get("expectedRevision")
    if type(expected) is not int or expected < 0:
        raise OperatorError("Complete the expected Lease revision.")
    target_kind, target_id, request_payload = _request(action, source_id, payload)
    identity = LeaseCommandIdentity(action, target_kind, target_id, expected, key, request_payload)
    return fingerprint(identity.request_json())


def _request(action, source_id, payload):
    builders = {
        "create": lambda: _create(payload),
        "patch": lambda: _patch(source_id, payload),
        "replace_initial_term": lambda: ("lease", source_id, asdict(_term(payload))),
        "add_participant": lambda: _participant(action, source_id, payload),
        "update_participant": lambda: _participant(action, source_id, payload),
        "remove_participant": lambda: (
            "lease",
            source_id,
            {"participantId": payload["participantId"]},
        ),
        "execute": lambda: _timeline(action, source_id, payload),
        "ended": lambda: _timeline(action, source_id, payload),
        "terminated": lambda: _timeline(action, source_id, payload),
        "complete_termination_case": lambda: _timeline(action, source_id, payload),
        "void": lambda: _timeline(action, source_id, payload),
        "add_renewal_option": lambda: _renewal(action, source_id, payload),
        "update_renewal_option": lambda: _renewal(action, source_id, payload),
        "decide_renewal_option": lambda: _renewal(action, source_id, payload),
        "create_termination_case": lambda: _termination(action, source_id, payload),
        "add_termination_proposal": lambda: _termination(action, source_id, payload),
        "accept_termination_proposal": lambda: _termination(action, source_id, payload),
        "transition_termination_case": lambda: _termination(action, source_id, payload),
    }
    try:
        return builders[action]()
    except KeyError as error:
        raise OperatorError("Lease command form is not registered.") from error


def _create(payload):
    term = _term(payload["initialTerm"])
    participants = tuple(_participant_command(item) for item in payload["participants"])
    command = LeaseCreateCommand(
        payload["spaceId"],
        payload["leaseKind"],
        payload["contractStartsOn"],
        payload.get("contractEndsOn"),
        payload["occupancyStartsOn"],
        term,
        participants,
        payload.get("notes"),
    )
    body = {
        "space_id": command.space_id,
        "lease_kind": command.lease_kind,
        "contract_starts_on": command.contract_starts_on,
        "contract_ends_on": command.contract_ends_on,
        "occupancy_starts_on": command.occupancy_starts_on,
        "initial_term": asdict(term),
        "participants": tuple(asdict(item) for item in participants),
        "notes": command.notes,
    }
    return "space", command.space_id, body


def _term(payload):
    return TermCommand(
        payload["baseRentMinor"],
        payload["currencyCode"],
        payload["paymentFrequency"],
        payload.get("paymentDueDay"),
        payload["agreedSecurityDepositMinor"],
    )


def _participant_command(payload):
    return ParticipantCommand(
        payload["tenantPartyId"],
        payload["participantRole"],
        payload.get("startsOn"),
        payload.get("endsOn"),
        payload.get("notes"),
    )


def _patch(source_id, payload):
    names = ("contractStartsOn", "contractEndsOn", "occupancyStartsOn", "notes")
    mapping = dict(
        zip(
            names,
            ("contract_starts_on", "contract_ends_on", "occupancy_starts_on", "notes"),
            strict=True,
        )
    )
    supplied = frozenset(mapping[name] for name in names if name in payload)
    command = LeasePatchCommand(
        **{field: payload.get(name) for name, field in mapping.items()}, supplied_fields=supplied
    )
    return "lease", source_id, _provided_fields(command)


def _participant(action, source_id, payload):
    command = _participant_command(payload)
    body = asdict(command)
    if action == "update_participant":
        body = {"participantId": payload["participantId"], "command": body}
    return "lease", source_id, body


def _timeline(action, source_id, payload):
    if action == "execute":
        body = {
            "executedOn": payload["executedOn"],
            "confirmed": payload["confirmed"],
            "expectedSpaceRevision": payload["expectedSpaceRevision"],
        }
    elif action == "void":
        body = {
            "confirmed": payload["confirmed"],
            "expectedSpaceRevision": payload["expectedSpaceRevision"],
        }
    else:
        reason = payload.get("endReason")
        if action == "ended":
            reason = "contract_completed"
        body = {
            "actualMoveOutOn": payload["actualMoveOutOn"],
            "endReason": reason,
            "terminationCaseId": (
                payload.get("caseId") if action == "complete_termination_case" else None
            ),
            "confirmed": payload["confirmed"],
            "expectedSpaceRevision": payload["expectedSpaceRevision"],
        }
    return "lease", source_id, body


def _renewal(action, source_id, payload):
    if action == "add_renewal_option":
        body = asdict(
            RenewalCommand(
                payload["proposedStartsOn"],
                payload.get("proposedEndsOn"),
                payload.get("noticeDueOn"),
                payload.get("responseDueOn"),
                payload.get("notes"),
            )
        )
    elif action == "update_renewal_option":
        names = ("proposedStartsOn", "proposedEndsOn", "noticeDueOn", "responseDueOn", "notes")
        mapping = dict(
            zip(
                names,
                (
                    "proposed_starts_on",
                    "proposed_ends_on",
                    "notice_due_on",
                    "response_due_on",
                    "notes",
                ),
                strict=True,
            )
        )
        supplied = frozenset(mapping[name] for name in names if name in payload)
        command = RenewalPatchCommand(
            **{field: payload.get(name) for name, field in mapping.items()},
            supplied_fields=supplied,
        )
        body = {"optionId": payload["optionId"], "command": _provided_fields(command)}
    else:
        body = {
            "optionId": payload["optionId"],
            "status": payload["status"],
            "decidedOn": payload["decidedOn"],
            "notes": normalize_renewal_decision_notes(payload.get("notes")),
            "notesSupplied": payload.get("notes") is not None,
        }
    return "lease", source_id, body


def _termination(action, source_id, payload):
    if action == "create_termination_case":
        command = TerminationCaseCommand(
            payload["reason"],
            payload["noticeReceivedOn"],
            payload["requestedTerminationOn"],
            payload["expectedMoveOutOn"],
            payload.get("tenantExplanation"),
            payload.get("contractClauseReference"),
            payload.get("operatorNotes"),
        )
        return "lease", source_id, asdict(command)
    case_id = payload["caseId"]
    if action == "add_termination_proposal":
        command = TerminationProposalCommand(
            payload["proposedTerminationOn"],
            payload["expectedMoveOutOn"],
            payload.get("rentResponsibilityEndsOn"),
            payload.get("terminationFeeMinor"),
            payload.get("currencyCode"),
            payload.get("feeWaived", False),
            payload.get("replacementTenantCondition"),
            payload.get("accessArrangement"),
            payload.get("otherTerms"),
            payload.get("responseDueOn"),
        )
        return "termination_case", case_id, asdict(command)
    if action == "accept_termination_proposal":
        body = {
            "proposalId": payload["proposalId"],
            "acceptedOn": payload["acceptedOn"],
            "confirmed": payload["confirmed"],
        }
        return "termination_case", case_id, body
    notes = payload.get("operatorNotes")
    body = {
        "status": payload["status"],
        "operatorNotes": None if notes is None else notes.strip() or None,
        "notesSupplied": notes is not None,
    }
    return "termination_case", case_id, body


def _provided_fields(command):
    return {field: getattr(command, field) for field in sorted(command.supplied_fields)}
