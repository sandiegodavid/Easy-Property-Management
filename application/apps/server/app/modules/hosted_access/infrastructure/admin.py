"""Administrator CLI entry point; no enrollment or host actions are exposed as business APIs."""

from datetime import UTC, datetime
from pathlib import Path

from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.configuration import (
    load_hosted_deployment,
    validate_workspace_binding,
)
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.service import WorkspaceService


def administer(path: Path, service: WorkspaceService, action: str, subject: str | None) -> str:
    deployment = load_hosted_deployment(path)
    # Revocation must remain possible after demo expiry or broken business data.
    # Store construction independently verifies the pinned operator/workspace.
    if action not in {"disable", "revoke", "enrollments"}:
        validate_workspace_binding(deployment, service)
    if action == "initialize":
        SQLiteHostedSessionStore.initialize(deployment)
        return "Hosted access initialized; verified enrollment and approval are still required."
    store = SQLiteHostedSessionStore(deployment)
    try:
        if action == "enrollments":
            return (
                "\n".join(str(item["subject"]) for item in store.enrollments()) or "No enrollments."
            )
        if action == "activate":
            if not subject:
                raise HostedAccessError(
                    "hosted_subject_required", "Supply the verified subject.", 400
                )
            store.activate(subject)
            return "Verified operator activated."
        if action == "disable":
            store.disable(datetime.now(UTC))
            return "Operator disabled and sessions revoked."
        if action == "rebind":
            if not subject:
                raise HostedAccessError(
                    "hosted_subject_required", "Supply the verified subject.", 400
                )
            store.rebind(subject, datetime.now(UTC))
            return "Subject rebound; explicit activation and fresh sign-in are required."
        if action == "revoke":
            store.revoke_all(datetime.now(UTC))
            return "All application sessions revoked; fresh sign-in required."
        raise HostedAccessError(
            "hosted_action_unknown", "Unknown hosted administration action.", 400
        )
    finally:
        store.engine.dispose()
