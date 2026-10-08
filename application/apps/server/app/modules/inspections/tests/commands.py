"""Explicit concurrency setup for legacy workflow scenarios, not a service proxy."""

from uuid import uuid4


def inspection_command(service, method, *args, **kwargs):
    if method == "create_template":
        revision = 0
    elif method == "patch_template":
        revision = service.unit_of_work.command_revision("template", args[0])
    elif method in {"create", "save_comparisons"}:
        revision = service.unit_of_work.command_revision("lease", args[0])
    elif method == "attach_evidence":
        context = service.unit_of_work.write(lambda tx: tx.observation_context(args[0]))
        revision = service.unit_of_work.command_revision("lease", context["lease_id"])
    else:
        revision = service.unit_of_work.command_revision("lease", service.get(args[0])["leaseId"])
    return getattr(service, method)(
        *args, expected_revision=revision, idempotency_key=str(uuid4()), **kwargs
    )
