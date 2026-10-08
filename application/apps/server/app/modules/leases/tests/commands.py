"""Explicit fixture commands; production LeaseService signatures remain intact."""

from uuid import uuid4

from app.modules.leases.application.commands import TIMELINE_ACTIONS
from app.modules.leases.application.service import LeaseNotFoundError, LeaseService


def lease_command(service: LeaseService, action: str, *args, **kwargs):
    """Opt in at each fixture call site to a fresh current revision and command key.

    Explicit values always win. Retry fixtures use the retained original revision.
    Contract tests call the real methods directly, including missing/invalid metadata.
    """
    kwargs.setdefault("idempotency_key", str(uuid4()))
    try:
        receipt = service.get_command_operation(idempotency_key=kwargs["idempotency_key"])
    except LeaseNotFoundError:
        receipt = None
    timeline = action in TIMELINE_ACTIONS or action in {"end", "terminate"}
    if action == "create":
        revision = 0
    elif receipt is not None:
        revision = receipt["expectedLeaseRevision"]
    else:
        lease_id = (
            service.get_termination_case(args[0])["leaseId"]
            if action
            in {
                "add_termination_proposal",
                "accept_termination_proposal",
                "transition_termination_case",
                "complete_termination_case",
            }
            else args[0]
        )
        revision = service.get(lease_id)["leaseRevision"]
    kwargs.setdefault("expected_lease_revision" if timeline else "expected_revision", revision)
    return getattr(service, action)(*args, **kwargs)
