"""Explicit fixture commands; service methods retain their required signatures."""

from uuid import uuid4


def current_tenant_command(service, action, *args, **kwargs):
    revision = 0 if action in {"create", "designate"} else service.get(args[0])["revision"]
    return getattr(service, action)(
        *args, expected_revision=revision, idempotency_key=str(uuid4()), **kwargs
    )
