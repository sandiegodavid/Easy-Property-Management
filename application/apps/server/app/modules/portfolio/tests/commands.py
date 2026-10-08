"""Explicit fixture commands; real public service signatures remain unchanged."""

from uuid import uuid4

from app.modules.portfolio.application.service import PortfolioService


def inventory_command(service: PortfolioService, action: str, *args, **kwargs):
    """Supply concurrency metadata explicitly at each fixture call site."""
    if action == "create_property":
        revision = 0
    else:
        target_id = args[0]
        if action in {"patch_space", "archive_space", "restore_space"}:
            space = service.unit_of_work.get_space(target_id)
            target_id = space.property_id if space else target_id
        property = service.unit_of_work.get_property(target_id)
        revision = property.property_revision if property else 0
    kwargs.setdefault("expected_revision", revision)
    kwargs.setdefault("idempotency_key", str(uuid4()))
    result = getattr(service, action)(*args, **kwargs)
    if action == "replace_ownerships":
        return result
    if action in {"add_space", "patch_space", "archive_space", "restore_space"}:
        return service.unit_of_work.get_space(result["id"])
    return service.unit_of_work.get_property(result["id"])
